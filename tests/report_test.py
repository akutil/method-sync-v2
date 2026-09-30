# @trace FR-56, FR-57, FR-77, FR-78, FR-79, FR-80, FR-81, FR-82, FR-83, FR-84, NFR-12, NFR-13
"""Тести звіту прогону (capability `run-report`, `enum-verification`, зміна `add-core`): unittest зі stdlib.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Звіт складає `write_report(runs_dir, slug, **fields)`, як у v1. Значення полів передає прогін: `mismatch`,
`enum_mismatch` і `enum_unseen` — перший вердикт прогону (вердикт звіряння або вердикт стадії), `removed` і
`left_to_human` — переліки, решта — рядки чи числа. Хто і з якого вердикту їх бере, доводить `cli_test.py`.

Відмінності від v1: дванадцять полів замість десяти (`enum_mismatch`, `enum_unseen`), описи всіх шести стадій, ліміт
`verify_cmd` у `mismatch`, ярлик `compile` — «команда перевірки не пройшла (<verify_cmd>)»; неповний звіт не
створює і не змінює `report.md`.
"""
import pathlib
import re
import shutil
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from method_sync.report import LABELS, REPORT_FIELDS, write_report  # noqa: E402

SLUG = "fapi-v1-premiumIndex"
VERIFY_CMD = "mvn -q -DskipTests test-compile"
FIXTURE = f"/work/method-sync-v2/runs/{SLUG}/fixture.json"
MARKET_ENUM = "com.example.binanceFutures.response.MarketType"
ORDER_ENUM = "com.example.binanceFutures.request.FuturesOrderType"
REVIEWER = "не викликався — рецензію запускає окрема сесія (принцип V)"
CLOSING = ("Правка лишена некомічена в робочій копії цільової бібліотеки. Рішення про історію репозиторію належить "
           "людині (принцип VI конституції).")
FIELDS_IN_ORDER = ("mode", "request_source", "response_source", "mismatch", "removed", "verify_cmd", "verify_result",
                   "iterations", "reviewer", "left_to_human", "enum_mismatch", "enum_unseen")
V1_LABELS = {
    "mode": "Режим",
    "request_source": "Джерело параметрів запиту",
    "response_source": "Джерело моделі відповіді",
    "mismatch": "Розходження до правки",
    "removed": "Видалені поля",
    "verify_cmd": "Команда перевірки",
    "verify_result": "Результат перевірки",
    "iterations": "Ітерацій циклу",
    "reviewer": "Висновок рецензента",
    "left_to_human": "Лишилось на людину",
    "enum_mismatch": "Значення енамів, яких бракувало (до правки)",
    "enum_unseen": "Оголошені константи, яких не було в живій відповіді (не видалено)",
}
STAGE_TEXT = {
    "compile": f"звіряння не відбулося: команда перевірки не пройшла ({VERIFY_CMD})",
    "workdir": "звіряння не відбулося: каталог раннера опинився всередині бібліотеки",
    "classpath": "звіряння не відбулося: класпас не зібрався",
    "javac": "звіряння не відбулося: раннер не зібрався",
    "timeout": "звіряння не відбулося: раннер не завершився вчасно",
    "runner": "звіряння не відбулося: раннер не дав придатного вердикту",
}


def verdict(green=False, extra=(), missing=(), enums=()):
    return {"green": green, "model": [], "live": [], "extra": list(extra), "missing": list(missing), "owners": {},
            "client_error": None, "enums": list(enums)}


def enum_entry(field, enum, missing=(), unseen=()):
    return {"field": field, "enum": enum, "declared": [], "live": [], "missing": list(missing),
            "unseen": list(unseen)}


def stage(name, **extra):
    return {"green": False, "stage": name, "reason": f"стадія {name} не пройшла", **extra}


FIRST = verdict(missing=["markPrice", "rateType"])


