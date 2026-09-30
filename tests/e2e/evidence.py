#!/usr/bin/env python3
"""End-to-end evidence harness for method-sync-v2: the executable mechanism behind the `e2e` tag.

Each scenario runs the real CLI exactly as the spec prescribes -
`PYTHONPATH=src python3 -m method_sync --registry <file> [...]` from the repository root - against a fresh
`git clone` of the target library in `.sandbox/e2e/<scenario>/`, the live exchange and, where the loop needs
it, the real coding agent. Nothing is mocked. The harness only prepares inputs (a clone, an edit inside the
clone, a TOML registry in a temporary directory) and reads outputs: the exit code, stdout and stderr, the files
the run wrote under `runs/`, the clone's git state, and the Claude Code session transcripts whose working
directory is the clone - an agent witness that does not depend on what the tool says about itself.

This is not a unit test. The file is not named `*_test.py` and `tests/e2e/` has no `__init__.py`, so
`npm run test:run` never collects it: it needs the private target library, Maven, the live exchange and the
agent. Run it with `npm run test:e2e`; `--list` shows the scenarios, `--only <name>` (repeatable) picks some.

Every invocation writes `docs/qa/e2e-report.md`, pass or fail, and copies per-scenario evidence into
`docs/qa/e2e/<scenario>/`. `Result: PASS` needs every scenario to pass with the current code: a scenario that
did not run now counts only if its stored result carries the same fingerprint (tool sources, this harness, the
library commit, the toolchain versions); otherwise it is NOT RUN and the result is FAIL. Scenarios that invoke
the agent run only after `premium-clean` has passed with the same fingerprint - a budget guard, lifted by
`--no-gate` - so a broken verification path cannot burn agent calls.

Hard boundaries (AGENTS.md, TC-7): the human's working copy is only cloned from, never written; nothing is ever
staged or committed in a clone.
"""

# The requirement ids each scenario proves sit in a `# @trace` line right above its `@scenario(...)`:
# scripts/check-traceability.mjs reads them, and so does `scenario()` below, so the report's "proves" column
# and the traceability chain cannot drift apart.

import argparse
import dataclasses
import datetime as dt
import difflib
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
ORIGIN = Path("/Users/akutil/humex/binancefutures")  # the human's working copy: a clone source only, never written
SANDBOX = REPO / ".sandbox" / "e2e"
EVIDENCE = REPO / "docs" / "qa" / "e2e"
REPORT = REPO / "docs" / "qa" / "e2e-report.md"
RUNS = REPO / "runs"
REQUIREMENTS = REPO / "docs" / "requirements.md"
KYIV = ZoneInfo("Europe/Kyiv")

BASE_URL = "https://fapi.binance.com"
VERIFY_CMD = "mvn -q -DskipTests test-compile"
PREMIUM, FUNDING, SCHEDULE = "/fapi/v1/premiumIndex", "/fapi/v1/fundingRate", "/fapi/v1/tradingSchedule"
PKG = "com.example.binanceFutures.response"
MARK_MODEL = f"{PKG}.FuturesMarkPriceInfo"
FUNDING_MODEL = f"{PKG}.FuturesFundingRateInfo"
SCHEDULE_MODEL = f"{PKG}.TradingScheduleResponse"
MARKET_ENUM = f"{PKG}.MarketType"
RESPONSE_DIR = "src/main/java/com/example/binanceFutures/response"
MARK_JAVA = f"{RESPONSE_DIR}/FuturesMarkPriceInfo.java"
FUNDING_JAVA = f"{RESPONSE_DIR}/FuturesFundingRateInfo.java"
MARKET_JAVA = f"{RESPONSE_DIR}/MarketType.java"
# Live key sets the scenarios are built on (probed 2026-09-30); every scenario re-probes its own as a precondition.
MARK_FIELDS = ["estimatedSettlePrice", "indexPrice", "interestRate", "lastFundingRate",
               "markPrice", "nextFundingTime", "symbol", "time"]
FUNDING_LIVE = ["fundingRate", "fundingTime", "markPrice", "rateType", "symbol"]
FUNDING_CALL = '"BTCUSDT", 3, null, null'

# Texts the specs promise verbatim (run-report, run-cli, live-capture, enum-verification).
REPORT_FIELDS = ("mode", "request_source", "response_source", "mismatch", "removed", "verify_cmd",
                 "verify_result", "iterations", "reviewer", "left_to_human", "enum_mismatch", "enum_unseen")
NO_MISMATCH = "зайві в моделі: —; бракує в моделі: —"
NOTHING_REMOVED = "нічого не видалено"
NO_ENUM_MISMATCH = "розходжень енамів немає"
DRY_RUN_RESULT = "dry-run: агента не кликали"
UNSEEN_MARK = " — не видалено"
LIVE_UNAVAILABLE = "жива відповідь недоступна"
UNKNOWN_PREFIX = "невідомий префікс"
VERDICT_KEYS = frozenset({"green", "model", "live", "extra", "missing", "owners", "client_error", "enums"})
SEVERITY = (0, 1, 3, 2, 4)  # NFR-7: 0 < 1 < 3 < 2 < 4
GATE = "premium-clean"
TOSTRING_BOGUS = r"""                ", bogusExtraField='" + bogusExtraField + '\'' +"""
TIMEOUT_RE = re.compile(r"\bstage\b\W{0,6}timeout\b")
TRACEBACK = "Traceback (most recent call last)"
FIELD_RE = re.compile(r"^- \*\*(?P<label>[^*]+)\*\* \(`(?P<name>[a-z_]+)`\): (?P<value>.*)$")
CONST_LINE = re.compile(r"[A-Z][A-Z0-9_]*\s*(?:\([^)]*\))?\s*,")


def cli_ceiling(iterations: int) -> int:
    """Harness safety net for one CLI call that should need at most `iterations` checks: per check verify_cmd
    600 + classpath 300 + javac 300 + runner 120 s (NFR-5, NFR-2), an agent call of 900 s between checks
    (NFR-3), the live call 15 s (NFR-4) and two minutes of slack. A correct run never reaches it."""
    return iterations * (600 + 300 + 300 + 120) + (iterations - 1) * 900 + 15 + 120


class Precondition(Exception):
    """The world is not in the state the scenario is built on, so running the CLI would prove nothing."""


# ----------------------------------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------------------------------

def clip(text: object, limit: int = 600) -> str:
    flat = " ⏎ ".join(part.strip() for part in str(text).strip().splitlines() if part.strip())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(path: str) -> str:
    """FR-25: outer slashes dropped, inner ones become dashes."""
    return path.strip("/").replace("/", "-")


def top_keys(body: object) -> list[str]:
    if isinstance(body, dict):
        return sorted(body)
    if isinstance(body, list):
        return sorted({key for item in body if isinstance(item, dict) for key in item})
    return []


def id_key(req: str) -> tuple:
    prefix, _, number = req.rpartition("-")
    return {"FR": 0, "NFR": 1}.get(prefix, 2), prefix, int(number) if number.isdigit() else 0


def parse_iso(value: object) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------------------
# Requirements (single source of truth for the e2e contract and for NFR-15's versions)
# ----------------------------------------------------------------------------------------------------------

def requirement_rows() -> list[tuple[str, str]]:
    """Every table row that starts with an FR/NFR id. The same id heads more than one row (section 5.8 restates
    FR-23 and FR-51 as clarifications), so rows are judged one by one, as check-acceptance-methods does."""
    rows = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*((?:FR|NFR)-\d+)\s*\|", line)
        if match:
            rows.append((match[1], line))
    return rows


def e2e_requirements() -> list[str]:
    return sorted({req for req, line in requirement_rows() if re.search(r"verify:[^|]*\be2e\b", line)}, key=id_key)


def nfr15() -> dict[str, str | None]:
    row = next((line for req, line in requirement_rows() if req == "NFR-15" and "verify:" in line), "")

    def pick(label: str) -> str | None:
        match = re.search(label + r" (\d+(?:\.\d+)+)", row)
        return match[1] if match else None

    return {"os": "macOS" if "macOS" in row else None, "python": pick("Python"), "java": pick("Java"),
            "maven": pick("Maven"), "claude": pick("Claude Code CLI")}


def probe_versions() -> tuple[dict, dict]:
    def output(cmd: list[str]) -> str:
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return (done.stdout + done.stderr).strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"<{type(exc).__name__}: {exc}>"

    raw = {"python3 --version": output(["python3", "--version"]), "java -version": output(["java", "-version"]),
           "mvn -v": output(["mvn", "-v"]), "claude --version": output(["claude", "--version"]),
           "which": {tool: shutil.which(tool) for tool in ("python3", "java", "javac", "mvn", "claude")}}

    def pick(key: str, pattern: str) -> str | None:
        match = re.search(pattern, raw[key], re.M)
        return match[1] if match else None

    parsed = {"os": platform.system(), "os_version": platform.mac_ver()[0] or platform.release(),
              "arch": platform.machine(), "python": pick("python3 --version", r"Python (\S+)"),
              "java": pick("java -version", r'version "([^"]+)"'), "maven": pick("mvn -v", r"Apache Maven (\S+)"),
              "maven_jdk": pick("mvn -v", r"Java version: ([^,\s]+)"),
              "claude": pick("claude --version", r"^(\d+(?:\.\d+)+)")}
    return parsed, raw


# ----------------------------------------------------------------------------------------------------------
# Git, the runs/ tree and the agent witness
# ----------------------------------------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), *args]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if done.returncode:
        raise RuntimeError(f"{' '.join(cmd)}: код {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def origin_git(*args: str) -> bytes:
    """Read-only git on the human's working copy; --no-optional-locks keeps git from refreshing its index."""
    done = subprocess.run(["git", "--no-optional-locks", "-C", str(ORIGIN), *args], capture_output=True, timeout=300)
    return done.stdout if done.returncode == 0 else b"<git error: " + done.stderr.strip() + b">"


def origin_state() -> dict:
    status = origin_git("status", "--porcelain")
    return {"head": origin_git("rev-parse", "HEAD").decode(errors="replace").strip(),
            "status_sha": hashlib.sha256(status).hexdigest(),
            "diff_sha": hashlib.sha256(origin_git("diff")).hexdigest(),
            "status": status.decode(errors="replace").splitlines()}


@dataclasses.dataclass
class GitState:
    head: str
    status: list[str]  # `git status --porcelain` lines, leading space kept
    cached: list[str]  # `git diff --cached --name-only`
    diff: str          # `git diff`


def git_state(repo: Path) -> GitState:
    return GitState(head=git(repo, "rev-parse", "HEAD").strip(),
                    status=git(repo, "status", "--porcelain").splitlines(),
                    cached=git(repo, "diff", "--cached", "--name-only").splitlines(),
                    diff=git(repo, "diff"))


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """runs/-relative path -> (mtime_ns, sha256): what a CLI run wrote is whatever changed across it."""
    found = {}
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                found[path.relative_to(root).as_posix()] = (path.stat().st_mtime_ns,
                                                            hashlib.sha256(path.read_bytes()).hexdigest())
    return found


def agent_sessions(clone: Path, since: float) -> list[dict]:
    """Claude Code sessions (headless `claude -p` persists them by default) whose cwd is the clone.

    Claude Code keeps each session as ~/.claude/projects/<cwd with every non-alphanumeric char as '-'>/<id>.jsonl
    and stamps every record with `cwd`; the Bash commands the agent attempted are its `tool_use` blocks."""
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    folder = base / re.sub(r"[^A-Za-z0-9]", "-", str(clone))
    target = os.path.realpath(clone)
    found = []
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        if path.stat().st_mtime < since:
            continue
        in_clone, bash = False, []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("cwd") and os.path.realpath(str(record["cwd"])) == target:
                    in_clone = True
                message = record.get("message")
                parts = message.get("content") if isinstance(message, dict) else None
                for part in parts if isinstance(parts, list) else []:
                    if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash":
                        bash.append(str((part.get("input") or {}).get("command")))
        if in_clone:
            found.append({"session": path.stem, "bash_commands": bash})
    return found


def kill_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


# ----------------------------------------------------------------------------------------------------------
# Reading what the tool wrote (formats from the specs: run-report, field-verification FR-41)
# ----------------------------------------------------------------------------------------------------------

def verdict_lines(text: str) -> tuple[list[dict], list[dict]]:
    """One-line JSON objects in a log: runner comparison verdicts (FR-41 keys) and stage verdicts."""
    comparisons, stages = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("{") and stripped.endswith("}")):
            continue
        try:
            obj = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(obj, dict) and VERDICT_KEYS <= obj.keys():
            comparisons.append(obj)
        elif isinstance(obj, dict) and {"green", "stage", "reason"} <= obj.keys():
            stages.append(obj)
    return comparisons, stages


