# @trace FR-93, NFR-8, NFR-10
"""Межі прогону на рівні процесу CLI (дописано оркестратором 2026-09-30, швидкий шлях).

Чекер приймання показав, що FR-93, NFR-8 і NFR-10 мали лише e2e-доказ (`tests/e2e/evidence.py`), а половина
`local-verifiable` не мала тесту. Поведінка вже існує, тож це покриття, а не test-first: тести зелені з першого
прогону. Шви ті самі, що в `cli_test.py`: справжній `git init`, `LocalServer`, параметри `verify` і `agent`.
"""
import pathlib
import re
import subprocess
import unittest

from cli_test import GREEN, PREMIUM_ENTRY, RED_FUNDING, FUNDING_ENTRY, CliCase, Verifier

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "method_sync"


def git(lib, *args):
    return subprocess.run(["git", "-C", str(lib), *args], capture_output=True, text=True, check=True).stdout


class RunLeavesTheLibraryAlone(CliCase):
    def test_no_difference_leaves_status_unchanged_and_calls_no_agent(self):
        """NFR-8: прогін на методі без розходжень не змінює робочої копії бібліотеки."""
        self.serve()
        before = git(self.lib, "status", "--porcelain")
        code, _, _ = self.cli("--registry", self.registry(PREMIUM_ENTRY), verifier=Verifier({PREMIUM_ENTRY["path"]: [GREEN]}))
        self.assertEqual(code, 0)
        self.assertEqual(git(self.lib, "status", "--porcelain"), before)
        self.assertEqual(self.agent.calls, [])

    def test_run_with_the_agent_stages_nothing_and_moves_no_head(self):
        """NFR-10: прогін не додає в індекс бібліотеки жодного файлу і не рухає HEAD."""
        self.serve()
        git(self.lib, "add", "--", ".claude/skills/add-binance-rest-endpoint/SKILL.md")
        git(self.lib, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "base")
        head, cached = git(self.lib, "rev-parse", "HEAD"), git(self.lib, "diff", "--cached", "--name-only")
        self.cli("--registry", self.registry(FUNDING_ENTRY),
                 verifier=Verifier({FUNDING_ENTRY["path"]: [RED_FUNDING, GREEN]}))
        self.assertTrue(self.agent.calls, "агента мали покликати на червоній перевірці")
        self.assertEqual(git(self.lib, "diff", "--cached", "--name-only"), cached)
        self.assertEqual(git(self.lib, "rev-parse", "HEAD"), head)


class OnlyAllowedCommandsAgainstTheLibrary(unittest.TestCase):
    def test_the_only_maven_goal_the_tool_names_is_dependency_build_classpath(self):
        """FR-93: проти бібліотеки інструмент кличе лише verify_cmd, build-classpath і свій раннер — не тести."""
        maven_goals = set()
        for source in SRC.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            maven_goals |= set(re.findall(r'"(dependency:[a-z-]+|test|surefire:[a-z-]+|failsafe:[a-z-]+|verify|install)"', text))
            self.assertNotRegex(text, r"-Dtest=|surefire|failsafe", source.name)
        self.assertEqual(maven_goals, {"dependency:build-classpath"})


if __name__ == "__main__":
    unittest.main()
