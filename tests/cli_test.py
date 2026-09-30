# @trace FR-14, FR-15, FR-16, FR-17, FR-18, FR-19, FR-20, FR-21, FR-22, FR-27, FR-61, FR-64, FR-65, FR-66, FR-67, FR-68, FR-71, FR-77, FR-79, FR-80, FR-81, FR-82, NFR-6, NFR-7, NFR-11, NFR-13
"""Тести CLI (capability `run-cli`, зміна `add-core`): unittest зі stdlib.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

`main(argv, *, runs_dir, verify, agent)` проганяє реєстр так само, як процес CLI. Сторонній світ підмінено лише на
межі, як у v1 і в `live_test.py`: біржу заступає справжній `LocalServer` (живий виклик і фікстура — справжні, через
`live.capture`), перевірку й агента — параметри `verify` і `agent`, що віддають задані вердикти й записують виклики.
Бібліотека — тимчасовий каталог після справжнього `git init` зі стандартом стилю і файлами класів моделей: реєстр
перевіряє `lib` і `.git`, ранні перевірки шукають `SKILL.md` і `<model>.java`, бриф — еталон у `response/`.
`runs_dir` — тимчасовий, тож тести не пишуть у `runs/` репозиторію.

Відмінності від v1 (design.md, таблиця): ранні перевірки FR-22 → FR-20 → FR-21 ідуть до живого виклику; відсутній
клас моделі — код 2; `FixtureWriteError` — код 1 і прогін іде далі; `--dry-run` пише `iteration-1.log`;
`--max-iterations` ≥ 1; хибний командний рядок — код 2 і пояснення кирилицею без тексту argparse.
"""
import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from live_test import FUNDING_RAW, PREMIUM_RAW, LocalServer, Reply, git_init  # noqa: E402
from method_sync.__main__ import (  # noqa: E402
    EXIT_LIVE_UNAVAILABLE,
    EXIT_NO_STYLE_STANDARD,
    EXIT_OK,
    EXIT_RED,
    EXIT_REGISTRY,
    main,
    worst,
)

PKG = "com.example.binanceFutures.response"
MARK_MODEL, FUNDING_MODEL, SCHEDULE_MODEL = (f"{PKG}.{name}" for name in
                                             ("FuturesMarkPriceInfo", "FuturesFundingRateInfo",
                                              "TradingScheduleResponse"))
PREMIUM, FUNDING, SCHEDULE = "/fapi/v1/premiumIndex", "/fapi/v1/fundingRate", "/fapi/v1/tradingSchedule"
PREMIUM_SLUG, FUNDING_SLUG = "fapi-v1-premiumIndex", "fapi-v1-fundingRate"
VERIFY_CMD = "mvn -q -DskipTests test-compile"
FUNDING_CALL = '"BTCUSDT", 3, null, null'
SKILL = ".claude/skills/add-binance-rest-endpoint/SKILL.md"
REVIEWER = "не викликався — рецензію запускає окрема сесія (принцип V)"
CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
TRACEBACK = "Traceback (most recent call last)"

PREMIUM_ENTRY = {"path": PREMIUM, "model": MARK_MODEL, "client_method": "getMarkPrice", "args": {"symbol": "BTCUSDT"}}
FUNDING_ENTRY = {"path": FUNDING, "model": FUNDING_MODEL, "client_method": "getFundingRates",
                 "args": {"symbol": "BTCUSDT", "limit": 3}, "call": FUNDING_CALL}
SCHEDULE_ENTRY = {"path": SCHEDULE, "model": SCHEDULE_MODEL, "client_method": "getTradingSchedule"}


def verdict(green=False, extra=(), missing=(), enums=(), client_error=None):
    return {"green": green, "model": [], "live": [], "extra": list(extra), "missing": list(missing), "owners": {},
            "client_error": client_error, "enums": list(enums)}


GREEN = verdict(green=True)
RED_FUNDING = verdict(missing=["markPrice", "rateType"])
COMPILE_STAGE = {"green": False, "stage": "compile",
                 "reason": f"команда перевірки {VERIFY_CMD} завершилась з кодом 1"}


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {toml_value(item)}" for key, item in value.items()) + " }"
    return str(value)