def enum_entry(verdict: dict, field: str) -> dict | None:
    return next((e for e in verdict.get("enums") or [] if isinstance(e, dict) and e.get("field") == field), None)


def parse_report(text: str) -> tuple[str, list[tuple[str, str]]]:
    lines = text.split("\n")
    fields = [(m["name"], m["value"]) for line in lines if (m := FIELD_RE.match(line))]
    return (lines[0] if lines else ""), fields


# ----------------------------------------------------------------------------------------------------------
# Java sources of the target library: setup edits and post-run inspection
# ----------------------------------------------------------------------------------------------------------

def line_changes(before: str, after: str) -> tuple[list[tuple[int, list[str]]], list[tuple[int, list[str]]]]:
    """(inserted, deleted) hunks between two texts; a replaced line counts as both. Positions index `before`."""
    old, new = before.split("\n"), after.split("\n")
    inserted, deleted = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            deleted.append((i1, old[i1:i2]))
        if tag in ("insert", "replace"):
            inserted.append((i1, new[j1:j2]))
    return inserted, deleted


def enum_layout(src: str) -> tuple[list[tuple[str, int]], int | None]:
    """Constants of the enum in `src` as (name, line index), and the line index of `@JsonEnumDefaultValue`."""
    lines = src.split("\n")
    start = next((i for i, line in enumerate(lines) if re.search(r"\benum\s+\w+\s*\{", line)), None)
    if start is None:
        return [], None
    constants, sentinel = [], None
    for index in range(start + 1, len(lines)):
        text = lines[index].strip()
        if not text or text.startswith("//"):
            continue
        if text.startswith("@JsonEnumDefaultValue"):
            sentinel = index
            text = text[len("@JsonEnumDefaultValue"):].strip()
            if not text:
                continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*(?:\(.*\))?\s*([,;]?)\s*(?://.*)?", text)
        if not match:
            break
        constants.append((match[1], index))
        if match[2] == ";":
            break
    return constants, sentinel


def enum_names(src: str) -> list[str]:
    return [name for name, _ in enum_layout(src)[0]]


def enum_insertions(before: str, after: str) -> tuple[bool, str]:
    """FR-55: only constant lines added, after the last real constant and before the sentinel; nothing removed."""
    inserted, deleted = line_changes(before, after)
    constants, sentinel = enum_layout(before)
    if deleted:
        at, lines = deleted[0]
        return False, f"вилучено або змінено рядки (перший — рядок {at + 1}: {' ⏎ '.join(lines)})"
    if not inserted:
        return False, "жодного рядка не додано"
    if sentinel is None:
        return False, "до прогону в енамі немає @JsonEnumDefaultValue"
    real = [index for _, index in constants if index < sentinel]
    if not real:
        return False, "до прогону в енамі немає справжніх констант"
    low, high = real[-1], sentinel
    misplaced = [at for at, _ in inserted if not low < at <= high]
    foreign = [line for _, lines in inserted for line in lines if line.strip() and not CONST_LINE.fullmatch(line.strip())]
    added = ", ".join(line.strip() for _, lines in inserted for line in lines if line.strip())
    if misplaced or foreign:
        return False, f"додано {added}; не на місці (перед рядком {[m + 1 for m in misplaced]}) або не константа: {foreign}"
    return True, f"додано {added} між рядками {low + 1} і {high + 1} (до прогону)"


def tostring_body(src: str) -> str:
    match = re.search(r"\bString\s+toString\s*\(\s*\)\s*\{", src)
    if not match:
        return ""
    end = re.search(r"^    \}\s*$", src[match.end():], re.M)
    return src[match.end(): match.end() + end.start()] if end else src[match.end():]


def java_property(src: str, name: str) -> dict[str, bool]:
    cap = name[:1].upper() + name[1:]
    return {"поле": re.search(rf"^\s*private\s+[\w.<>\[\], ?]+\s+{name}\s*;", src, re.M) is not None,
            "гетер": re.search(rf"\b(?:get|is){cap}\s*\(\s*\)", src) is not None,
            "сетер": re.search(rf"\bset{cap}\s*\(", src) is not None,
            "рядок у toString": re.search(rf"\b{name}\b", tostring_body(src)) is not None}


def _hits(lines: list[str], test: Callable[[str], object], what: str) -> list[int]:
    found = [index for index, line in enumerate(lines) if test(line)]
    if not found:
        raise Precondition(f"у файлі немає {what}")
    return found


def add_bogus_field(src: str) -> str:
    """bogusExtraField: String with getter, setter and a toString line, written like its neighbours. Pure
    insertions, so an exact revert is a pure deletion."""
    lines = src.split("\n")
    field = _hits(lines, lambda l: re.fullmatch(r"    private [\w<>, ]+ \w+;", l), "оголошень полів")[-1]
    setter = _hits(lines, lambda l: re.fullmatch(r"    public void set\w+\(.*\) \{", l), "сетерів")[-1]
    setter_end = next((i for i in range(setter + 1, len(lines)) if lines[i] == "    }"), None)
    close = _hits(lines, lambda l: l.strip() == "'}';", "закриття toString")[-1]
    if setter_end is None or not field < setter_end < close:
        raise Precondition("порядок поля, сетерів і toString не такий, як очікує сценарій")
    lines[close:close] = [TOSTRING_BOGUS]
    lines[setter_end + 1:setter_end + 1] = [
        "", "    public String getBogusExtraField() {", "        return bogusExtraField;", "    }",
        "", "    public void setBogusExtraField(String bogusExtraField) {",
        "        this.bogusExtraField = bogusExtraField;", "    }"]
    lines[field + 1:field + 1] = ["", "    private String bogusExtraField;"]
    return "\n".join(lines)


def remove_field(name: str, java_type: str) -> Callable[[str], str]:
    """A setup edit that drops one property - field, getter, setter, toString line - with pure deletions."""
    cap = name[:1].upper() + name[1:]

    def transform(src: str) -> str:
        lines = src.split("\n")
        drop: set[int] = set()

        def block(signature: str, what: str) -> None:
            start = _hits(lines, lambda l: l == signature, what)[0]
            end = next((i for i in range(start + 1, len(lines)) if lines[i] == "    }"), None)
            if end is None:
                raise Precondition(f"не знайдено кінця: {what}")
            drop.update(range(start, end + 1))
            if end + 1 < len(lines) and lines[end + 1] == "":
                drop.add(end + 1)

        field = _hits(lines, lambda l: l == f"    private {java_type} {name};", f"поля {name}")[0]
        drop.add(field)
        if field + 1 < len(lines) and lines[field + 1] == "":
            drop.add(field + 1)
        block(f"    public {java_type} get{cap}() {{", f"гетера {name}")
        block(f"    public void set{cap}({java_type} {name}) {{", f"сетера {name}")
        drop.update(_hits(lines, lambda l: f'", {name}=' in l, f"рядка {name} у toString"))
        return "\n".join(line for index, line in enumerate(lines) if index not in drop)

    return transform


def add_invented_constant(src: str) -> str:
    """ZZ_INVENTED right after the last real constant, before the sentinel (pure insertion)."""
    lines = src.split("\n")
    constants, sentinel = enum_layout(src)
    real = [index for _, index in constants if sentinel is not None and index < sentinel]
    if not real or not lines[real[-1]].rstrip().endswith(","):
        raise Precondition("у MarketType немає запасника або остання справжня константа не закінчується комою")
    lines.insert(real[-1] + 1, "    ZZ_INVENTED,")
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------------
# Registries (TOML; tomllib only reads, so the harness writes and round-trips them itself)
# ----------------------------------------------------------------------------------------------------------

def toml_str(value: str) -> str:
    if ('"' in value or "\\" in value) and "'" not in value and not re.search(r"[\x00-\x1f\x7f]", value):
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False)


def toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return toml_str(value)
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_key(k)} = {toml_value(v)}" for k, v in value.items()) + " }" if value else "{}"
    raise TypeError(f"TOML value of type {type(value).__name__}")


def premium_method() -> dict:
    return {"path": PREMIUM, "model": MARK_MODEL, "client_method": "getMarkPrice", "args": {"symbol": "BTCUSDT"}}


def funding_method() -> dict:
    return {"path": FUNDING, "model": FUNDING_MODEL, "client_method": "getFundingRates",
            "args": {"symbol": "BTCUSDT", "limit": 3}, "call": FUNDING_CALL}


def schedule_method() -> dict:
    return {"path": SCHEDULE, "model": SCHEDULE_MODEL, "client_method": "getTradingSchedule"}


# ----------------------------------------------------------------------------------------------------------
# Scenario model
# ----------------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Check:
    name: str
    ids: tuple[str, ...]
    ok: bool
    expected: str
    observed: str


@dataclasses.dataclass
class Row:
    name: str
    ids: tuple[str, ...]
    expected: str
    verdict: str   # PASS | FAIL | NOT RUN
    observed: str
    evidence: str  # repo-relative directory or "—"
    when: str      # ISO time of the run behind the verdict
    carried: bool = False
    notes: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Scenario:
    name: str
    fn: Callable
    ids: tuple[str, ...]
    expected: str
    agent: bool
    guard: bool


@dataclasses.dataclass
class Harness:
    tmp: Path
    started: dt.datetime
    lib_commit: str
    lib_branch: str
    tool_commit: str
    versions: dict
    raw_versions: dict
    fingerprint: str
    origin_before: dict


@dataclasses.dataclass
class CliRun:
    label: str
    argv: list[str]
    started: dt.datetime
    exit_code: int | None  # None: stopped at the harness ceiling
    seconds: float
    stdout: str
    stderr: str
    before: GitState
    after: GitState
    written: dict[str, Path]  # runs/-relative path -> evidence copy
    sessions: list[dict]

    def lines(self) -> list[str]:
        return [line.rstrip() for line in self.stdout.splitlines() if line.strip()]

    def method_lines(self) -> list[str]:
        return [line for line in self.lines() if line.startswith("/")]

    def text(self, relpath: str) -> str | None:
        path = self.written.get(relpath)
        return path.read_text(encoding="utf-8", errors="replace") if path else None

    def slug_files(self, slug_: str) -> list[str]:
        prefix = slug_ + "/"
        return sorted(r[len(prefix):] for r in self.written if r.startswith(prefix))

    def iteration_numbers(self, slug_: str) -> list[int]:
        return sorted(int(m[1]) for name in self.slug_files(slug_) if (m := re.fullmatch(r"iteration-(\d+)\.log", name)))

    def iterations_of(self, path: str) -> int | None:
        for line in self.method_lines():
            fields = line.split()
            if len(fields) == 4 and fields[0] == path and (m := re.fullmatch(r"ітерацій=(\d+)", fields[2])):
                return int(m[1])
        return None


