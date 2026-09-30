# @trace FR-20, FR-21, FR-22, FR-72
"""Тести навігації по цільовій бібліотеці (capability `run-cli`, `sync-loop`, зміна `add-core`): unittest зі stdlib.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Модуль зі шляху (FR-21), письмовий стандарт стилю (FR-22), файл класу моделі (FR-20) і еталонний файл для брифу
(FR-72) — на тимчасових каталогах і на одноразовій копії `.sandbox/binancefutures` (лише читання). Робочої копії
людини тести не торкаються, на відміну від v1.

Відмінності від v1: режиму реалізації з нуля немає (без `service_file`, `style_skill`, `is_implemented`); еталон
обирається за кодовими точками Unicode.
"""
import pathlib
import shutil
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from method_sync.library import (  # noqa: E402
    STYLE_STANDARD,
    StyleStandardMissing,
    model_file,
    module_for,
    reference_model,
    style_standard,
)

SANDBOX = REPO / ".sandbox" / "binancefutures"
PKG = "com.example.binanceFutures.response"
MARK_MODEL = f"{PKG}.FuturesMarkPriceInfo"
RESPONSE = pathlib.Path("src/main/java/com/example/binanceFutures/response")


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self.lib = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-lib-"))
        self.addCleanup(shutil.rmtree, self.lib, ignore_errors=True)

    def put(self, relative, text=""):
        path = self.lib / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class DerivesModuleFromThePathPrefix(unittest.TestCase):
    """FR-21: п'ять відомих префіксів; інший — помилка (CLI зупиняє метод кодом 2)."""

    def test_known_prefixes(self):
        cases = {
            "/fapi/v1/premiumIndex": "binanceFutures",
            "/dapi/v1/fundingRate": "binanceDelivery",
            "/sapi/v1/margin/allPairs": "binanceMargin",
            "/papi/v1/balance": "portfolioMargin",
            "/api/v3/ticker/price": "binanceSpot",
        }
        for path, module in cases.items():
            with self.subTest(path=path):
                self.assertEqual(module_for(path), module)

    def test_unknown_prefix(self):
        with self.assertRaises(ValueError):
            module_for("/eapi/v1/ticker")


class RequiresTheWrittenStyleStandard(LibraryCase):
    """FR-22: без `SKILL.md` — `StyleStandardMissing`, що називає очікуваний шлях із фактичним `lib`."""

    def test_path(self):
        self.assertEqual(STYLE_STANDARD, ".claude/skills/add-binance-rest-endpoint/SKILL.md")

    def test_missing(self):
        with self.assertRaises(StyleStandardMissing) as caught:
            style_standard(self.lib)
        self.assertIn(f"{self.lib}/.claude/skills/add-binance-rest-endpoint/SKILL.md", str(caught.exception))

    def test_present(self):
        self.put(STYLE_STANDARD, "# стандарт\n")
        style_standard(self.lib)


class FindsTheModelClass(LibraryCase):
    """FR-20: `<lib>/src/main/java/<model з / замість .>.java` або `None`."""

    def test_present_and_absent(self):
        expected = self.put(f"src/main/java/{MARK_MODEL.replace('.', '/')}.java", "public class X {}\n")
        self.assertEqual(model_file(self.lib, MARK_MODEL), expected)
        self.assertIsNone(model_file(self.lib, f"{PKG}.NoSuchInfo"))


class PicksTheReferenceFile(LibraryCase):
    """FR-72: перший за кодовими точками `*.java` у `response/`, без ` extends ` і `import com.binance`."""

    def test_first_self_contained_file(self):
        self.put(RESPONSE / "Alpha.java", "public class Alpha extends Base {\n}\n")
        self.put(RESPONSE / "Beta.java", "import com.binance.api.client.domain.market.TickerPrice;\n"
                                         "public class Beta {\n}\n")
        self.put(RESPONSE / "Gamma.java", "public class Gamma {\n}\n")
        self.put(RESPONSE / "delta.java", "public class delta {\n}\n")  # за колацією локалі стояв би раніше Gamma
        found = reference_model(self.lib, "binanceFutures")
        self.assertEqual(found, self.lib / RESPONSE / "Gamma.java")
        self.assertTrue(found.is_absolute())

    @unittest.skipUnless(SANDBOX.is_dir(), "немає копії .sandbox/binancefutures")
    def test_reference_in_the_sandbox_clone(self):
        found = reference_model(SANDBOX, "binanceFutures")
        self.assertEqual(found, SANDBOX / RESPONSE / "AdlQuantile.java")

    @unittest.skipUnless(SANDBOX.is_dir(), "немає копії .sandbox/binancefutures")
    def test_sandbox_clone_has_the_standard_and_the_model(self):
        style_standard(SANDBOX)
        self.assertIsNotNone(model_file(SANDBOX, MARK_MODEL))


if __name__ == "__main__":
    unittest.main()
