#!/usr/bin/env python3
"""Селф-тест гейта стейджу: unittest зі stdlib, без залежностей.

Запуск: python3 -m unittest discover -s .claude/hooks -p '*_test.py'

Кожен кейс — це справжній payload PreToolUse, який Claude Code подає хуку на stdin, і перевірка,
блокує хук команду чи пропускає. Тест червоніє, якщо гейт перестане ловити котрийсь із випадків,
названих у принципі VII конституції.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HOOK = pathlib.Path(__file__).with_name("block-unsafe-stage.py")
CWD = str(pathlib.Path(__file__).resolve().parents[2])


def run(command, cwd=CWD):
    """Віддати хуку payload і повернути причину блокування або None."""
    payload = json.dumps({"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}})
    out = subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, check=True
    ).stdout.strip()
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


class BlocksBulkStaging(unittest.TestCase):
    def test_dot(self):
        self.assertIn("гуртовий стейдж", run("git add ."))

    def test_all_flags(self):
        for cmd in ("git add -A", "git add --all", "git add -u"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(run(cmd))

    def test_directory(self):
        # Каталог створюється тут, а не береться з репо: у method-sync тест спирався на наявний
        # там specs/ і після перенесення в репо без нього падав з TypeError на None.
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "specs").mkdir()
            self.assertIn("цілий каталог", run("git add specs", cwd=tmp))

    def test_other_repo_via_dash_c(self):
        """Найчастіший випадок інструмента: стейдж у чужій робочій копії через git -C."""
        self.assertIsNotNone(run("git -C /Users/akutil/humex/binancefutures add ."))

    def test_inside_compound_command(self):
        self.assertIsNotNone(run("cd /tmp && git add ."))

    def test_commit_dash_a(self):
        for cmd in ("git commit -am wip", "git commit -a -m wip", "git -c user.name=x commit -a"):
            with self.subTest(cmd=cmd):
                self.assertIn("в обхід поіменних шляхів", run(cmd))


class BlocksSecrets(unittest.TestCase):
    def test_config_properties(self):
        self.assertIn("секретами", run("git add src/test/resources/config.properties"))

    def test_env_and_keys(self):
        for path in (".env", ".env.local", "deploy/id_rsa", "certs/client.p12"):
            with self.subTest(path=path):
                self.assertIsNotNone(run(f"git add {path}"))


class LetsSafeCommandsThrough(unittest.TestCase):
    def test_named_files(self):
        self.assertIsNone(run("git add AGENTS.md CLAUDE.md"))

    def test_named_file_in_other_repo(self):
        self.assertIsNone(run("git -C /Users/akutil/humex/binancefutures add src/main/java/Foo.java"))

    def test_read_only_git(self):
        for cmd in ("git status --short", "git diff", "git log --oneline -5", "git commit -m ok"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(run(cmd))

    def test_not_git_at_all(self):
        self.assertIsNone(run("python3 -m unittest"))


if __name__ == "__main__":
    unittest.main()
