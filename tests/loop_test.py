# @trace FR-60, FR-61, FR-62, FR-63, FR-64, FR-68, FR-75, NFR-1, NFR-3, NFR-13
"""Тести циклу «перевірка → агент» (capability `sync-loop`, зміна `add-core`): unittest зі stdlib.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Як у v1, перевірка й агент подаються циклу параметрами (шви `verify` і `agent`): тут вони — функції, що віддають
задані вердикти і рахують виклики. Механіка циклу — коли він зупиняється, коли кличе агента, що лишає в лозі —
від цього не залежить. Один тест (NFR-1) кличе справжній `agent.invoke` із завислим процесом на місці `claude`.

Відмінності від v1: `verify_cmd` із `*` — агента не кличуть (FR-68); лог несе ключі `green`, `extra`, `missing`
англійською, розходження енамів, а для вердикту стадії — `stage` і `reason` замість порожніх переліків (FR-64).
"""
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from method_sync import agent as agent_module  # noqa: E402
from method_sync.loop import MAX_ITERATIONS, run_loop  # noqa: E402

SLUG = "fapi-v1-premiumIndex"
MARKET_ENUM = "com.example.binanceFutures.response.MarketType"
MARKET_DECLARED = ["CN_EQUITY", "COMMODITY", "EQUITY", "HK_EQUITY", "KR_EQUITY"]


def verdict(green=False, extra=(), missing=(), enums=(), client_error=None):
    return {"green": green, "model": [], "live": [], "extra": list(extra), "missing": list(missing), "owners": {},
            "client_error": client_error, "enums": list(enums)}


GREEN = verdict(green=True)
RED = verdict(extra=["bogusExtraField"], missing=["interestRate"])
FX_ENTRY = {"field": "marketSchedules", "enum": MARKET_ENUM, "declared": MARKET_DECLARED,
            "live": sorted(MARKET_DECLARED + ["FX"]), "missing": ["FX"], "unseen": []}
COMPILE_STAGE = {"green": False, "stage": "compile",
                 "reason": "команда перевірки mvn -q -DskipTests test-compile завершилась з кодом 1"}


def verifier(*verdicts, outputs=None):
    """Шов `verify`: віддає задані вердикти по черзі, останній повторює."""
    queue = list(verdicts)

    def verify():
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        verify.calls += 1
        output = outputs[verify.calls - 1] if outputs else f"вивід перевірки #{verify.calls}"
        return result, output

    verify.calls = 0
    return verify


def agent(reply="агент відпрацював"):
    """Шов `agent`: нічого не пише, запам'ятовує, з чим його покликали."""
    def invoke(verdict_, output):
        invoke.seen.append((verdict_, output))
        return reply

    invoke.seen = []
    return invoke


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.runs = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-runs-"))
        self.addCleanup(shutil.rmtree, self.runs, ignore_errors=True)

    def log(self, number):
        return (self.runs / SLUG / f"iteration-{number}.log").read_text(encoding="utf-8")

    def logs(self):
        return sorted(path.name for path in (self.runs / SLUG).glob("iteration-*.log"))


class StopsOnTheFirstGreen(LoopCase):
    """FR-60, FR-75: цикл до першого зеленого; слова агента вердикту не дають."""

    def test_green_on_the_third_check(self):
        verify, invoke = verifier(RED, RED, GREEN), agent("перевірка зелена, усе готово")
        result = run_loop(self.runs, SLUG, verify, invoke)
        self.assertEqual((verify.calls, len(invoke.seen), result.iterations), (3, 2, 3))
        self.assertTrue(result.green)
        self.assertTrue(result.converged)

    def test_agent_gets_the_verdict_and_output_of_the_check_before_it(self):
        second = verdict(extra=["bogusExtraField"])
        first = verdict(extra=["bogusExtraField", "otherField"])
        verify, invoke = verifier(first, second, GREEN), agent()
        run_loop(self.runs, SLUG, verify, invoke)
        self.assertEqual(invoke.seen, [(first, "вивід перевірки #1"), (second, "вивід перевірки #2")])

    def test_green_first_check_needs_no_agent(self):
        """FR-63: зелена перша перевірка — одна ітерація, один лог, агента не кликали."""
        invoke = agent()
        result = run_loop(self.runs, SLUG, verifier(GREEN), invoke)
        self.assertEqual((result.iterations, len(invoke.seen)), (1, 0))
        self.assertEqual(self.logs(), ["iteration-1.log"])
        self.assertIn("агента покликано: ні", self.log(1))
        self.assertEqual((result.initial_verdict["extra"], result.initial_verdict["missing"]), ([], []))

    def test_initial_verdict_survives_until_the_end(self):
        """FR-79 спирається на це: звіт показує те, що прогін застав."""
        result = run_loop(self.runs, SLUG, verifier(RED, GREEN), agent())
        self.assertEqual(result.initial_verdict, RED)
        self.assertTrue(result.verdict["green"])