@dataclasses.dataclass(frozen=True)
class Verified:
    """Method line of a method that reached verification: exactly four whitespace-separated fields (FR-19)."""
    path: str
    result: str
    iterations: int | None  # None: at least two (the agent had to act)

    def matches(self, line: str) -> bool:
        fields = line.split()
        if len(fields) != 4 or fields[:2] != [self.path, "refresh"] or fields[3] != f"перевірка={self.result}":
            return False
        match = re.fullmatch(r"ітерацій=(\d+)", fields[2])
        return bool(match) and (int(match[1]) >= 2 if self.iterations is None else int(match[1]) == self.iterations)

    def describe(self) -> str:
        count = "N≥2" if self.iterations is None else self.iterations
        return f"{self.path} refresh ітерацій={count} перевірка={self.result}"


@dataclasses.dataclass(frozen=True)
class Stopped:
    """Method line of a method stopped before verification: the path and the reason, no iteration fields."""
    path: str
    needles: tuple[str, ...]

    def matches(self, line: str) -> bool:
        return (line.startswith(self.path + " ") and all(n in line for n in self.needles)
                and "ітерацій=" not in line and "перевірка=" not in line)

    def describe(self) -> str:
        return f"{self.path} … " + " … ".join(f"«{n}»" for n in self.needles)


SCENARIOS: list[Scenario] = []
_TRACES = {m[2]: tuple(re.split(r"\s*,\s*", m[1].strip()))
           for m in re.finditer(r'^# @trace ([^\n]+)\n@scenario\("([\w-]+)"', Path(__file__).read_text("utf-8"), re.M)}


def scenario(name: str, *, agent: bool = False, guard: bool = False) -> Callable:
    def register(fn: Callable) -> Callable:
        if name not in _TRACES:
            raise SystemExit(f"harness: над @scenario(\"{name}\") немає рядка «# @trace …»")
        SCENARIOS.append(Scenario(name, fn, _TRACES[name], " ".join((fn.__doc__ or "").split()), agent, guard))
        return fn
    return register


