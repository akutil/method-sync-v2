# @trace FR-90, FR-91, FR-92, NFR-14
"""Межі інструмента (capability `run-cli`, зміна `add-core`): unittest зі stdlib.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Правило без автоматизованого гейта слабке, тому межі перевіряються читанням власного вихідного коду, як у v1:
жодного запуску git з підкомандою, що міняє історію чи індекс (FR-90); жодного імені файлу з секретами в рядкових
літералах і коментарях (FR-92); лише stdlib (NFR-14). Кожен сканер спершу доводить, що ловить підкладений порушник,
інакше порожній результат по `src/` нічого б не важив. Запис лише під трьома коренями (FR-91) — `assert_writable`
на справжніх каталогах і символьних посиланнях.

Відмінності від v1: git ловиться і рядком команди, і списком аргументів; `.env`, `.secret`, `.p12` — із межами слова,
тож `os.environ` не збіг; сканер секретів читає лише літерали й коментарі (`tokenize`).
"""
import ast
import io
import pathlib
import re
import shutil
import sys
import tempfile
import tokenize
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from method_sync.boundaries import OutsideBoundary, assert_writable  # noqa: E402

SOURCE_DIR = REPO / "src" / "method_sync"
EXPECTED_MODULES = ("__init__", "__main__", "agent", "boundaries", "library", "live", "loop", "registry", "report",
                    "verify")
GIT_SUBCOMMANDS = r"(?:add|commit|push|merge|rebase|reset)"
GIT_LINE = re.compile(rf"\bgit\s+(?:-C\s+\S+\s+)?{GIT_SUBCOMMANDS}\b")
GIT_LIST = re.compile(rf"""['"]git['"]\s*,\s*(?:['"]-C['"]\s*,\s*[^,\]]+,\s*)?['"]{GIT_SUBCOMMANDS}['"]""")
SECRET_PATTERNS = (
    re.compile(r"config\.properties"),
    re.compile(r"id_rsa"),
    re.compile(r"(?<![A-Za-z0-9_])\.env"),
    re.compile(r"\.secret(?![A-Za-z0-9_])"),
    re.compile(r"\.p12(?![A-Za-z0-9_])"),
)
TEXT_TOKENS = {tokenize.STRING, tokenize.COMMENT} | {
    getattr(tokenize, name) for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE") if hasattr(tokenize, name)}


def sources():
    return sorted(SOURCE_DIR.glob("*.py"))


def git_invocations(text):
    return GIT_LINE.findall(text) + GIT_LIST.findall(text)


def secret_names(text):
    """Імена файлів із секретами в рядкових літералах (зокрема docstring і частинах f-рядків) і коментарях."""
    found = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in TEXT_TOKENS:
            found += [match.group(0) for pattern in SECRET_PATTERNS for match in pattern.finditer(token.string)]
    return found


def third_party_imports(path):
    """(модуль, файл) для кожного імпорту поза stdlib і `method_sync`; відносні імпорти не рахуються."""
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    tops = {name.split(".")[0] for name in names}
    return sorted((top, pathlib.Path(path).name) for top in tops
                  if top != "method_sync" and top not in sys.stdlib_module_names)


class PackageIsComplete(unittest.TestCase):
    def test_every_module_exists(self):
        present = {path.stem for path in sources()}
        self.assertEqual(sorted(set(EXPECTED_MODULES) - present), [])


class NeverTouchesGitHistory(unittest.TestCase):
    """FR-90: ні рядком команди, ні списком аргументів."""

    def test_scanner_catches_both_forms(self):
        planted = ('subprocess.run(["git", "add", path])\n'
                   'os.system("git commit -m x")\n'
                   'subprocess.run(["git", "-C", lib, "reset", "--hard"])\n')
        self.assertEqual(len(git_invocations(planted)), 3)
        self.assertEqual(git_invocations('subprocess.run(["git", "-C", lib, "status"])\n"git status"'), [])

    def test_sources_have_none(self):
        for source in sources():
            with self.subTest(file=source.name):
                self.assertEqual(git_invocations(source.read_text(encoding="utf-8")), [])


class NeverNamesSecretFiles(unittest.TestCase):
    """FR-92: імена файлів із секретами не стоять у літералах і коментарях; `os.environ` — не збіг."""

    def test_scanner_catches_planted_names(self):
        planted = ('open("config.properties")  # id_rsa\n'
                   'glob(f"{root}/.env*")\n'
                   'names = ["keys.secret", "cert.p12"]\n')
        self.assertEqual(len(secret_names(planted)), 5)
        self.assertEqual(secret_names('value = os.environ["HOME"]\nlabel = "a.secrets, x.p12a, my.environment"\n'),
                         [])

    def test_sources_have_none(self):
        for source in sources():
            with self.subTest(file=source.name):
                self.assertEqual(secret_names(source.read_text(encoding="utf-8")), [])


class OnlyStandardLibrary(unittest.TestCase):
    """NFR-14: імпорти пакета — лише `sys.stdlib_module_names` Python 3.14 і `method_sync`."""

    def test_scanner_names_the_module_and_the_file(self):
        planted = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-src-")) / "planted.py"
        self.addCleanup(shutil.rmtree, planted.parent, ignore_errors=True)
        planted.write_text("import json\nimport requests.adapters\nfrom . import live\n"
                           "from method_sync import registry\n", encoding="utf-8")
        self.assertEqual(third_party_imports(planted), [("requests", "planted.py")])

    def test_sources_import_only_stdlib(self):
        for source in sources():
            with self.subTest(file=source.name):
                self.assertEqual(third_party_imports(source), [])


class WritesOnlyUnderThreeRoots(unittest.TestCase):
    """FR-91: `runs/`, тимчасовий каталог прогону і цільова бібліотека; шлях — після `..` і символьних посилань."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-roots-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lib, self.runs, self.run_tmp, self.outside = (self.tmp / name for name in ("lib", "runs", "run", "docs"))
        for directory in (self.lib, self.runs, self.run_tmp, self.outside):
            directory.mkdir()
        self.roots = (self.lib, self.runs, self.run_tmp)

    def test_allows_the_three_roots(self):
        for path in (self.lib / "src/main/java/Foo.java", self.runs / "fapi-v1-premiumIndex/fixture.json",
                     self.run_tmp / "MethodSyncVerify.java"):
            with self.subTest(path=path):
                assert_writable(path, self.roots)

    def test_rejects_anything_else_and_names_the_path(self):
        with self.assertRaises(OutsideBoundary) as caught:
            assert_writable(self.outside / "fixture.json", self.roots)
        self.assertIn(str((self.outside / "fixture.json").resolve()), str(caught.exception))

    def test_rejects_escape_through_parent(self):
        with self.assertRaises(OutsideBoundary):
            assert_writable(self.runs / ".." / "docs" / "fixture.json", self.roots)

    def test_rejects_escape_through_symlink(self):
        (self.runs / "fapi-v1-fundingRate").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(OutsideBoundary) as caught:
            assert_writable(self.runs / "fapi-v1-fundingRate" / "fixture.json", self.roots)
        self.assertIn(str(self.outside.resolve() / "fixture.json"), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
