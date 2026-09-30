# @trace FR-30, FR-53, FR-55, FR-65, FR-66, FR-67, FR-68, FR-71, FR-72, FR-73, FR-74, FR-75, FR-76, NFR-3, NFR-13
"""Тести брифу і запуску кодуючого агента (capability `sync-loop`, `enum-verification`, зміна `add-core`).

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Бриф — єдине, на що спирається агент, тож склад брифу перевіряється текстом, як у v1. Запуск агента (`invoke`)
перевіряється на справжньому процесі: на місці `claude` у `PATH` стоїть маленький скрипт, як у сценаріях
специфікації, — він записує свої аргументи, робочий каталог і stdin, зависає або падає з кодом 1. Поведінку
самого агента тут ніхто не підробляє: це межа процесу, а не модель агента.

Відмінності від v1: режиму реалізації з нуля немає (бриф не велить виконувати скіл); бриф несе розходження енамів
і місце нової константи; збій запуску, ненульовий код і таймаут агента — текст для логу, а не виняток.
"""
import inspect
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from method_sync.agent import TIMEOUT_SECONDS, build_brief, command, invoke  # noqa: E402

ROOT = "/work/method-sync-v2"
LIB = f"{ROOT}/.sandbox/binancefutures"
PKG = "com.example.binanceFutures.response"
FUNDING = "/fapi/v1/fundingRate"
FUNDING_MODEL = f"{PKG}.FuturesFundingRateInfo"
MARKET_ENUM = f"{PKG}.MarketType"
REFERENCE = f"{LIB}/src/main/java/com/example/binanceFutures/response/AdlQuantile.java"
FIXTURE = f"{ROOT}/runs/fapi-v1-fundingRate/fixture.json"
VERIFY_CMD = "mvn -q -DskipTests test-compile"
OUTPUT = "[INFO] BUILD SUCCESS\n[INFO] вивід перевірки дослівно"
CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
GRANTING_FLAGS = ("--dangerously-skip-permissions", "--settings", "--mcp-config", "--permission-prompt-tool",
                  "--disallowedTools", "--tools")


def verdict(green=False, extra=(), missing=(), enums=()):
    return {"green": green, "model": [], "live": [], "extra": list(extra), "missing": list(missing), "owners": {},
            "client_error": None, "enums": list(enums)}


BRIEF = dict(lib=LIB, method_path=FUNDING, model=FUNDING_MODEL, reference_method=REFERENCE, fixture_path=FIXTURE,
             mismatch=verdict(missing=["markPrice", "rateType"]), verify_output=OUTPUT, verify_cmd=VERIFY_CMD)


def brief(**overrides):
    fields = dict(BRIEF)
    fields.update(overrides)
    return build_brief(**fields)


def lines_with(text, needle):
    return [line for line in text.splitlines() if needle in line.casefold()]


class BriefCarriesEveryInput(unittest.TestCase):
    """FR-71: абсолютний `lib`, метод, модель, розходження словами, вивід перевірки, фікстура й еталон."""

    def test_names_every_input(self):
        text = brief()
        for part in (LIB, FUNDING, FUNDING_MODEL, OUTPUT, FIXTURE, REFERENCE):
            with self.subTest(part=part[:50]):
                self.assertIn(part, text)

    def test_missing_fields_are_to_add_and_nothing_to_remove(self):
        text = brief()
        missing_lines = lines_with(text, "бракує в моделі")
        extra_lines = lines_with(text, "зайві в моделі")
        self.assertTrue(any("markPrice" in line and "rateType" in line for line in missing_lines), missing_lines)
        self.assertTrue(extra_lines)
        self.assertFalse(any("markPrice" in line or "rateType" in line for line in extra_lines), extra_lines)

    def test_extra_fields_are_to_remove(self):
        text = brief(mismatch=verdict(extra=["bogusExtraField"]))
        self.assertTrue(any("bogusExtraField" in line for line in lines_with(text, "зайві в моделі")))
        self.assertFalse(any("bogusExtraField" in line for line in lines_with(text, "бракує в моделі")))

    def test_no_comparison_names_the_stage_and_empty_output(self):
        text = brief(mismatch={"green": False, "stage": "compile", "reason": "verify_cmd завершилась з кодом 1"},
                     verify_output="")
        self.assertIn("compile", text)
        self.assertRegex(text.casefold(), r"звіряння\b[^.\n]*\bне відбулося")
        self.assertIn("(вивід перевірки порожній)", text)
        self.assertEqual(lines_with(text, "зайві в моделі") + lines_with(text, "бракує в моделі"), [])