class Ctx:
    """One scenario's workspace: its clone, its evidence directory, its checks."""

    def __init__(self, scen: Scenario, harness: Harness) -> None:
        self.scen, self.h = scen, harness
        self.clone = SANDBOX / scen.name
        self.evidence = EVIDENCE / scen.name
        self.checks: list[Check] = []
        self.notes: list[str] = []
        self.runs: list[CliRun] = []

    # -- recording ------------------------------------------------------------------------------------------
    def check(self, name: str, ids: Iterable[str], ok: object, expected: object, observed: object) -> bool:
        ids = tuple(ids)
        stray = sorted(set(ids) - set(self.scen.ids))
        if stray:
            raise AssertionError(f"перевірка «{name}» посилається на {stray}, яких немає в @trace {self.scen.name}")
        self.checks.append(Check(name, ids, bool(ok), clip(expected, 4000), clip(observed, 4000)))
        return bool(ok)

    # -- the world ------------------------------------------------------------------------------------------
    def live(self, url: str) -> tuple[int, object]:
        request = urllib.request.Request(url, headers={"User-Agent": "method-sync-v2-e2e-harness"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except (OSError, ValueError) as exc:
            raise Precondition(f"{url}: {exc}") from exc

    def need_live_keys(self, url: str, keys: list[str]) -> None:
        status, body = self.live(url)
        if status != 200 or top_keys(body) != sorted(keys):
            raise Precondition(f"{url} → HTTP {status}, ключі {top_keys(body)}; сценарій побудовано на {sorted(keys)}")

    def need_fx(self) -> None:
        status, body = self.live(BASE_URL + SCHEDULE)
        keys = sorted((body or {}).get("marketSchedules") or {}) if isinstance(body, dict) else []
        if status != 200 or "FX" not in keys:
            raise Precondition(f"{BASE_URL}{SCHEDULE} → HTTP {status}, ключі marketSchedules {keys}: FX немає")

    def need_refused(self, host: str, port: int) -> None:
        with socket.socket() as probe:
            probe.settimeout(3)
            try:
                probe.connect((host, port))
            except OSError:
                return
        raise Precondition(f"на {host}:{port} хтось слухає — недосяжної адреси не вийде")

    def fresh_clone(self) -> None:
        if self.clone.parent != SANDBOX or not SANDBOX.is_relative_to(REPO / ".sandbox"):
            raise AssertionError(f"клон поза .sandbox/: {self.clone}")
        if self.clone.exists():
            shutil.rmtree(self.clone)
        SANDBOX.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(["git", "clone", "--quiet", str(ORIGIN), str(self.clone)],
                              capture_output=True, text=True, timeout=600)
        if done.returncode:
            raise Precondition(f"git clone {ORIGIN}: {done.stderr.strip()}")
        head = git(self.clone, "rev-parse", "HEAD").strip()
        if head != self.h.lib_commit:
            raise Precondition(f"HEAD клону {head} ≠ HEAD {ORIGIN} {self.h.lib_commit}")
        if not (self.clone / ".claude/skills/add-binance-rest-endpoint/SKILL.md").is_file():
            raise Precondition("у клоні немає стандарту стилю .claude/skills/add-binance-rest-endpoint/SKILL.md")
        risky = [p for p in git(self.clone, "ls-files").splitlines()
                 if re.search(r"(^|/)(config\.properties|\.env[^/]*|[^/]*\.secret|id_rsa|[^/]*\.p12)$", p)]
        if risky:
            raise Precondition(f"у клоні є файли з іменами секретів: {risky}")

    def read(self, relpath: str) -> str:
        return (self.clone / relpath).read_text(encoding="utf-8")

    def edit(self, relpath: str, transform: Callable[[str], str]) -> str:
        before = self.read(relpath)
        after = transform(before)
        if after == before:
            raise Precondition(f"правка {relpath} нічого не змінила")
        (self.clone / relpath).write_text(after, encoding="utf-8")
        return after

    def need_absent(self, relpath: str, names: list[str]) -> None:
        present = [n for n in names if java_property(self.read(relpath), n)["поле"]]
        if present:
            raise Precondition(f"{relpath} у клоні вже має {present} — розходження немає")

    def registry(self, methods: list[dict], base_url: str = BASE_URL) -> Path:
        doc = {"lib": str(self.clone), "verify_cmd": VERIFY_CMD, "live": {"base_url": base_url}, "method": methods}
        lines = [f"lib = {toml_str(doc['lib'])}", f"verify_cmd = {toml_str(VERIFY_CMD)}", "",
                 "[live]", f"base_url = {toml_str(base_url)}"]
        for method in methods:
            lines += ["", "[[method]]", *(f"{toml_key(k)} = {toml_value(v)}" for k, v in method.items())]
        text = "\n".join(lines) + "\n"
        if tomllib.loads(text) != doc:
            raise AssertionError(f"реєстр {self.scen.name} не відтворюється через tomllib")
        path = self.h.tmp / f"{self.scen.name}.toml"
        path.write_text(text, encoding="utf-8")
        return path

    # -- the CLI --------------------------------------------------------------------------------------------
    def cli(self, registry: Path, *flags: str, label: str = "run", budget: int = 1) -> CliRun:
        out = self.evidence / label
        out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(registry, out / "registry.toml")
        argv = ["python3", "-m", "method_sync", "--registry", str(registry), *flags]
        env = dict(os.environ, PYTHONPATH="src")
        before = git_state(self.clone)
        runs_before = snapshot(RUNS)
        started, since, t0 = now_utc(), time.time() - 1, time.monotonic()
        ceiling = cli_ceiling(budget)
        print(f"[e2e]   {self.scen.name}/{label}: PYTHONPATH=src {' '.join(argv)}", flush=True)
        with open(out / "cli-stdout.txt", "wb") as stdout, open(out / "cli-stderr.txt", "wb") as stderr:
            proc = subprocess.Popen(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=stdout,
                                    stderr=stderr, start_new_session=True)
            try:
                code: int | None = proc.wait(timeout=ceiling)
            except subprocess.TimeoutExpired:
                kill_group(proc)
                code = None
            except BaseException:
                kill_group(proc)
                raise
        seconds = time.monotonic() - t0
        after = git_state(self.clone)
        runs_after = snapshot(RUNS)
        written = {}
        for relpath in sorted(p for p, sig in runs_after.items() if runs_before.get(p) != sig):
            copy = out / "runs" / relpath
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RUNS / relpath, copy)
            written[relpath] = copy
        sessions = agent_sessions(self.clone, since)
        (out / "command.txt").write_text(
            f"cwd: {REPO}\nenv: PYTHONPATH=src\nargv: {' '.join(argv)}\nexit: {code}\n"
            f"seconds: {seconds:.1f}\nharness ceiling: {ceiling} s\nstarted: {started.isoformat(timespec='seconds')}\n",
            encoding="utf-8")
        for name, lines in (("lib-status-before.txt", before.status), ("lib-status-after.txt", after.status),
                            ("lib-cached-before.txt", before.cached), ("lib-cached-after.txt", after.cached)):
            (out / name).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        (out / "lib-before.diff").write_text(before.diff, encoding="utf-8")
        (out / "lib.diff").write_text(after.diff, encoding="utf-8")
        write_json(out / "agent-sessions.json", sessions)
        run = CliRun(label, argv, started, code, seconds,
                     (out / "cli-stdout.txt").read_text(encoding="utf-8", errors="replace"),
                     (out / "cli-stderr.txt").read_text(encoding="utf-8", errors="replace"),
                     before, after, written, sessions)
        self.runs.append(run)
        print(f"[e2e]   {self.scen.name}/{label}: код {code}, {seconds:.1f} с, сесій агента {len(sessions)}", flush=True)
        return run

    # -- expectations ---------------------------------------------------------------------------------------
    def expect_exit(self, run: CliRun, code: int, ids: Iterable[str]) -> bool:
        observed = "зупинено на стелі часу harness" if run.exit_code is None else str(run.exit_code)
        if run.exit_code != code and last_line(run.stderr):
            observed += f"; stderr: {last_line(run.stderr)}"
        return self.check(f"код виходу {code}", ids, run.exit_code == code, code, observed)

    def expect_method_lines(self, run: CliRun, specs: list, ids: Iterable[str]) -> bool:
        lines = run.method_lines()
        ok = len(lines) == len(specs) and all(spec.matches(line) for spec, line in zip(specs, lines))
        return self.check("рядки методів у stdout, у порядку реєстру", ids, ok,
                          " ⏎ ".join(spec.describe() for spec in specs), " ⏎ ".join(lines) or "рядків методів немає")

    def expect_summary(self, run: CliRun, total: int, green: int, ids: Iterable[str]) -> bool:
        want = f"підсумок: {total} методів, {green} зелених, {total - green} червоних"
        got = run.lines()[-1] if run.lines() else ""
        return self.check("останній рядок stdout — підсумок", ids, got == want, want, got or "stdout порожній")

    def expect_iteration_logs(self, run: CliRun, slug_: str, count: int, ids: Iterable[str]) -> bool:
        want = [f"iteration-{i}.log" for i in range(1, count + 1)]
        got = [f"iteration-{i}.log" for i in run.iteration_numbers(slug_)]
        return self.check(f"цей прогін записав логи ітерацій 1…{count}", ids, got == want,
                          ", ".join(want), ", ".join(got) or "жодного")

    def expect_agent_calls(self, run: CliRun, count: int, ids: Iterable[str]) -> bool:
        sessions = ", ".join(s["session"] for s in run.sessions)
        return self.check(f"сесій агента з cwd = клон: {count}", ids, len(run.sessions) == count,
                          f"{count} (транскрипти Claude Code)", f"{len(run.sessions)}" + (f": {sessions}" if sessions else ""))

    def expect_fixture(self, run: CliRun, slug_: str, path: str, args: dict, ids: Iterable[str]) -> bool:
        name = "фікстура живої відповіді: path, args, HTTP 200, body з ключами, captured_at в UTC"
        want = f"runs/{slug_}/fixture.json цього прогону: path={path}, args={args}, http_status=200"
        text = run.text(f"{slug_}/fixture.json")
        if text is None:
            return self.check(name, ids, False, want, "цей прогін фікстури не записав")
        try:
            fixture = json.loads(text)
        except ValueError as exc:
            return self.check(name, ids, False, want, f"не JSON: {exc}")
        problems = [f"{key}={fixture.get(key)!r}" for key, value in (("path", path), ("args", args), ("http_status", 200))
                    if fixture.get(key) != value]
        keys = top_keys(fixture.get("body"))
        if not keys:
            problems.append("body без жодного ключа об'єкта")
        captured = parse_iso(fixture.get("captured_at"))
        if captured is None or captured.utcoffset() != dt.timedelta(0):
            problems.append(f"captured_at={fixture.get('captured_at')!r} не ISO-8601 UTC")
        elif captured < run.started - dt.timedelta(seconds=5):
            problems.append(f"captured_at {captured.isoformat()} раніший за старт прогону")
        return self.check(name, ids, not problems, want, "; ".join(problems) or f"body: ключі {', '.join(keys)}")

    def expect_no_writes(self, run: CliRun, slug_: str, name: str, ids: Iterable[str]) -> bool:
        return self.check(f"цей прогін не лишив runs/{slug_}/{name}", ids, run.text(f"{slug_}/{name}") is None,
                          "файл не записано і не змінено", "записано" if run.text(f"{slug_}/{name}") is not None else "не записано")

    def expect_no_verification(self, run: CliRun, slug_: str, ids: Iterable[str]) -> bool:
        traces = [n for n in run.slug_files(slug_) if n == "report.md" or n.startswith("iteration-")]
        return self.check("перевірки не було: ні логів ітерацій, ні звіту", ids, not traces,
                          "нічого з iteration-*.log і report.md", ", ".join(traces) or "нічого")

    def verdict(self, run: CliRun, slug_: str, number: int, ids: Iterable[str]) -> dict | None:
        name = f"раннер дав вердикт звіряння (iteration-{number}.log)"
        text = run.text(f"{slug_}/iteration-{number}.log")
        if text is None:
            self.check(name, ids, False, f"runs/{slug_}/iteration-{number}.log з рядком-вердиктом",
                       f"цей прогін не записав iteration-{number}.log")
            return None
        comparisons, stages = verdict_lines(text)
        if not comparisons:
            observed = "; ".join(f"stage={s.get('stage')}: {s.get('reason')}" for s in stages)
            self.check(name, ids, False, "рядок JSON з ключами " + ", ".join(sorted(VERDICT_KEYS)),
                       observed or f"рядка-вердикту немає; останній рядок логу: {last_line(text)}")
            return None
        found = comparisons[-1]
        self.check(name, ids, True, "рядок-вердикт є", f"green={found.get('green')}")
        return found

    def expect_runner_exited(self, run: CliRun, slug_: str, ids: Iterable[str]) -> bool:
        numbers = run.iteration_numbers(slug_)
        stuck = [n for n in numbers if TIMEOUT_RE.search(run.text(f"{slug_}/iteration-{n}.log") or "")]
        observed = f"стадія timeout в ітераціях {stuck}" if stuck else ("логів ітерацій немає" if not numbers else "timeout немає")
        return self.check("раннер завершувався сам (жодної стадії timeout)", ids, bool(numbers) and not stuck,
                          "логи ітерацій без стадії timeout", observed)

    def report(self, run: CliRun, slug_: str, ids: Iterable[str]) -> dict[str, str] | None:
        name = f"звіт runs/{slug_}/report.md записано: заголовок і 12 полів FR-78 у порядку"
        text = run.text(f"{slug_}/report.md")
        if text is None:
            self.check(name, ids, False, "report.md цього прогону", "цей прогін звіту не записав")
            return None
        title, fields = parse_report(text)
        names = [n for n, _ in fields]
        ok = title == f"# Звіт прогону — {slug_}" and names == list(REPORT_FIELDS)
        self.check(name, ids, ok, f"# Звіт прогону — {slug_}; поля {', '.join(REPORT_FIELDS)}",
                   f"{title}; поля {', '.join(names) or 'жодного'}")
        return dict(fields)

    def expect_field(self, report: dict[str, str], field: str, ids: Iterable[str], equals: str) -> bool:
        got = report.get(field)
        return self.check(f"звіт: {field}", ids, got == equals, equals, "поля немає" if got is None else got)

    def expect_lib_unchanged(self, run: CliRun, ids: Iterable[str]) -> bool:
        same = run.before.status == run.after.status and run.before.diff == run.after.diff and run.before.cached == run.after.cached
        return self.check("копія бібліотеки та сама: git status, diff і diff --cached як до прогону", ids, same,
                          f"status {run.before.status or '[]'}, diff {len(run.before.diff)} байт",
                          f"status {run.after.status or '[]'}, diff {len(run.after.diff)} байт")

    def expect_changed(self, run: CliRun, allowed: set[str], exact: bool, ids: Iterable[str]) -> bool:
        paths = sorted({line[3:] for line in run.after.status})
        ok = set(paths) == allowed if exact else set(paths) <= allowed
        return self.check("змінено лише " + ", ".join(sorted(allowed)), ids, ok,
                          ("рівно " if exact else "не більше ніж ") + ", ".join(sorted(allowed)), ", ".join(paths) or "нічого")

    def expect_line_changes(self, before: str, after: str, only: str, relpath: str, ids: Iterable[str]) -> bool:
        inserted, deleted = line_changes(before, after)
        wrong, needed = (deleted, inserted) if only == "insert" else (inserted, deleted)
        added, removed = sum(len(l) for _, l in inserted), sum(len(l) for _, l in deleted)
        observed = f"додано {added}, вилучено {removed} рядків"
        if wrong:
            observed += f"; перше порушення біля рядка {wrong[0][0] + 1}: {' ⏎ '.join(wrong[0][1])}"
        what = "лише доданими рядками" if only == "insert" else "лише вилученням рядків"
        return self.check(f"{relpath.rsplit('/', 1)[-1]} змінено {what} відносно стану до прогону", ids,
                          bool(needed) and not wrong, what, observed)

    def converged(self, run: CliRun, path: str, slug_: str, ids: list[str]) -> int | None:
        """Exit 0 after the loop: a green line with N >= 2 checks, the summary, logs 1..N, N-1 agent sessions."""
        self.expect_exit(run, 0, ["NFR-6", *ids])
        self.expect_method_lines(run, [Verified(path, "green", None)], ["FR-19", *ids])
        self.expect_summary(run, 1, 1, ["FR-19"])
        count = run.iterations_of(path)
        if count is not None:
            self.expect_iteration_logs(run, slug_, count, ["FR-64"])
            self.expect_agent_calls(run, count - 1, ["FR-60", *ids])
        return count

    def last_green(self, run: CliRun, slug_: str, count: int | None, ids: list[str]) -> dict | None:
        if count is None:
            return None
        final = self.verdict(run, slug_, count, ids)
        if final:
            self.check("остання перевірка зелена", ids, final.get("green") is True and final.get("client_error") is None,
                       "green=true, client_error=null", f"green={final.get('green')}, client_error={final.get('client_error')!r}")
        return final

    def common(self, run: CliRun) -> None:
        """Every CLI run: the index stays empty, library tests untouched and not run, history intact, no crash."""
        self.check("індекс копії порожній до і після прогону", ["NFR-10"], run.before.cached == [] == run.after.cached,
                   "git diff --cached --name-only порожній до і після", f"до {run.before.cached}, після {run.after.cached}")
        tests = [line for line in run.after.status if line[3:].startswith("src/test/")]
        self.check("тести бібліотеки не змінено", ["FR-93"], not tests, "у git status немає src/test/", "; ".join(tests) or "немає")
        reports = [p for p in ("target/surefire-reports", "target/failsafe-reports") if (self.clone / p).exists()]
        self.check("тести бібліотеки не запускались", ["FR-93"], not reports,
                   "немає target/surefire-reports і target/failsafe-reports", ", ".join(reports) or "немає")
        self.check("історія копії та сама (HEAD, жодного коміту)", ["FR-90"],
                   run.before.head == run.after.head == self.h.lib_commit, self.h.lib_commit[:12], run.after.head[:12])
        crashed = TRACEBACK in run.stdout or TRACEBACK in run.stderr
        self.check("у stdout і stderr немає Python Traceback", ["NFR-6"], not crashed, "немає", "є" if crashed else "немає")


# ----------------------------------------------------------------------------------------------------------
# Scenarios - the evidence set. Run order = definition order: cheap ones first, the agent ones after the gate.
# ----------------------------------------------------------------------------------------------------------

# @trace NFR-15
@scenario("environment", guard=True)
def environment(ctx: Ctx) -> None:
    """Середовище власника за NFR-15: macOS; Python, Java, Maven і Claude Code CLI тих версій, що записані у вимозі (версії читаються з рядка NFR-15)."""
    expected, seen = nfr15(), ctx.h.versions
    ctx.check("ОС — macOS", ["NFR-15"], expected["os"] == "macOS" and seen["os"] == "Darwin", "macOS",
              f"{seen['os']} {seen['os_version']} ({seen['arch']})")
    for key, label in (("python", "Python"), ("java", "Java"), ("maven", "Maven"), ("claude", "Claude Code CLI")):
        ctx.check(f"{label} як у NFR-15", ["NFR-15"], expected[key] is not None and seen[key] == expected[key],
                  expected[key] or "у рядку NFR-15 не знайдено", seen[key] or "не визначено")
    if seen.get("maven_jdk") and seen["maven_jdk"] != seen["java"]:
        ctx.notes.append(f"Maven працює на JDK {seen['maven_jdk']} (JAVA_HOME не задано), а javac і java з PATH — {seen['java']}")
    if os.environ.get("CLAUDECODE"):
        ctx.notes.append("harness запущено зсередини сесії Claude Code (CLAUDECODE задано): агент інструмента успадкує змінні "
                         "хост-сесії; доказовий прогін — з термінала власника")
    write_json(ctx.evidence / "versions.json", {"parsed": seen, "raw": ctx.h.raw_versions, "nfr15": expected})


# @trace FR-19, FR-23, FR-24, FR-33, FR-34, FR-36, FR-39, FR-42, FR-44, FR-56, FR-63, FR-64, FR-77, FR-78, FR-79, FR-81, FR-90, FR-93, NFR-6, NFR-8, NFR-9, NFR-10
@scenario("premium-clean")
def premium_clean(ctx: Ctx) -> None:
    """Метод без розходжень: код 0, одна ітерація, агента немає; фікстура живої відповіді; вердикт раннера зелений — поля моделі — 8 властивостей Jackson `FuturesMarkPriceInfo`, extra і missing порожні, client_error null; звіт із порожніми розходженнями; `git status` копії як до прогону; другий прогін поспіль — `ітерацій=1` і той самий порожній `git diff`."""
    ctx.need_live_keys(f"{BASE_URL}{PREMIUM}?symbol=BTCUSDT", MARK_FIELDS)
    ctx.fresh_clone()
    registry = ctx.registry([premium_method()])
    key = slug(PREMIUM)
    first = ctx.cli(registry, label="run-1", budget=1)
    ctx.expect_exit(first, 0, ["NFR-6", "FR-63"])
    ctx.expect_method_lines(first, [Verified(PREMIUM, "green", 1)], ["FR-19", "FR-63"])
    ctx.expect_summary(first, 1, 1, ["FR-19"])
    ctx.expect_iteration_logs(first, key, 1, ["FR-63", "FR-64"])
    ctx.expect_agent_calls(first, 0, ["FR-63"])
    ctx.expect_fixture(first, key, PREMIUM, {"symbol": "BTCUSDT"}, ["FR-23", "FR-24"])
    verdict = ctx.verdict(first, key, 1, ["FR-33"])
    if verdict:
        owners = verdict.get("owners")
        ctx.check("вердикт зелений: extra і missing порожні", ["FR-39"],
                  verdict.get("green") is True and verdict.get("extra") == [] and verdict.get("missing") == [],
                  "green=true, extra=[], missing=[]",
                  f"green={verdict.get('green')}, extra={verdict.get('extra')}, missing={verdict.get('missing')}")
        ctx.check("поля моделі — властивості Jackson FuturesMarkPriceInfo", ["FR-36"], verdict.get("model") == MARK_FIELDS,
                  MARK_FIELDS, verdict.get("model"))
        ctx.check("owners відносить кожне поле до FuturesMarkPriceInfo", ["FR-36"],
                  isinstance(owners, dict) and sorted(owners) == MARK_FIELDS and set(owners.values()) == {MARK_MODEL},
                  f"{{поле: {MARK_MODEL}}} для 8 полів", owners)
        ctx.check("клієнт бібліотеки відпрацював виклик без винятку", ["FR-34"], verdict.get("client_error") is None,
                  "client_error=null", repr(verdict.get("client_error")))
        ctx.check("енамних полів у моделі немає", ["FR-56"], verdict.get("enums") == [], "enums=[]", verdict.get("enums"))
    ctx.expect_runner_exited(first, key, ["FR-42"])
    report = ctx.report(first, key, ["FR-77", "FR-78"])
    if report:
        ctx.expect_field(report, "mode", ["FR-78"], "refresh")
        ctx.expect_field(report, "request_source", ["FR-78"], "registry")
        ctx.expect_field(report, "response_source", ["FR-78"], str(RUNS / key / "fixture.json"))
        ctx.expect_field(report, "mismatch", ["FR-63", "FR-79"], NO_MISMATCH)
        ctx.expect_field(report, "removed", ["FR-81"], NOTHING_REMOVED)
        ctx.expect_field(report, "verify_cmd", ["FR-78"], VERIFY_CMD)
        ctx.expect_field(report, "verify_result", ["FR-63"], "green")
        ctx.expect_field(report, "iterations", ["FR-63"], "1")
        ctx.expect_field(report, "enum_mismatch", ["FR-56", "FR-63"], NO_ENUM_MISMATCH)
    ctx.expect_lib_unchanged(first, ["NFR-8", "FR-44"])
    ctx.common(first)
    if first.exit_code != 0:
        ctx.check("другий прогін поспіль", ["NFR-9"], False, "іде після першого з кодом 0",
                  "не запускався: перший прогін не завершився кодом 0")
        return
    second = ctx.cli(registry, label="run-2", budget=1)
    ctx.expect_exit(second, 0, ["NFR-9"])
    ctx.expect_method_lines(second, [Verified(PREMIUM, "green", 1)], ["NFR-9"])
    ctx.expect_agent_calls(second, 0, ["NFR-9"])
    ctx.check("git diff після другого прогону такий самий, як після першого, і порожній", ["NFR-9"],
              second.after.diff == first.after.diff == "" and second.after.status == first.after.status,
              "порожній diff, той самий status", f"diff {len(second.after.diff)} байт, status {second.after.status or '[]'}")
    ctx.common(second)


# @trace FR-18, FR-19, FR-24, FR-39, FR-64, FR-77, FR-79, FR-90, FR-93, NFR-6, NFR-10
@scenario("funding-dry-run")
def funding_dry_run(ctx: Ctx) -> None:
    """`--dry-run` на справжньому розходженні `/fapi/v1/fundingRate`: код 1; одна перевірка — `перевірка=red`; агента немає; фікстура, `iteration-1.log` і звіт записані, `verify_result` — «dry-run: агента не кликали», `mismatch` — бракує markPrice, rateType; копія без змін."""
    ctx.need_live_keys(f"{BASE_URL}{FUNDING}?symbol=BTCUSDT&limit=3", FUNDING_LIVE)
    ctx.fresh_clone()
    ctx.need_absent(FUNDING_JAVA, ["markPrice", "rateType"])
    key = slug(FUNDING)
    run = ctx.cli(ctx.registry([funding_method()]), "--dry-run", budget=1)
    ctx.expect_exit(run, 1, ["FR-18", "NFR-6"])
    ctx.expect_method_lines(run, [Verified(FUNDING, "red", 1)], ["FR-18", "FR-19"])
    ctx.expect_summary(run, 1, 0, ["FR-19"])
    ctx.expect_agent_calls(run, 0, ["FR-18"])
    ctx.expect_iteration_logs(run, key, 1, ["FR-18", "FR-64"])
    ctx.expect_fixture(run, key, FUNDING, {"symbol": "BTCUSDT", "limit": 3}, ["FR-18", "FR-24"])
    verdict = ctx.verdict(run, key, 1, ["FR-18"])
    if verdict:
        ctx.check("вердикт червоний: missing = markPrice, rateType; extra порожній", ["FR-39"],
                  verdict.get("green") is False and verdict.get("missing") == ["markPrice", "rateType"] and verdict.get("extra") == [],
                  "green=false, missing=[markPrice, rateType], extra=[]",
                  f"green={verdict.get('green')}, missing={verdict.get('missing')}, extra={verdict.get('extra')}")
    report = ctx.report(run, key, ["FR-18", "FR-77"])
    if report:
        ctx.expect_field(report, "verify_result", ["FR-18"], DRY_RUN_RESULT)
        ctx.expect_field(report, "iterations", ["FR-18"], "1")
        ctx.expect_field(report, "mismatch", ["FR-79"], "зайві в моделі: —; бракує в моделі: markPrice, rateType")
    ctx.expect_lib_unchanged(run, ["FR-18"])
    ctx.common(run)


# @trace FR-19, FR-23, FR-26, FR-27, FR-28, FR-90, FR-93, NFR-6, NFR-10
@scenario("live-unavailable")
def live_unavailable(ctx: Ctx) -> None:
    """`base_url = "http://127.0.0.1:9"` (порт ніхто не слухає): код 3; рядок методу — «жива відповідь недоступна» з URL виклику; цей прогін не лишив ні фікстури, ні логів, ні звіту; агента немає; копія без змін."""
    ctx.need_refused("127.0.0.1", 9)
    ctx.fresh_clone()
    base, key = "http://127.0.0.1:9", slug(PREMIUM)
    run = ctx.cli(ctx.registry([premium_method()], base_url=base), budget=1)
    ctx.expect_exit(run, 3, ["FR-26", "NFR-6"])
    ctx.expect_method_lines(run, [Stopped(PREMIUM, (LIVE_UNAVAILABLE, f"{base}{PREMIUM}?symbol=BTCUSDT"))], ["FR-23", "FR-26"])
    ctx.expect_summary(run, 1, 0, ["FR-19"])
    ctx.expect_no_writes(run, key, "fixture.json", ["FR-26", "FR-28"])
    ctx.expect_no_verification(run, key, ["FR-27"])
    ctx.expect_agent_calls(run, 0, ["FR-27"])
    ctx.expect_lib_unchanged(run, ["FR-27"])
    ctx.common(run)


# @trace FR-19, FR-23, FR-26, FR-27, FR-28, FR-90, FR-93, NFR-6, NFR-10
@scenario("live-scheme")
def live_scheme(ctx: Ctx) -> None:
    """`base_url` зі схемою `file://` на каталог, де за шляхом методу лежить придатний JSON: адресу відхилено до відкриття — код 3, «жива відповідь недоступна» з URL, фікстури й перевірки немає, агента немає, копія без змін."""
    ctx.fresh_clone()
    root = ctx.h.tmp / "file-scheme"
    (root / SCHEDULE.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
    (root / SCHEDULE.lstrip("/")).write_text('{"updateTime": 1}', encoding="utf-8")
    base, key = root.as_uri(), slug(SCHEDULE)
    run = ctx.cli(ctx.registry([schedule_method()], base_url=base), budget=1)
    ctx.expect_exit(run, 3, ["FR-23", "NFR-6"])
    ctx.expect_method_lines(run, [Stopped(SCHEDULE, (LIVE_UNAVAILABLE, f"{base}{SCHEDULE}"))], ["FR-23", "FR-26"])
    ctx.expect_summary(run, 1, 0, ["FR-19"])
    ctx.expect_no_writes(run, key, "fixture.json", ["FR-23", "FR-28"])
    ctx.expect_no_verification(run, key, ["FR-27"])
    ctx.expect_agent_calls(run, 0, ["FR-27"])
    ctx.expect_lib_unchanged(run, ["FR-27"])
    ctx.common(run)


# @trace FR-14, FR-15, FR-19, FR-21, FR-23, FR-26, FR-28, FR-29, FR-90, FR-93, NFR-6, NFR-7, NFR-10
@scenario("mixed-run")
def mixed_run(ctx: Ctx) -> None:
    """Один реєстр: зелений `/fapi/v1/premiumIndex`, `/xapi/v1/nothing` (невідомий префікс, код 2) і `/fapi/v1/fundingRate` з `NOSUCHSYMBOL` (біржа віддає `[]` — жива відповідь недоступна, код 3): усі три оброблено в порядку реєстру, рядок на кожен і підсумок; код процесу — найгірший за шкалою 0 < 1 < 3 < 2 < 4, тобто 2."""
    status, body = ctx.live(f"{BASE_URL}{FUNDING}?symbol=NOSUCHSYMBOL")
    if status != 200 or body != []:
        raise Precondition(f"{BASE_URL}{FUNDING}?symbol=NOSUCHSYMBOL → HTTP {status}, тіло {clip(body, 120)}; сценарій чекає 200 і []")
    ctx.need_live_keys(f"{BASE_URL}{PREMIUM}?symbol=BTCUSDT", MARK_FIELDS)
    ctx.fresh_clone()
    odd = {"path": "/xapi/v1/nothing", "model": MARK_MODEL, "client_method": "getMarkPrice", "args": {"symbol": "BTCUSDT"}}
    nosuch = {"path": FUNDING, "model": FUNDING_MODEL, "client_method": "getFundingRates", "args": {"symbol": "NOSUCHSYMBOL"}}
    run = ctx.cli(ctx.registry([premium_method(), odd, nosuch]), budget=1)
    worst = max((0, 2, 3), key=SEVERITY.index)
    ctx.expect_exit(run, worst, ["NFR-6", "NFR-7"])
    ctx.expect_method_lines(run, [Verified(PREMIUM, "green", 1), Stopped("/xapi/v1/nothing", (UNKNOWN_PREFIX,)),
                                  Stopped(FUNDING, (LIVE_UNAVAILABLE, f"{BASE_URL}{FUNDING}?symbol=NOSUCHSYMBOL"))],
                            ["FR-14", "FR-15", "FR-21", "FR-23", "FR-26"])
    ctx.expect_summary(run, 3, 1, ["FR-15", "FR-19"])
    ctx.expect_agent_calls(run, 0, ["FR-15"])
    produced = run.slug_files(slug(PREMIUM))
    ctx.check("зелений метод отримав фікстуру, лог і звіт попри сусідні невдачі", ["FR-15"],
              {"fixture.json", "iteration-1.log", "report.md"} <= set(produced),
              "fixture.json, iteration-1.log, report.md", ", ".join(produced) or "нічого")
    ctx.expect_no_writes(run, slug(FUNDING), "fixture.json", ["FR-28", "FR-29"])
    ctx.check("для /xapi/v1/nothing нічого не записано", ["FR-21"], not run.slug_files(slug("/xapi/v1/nothing")),
              "нічого", ", ".join(run.slug_files(slug("/xapi/v1/nothing"))) or "нічого")
    ctx.expect_lib_unchanged(run, ["FR-15"])
    ctx.common(run)


# @trace FR-19, FR-39, FR-60, FR-64, FR-70, FR-73, FR-77, FR-79, FR-81, FR-90, FR-93, NFR-6, NFR-10
@scenario("premium-bogus", agent=True)
def premium_bogus(ctx: Ctx) -> None:
    """У копії до `FuturesMarkPriceInfo` дописано `bogusExtraField` (поле `String`, гетер, сетер, рядок у `toString`, як сусідні): код 0 після циклу з агентом; `mismatch` — «зайві в моделі: bogusExtraField», `removed` — `bogusExtraField`; поле зникло; змінено лише цей файл і лише вилученням рядків; індекс порожній."""
    ctx.need_live_keys(f"{BASE_URL}{PREMIUM}?symbol=BTCUSDT", MARK_FIELDS)
    ctx.fresh_clone()
    before = ctx.edit(MARK_JAVA, add_bogus_field)
    key = slug(PREMIUM)
    run = ctx.cli(ctx.registry([premium_method()]), budget=5)
    count = ctx.converged(run, PREMIUM, key, ["FR-70"])
    first = ctx.verdict(run, key, 1, ["FR-39"])
    if first:
        ctx.check("перша перевірка застала extra = bogusExtraField", ["FR-39", "FR-79"],
                  first.get("green") is False and first.get("extra") == ["bogusExtraField"] and first.get("missing") == [],
                  "green=false, extra=[bogusExtraField], missing=[]",
                  f"green={first.get('green')}, extra={first.get('extra')}, missing={first.get('missing')}")
    ctx.last_green(run, key, count, ["FR-70"])
    report = ctx.report(run, key, ["FR-77"])
    if report:
        ctx.expect_field(report, "mismatch", ["FR-79"], "зайві в моделі: bogusExtraField; бракує в моделі: —")
        ctx.expect_field(report, "removed", ["FR-81"], "bogusExtraField")
        ctx.expect_field(report, "verify_result", ["FR-77"], "green")
        if count is not None:
            ctx.expect_field(report, "iterations", ["FR-77"], str(count))
    after = ctx.read(MARK_JAVA)
    left = [line.strip() for line in after.split("\n") if "ogusExtraField" in line]
    ctx.check("bogusExtraField прибрано: ні поля, ні гетера, ні сетера, ні рядка в toString", ["FR-70"], not left,
              "жодного рядка з bogusExtraField", " ⏎ ".join(left) or "жодного")
    ctx.expect_changed(run, {MARK_JAVA}, exact=False, ids=["FR-73"])
    ctx.expect_line_changes(before, after, "delete", MARK_JAVA, ["FR-73"])
    head = git(ctx.clone, "show", f"HEAD:{MARK_JAVA}")
    ctx.notes.append("FuturesMarkPriceInfo.java після прогону збігся з HEAD байт у байт" if after == head
                     else "FuturesMarkPriceInfo.java після прогону відрізняється від HEAD (див. lib.diff)")
    ctx.common(run)


# @trace FR-19, FR-34, FR-39, FR-60, FR-64, FR-69, FR-73, FR-77, FR-79, FR-81, FR-90, FR-93, NFR-6, NFR-10
@scenario("funding-drift", agent=True)
def funding_drift(ctx: Ctx) -> None:
    """Справжнє розходження: у копії `FuturesFundingRateInfo` немає `markPrice` і `rateType`, які віддає `/fapi/v1/fundingRate`; виклик — `call = '"BTCUSDT", 3, null, null'`: код 0 після циклу з агентом; `mismatch` — «бракує в моделі: markPrice, rateType»; обидва поля додано з гетером, сетером і рядком у `toString`; змінено лише цей файл і лише доданими рядками."""
    ctx.need_live_keys(f"{BASE_URL}{FUNDING}?symbol=BTCUSDT&limit=3", FUNDING_LIVE)
    ctx.fresh_clone()
    ctx.need_absent(FUNDING_JAVA, ["markPrice", "rateType"])
    before = ctx.read(FUNDING_JAVA)
    key = slug(FUNDING)
    run = ctx.cli(ctx.registry([funding_method()]), budget=5)
    count = ctx.converged(run, FUNDING, key, ["FR-69"])
    first = ctx.verdict(run, key, 1, ["FR-34"])
    if first:
        ctx.check("перша перевірка: missing = markPrice, rateType; extra порожній", ["FR-39", "FR-79"],
                  first.get("green") is False and first.get("missing") == ["markPrice", "rateType"] and first.get("extra") == [],
                  "green=false, missing=[markPrice, rateType], extra=[]",
                  f"green={first.get('green')}, missing={first.get('missing')}, extra={first.get('extra')}")
        ctx.check("виклик клієнта з `call` пройшов javac і клієнта без винятку", ["FR-34"], first.get("client_error") is None,
                  "client_error=null", repr(first.get("client_error")))
    ctx.last_green(run, key, count, ["FR-69"])
    report = ctx.report(run, key, ["FR-77"])
    if report:
        ctx.expect_field(report, "mismatch", ["FR-79"], "зайві в моделі: —; бракує в моделі: markPrice, rateType")
        ctx.expect_field(report, "removed", ["FR-81"], NOTHING_REMOVED)
        ctx.expect_field(report, "verify_result", ["FR-77"], "green")
        if count is not None:
            ctx.expect_field(report, "iterations", ["FR-77"], str(count))
    after = ctx.read(FUNDING_JAVA)
    for name in ("markPrice", "rateType"):
        parts = java_property(after, name)
        ctx.check(f"{name} додано: поле, гетер, сетер, рядок у toString", ["FR-69"], all(parts.values()), "усе є",
                  "бракує: " + ", ".join(k for k, ok in parts.items() if not ok) if not all(parts.values()) else "усе є")
    ctx.expect_changed(run, {FUNDING_JAVA}, exact=True, ids=["FR-73"])
    ctx.expect_line_changes(before, after, "insert", FUNDING_JAVA, ["FR-73"])
    ctx.common(run)


# @trace FR-19, FR-39, FR-42, FR-44, FR-46, FR-60, FR-64, FR-69, FR-73, FR-77, FR-79, FR-90, FR-93, NFR-6, NFR-10
@scenario("strict-missing", agent=True)
def strict_missing(ctx: Ctx) -> None:
    """У копії з `FuturesMarkPriceInfo` (без `ignoreUnknown`, мапер бібліотеки строгий) прибрано `time` з гетером, сетером і рядком у `toString`: клієнт кидає виняток, а звіряння все одно йде — у першому лозі `client_error` з `Unrecognized field "time"` і `missing = time`, раннер завершився сам; агент повертає поле; остання перевірка зелена; змінено лише цей файл і лише доданими рядками. Поле — `time`, а не `interestRate` з підписаного набору: гетер `interestRate` (як і решти шести полів) викликає тест бібліотеки `BinanceFuturesApiRestClientImplTest.java:261`, тож `verify_cmd` (`test-compile`) упав би на стадії `compile` і до клієнта справа не дійшла б; `getTime()` тести не викликають (перевірено компіляцією і пробою 2026-09-30)."""
    ctx.need_live_keys(f"{BASE_URL}{PREMIUM}?symbol=BTCUSDT", MARK_FIELDS)
    ctx.fresh_clone()
    before = ctx.edit(MARK_JAVA, remove_field("time", "Long"))
    key = slug(PREMIUM)
    run = ctx.cli(ctx.registry([premium_method()]), budget=5)
    count = ctx.converged(run, PREMIUM, key, ["FR-69"])
    first = ctx.verdict(run, key, 1, ["FR-42", "FR-46"])
    if first:
        error = first.get("client_error") or ""
        ctx.check("виняток клієнта у вердикті: client_error", ["FR-44", "FR-46"],
                  "UnrecognizedPropertyException" in error and 'Unrecognized field "time"' in error,
                  'client_error з UnrecognizedPropertyException: Unrecognized field "time"', repr(first.get("client_error")))
        ctx.check("звіряння пройшло попри виняток: missing = time, extra порожній", ["FR-39", "FR-46"],
                  first.get("missing") == ["time"] and first.get("extra") == [],
                  "missing=[time], extra=[]", f"missing={first.get('missing')}, extra={first.get('extra')}")
        ctx.check("вердикт із client_error червоний", ["FR-46"], first.get("green") is False, "green=false", f"green={first.get('green')}")
        # Throwable.toString() of the client carries Jackson's multi-line message: match on its first line.
        head = error.splitlines()[0] if error else ""
        log = run.text(f"{key}/iteration-1.log") or ""
        human = [line for line in log.splitlines() if head and head in line and not line.strip().startswith("{")]
        ctx.check("текст винятку є в людському лозі першої ітерації", ["FR-46"], bool(human),
                  "рядок із першим рядком client_error поза рядком-вердиктом", f"{len(human)} таких рядків")
    ctx.expect_runner_exited(run, key, ["FR-42"])
    ctx.last_green(run, key, count, ["FR-46", "FR-69"])
    report = ctx.report(run, key, ["FR-77"])
    if report:
        ctx.expect_field(report, "mismatch", ["FR-79"], "зайві в моделі: —; бракує в моделі: time")
        ctx.expect_field(report, "verify_result", ["FR-77"], "green")
        if count is not None:
            ctx.expect_field(report, "iterations", ["FR-77"], str(count))
    after = ctx.read(MARK_JAVA)
    parts = java_property(after, "time")
    ctx.check("time повернуто: поле, гетер, сетер, рядок у toString", ["FR-69"], all(parts.values()), "усе є",
              "бракує: " + ", ".join(k for k, ok in parts.items() if not ok) if not all(parts.values()) else "усе є")
    ctx.expect_changed(run, {MARK_JAVA}, exact=False, ids=["FR-73"])
    ctx.expect_line_changes(before, after, "insert", MARK_JAVA, ["FR-73"])
    head_text = git(ctx.clone, "show", f"HEAD:{MARK_JAVA}")
    ctx.notes.append("FuturesMarkPriceInfo.java після прогону збігся з HEAD байт у байт" if after == head_text
                     else "FuturesMarkPriceInfo.java після прогону відрізняється від HEAD (див. lib.diff)")
    ctx.common(run)


# @trace FR-19, FR-51, FR-55, FR-56, FR-58, FR-60, FR-64, FR-73, FR-77, FR-79, FR-90, FR-93, NFR-6, NFR-10
@scenario("schedule-fx", agent=True)
def schedule_fx(ctx: Ctx) -> None:
    """`/fapi/v1/tradingSchedule` віддає в `marketSchedules` ключ `FX`, якого немає в `MarketType`: код 0 після циклу з агентом; перша перевірка — розходження енаму `marketSchedules` (`MarketType`: `FX`); `enum_mismatch` у звіті називає його; `MarketType.java` оголошує кожне значення, якого бракувало, — лише доданими рядками після останньої справжньої константи й перед запасником `UNKNOWN`; інших файлів не змінено."""
    ctx.need_fx()
    ctx.fresh_clone()
    before = ctx.read(MARKET_JAVA)
    if "FX" in enum_names(before):
        raise Precondition("MarketType у клоні вже оголошує FX — розходження немає")
    key = slug(SCHEDULE)
    run = ctx.cli(ctx.registry([schedule_method()]), budget=5)
    count = ctx.converged(run, SCHEDULE, key, ["FR-58"])
    missing: list[str] = []
    first = ctx.verdict(run, key, 1, ["FR-51"])
    if first:
        entry = enum_entry(first, "marketSchedules")
        missing = list((entry or {}).get("missing") or [])
        ctx.check("перша перевірка: розходження енаму marketSchedules (MarketType), серед значень FX", ["FR-51"],
                  first.get("green") is False and first.get("extra") == [] and first.get("missing") == []
                  and entry is not None and entry.get("enum") == MARKET_ENUM and "FX" in missing,
                  f"green=false, поля без розходжень; marketSchedules → {MARKET_ENUM}, missing ∋ FX",
                  f"green={first.get('green')}, extra={first.get('extra')}, missing={first.get('missing')}, запис={entry}")
    ctx.last_green(run, key, count, ["FR-58"])
    report = ctx.report(run, key, ["FR-77"])
    if report:
        prefix = f"marketSchedules ({MARKET_ENUM}): "
        value = report.get("enum_mismatch") or ""
        group = next((g for g in value.split("; ") if g.startswith(prefix)), None)
        ctx.check("enum_mismatch називає marketSchedules (MarketType) і FX", ["FR-56"],
                  group is not None and "FX" in group[len(prefix):].split(", "), f"група «{prefix}…» зі значенням FX", value)
        ctx.expect_field(report, "mismatch", ["FR-79"], NO_MISMATCH)
        ctx.expect_field(report, "verify_result", ["FR-77"], "green")
        if count is not None:
            ctx.expect_field(report, "iterations", ["FR-77"], str(count))
    after = ctx.read(MARKET_JAVA)
    ctx.check("MarketType оголошує кожне значення, якого бракувало на першій перевірці", ["FR-58"],
              bool(missing) and set(missing) <= set(enum_names(after)), missing or "missing першої перевірки невідомий",
              enum_names(after))
    placed, detail = enum_insertions(before, after)
    ctx.check("MarketType.java: лише додані константи після останньої справжньої, перед запасником", ["FR-55"], placed,
              "лише додані рядки констант між останньою справжньою константою і @JsonEnumDefaultValue", detail)
    ctx.expect_changed(run, {MARKET_JAVA}, exact=True, ids=["FR-73"])
    ctx.common(run)


# @trace FR-19, FR-51, FR-53, FR-55, FR-57, FR-58, FR-60, FR-64, FR-73, FR-77, FR-90, FR-93, NFR-6, NFR-10
@scenario("schedule-unseen", agent=True)
def schedule_unseen(ctx: Ctx) -> None:
    """Як `schedule-fx`, але в копії перед запасником дописано вигадану константу `ZZ_INVENTED`: перша перевірка — `FX` бракує, `ZZ_INVENTED` невидима; остання перевірка зелена попри невидиму константу; `enum_unseen` у звіті — `ZZ_INVENTED` з позначкою «не видалено»; `FX` дописано, `ZZ_INVENTED` лишилась; `MarketType.java` — без жодного вилученого рядка."""
    ctx.need_fx()
    ctx.fresh_clone()
    before = ctx.edit(MARKET_JAVA, add_invented_constant)
    if "FX" in enum_names(before):
        raise Precondition("MarketType у клоні вже оголошує FX — розходження немає")
    key = slug(SCHEDULE)
    run = ctx.cli(ctx.registry([schedule_method()]), budget=5)
    count = ctx.converged(run, SCHEDULE, key, ["FR-58"])
    first = ctx.verdict(run, key, 1, ["FR-51"])
    if first:
        entry = enum_entry(first, "marketSchedules") or {}
        ctx.check("перша перевірка: FX бракує, ZZ_INVENTED — невидима", ["FR-51", "FR-57"],
                  "FX" in (entry.get("missing") or []) and "ZZ_INVENTED" in (entry.get("unseen") or []),
                  "missing ∋ FX, unseen ∋ ZZ_INVENTED", f"missing={entry.get('missing')}, unseen={entry.get('unseen')}")
    if count is not None:
        final = ctx.verdict(run, key, count, ["FR-53"])
        if final:
            entry = enum_entry(final, "marketSchedules") or {}
            ctx.check("остання перевірка зелена, хоча ZZ_INVENTED лишається невидимою", ["FR-53", "FR-58"],
                      final.get("green") is True and "ZZ_INVENTED" in (entry.get("unseen") or []),
                      "green=true, unseen ∋ ZZ_INVENTED", f"green={final.get('green')}, unseen={entry.get('unseen')}")
    report = ctx.report(run, key, ["FR-77"])
    if report:
        prefix = f"marketSchedules ({MARKET_ENUM}): "
        value = report.get("enum_unseen") or ""
        group = next((g for g in value.split("; ") if g.startswith(prefix)), None)
        named = group is not None and group.endswith(UNSEEN_MARK) and "ZZ_INVENTED" in group[len(prefix):-len(UNSEEN_MARK)].split(", ")
        ctx.check("enum_unseen: ZZ_INVENTED з позначкою «не видалено»", ["FR-57"], named,
                  f"група «{prefix}… ZZ_INVENTED …{UNSEEN_MARK}»", value)
        ctx.expect_field(report, "verify_result", ["FR-77"], "green")
        if count is not None:
            ctx.expect_field(report, "iterations", ["FR-77"], str(count))
    after = ctx.read(MARKET_JAVA)
    ctx.check("ZZ_INVENTED не видалено", ["FR-53"], "ZZ_INVENTED" in enum_names(after), "ZZ_INVENTED в MarketType", enum_names(after))
    ctx.check("FX дописано", ["FR-58"], "FX" in enum_names(after), "FX в MarketType", enum_names(after))
    placed, detail = enum_insertions(before, after)
    ctx.check("MarketType.java: лише додані константи після останньої наявної (ZZ_INVENTED), перед запасником",
              ["FR-53", "FR-55"], placed, "жодного вилученого рядка; нові константи перед @JsonEnumDefaultValue", detail)
    ctx.expect_changed(run, {MARKET_JAVA}, exact=True, ids=["FR-73"])
    ctx.common(run)


# @trace TC-7
@scenario("boundary", guard=True)
def boundary(ctx: Ctx) -> None:
    """Робоча копія людини `/Users/akutil/humex/binancefutures` після всіх сценаріїв така сама, як до першого: HEAD, відбитки `git status --porcelain` і `git diff` (читання з `--no-optional-locks`)."""
    before, after = ctx.h.origin_before, origin_state()
    ctx.check("HEAD робочої копії людини той самий", ["TC-7"], before["head"] == after["head"], before["head"], after["head"])
    status_moved = sorted(set(before["status"]) ^ set(after["status"]))
    ctx.check("git status робочої копії людини той самий", ["TC-7"], before["status_sha"] == after["status_sha"],
              f"sha256 {before['status_sha'][:12]}", f"sha256 {after['status_sha'][:12]}" + (f"; різниця: {status_moved}" if status_moved else ""))
    ctx.check("git diff робочої копії людини той самий", ["TC-7"], before["diff_sha"] == after["diff_sha"],
              f"sha256 {before['diff_sha'][:12]}", f"sha256 {after['diff_sha'][:12]}")
    write_json(ctx.evidence / "origin.json", {moment: {k: state[k] for k in ("head", "status_sha", "diff_sha")}
                                              for moment, state in (("before", before), ("after", after))})


# ----------------------------------------------------------------------------------------------------------
# Running, carrying over, reporting
# ----------------------------------------------------------------------------------------------------------

def fingerprint(lib_commit: str, versions: dict) -> str:
    digest = hashlib.sha256()
    for path in sorted((REPO / "src" / "method_sync").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(rel(path).encode() + b"\0" + path.read_bytes() + b"\0")
    digest.update(Path(__file__).read_bytes())
    digest.update(lib_commit.encode())
    digest.update(json.dumps(versions, sort_keys=True).encode())
    return digest.hexdigest()[:16]


def load_result(name: str) -> dict | None:
    try:
        return json.loads((EVIDENCE / name / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def carried_row(scen: Scenario, fp: str) -> Row:
    stored = load_result(scen.name)
    if not scen.guard and stored and stored.get("fingerprint") == fp and stored.get("verdict") in ("PASS", "FAIL"):
        return Row(scen.name, scen.ids, scen.expected, stored["verdict"], stored.get("observed", ""),
                   rel(EVIDENCE / scen.name) + "/", stored.get("finished", ""), carried=True,
                   notes=tuple(stored.get("notes") or ()))
    reason = "не запускався в цьому прогоні"
    if stored and not scen.guard:
        reason += f"; попередній результат ({stored.get('verdict')}, {stored.get('finished')}) має інший відбиток коду і не зараховується"
    return Row(scen.name, scen.ids, scen.expected, "NOT RUN", reason, "—", "")


def run_scenario(scen: Scenario, harness: Harness) -> Row:
    ctx = Ctx(scen, harness)
    started = now_utc().isoformat(timespec="seconds")
    shutil.rmtree(ctx.evidence, ignore_errors=True)
    ctx.evidence.mkdir(parents=True, exist_ok=True)
    print(f"[e2e] {scen.name}: старт", flush=True)
    problem = None
    try:
        scen.fn(ctx)
    except Precondition as exc:
        problem = f"передумова не виконана: {exc}"
    except Exception:  # a harness defect must surface as a FAIL with its trace, never as a silent pass
        problem = "збій harness: " + " ⏎ ".join(traceback.format_exc().strip().splitlines()[-6:])
    if problem is None and ctx.checks and all(c.ok for c in ctx.checks):
        unchecked = tuple(i for i in scen.ids if not any(i in c.ids for c in ctx.checks))
        if unchecked:
            ctx.checks.append(Check("кожна вимога з @trace має перевірку", unchecked, False, "так", "без перевірки: " + ", ".join(unchecked)))
    failed = [c for c in ctx.checks if not c.ok]
    verdict = "PASS" if problem is None and ctx.checks and not failed else "FAIL"
    runs = "; ".join(f"{r.label}: код {'—' if r.exit_code is None else r.exit_code}, {r.seconds:.0f} с, сесій агента {len(r.sessions)}"
                     for r in ctx.runs)
    if problem:
        head = problem
    elif failed:
        head = (f"не пройшло {len(failed)} з {len(ctx.checks)} перевірок; перша — «{failed[0].name}»: очікувалось "
                f"{failed[0].expected}; спостерігалось {failed[0].observed}")
    elif not ctx.checks:
        head = "жодної перевірки не виконано"
    else:
        head = f"пройшли всі перевірки ({len(ctx.checks)})"
    if verdict == "FAIL":  # the CLI's own last word, even when the first failing check is not about the exit code
        head += "".join(f"; stderr {r.label}: {last_line(r.stderr)}" for r in ctx.runs
                        if last_line(r.stderr) and last_line(r.stderr) not in head)
    observed = "; ".join(part for part in (head, runs, *ctx.notes) if part)
    finished = now_utc().isoformat(timespec="seconds")
    write_json(ctx.evidence / "result.json", {
        "scenario": scen.name, "verdict": verdict, "ids": list(scen.ids), "expected": scen.expected,
        "observed": observed, "started": started, "finished": finished, "fingerprint": harness.fingerprint,
        "tool_commit": harness.tool_commit, "lib_commit": harness.lib_commit, "agent": scen.agent,
        "notes": ctx.notes, "checks": [dataclasses.asdict(c) for c in ctx.checks],
        "runs": [{"label": r.label, "argv": r.argv, "exit_code": r.exit_code, "seconds": round(r.seconds, 1),
                  "agent_sessions": [s["session"] for s in r.sessions]} for r in ctx.runs]})
    print(f"[e2e] {scen.name}: {verdict} — {clip(observed, 300)}", flush=True)
    return Row(scen.name, scen.ids, scen.expected, verdict, observed, rel(ctx.evidence) + "/", finished,
               notes=tuple(ctx.notes))


def cell(text: object, limit: int = 1000) -> str:
    return clip(text, limit).replace("|", "\\|")


def write_report(rows: list[Row], harness: Harness, selection: str, interrupted: bool) -> str:
    e2e = e2e_requirements()
    failed = [r for r in rows if r.verdict == "FAIL"]
    not_run = [r for r in rows if r.verdict == "NOT RUN"]
    uncovered = [req for req in e2e if not any(req in r.ids for r in rows)]
    if failed or not_run or uncovered or interrupted:
        parts = [f"{len(failed)} of {len(rows)} scenarios failed"]
        parts += [f"{len(not_run)} not run"] if not_run else []
        parts += [f"{len(uncovered)} e2e requirement(s) without a scenario"] if uncovered else []
        parts += ["interrupted"] if interrupted else []
        result = f"Result: FAIL ({', '.join(parts)})"
    else:
        result = "Result: PASS"
    v = harness.versions
    local = harness.started.astimezone(KYIV)
    lines = [
        "# Наскрізні докази (e2e) — method-sync-v2", "", result, "",
        f"- Прогін: {local:%Y-%m-%d %H:%M} за Києвом ({harness.started:%H:%M} UTC), тривалість "
        f"{(now_utc() - harness.started).total_seconds() / 60:.1f} хв; вибір: {selection}.",
        "- Команда: `npm run test:e2e` → `python3 tests/e2e/evidence.py`; CLI у кожному сценарії — "
        "`PYTHONPATH=src python3 -m method_sync --registry <реєстр> [...]` з кореня репозиторію; реєстр — TOML у "
        "тимчасовому каталозі, його копія — у доказах сценарію.",
        f"- Середовище (NFR-15): macOS {v['os_version']} ({v['os']}, {v['arch']}) · Python {v['python']} · Java {v['java']} · "
        f"Maven {v['maven']} (на JDK {v['maven_jdk']}) · Claude Code CLI {v['claude']}.",
        f"- Цільова бібліотека: `{ORIGIN}` @ `{harness.lib_commit}` (гілка `{harness.lib_branch}`) — лише джерело клонів; "
        "кожен сценарій іде по свіжому `git clone` у `.sandbox/e2e/<сценарій>/`, жива біржа — "
        f"`{BASE_URL}`, `verify_cmd` — `{VERIFY_CMD}`.",
        f"- Інструмент: method-sync-v2 @ `{harness.tool_commit[:12]}`; відбиток коду `{harness.fingerprint}` "
        "(src/method_sync, цей harness, коміт бібліотеки, версії середовища).",
    ]
    notes = [note for r in rows if r.name == "environment" for note in r.notes]
    if notes:
        lines += ["", "## Примітки", "", *(f"- {note}." for note in notes)]
    lines += ["", "## Сценарії", "", "| Сценарій | Доводить | Очікується | Спостерігалось | Вердикт | Докази |",
              "|---|---|---|---|---|---|"]
    for r in rows:
        verdict = f"{r.verdict} (перенесено з прогону {r.when})" if r.carried else r.verdict
        evidence = f"`{r.evidence}`" if r.evidence != "—" else "—"
        lines.append(f"| `{r.name}` | {', '.join(r.ids)} | {cell(r.expected)} | {cell(r.observed)} | {verdict} | {evidence} |")
    lines += ["", "## Вимоги з тегом e2e", "", "| Вимога | Сценарії | Вердикт |", "|---|---|---|"]
    for req in e2e:
        covering = [r for r in rows if req in r.ids]
        if not covering:
            state = "НЕ ПОКРИТО"
        elif all(r.verdict == "PASS" for r in covering):
            state = "PASS"
        elif any(r.verdict == "FAIL" for r in covering):
            state = "FAIL"
        else:
            state = "NOT RUN"
        lines.append(f"| {req} | {', '.join(r.name for r in covering) or '—'} | {state} |")
    extra = sorted({i for r in rows for i in r.ids} - set(e2e), key=id_key)
    lines += ["", f"Сценарії спостерігають і вимоги без тегу e2e (їхній основний доказ — unit-тести `tests/*_test.py`): "
                  f"{', '.join(extra)}.", "", "## Як читати", "",
              "- Вердикт сценарію — PASS лише тоді, коли пройшли всі його перевірки; кожна перевірка з очікуваним і "
              "спостереженим, з вимогами, які вона доводить, — у `docs/qa/e2e/<сценарій>/result.json`.",
              "- Докази прогону CLI — у `docs/qa/e2e/<сценарій>/<прогін>/`: `registry.toml`, `command.txt`, `cli-stdout.txt`, "
              "`cli-stderr.txt`, `runs/<slug>/` (файли, які записав саме цей прогін), `lib-status-before.txt`, "
              "`lib-status-after.txt`, `lib-cached-before.txt`, `lib-cached-after.txt`, `lib-before.diff`, `lib.diff`, "
              "`agent-sessions.json`.",
              "- Чи кликали агента, свідчать транскрипти Claude Code, чий `cwd` — клон сценарію, а не слова самого інструмента.",
              "- NOT RUN ніколи не зараховується як PASS. Сценарій, що не запускався цього разу, зараховується лише з "
              "результатом попереднього запуску з тим самим відбитком коду і позначається «перенесено».",
              f"- Сценарії з агентом ідуть лише після зеленого `{GATE}` з тим самим відбитком коду: це береже бюджет агента, "
              "коли зламано сам шлях перевірки (`--no-gate` знімає обмеження)."]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def print_list() -> None:
    print("Сценарії (порядок = порядок запуску; guard — завжди, agent — кличе справжнього агента):")
    for scen in SCENARIOS:
        kind = "guard" if scen.guard else "agent" if scen.agent else "-"
        print(f"\n{scen.name}  [{kind}]\n  доводить: {', '.join(scen.ids)}\n  очікується: {scen.expected}")
    print(f"\nСценарії з агентом ідуть лише після зеленого {GATE} з поточним кодом (--no-gate знімає обмеження).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tests/e2e/evidence.py",
                                     description="E2E evidence for method-sync-v2: the real CLI against fresh clones of "
                                                 "the target library, the live exchange and the real agent.")
    parser.add_argument("--only", action="append", default=[], metavar="SCENARIO",
                        help="run only this scenario (repeatable); the guards always run")
    parser.add_argument("--list", action="store_true", help="list the scenarios and exit")
    parser.add_argument("--no-gate", action="store_true",
                        help=f"run agent scenarios even if {GATE} has not passed with the current code")
    args = parser.parse_args(argv)
    if args.list:
        print_list()
        return 0
    by_name = {scen.name: scen for scen in SCENARIOS}
    unknown = [name for name in args.only if name not in by_name]
    if unknown:
        print(f"невідомий сценарій: {', '.join(unknown)}; є: {', '.join(by_name)}", file=sys.stderr)
        return 2

    started = now_utc()
    versions, raw = probe_versions()
    try:
        lib_commit = origin_git("rev-parse", "HEAD").decode().strip()
        lib_branch = origin_git("rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        lib_commit = lib_branch = f"<недоступно: {exc}>"
    harness = Harness(tmp=Path(tempfile.mkdtemp(prefix="method-sync-e2e-")), started=started, lib_commit=lib_commit,
                      lib_branch=lib_branch, tool_commit=git(REPO, "rev-parse", "HEAD").strip(), versions=versions,
                      raw_versions=raw, fingerprint=fingerprint(lib_commit, versions), origin_before=origin_state())
    if os.environ.get("CLAUDECODE"):
        print("[e2e] увага: запуск зсередини сесії Claude Code — агент інструмента успадкує змінні хост-сесії", flush=True)

    wanted = set(args.only) if args.only else {s.name for s in SCENARIOS if not s.guard}
    gate_added = False
    if not args.no_gate and GATE not in wanted and any(by_name[n].agent for n in wanted):
        gate = carried_row(by_name[GATE], harness.fingerprint)
        if not (gate.carried and gate.verdict == "PASS"):
            wanted.add(GATE)
            gate_added = True
    plan = [scen for scen in SCENARIOS if scen.guard or scen.name in wanted]
    selection = ("--only " + ", ".join(args.only) if args.only else "усі сценарії") + \
        (f" (+ {GATE} як умова для сценаріїв з агентом)" if gate_added else "") + (", --no-gate" if args.no_gate else "")
    print(f"Scope: {len(SCENARIOS)} scenario(s); у цьому прогоні: {', '.join(s.name for s in plan)}", flush=True)

    rows: dict[str, Row] = {}
    interrupted, current = False, None
    try:
        for scen in plan:
            current = scen
            if scen.agent and not args.no_gate:
                gate = rows.get(GATE) or carried_row(by_name[GATE], harness.fingerprint)
                if gate.verdict != "PASS":
                    rows[scen.name] = Row(scen.name, scen.ids, scen.expected, "NOT RUN",
                                          f"не запускався: сценарії з агентом ідуть лише після зеленого {GATE} з поточним "
                                          f"кодом, а {GATE} — {gate.verdict}: {clip(gate.observed, 240)}", "—", "")
                    print(f"[e2e] {scen.name}: NOT RUN — {GATE} не зелений", flush=True)
                    continue
            rows[scen.name] = run_scenario(scen, harness)
        current = None
    except KeyboardInterrupt:
        interrupted = True
        if current is not None and current.name not in rows:
            rows[current.name] = Row(current.name, current.ids, current.expected, "FAIL", "перервано (Ctrl-C) посеред сценарію",
                                     rel(EVIDENCE / current.name) + "/", now_utc().isoformat(timespec="seconds"))
    finally:
        shutil.rmtree(harness.tmp, ignore_errors=True)
    ordered = [rows.get(s.name) or (Row(s.name, s.ids, s.expected, "NOT RUN", "не запускався (прогін перервано)", "—", "")
                                    if s.guard else carried_row(s, harness.fingerprint)) for s in SCENARIOS]
    result = write_report(ordered, harness, selection, interrupted)
    print(f"[e2e] звіт: {rel(REPORT)}; докази: {rel(EVIDENCE)}/<сценарій>/", flush=True)
    print(result, flush=True)
    if interrupted:
        return 130
    return 0 if result == "Result: PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