def base_fields(**overrides):
    fields = {
        "mode": "refresh", "request_source": "registry", "response_source": FIXTURE, "mismatch": FIRST,
        "removed": [], "verify_cmd": VERIFY_CMD, "verify_result": "green", "iterations": 2, "reviewer": REVIEWER,
        "left_to_human": [], "enum_mismatch": FIRST, "enum_unseen": FIRST,
    }
    fields.update(overrides)
    return fields


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.runs = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-runs-"))
        self.addCleanup(shutil.rmtree, self.runs, ignore_errors=True)

    def report(self, **overrides):
        path = write_report(self.runs, SLUG, **base_fields(**overrides))
        return path, path.read_text(encoding="utf-8")

    def value(self, text, name):
        match = re.search(rf"^- \*\*{re.escape(V1_LABELS[name])}\*\* \(`{name}`\): (.*)$", text, re.MULTILINE)
        self.assertIsNotNone(match, f"немає рядка поля {name}")
        return match.group(1)


class LayoutAndLabels(ReportCase):
    """FR-77, FR-78, FR-84: розкладка v1, дванадцять полів у порядку FR-78, підписи, завершальний абзац."""

    def test_field_list_and_labels(self):
        self.assertEqual(tuple(REPORT_FIELDS), FIELDS_IN_ORDER)
        self.assertEqual({name: LABELS[name] for name in FIELDS_IN_ORDER}, V1_LABELS)

    def test_layout(self):
        path, text = self.report()
        self.assertEqual(path, self.runs / SLUG / "report.md")
        lines = text.split("\n")
        self.assertEqual(lines[0], f"# Звіт прогону — {SLUG}")
        self.assertEqual(lines[1], "")
        for number, name in enumerate(FIELDS_IN_ORDER):
            with self.subTest(field=name):
                self.assertTrue(lines[2 + number].startswith(f"- **{V1_LABELS[name]}** (`{name}`): "),
                                lines[2 + number])
        self.assertEqual(lines[14], "")
        self.assertTrue(text.endswith("\n"))
        closing = lines[15:-1]
        self.assertTrue(closing and all(line.strip() for line in closing), closing)
        self.assertEqual(" ".join(closing), CLOSING)
        self.assertEqual(sum(1 for line in lines if line.startswith("- **")), 12)

    def test_verify_cmd_line(self):
        _, text = self.report()
        self.assertIn(f"- **Команда перевірки** (`verify_cmd`): {VERIFY_CMD}\n", text)

    def test_new_report_replaces_the_old_one(self):
        self.report(iterations=5)
        _, text = self.report(iterations=1)
        self.assertEqual(self.value(text, "iterations"), "1")


class ServiceFields(ReportCase):
    """FR-78, FR-83, NFR-13: службові значення як є, ідентифікатори англійською, `left_to_human` — «—»."""

    def test_values(self):
        _, text = self.report()
        self.assertEqual(self.value(text, "mode"), "refresh")
        self.assertEqual(self.value(text, "request_source"), "registry")
        self.assertEqual(self.value(text, "response_source"), FIXTURE)
        self.assertEqual(self.value(text, "iterations"), "2")
        self.assertEqual(self.value(text, "left_to_human"), "—")
        self.assertEqual(self.value(text, "reviewer"), REVIEWER)


class MismatchShowsTheFirstCheck(ReportCase):
    """FR-79, FR-80: `extra`/`missing` першої перевірки або стадія словами, а не тире."""

    def test_extra_and_missing(self):
        _, text = self.report()
        self.assertEqual(self.value(text, "mismatch"), "зайві в моделі: —; бракує в моделі: markPrice, rateType")

    def test_each_stage_in_words(self):
        for name, expected in STAGE_TEXT.items():
            with self.subTest(stage=name):
                _, text = self.report(mismatch=stage(name))
                self.assertEqual(self.value(text, "mismatch"), expected)

    def test_verify_cmd_time_limit(self):
        _, text = self.report(mismatch=stage("compile", limit_s=600))
        self.assertEqual(self.value(text, "mismatch"),
                         f"звіряння не відбулося: команда перевірки не завершилась за 600 с ({VERIFY_CMD})")