class Verifier:
    """Шов `verify(lib, method, url, verify_cmd)`: вердикти по черзі для кожного шляху, останній повторює."""

    def __init__(self, by_path=None):
        self.queues = {path: list(verdicts) for path, verdicts in (by_path or {}).items()}
        self.calls = []

    def __call__(self, lib, method, url, verify_cmd):
        self.calls.append((method.path, url, verify_cmd))
        queue = self.queues.setdefault(method.path, [GREEN])
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        return result, f"вивід перевірки {method.path} #{len(self.calls)}"

    def paths(self):
        return [path for path, _, _ in self.calls]


class Agent:
    """Шов `agent(brief, cwd, add_dirs, allowed_commands)`: нічого не пише, записує, з чим його покликали."""

    def __init__(self):
        self.calls = []

    def __call__(self, brief, cwd=None, add_dirs=(), allowed_commands=(), **_):
        self.calls.append({"brief": brief, "cwd": cwd, "add_dirs": list(add_dirs),
                           "allowed_commands": list(allowed_commands)})
        return "агент відпрацював"


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs = self.tmp / "runs"
        self.runs.mkdir()
        self.lib = self.make_lib()

    def make_lib(self, name="lib", skill=True, models=(MARK_MODEL, FUNDING_MODEL, SCHEDULE_MODEL)):
        lib = git_init(self.tmp / name)
        if skill:
            (lib / SKILL).parent.mkdir(parents=True)
            (lib / SKILL).write_text("# Стандарт стилю бібліотеки\n", encoding="utf-8")
        for fqn in models:
            package, simple = fqn.rsplit(".", 1)
            path = lib / "src/main/java" / f"{fqn.replace('.', '/')}.java"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"package {package};\n\npublic class {simple} {{\n}}\n", encoding="utf-8")
        return lib

    def serve(self, routes=None, default=None):
        routes = {PREMIUM: Reply(body=PREMIUM_RAW), FUNDING: Reply(body=FUNDING_RAW)} if routes is None else routes
        self.server = LocalServer(routes, default)
        self.addCleanup(self.server.close)
        return self.server

    def registry(self, *entries, verify_cmd=VERIFY_CMD, lib=None):
        lines = [f"lib = {toml_value(str(lib or self.lib))}", f"verify_cmd = {toml_value(verify_cmd)}", "",
                 "[live]", f"base_url = {toml_value(self.server.url)}"]
        for entry in entries:
            lines += ["", "[[method]]"] + [f"{key} = {toml_value(value)}" for key, value in entry.items()]
        path = self.tmp / "registry.toml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def cli(self, *argv, verifier=None):
        self.verifier, self.agent = verifier or Verifier(), Agent()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(list(argv), runs_dir=self.runs, verify=self.verifier, agent=self.agent)
            except SystemExit as exit_:
                code = exit_.code
        self.assertNotIn(TRACEBACK, out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def lines(out):
        return [line for line in out.splitlines() if line.strip()]

    def line_for(self, out, path):
        found = [line for line in self.lines(out) if line.split()[0] == path]
        self.assertTrue(found, f"немає рядка {path} у stdout:\n{out}")
        return found[0]

    def report_value(self, slug, name):
        text = (self.runs / slug / "report.md").read_text(encoding="utf-8")
        match = re.search(rf"^- \*\*[^*]+\*\* \(`{name}`\): (.*)$", text, re.MULTILINE)
        self.assertIsNotNone(match, f"у звіті {slug} немає поля {name}")
        return match.group(1)

    def assertMentionsPath(self, text, path):
        path = pathlib.Path(path)
        self.assertTrue(str(path) in text or str(path.resolve()) in text, f"немає {path} у тексті")

    def snapshot(self, root):
        return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class EarlyStopsComeBeforeTheLiveCall(CliCase):
    """FR-20, FR-21, FR-22, FR-77: у порядку v1 і до живого виклику; зупинений метод звіту не отримує."""

    def test_prefix_and_model_stop_without_a_live_call(self):
        self.serve(routes={}, default=Reply(503, b'{"code":-1,"msg":"busy"}'))
        previous = self.runs / PREMIUM_SLUG / "report.md"
        previous.parent.mkdir()
        previous.write_bytes("# Звіт прогону — попередній\n".encode("utf-8"))
        registry = self.registry(
            {"path": "/eapi/v1/ticker", "model": MARK_MODEL, "client_method": "getTicker"},
            {**PREMIUM_ENTRY, "model": f"{PKG}.NoSuchInfo"},
            FUNDING_ENTRY)
        code, out, _ = self.cli("--registry", registry)
        self.assertIn("невідомий префікс", self.line_for(out, "/eapi/v1/ticker"))
        premium = self.line_for(out, PREMIUM)
        self.assertIn(f"{PKG}.NoSuchInfo", premium)
        self.assertIn("реалізація з нуля поза обсягом", premium)
        self.assertEqual(self.server.targets(), ["/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3"])
        self.assertEqual(code, EXIT_REGISTRY)
        self.assertEqual((self.verifier.calls, self.agent.calls), ([], []))
        self.assertEqual(previous.read_bytes(), "# Звіт прогону — попередній\n".encode("utf-8"))
        self.assertFalse((self.runs / "eapi-v1-ticker").exists())

    def test_missing_style_standard_stops_first(self):
        self.serve()
        bare = self.make_lib(name="bare", skill=False)
        registry = self.registry({**PREMIUM_ENTRY, "model": f"{PKG}.NoSuchInfo"}, FUNDING_ENTRY, lib=bare)
        code, out, _ = self.cli("--registry", registry)
        for path in (PREMIUM, FUNDING):
            with self.subTest(path=path):
                self.assertIn(f"{bare}/{SKILL}", self.line_for(out, path))
        self.assertNotIn("реалізація з нуля поза обсягом", self.line_for(out, PREMIUM))
        self.assertEqual(self.server.targets(), [])
        self.assertEqual(code, EXIT_NO_STYLE_STANDARD)


class FailureDoesNotStopTheList(CliCase):
    """FR-15, FR-27: невдалий метод має свій рядок, решта списку обробляється."""

    def test_live_unavailable_touches_neither_agent_nor_library(self):
        self.serve(routes={FUNDING: Reply(body=b"[]"), PREMIUM: Reply(body=PREMIUM_RAW)})
        previous = self.runs / FUNDING_SLUG / "report.md"
        previous.parent.mkdir()
        previous.write_bytes(b"old report")
        before = self.snapshot(self.lib)
        registry = self.registry({**FUNDING_ENTRY, "args": {"symbol": "NOSUCHSYMBOL", "limit": 3}}, PREMIUM_ENTRY)
        code, out, _ = self.cli("--registry", registry)
        funding = self.line_for(out, FUNDING)
        self.assertIn("жива відповідь недоступна", funding)
        self.assertIn(f"{self.server.url}/fapi/v1/fundingRate?symbol=NOSUCHSYMBOL&limit=3", funding)
        self.assertIn("перевірка=green", self.line_for(out, PREMIUM))
        self.assertEqual(code, EXIT_LIVE_UNAVAILABLE)
        self.assertEqual((self.verifier.paths(), self.agent.calls), ([PREMIUM], []))
        self.assertEqual(previous.read_bytes(), b"old report")
        self.assertEqual(self.snapshot(self.lib), before)

    def test_fixture_write_error_is_code_one_and_the_run_goes_on(self):
        self.serve()
        outside = self.tmp / "docs"
        outside.mkdir()
        (self.runs / FUNDING_SLUG).symlink_to(outside, target_is_directory=True)
        code, out, _ = self.cli("--registry", self.registry(FUNDING_ENTRY, PREMIUM_ENTRY), "--dry-run")
        self.assertIn(str(outside.resolve() / "fixture.json"), self.line_for(out, FUNDING))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIn("перевірка=green", self.line_for(out, PREMIUM))
        self.assertTrue((self.runs / PREMIUM_SLUG / "fixture.json").is_file())
        self.assertTrue((self.runs / PREMIUM_SLUG / "report.md").is_file())
        self.assertEqual(code, EXIT_RED)
        self.assertEqual(self.verifier.paths(), [PREMIUM])


class OnlyFlag(CliCase):
    """FR-16, FR-17: лише названий метод; шлях поза реєстром — код 2 до першого методу."""

    def test_only_the_named_method(self):
        self.serve()
        registry = self.registry(FUNDING_ENTRY, PREMIUM_ENTRY, SCHEDULE_ENTRY)
        code, out, _ = self.cli("--registry", registry, "--only", PREMIUM)
        self.assertEqual(self.lines(out), [self.line_for(out, PREMIUM), "підсумок: 1 методів, 1 зелених, 0 червоних"])
        self.assertEqual(self.line_for(out, PREMIUM).split(), [PREMIUM, "refresh", "ітерацій=1", "перевірка=green"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(self.server.targets(), ["/fapi/v1/premiumIndex?symbol=BTCUSDT"])
        self.assertEqual(sorted(path.name for path in self.runs.iterdir()), [PREMIUM_SLUG])

    def test_path_not_in_the_registry(self):
        self.serve()
        code, out, err = self.cli("--registry", self.registry(PREMIUM_ENTRY), "--only", "/fapi/v1/nosuchMethod")
        self.assertEqual(code, EXIT_REGISTRY)
        self.assertIn("у реєстрі немає методу /fapi/v1/nosuchMethod", err)
        self.assertEqual(out.strip(), "")
        self.assertEqual(self.server.targets(), [])
        self.assertEqual(list(self.runs.iterdir()), [])


class BadCommandLine(CliCase):
    """FR-61, NFR-13: хибний командний рядок — код 2 до першого методу, пояснення кирилицею без argparse."""

    def test_rejected_flags_and_values(self):
        self.serve()
        registry = self.registry(PREMIUM_ENTRY)
        cases = ((["--bogus"], ["--bogus"]), (["--only"], ["--only"]),
                 (["--max-iterations", "abc"], ["--max-iterations", "abc"]),
                 (["--max-iterations", "0"], ["--max-iterations", "0"]))
        for extra, named in cases:
            with self.subTest(argv=extra):
                code, out, err = self.cli("--registry", registry, *extra)
                self.assertEqual(code, EXIT_REGISTRY)
                self.assertEqual(out.strip(), "")
                for part in named:
                    self.assertIn(part, err)
                self.assertRegex(err, CYRILLIC)
                self.assertNotIn("usage:", err)
                self.assertNotIn("error:", err)
        self.assertEqual(self.server.targets(), [])
        self.assertEqual(list(self.runs.iterdir()), [])

    def test_missing_registry_flag(self):
        code, out, err = self.cli()
        self.assertEqual(code, EXIT_REGISTRY)
        self.assertIn("--registry", err)
        self.assertRegex(err, CYRILLIC)
        self.assertNotIn("usage:", err)
        self.assertNotIn("error:", err)

    def test_unusable_registry(self):
        missing = self.tmp / "nope.toml"
        code, _, err = self.cli("--registry", str(missing))
        self.assertEqual(code, EXIT_REGISTRY)
        self.assertIn(str(missing), err)
        self.assertRegex(err, CYRILLIC)


class DryRun(CliCase):
    """FR-18, FR-64, FR-82: одна перевірка без агента, фікстура, звіт і `iteration-1.log`; код 0 чи 1."""

    def test_red_dry_run(self):
        self.serve()
        verifier = Verifier({FUNDING: [RED_FUNDING]})
        code, out, _ = self.cli("--registry", self.registry(PREMIUM_ENTRY, FUNDING_ENTRY), "--dry-run",
                                "--max-iterations", "3", "--only", FUNDING, verifier=verifier)
        self.assertEqual((self.verifier.paths(), self.agent.calls), ([FUNDING], []))
        self.assertEqual(self.line_for(out, FUNDING).split(), [FUNDING, "refresh", "ітерацій=1", "перевірка=red"])
        self.assertEqual(code, EXIT_RED)
        method_dir = self.runs / FUNDING_SLUG
        self.assertEqual(sorted(path.name for path in method_dir.iterdir()),
                         ["fixture.json", "iteration-1.log", "report.md"])
        log = (method_dir / "iteration-1.log").read_text(encoding="utf-8")
        for part in ("markPrice", "rateType", "агента покликано: ні", f"вивід перевірки {FUNDING} #1"):
            with self.subTest(part=part):
                self.assertIn(part, log)
        self.assertEqual(self.report_value(FUNDING_SLUG, "verify_result"), "dry-run: агента не кликали")
        self.assertEqual(self.report_value(FUNDING_SLUG, "iterations"), "1")

    def test_green_dry_run(self):
        self.serve()
        code, out, _ = self.cli("--registry", self.registry(PREMIUM_ENTRY), "--dry-run", "--only", PREMIUM)
        self.assertEqual(self.line_for(out, PREMIUM).split(), [PREMIUM, "refresh", "ітерацій=1", "перевірка=green"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(self.report_value(PREMIUM_SLUG, "verify_result"), "green")
        self.assertTrue((self.runs / PREMIUM_SLUG / "iteration-1.log").is_file())


class LoopThroughTheCli(CliCase):
    """FR-19, FR-65–FR-68, FR-71, FR-79–FR-82: рядок методу, виклик агента, звіт із першого вердикту."""

    def test_green_on_the_second_iteration(self):
        self.serve()
        verifier = Verifier({FUNDING: [RED_FUNDING, GREEN]})
        code, out, _ = self.cli("--registry", self.registry(FUNDING_ENTRY), verifier=verifier)
        self.assertEqual(self.line_for(out, FUNDING).split(), [FUNDING, "refresh", "ітерацій=2", "перевірка=green"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(self.verifier.calls[0][1:],
                         (f"{self.server.url}/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3", VERIFY_CMD))
        self.assertEqual(len(self.agent.calls), 1)
        call = self.agent.calls[0]
        self.assertTrue(os.path.isabs(str(call["cwd"])))
        self.assertEqual(os.path.realpath(call["cwd"]), os.path.realpath(self.lib))
        self.assertEqual([os.path.realpath(path) for path in call["add_dirs"]], [os.path.realpath(self.runs)])
        self.assertTrue(all(os.path.isabs(str(path)) for path in call["add_dirs"]))
        self.assertEqual(call["allowed_commands"], [VERIFY_CMD])
        fixture = self.runs / FUNDING_SLUG / "fixture.json"
        reference = self.lib / "src/main/java/com/example/binanceFutures/response/FuturesFundingRateInfo.java"
        for path in (fixture, self.lib, reference):
            with self.subTest(path=path.name):
                self.assertMentionsPath(call["brief"], path)
        self.assertIn(FUNDING_MODEL, call["brief"])
        self.assertIn(f"вивід перевірки {FUNDING} #1", call["brief"])
        self.assertEqual(self.report_value(FUNDING_SLUG, "mismatch"),
                         "зайві в моделі: —; бракує в моделі: markPrice, rateType")
        self.assertEqual(self.report_value(FUNDING_SLUG, "removed"), "нічого не видалено")
        self.assertEqual(self.report_value(FUNDING_SLUG, "verify_result"), "green")
        self.assertEqual(self.report_value(FUNDING_SLUG, "iterations"), "2")
        self.assertEqual(self.report_value(FUNDING_SLUG, "reviewer"), REVIEWER)
        self.assertEqual(self.report_value(FUNDING_SLUG, "enum_mismatch"), "розходжень енамів немає")
        self.assertEqual(self.report_value(FUNDING_SLUG, "enum_unseen"), "невидимих констант немає")
        self.assertMentionsPath(self.report_value(FUNDING_SLUG, "response_source"), fixture)

    def test_first_check_without_comparison(self):
        self.serve()
        verifier = Verifier({FUNDING: [COMPILE_STAGE, verdict(extra=["bogusExtraField"]), GREEN]})
        self.cli("--registry", self.registry(FUNDING_ENTRY), verifier=verifier)
        self.assertEqual(self.report_value(FUNDING_SLUG, "mismatch"),
                         f"звіряння не відбулося: команда перевірки не пройшла ({VERIFY_CMD})")
        self.assertEqual(self.report_value(FUNDING_SLUG, "removed"), "нічого не видалено")
        self.assertEqual(self.report_value(FUNDING_SLUG, "enum_mismatch"), "звіряння не відбулося")
        self.assertEqual(self.report_value(FUNDING_SLUG, "enum_unseen"), "звіряння не відбулося")
        self.assertEqual(self.report_value(FUNDING_SLUG, "iterations"), "3")

    def test_loop_that_does_not_converge(self):
        self.serve()
        client_only = verdict(client_error="com.binance.api.client.exception.BinanceApiException: Invalid symbol.")
        code, out, _ = self.cli("--registry", self.registry(FUNDING_ENTRY), verifier=Verifier({FUNDING: [client_only]}))
        self.assertEqual((len(self.verifier.calls), len(self.agent.calls)), (5, 4))
        self.assertEqual(self.line_for(out, FUNDING).split(), [FUNDING, "refresh", "ітерацій=5", "перевірка=red"])
        self.assertEqual(self.report_value(FUNDING_SLUG, "verify_result"), "цикл не зійшовся за 5 ітерацій")
        self.assertEqual(code, EXIT_RED)

    def test_star_in_verify_cmd(self):
        self.serve()
        registry = self.registry(FUNDING_ENTRY, verify_cmd="ls src/*.java")
        code, out, _ = self.cli("--registry", registry, "--max-iterations", "2",
                                verifier=Verifier({FUNDING: [RED_FUNDING]}))
        self.assertEqual((len(self.verifier.calls), self.agent.calls), (2, []))
        log = (self.runs / FUNDING_SLUG / "iteration-1.log").read_text(encoding="utf-8")
        self.assertIn("агента покликано: ні", log)
        self.assertEqual(self.report_value(FUNDING_SLUG, "verify_result"), "цикл не зійшовся за 2 ітерацій")
        self.assertEqual(code, EXIT_RED)

    def test_stopped_methods_count_as_red(self):
        self.serve()
        lib = self.make_lib(name="no-schedule", models=(MARK_MODEL, FUNDING_MODEL))
        registry = self.registry(PREMIUM_ENTRY, FUNDING_ENTRY, SCHEDULE_ENTRY, lib=lib)
        code, out, _ = self.cli("--registry", registry, "--dry-run", verifier=Verifier({FUNDING: [RED_FUNDING]}))
        schedule = self.line_for(out, SCHEDULE)
        self.assertNotIn("ітерацій=", schedule)
        self.assertNotIn("перевірка=", schedule)
        self.assertEqual(self.lines(out)[-1], "підсумок: 3 методів, 1 зелених, 2 червоних")
        self.assertEqual(code, EXIT_REGISTRY)


class ExitCodes(unittest.TestCase):
    """NFR-6, NFR-7: коди 0–4 і найгірший за шкалою 0 < 1 < 3 < 2 < 4."""

    def test_values(self):
        self.assertEqual((EXIT_OK, EXIT_RED, EXIT_REGISTRY, EXIT_LIVE_UNAVAILABLE, EXIT_NO_STYLE_STANDARD),
                         (0, 1, 2, 3, 4))

    def test_worst_not_last_nor_largest(self):
        for codes, expected in (([1, 3], 3), ([3, 2, 0], 2), ([2, 4], 4), ([1, 0], 1), ([0, 0], 0), ([], 0)):
            with self.subTest(codes=codes):
                self.assertEqual(worst(codes), expected)


if __name__ == "__main__":
    unittest.main()