class StopsOnTheIterationLimit(LoopCase):
    """FR-61, FR-62: не більше за ліміт перевірок, агента після останньої не кличуть, підсумок каже чесно."""

    def test_default_limit_exhausted(self):
        self.assertEqual(MAX_ITERATIONS, 5)
        verify, invoke = verifier(RED), agent()
        result = run_loop(self.runs, SLUG, verify, invoke)
        self.assertEqual((verify.calls, len(invoke.seen), result.iterations), (5, 4, 5))
        self.assertEqual(result.summary, "цикл не зійшовся за 5 ітерацій")
        self.assertFalse(result.green)
        self.assertFalse(result.converged)

    def test_no_agent_after_the_last_check(self):
        invoke = agent()
        result = run_loop(self.runs, SLUG, verifier(RED), invoke, max_iterations=2)
        self.assertEqual(len(invoke.seen), 1)
        self.assertIn("агента покликано: так", self.log(1))
        self.assertIn("агента покликано: ні", self.log(2))
        self.assertEqual(result.summary, "цикл не зійшовся за 2 ітерацій")


class StarInVerifyCmdIsNotAPermissionPattern(LoopCase):
    """FR-68: `*` у `verify_cmd` розширив би `Bash(…)` до шаблону — агента не кличуть, цикл іде далі."""

    def test_agent_is_never_called(self):
        verify, invoke = verifier(RED), agent()
        result = run_loop(self.runs, SLUG, verify, invoke, max_iterations=2, verify_cmd="ls src/*.java")
        self.assertEqual((len(invoke.seen), verify.calls), (0, 2))
        first = self.log(1)
        self.assertIn("агента покликано: ні", first)
        self.assertIn("verify_cmd", first)
        self.assertIn("*", first)
        self.assertEqual(result.summary, "цикл не зійшовся за 2 ітерацій")

    def test_plain_verify_cmd_still_calls_the_agent(self):
        invoke = agent()
        run_loop(self.runs, SLUG, verifier(RED, GREEN), invoke, verify_cmd="mvn -q -DskipTests test-compile")
        self.assertEqual(len(invoke.seen), 1)


class LeavesALogOfEveryIteration(LoopCase):
    """FR-64, NFR-13: лог кожної ітерації — номер, ключі вердикту англійською, енами, агент, повний вивід."""

    def test_one_file_per_iteration(self):
        run_loop(self.runs, SLUG, verifier(RED, RED, GREEN), agent())
        self.assertEqual(self.logs(), ["iteration-1.log", "iteration-2.log", "iteration-3.log"])

    def test_log_after_which_the_agent_was_called(self):
        output = "\n".join(f"[INFO] рядок виводу перевірки {n}" for n in range(1, 3001))
        first = verdict(extra=["bogusExtraField"], enums=[FX_ENTRY])
        run_loop(self.runs, SLUG, verifier(first, GREEN, outputs=[output, "зелено"]), agent("прибрано bogusExtraField"))
        log = self.log(1)
        self.assertIn("ітерація 1", log)
        self.assertRegex(log, r"green\W*(False|false)")
        self.assertTrue(any("bogusExtraField" in line for line in log.splitlines() if "extra" in line), log[:500])
        self.assertFalse(any("bogusExtraField" in line for line in log.splitlines()[:20] if "missing" in line))
        for text in ("marketSchedules", MARKET_ENUM, "FX", "агента покликано: так", output, "прибрано bogusExtraField"):
            with self.subTest(text=text[:40]):
                self.assertIn(text, log)

    def test_stage_instead_of_lists(self):
        run_loop(self.runs, SLUG, verifier(COMPILE_STAGE, GREEN, outputs=["[ERROR] COMPILATION ERROR", "зелено"]),
                 agent())
        log = self.log(1)
        self.assertIn("compile", log)
        self.assertIn(COMPILE_STAGE["reason"], log)
        self.assertNotIn("extra", log)
        self.assertNotIn("missing", log)

    def test_agent_failure_is_logged_and_the_loop_goes_on(self):
        """FR-68: невдалий виклик агента — не падіння; його текст у лозі дослівно, далі — наступна перевірка."""
        failure = "виклик агента не вдався: код 1\nAPI Error: overloaded"
        verify = verifier(RED, GREEN)
        result = run_loop(self.runs, SLUG, verify, agent(failure))
        self.assertIn(failure, self.log(1))
        self.assertEqual(verify.calls, 2)
        self.assertTrue(result.green)


class RunIsFinite(LoopCase):
    """NFR-1, NFR-3: вічно червона перевірка і агент, що не завершується, — 3 перевірки, 2 виклики на ліміті.

    На місці `claude` у PATH — справжній процес, що ніколи не завершується (сценарій специфікації); ліміт агента
    підставлено як 0.5 с, щоб тест тривав секунди."""

    def test_forever_red_and_hanging_agent(self):
        bin_dir = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-bin-"))
        self.addCleanup(shutil.rmtree, bin_dir, ignore_errors=True)
        fake = bin_dir / "claude"
        fake.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
        fake.chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{old}"
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        calls = []

        def hanging(verdict_, output):
            calls.append(1)
            return agent_module.invoke("бриф", cwd=self.runs, timeout=0.5)

        verify = verifier(RED)
        started = time.monotonic()
        result = run_loop(self.runs, SLUG, verify, hanging, max_iterations=3)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual((verify.calls, len(calls)), (3, 2))
        for number in (1, 2):
            with self.subTest(iteration=number):
                self.assertIn("агент не вклався в 0.5 с", self.log(number))
        self.assertEqual(result.summary, "цикл не зійшовся за 3 ітерацій")


if __name__ == "__main__":
    unittest.main()