class BriefForbidsDocumentationAsASource(unittest.TestCase):
    """FR-30 (половина брифу): поля — лише з фікстури цього прогону, приклад із документації джерелом не є."""

    def test_documentation_is_ruled_out(self):
        text = brief()
        self.assertTrue(any(re.search(r"\bне\b", line.casefold()) for line in lines_with(text, "документац")),
                        "бриф мусить казати, що документація джерелом полів не є")


class BriefMirrorsTheReference(unittest.TestCase):
    """FR-72: еталон — абсолютним шляхом; мірорити його, без власних шаблонів коду, хелперів і формату DTO."""

    def test_reference_and_no_own_templates(self):
        text = brief()
        self.assertIn(REFERENCE, text)
        for stem in ("мірор", "шаблон", "хелпер", "DTO"):
            with self.subTest(stem=stem):
                self.assertIn(stem, text)

    def test_does_not_order_the_style_skill(self):
        """Реалізація з нуля поза обсягом (FR-94): бриф не велить виконувати скіл бібліотеки."""
        self.assertNotIn("Виконай скіл", brief())


class BriefNarrowsTheEdit(unittest.TestCase):
    """FR-73, FR-74: лише склад полів і константи енамів; заборони; місце нових рядків; відхилення — назвати."""

    def test_forbids_everything_else(self):
        text = brief().casefold()
        for stem in ("анотац", "імпорт", "поряд", "форматуван", "коментар"):
            with self.subTest(stem=stem):
                self.assertIn(stem, text)
        self.assertRegex(text, r"інш\w*\s+файл")

    def test_says_where_new_lines_go(self):
        text = brief()
        for part in ("після останнього наявного поля", "після останньої наявної пари", "toString",
                     "перед закриваючим"):
            with self.subTest(part=part):
                self.assertIn(part, text)

    def test_deviations_are_named_not_fixed(self):
        text = brief()
        self.assertIn("відхилення", text)
        self.assertRegex(text, r"(в кінці|наприкінці) відповіді")
        self.assertIn("окремим рядком", text)


class BriefForEnumMismatch(unittest.TestCase):
    """FR-55, FR-53: поле, клас енама і значення; лише дописати перед запасником; наявних констант не чіпати."""

    def setUp(self):
        entry = {"field": "marketSchedules", "enum": MARKET_ENUM,
                 "declared": ["BOGUS_MARKET", "CN_EQUITY", "COMMODITY", "EQUITY", "HK_EQUITY", "KR_EQUITY"],
                 "live": ["CN_EQUITY", "COMMODITY", "EQUITY", "FX", "HK_EQUITY", "KR_EQUITY"],
                 "missing": ["FX"], "unseen": ["BOGUS_MARKET"]}
        self.text = brief(mismatch=verdict(enums=[entry]))

    def test_names_field_enum_and_value(self):
        for part in ("marketSchedules", MARKET_ENUM, "FX"):
            with self.subTest(part=part):
                self.assertIn(part, self.text)

    def test_new_constant_goes_after_the_last_one_and_before_the_sentinel(self):
        self.assertIn("@JsonEnumDefaultValue", self.text)
        self.assertIn("після останньої", self.text)
        self.assertTrue(any("перед" in line for line in lines_with(self.text, "запасник")),
                        "бриф мусить ставити нову константу перед запасником")

    def test_existing_constants_are_left_alone(self):
        text = self.text.casefold()
        for stem in ("видаля", "перейменов", "переставля"):
            with self.subTest(stem=stem):
                self.assertIn(stem, text)
        self.assertNotIn("BOGUS_MARKET", self.text)  # невидиму константу прибрати не просить (FR-53)


class BriefHasOneAllowedCommand(unittest.TestCase):
    """FR-75: `verify_cmd` дослівно — єдина дозволена команда; повертатися лише із зеленим; звіряння не імітувати."""

    def test_verify_cmd_and_the_comparison_stays_with_the_tool(self):
        text = brief()
        self.assertIn(VERIFY_CMD, text)
        self.assertRegex(text, r"лише (з|із) зеленим")
        self.assertIn("не іміту", text)


class BriefKeepsTheAgentInsideTheLibrary(unittest.TestCase):
    """FR-76, NFR-13: лише всередині `lib`; без індексу, історії, тестів і облікових даних; текст українською."""

    def test_four_prohibitions(self):
        text = brief()
        self.assertIn(f"лише всередині {LIB}", text)
        for stem in ("індекс", "історі", "тест", "облікови"):
            with self.subTest(stem=stem):
                self.assertIn(stem, text.casefold())

    def test_names_no_secret_files(self):
        text = brief()
        self.assertNotIn("config.properties", text)
        self.assertNotRegex(text, r"(?<![A-Za-z0-9_])\.env")

    def test_ukrainian_text(self):
        self.assertRegex(brief(), CYRILLIC)