class RemovedNamesTheFirstExtra(ReportCase):
    """FR-81: поіменно або «нічого не видалено»."""

    def test_named(self):
        _, text = self.report(removed=["bogusExtraField"],
                              mismatch=verdict(extra=["bogusExtraField"]))
        self.assertEqual(self.value(text, "removed"), "bogusExtraField")
        self.assertEqual(self.value(text, "mismatch"), "зайві в моделі: bogusExtraField; бракує в моделі: —")

    def test_nothing_removed(self):
        _, text = self.report(removed=[])
        self.assertEqual(self.value(text, "removed"), "нічого не видалено")


class VerifyResultNeverPassesRedAsGreen(ReportCase):
    """FR-82: `green`, підсумок циклу або позначка `--dry-run` — дослівно."""

    def test_values(self):
        for result in ("green", "цикл не зійшовся за 5 ітерацій", "dry-run: агента не кликали"):
            with self.subTest(result=result):
                _, text = self.report(verify_result=result)
                self.assertEqual(self.value(text, "verify_result"), result)


class EnumFields(ReportCase):
    """FR-56, FR-57: групи через «; », «розходжень енамів немає», «невидимих констант немає», стадія."""

    def test_enum_mismatch_groups(self):
        first = verdict(enums=[enum_entry("marketSchedules", MARKET_ENUM, missing=["FX"]),
                               enum_entry("type", ORDER_ENUM, missing=["BOGUS_A", "BOGUS_B"])])
        _, text = self.report(enum_mismatch=first, enum_unseen=first)
        self.assertEqual(self.value(text, "enum_mismatch"),
                         f"marketSchedules ({MARKET_ENUM}): FX; type ({ORDER_ENUM}): BOGUS_A, BOGUS_B")
        self.assertEqual(self.value(text, "enum_unseen"), "невидимих констант немає")

    def test_enum_unseen_groups(self):
        first = verdict(enums=[enum_entry("marketSchedules", MARKET_ENUM, unseen=["BOGUS_A", "BOGUS_MARKET"])])
        _, text = self.report(enum_mismatch=first, enum_unseen=first)
        self.assertEqual(self.value(text, "enum_unseen"),
                         f"marketSchedules ({MARKET_ENUM}): BOGUS_A, BOGUS_MARKET — не видалено")
        self.assertEqual(self.value(text, "enum_mismatch"), "розходжень енамів немає")

    def test_no_enum_fields(self):
        _, text = self.report(enum_mismatch=verdict(), enum_unseen=verdict())
        self.assertEqual(self.value(text, "enum_mismatch"), "розходжень енамів немає")
        self.assertEqual(self.value(text, "enum_unseen"), "невидимих констант немає")

    def test_no_comparison(self):
        _, text = self.report(enum_mismatch=stage("compile"), enum_unseen=stage("compile"))
        self.assertEqual(self.value(text, "enum_mismatch"), "звіряння не відбулося")
        self.assertEqual(self.value(text, "enum_unseen"), "звіряння не відбулося")


class IncompleteReportIsNotWritten(ReportCase):
    """FR-78: без поля звіт не пишеться; попередній лишається байт у байт; причина називає поля."""

    def test_previous_report_is_untouched(self):
        previous, _ = self.report()
        before = previous.read_bytes()
        fields = base_fields(iterations=7)
        del fields["enum_mismatch"], fields["enum_unseen"]
        with self.assertRaises(ValueError) as caught:
            write_report(self.runs, SLUG, **fields)
        message = str(caught.exception)
        self.assertIn("звіт не записано: бракує полів", message)
        self.assertIn("enum_mismatch", message)
        self.assertIn("enum_unseen", message)
        self.assertEqual(previous.read_bytes(), before)

    def test_nothing_is_created(self):
        fields = base_fields()
        del fields["mode"]
        with self.assertRaises(ValueError):
            write_report(self.runs, SLUG, **fields)
        self.assertFalse((self.runs / SLUG / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