class CommandRunsTheAgentHeadless(unittest.TestCase):
    """FR-65, FR-66, FR-67: `claude -p <бриф> --permission-mode acceptEdits --add-dir <runs> --allowedTools
    Bash(<verify_cmd>)` і більше жодного прапорця, що дає права."""

    def setUp(self):
        self.text = "бриф"
        self.argv = command(self.text, add_dirs=[f"{ROOT}/runs"], allowed_commands=[VERIFY_CMD])

    def value_of(self, flag):
        self.assertEqual(self.argv.count(flag), 1, self.argv)
        return self.argv[self.argv.index(flag) + 1]

    def test_starts_with_claude_print_and_the_brief(self):
        self.assertEqual(self.argv[:3], ["claude", "-p", self.text])

    def test_each_flag_once(self):
        self.assertEqual(self.value_of("--permission-mode"), "acceptEdits")
        self.assertEqual(self.value_of("--add-dir"), f"{ROOT}/runs")
        self.assertEqual(self.value_of("--allowedTools"), f"Bash({VERIFY_CMD})")
        self.assertEqual([arg for arg in self.argv if arg.startswith("Bash(")], [f"Bash({VERIFY_CMD})"])

    def test_nothing_else_grants_rights(self):
        flags = [arg for arg in self.argv if arg.startswith("-")]
        self.assertEqual(sorted(flags), sorted(["-p", "--permission-mode", "--add-dir", "--allowedTools"]))
        for flag in GRANTING_FLAGS:
            with self.subTest(flag=flag):
                self.assertNotIn(flag, self.argv)


class InvokeCase(unittest.TestCase):
    """На місці `claude` у PATH — скрипт; справжній `invoke` запускає його як агента."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-agent-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.lib = self.tmp / "lib"
        self.lib.mkdir()
        old = os.environ["PATH"]
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        os.environ["PATH"] = f"{self.bin}:{old}"

    def fake_claude(self, body):
        fake = self.bin / "claude"
        fake.write_text(body, encoding="utf-8")
        fake.chmod(0o755)


class InvokeHandsTheBriefOverUnchanged(InvokeCase):
    """FR-65: бриф одним аргументом байт у байт, stdin порожній, робочий каталог — `lib`."""

    def test_argv_stdin_and_cwd(self):
        record = self.tmp / "record.json"
        self.fake_claude(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': sys.stdin.read()}},\n"
            f"          open({str(record)!r}, 'w', encoding='utf-8'))\n"
            "print('агент відпрацював')\n")
        text = 'Правка $HOME `whoami` "лапки" \'апостроф\'\nдругий рядок\n\tтаб'
        read_end, write_end = os.pipe()
        os.write(write_end, "дані зі stdin інструмента\n".encode("utf-8"))
        os.close(write_end)
        saved = os.dup(0)
        os.dup2(read_end, 0)
        os.close(read_end)
        try:
            reply = invoke(text, cwd=self.lib, add_dirs=[str(self.tmp)], allowed_commands=[VERIFY_CMD])
        finally:
            os.dup2(saved, 0)
            os.close(saved)
        seen = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(seen["argv"][seen["argv"].index("-p") + 1], text)
        self.assertEqual(seen["stdin"], "")
        self.assertEqual(seen["cwd"], os.path.realpath(self.lib))
        self.assertIn("агент відпрацював", reply)


class InvokeNeverFailsTheRun(InvokeCase):
    """FR-68, NFR-3: ліміт, ненульовий код і невдалий запуск — пояснення для логу, а не виняток."""

    def test_default_limit_is_900_seconds(self):
        self.assertEqual(TIMEOUT_SECONDS, 900)
        self.assertEqual(inspect.signature(invoke).parameters["timeout"].default, 900)

    def test_agent_over_the_limit(self):
        self.fake_claude("#!/bin/sh\nexec sleep 30\n")
        started = time.monotonic()
        reply = invoke("бриф", cwd=self.lib, timeout=0.5)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertIn("агент не вклався в 0.5 с", reply)

    def test_nonzero_exit(self):
        self.fake_claude("#!/bin/sh\necho 'API Error: overloaded'\nexit 1\n")
        reply = invoke("бриф", cwd=self.lib)
        self.assertIn("не вдався", reply)
        self.assertRegex(reply, r"\b1\b")
        self.assertIn("API Error: overloaded", reply)

    def test_agent_cannot_be_started(self):
        empty = self.tmp / "empty-bin"
        empty.mkdir()
        os.environ["PATH"] = str(empty)
        reply = invoke("бриф", cwd=self.lib)
        self.assertIn("не вдалося запустити", reply)
        self.assertIn("No such file or directory", reply)


if __name__ == "__main__":
    unittest.main()
