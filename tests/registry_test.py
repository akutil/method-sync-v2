# @trace FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, FR-10, NFR-11
"""Тести реєстру методів (capability `registry`, слайс `add-input`): unittest зі stdlib, без залежностей.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Реєстр веде людина руками, а інструмент перевіряє його цілком до першого методу. Кожен кейс — сценарій зі
спеки `openspec/changes/add-input/specs/registry/spec.md`: або придатний реєстр і те, що з нього прочитано, або
непридатний, і тоді `RegistryError`, чий текст називає винуватця: поле і місце (`верхнього рівня`, `[live]`,
`#N` чи `path` запису), шлях файлу реєстру чи значення `lib`. Будь-який інший клас винятку — теж провал: CLI
показав би його трасуванням (NFR-11, design.md D5).

«Придатний реєстр» — дослівно зі сценарію «Базовий придатний реєстр приймається»; його `lib` — тимчасовий
каталог після справжнього `git init`. «Варіант» — той самий текст, де замінено лише названий рядок чи секцію.

Процес CLI тут не запускається, тож слайс `add-run-cli` доводить те, що видно лише на ньому (design.md,
«Покриття сценаріїв у цьому слайсі»): сценарій «Без --registry прогін не починається» (FR-1), код виходу `2`,
повідомлення в stderr без трасування (NFR-11), stdout без рядків методів, незмінні `runs/` і `git status` `lib`.
"""
import contextlib
import dataclasses
import datetime
import io
import itertools
import json
import os
import pathlib
import pwd
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
import uuid
import warnings

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import method_sync.registry as registry  # noqa: E402

PREMIUM, FUNDING, SCHEDULE = "/fapi/v1/premiumIndex", "/fapi/v1/fundingRate", "/fapi/v1/tradingSchedule"
PKG = "com.example.binanceFutures.response"
TOP, LIVE = "верхнього рівня", "[live]"

# Сценарій «Базовий придатний реєстр приймається», дослівно: коментарі `#`, `lib` (абсолютний шлях до каталогу
# після `git init` стане на місце "<repo>"), `verify_cmd`, `status`, секція `[live]` і два записи `[[method]]`.
VALID = """\
# Реєстр method-sync: які методи біржі звіряти і чим перевіряти бібліотеку.
lib = "<repo>"
verify_cmd = "mvn -q -DskipTests test-compile"
status = "active"

# Базова адреса живого виклику.
[live]
base_url = "https://nonexistent.invalid"

# Уже реалізовані методи.
[[method]]
path = "/fapi/v1/premiumIndex"
model = "com.example.binanceFutures.response.FuturesMarkPriceInfo"
client_method = "getMarkPrice"
args = { symbol = "BTCUSDT" }

[[method]]
path = "/fapi/v1/fundingRate"
model = "com.example.binanceFutures.response.FuturesFundingRateInfo"
client_method = "getFundingRates"
args = { symbol = "BTCUSDT", limit = 3 }
call = '"BTCUSDT", 3, null, null'
"""
RECORDS = "# Уже реалізовані методи.\n"  # з цього рядка до кінця файлу — обидва записи [[method]]

# Рядки придатного реєстру, які замінюють варіанти.
STATUS = 'status = "active"\n'
VERIFY_CMD = 'verify_cmd = "mvn -q -DskipTests test-compile"\n'
BASE_URL = 'base_url = "https://nonexistent.invalid"\n'
LIVE_SECTION = "[live]\n" + BASE_URL
PREMIUM_PATH = 'path = "/fapi/v1/premiumIndex"\n'
PREMIUM_MODEL = f'model = "{PKG}.FuturesMarkPriceInfo"\n'
PREMIUM_CLIENT = 'client_method = "getMarkPrice"\n'
PREMIUM_ARGS = 'args = { symbol = "BTCUSDT" }\n'
FUNDING_PATH = 'path = "/fapi/v1/fundingRate"\n'
FUNDING_MODEL = f'model = "{PKG}.FuturesFundingRateInfo"\n'
FUNDING_CLIENT = 'client_method = "getFundingRates"\n'
FUNDING_CALL = '"BTCUSDT", 3, null, null'
FUNDING_CALL_LINE = f"call = '{FUNDING_CALL}'\n"

# Третій запис зі сценарію «Необов'язкові поля можна пропустити»: без `args` і без `call`.
THIRD = f"""
[[method]]
path = "/fapi/v1/tradingSchedule"
model = "{PKG}.TradingScheduleResponse"
client_method = "getTradingSchedule"
"""


def git_init(path):
    """Справжній git-репозиторій у тимчасовому каталозі: реєстр вимагає каталог із `.git` (FR-6)."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, capture_output=True, env=env)
    return path


def git_status(path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(["git", "-C", str(path), "status", "--porcelain"], check=True, capture_output=True,
                          text=True, env=env).stdout


def toml_string(value):
    """Базовий рядок TOML для шляху: екранування JSON — підмножина екранування TOML."""
    return json.dumps(str(value))


def top(line):
    """Заміна, що додає рядок на верхньому рівні, до секції [live] (одразу після `status`)."""
    return STATUS, STATUS + line + "\n"


class RegistryCase(unittest.TestCase):
    """Спільне для сценаріїв: бібліотека після `git init`, придатний реєстр, його варіанти і вердикт `load()`."""

    @classmethod
    def setUpClass(cls):
        shared = pathlib.Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.repo = git_init(shared / "repo")
        cls.lib_line = f"lib = {toml_string(cls.repo)}\n"
        cls.valid = VALID.replace('lib = "<repo>"\n', cls.lib_line)

    def setUp(self):
        self.tmp = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.numbers = itertools.count(1)

    # -- входи ----------------------------------------------------------------------------------------------
    def variant(self, *edits, text=None):
        """Придатний реєстр, де замінено лише названі рядки чи секції; кожен старий шматок трапляється рівно раз."""
        text = self.valid if text is None else text
        for old, new in edits:
            self.assertEqual(text.count(old), 1, f"варіант не зібрано: {old!r} мусить трапитися рівно раз")
            text = text.replace(old, new)
        return text

    def without_records(self, *edits):
        """Придатний реєстр без обох записів [[method]]; усе до них — як було."""
        return self.variant(*edits, text=self.valid[: self.valid.index(RECORDS)])

    def write(self, text, directory=None):
        path = (directory or self.tmp) / f"registry-{next(self.numbers)}.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    # -- вердикт --------------------------------------------------------------------------------------------
    def accepts(self, text):
        return self.accepts_path(self.write(text))

    def accepts_path(self, path):
        """Реєстр прийнято: `load()` віддає Registry, нічого не пише в stderr і не попереджає."""
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            loaded = registry.load(path)
        self.assertIsInstance(loaded, registry.Registry)
        self.assertEqual(stderr.getvalue(), "", "load() писав у stderr")
        self.assertEqual([str(item.message) for item in caught], [], "load() попереджав")
        return loaded

    def rejects(self, text):
        return self.rejects_path(self.write(text))

    def rejects_path(self, path):
        """Реєстр відхилено саме `RegistryError`; віддає текст повідомлення."""
        try:
            registry.load(path)
        except registry.RegistryError as error:
            message = str(error)
        except Exception as error:  # інший клас CLI показав би трасуванням (NFR-11, design.md D5)
            self.fail(f"load() кинув {type(error).__name__}, а не RegistryError: {error}")
        else:
            self.fail(f"load() прийняв непридатний реєстр {path}")
        self.assertTrue(message.strip(), "порожнє повідомлення нікого не називає")
        return message

    # -- що назване в повідомленні --------------------------------------------------------------------------
    def assertNames(self, message, *fields):
        """Поле названо окремим словом, а не шматком шляху чи іншого слова."""
        for name in fields:
            self.assertRegex(message, rf"(?<!\w){re.escape(name)}(?!\w)", f"повідомлення не називає поле {name}")

    def assertRecord(self, message, number, path=None):
        """Запис названо номером `#N` (лік із 1) або своїм `path`: спека приймає будь-що з двох."""
        by_number = re.search(rf"#{number}(?!\d)", message) is not None
        by_path = path is not None and path in message
        named = f"#{number}" + (f" чи {path}" if path else "")
        self.assertTrue(by_number or by_path, f"повідомлення не називає запис {named}: {message}")

    def assertNotRecord(self, message, number, path):
        """Винуватець — інший запис, тож цей не названо ні номером, ні шляхом."""
        self.assertIsNone(re.search(rf"#{number}(?!\d)", message), f"названо не той запис #{number}: {message}")
        self.assertNotIn(path, message, f"названо не той запис {path}: {message}")


class ReadsValidRegistry(RegistryCase):
    """Вимога «Вхід прогону — TOML-файл з аргументу --registry» (FR-1): сценарій «Базовий придатний реєстр
    приймається» — реєстр у стилі v1 розібрано `tomllib` і віддано прогону як є."""

    def test_top_level_fields(self):
        loaded = self.accepts(self.valid)
        self.assertEqual(loaded.lib, self.repo)
        self.assertEqual(loaded.verify_cmd, "mvn -q -DskipTests test-compile")
        self.assertEqual(loaded.base_url, "https://nonexistent.invalid")
        self.assertEqual(loaded.status, "active")
        self.assertIsNone(loaded.credentials)

    def test_methods_in_file_order_as_written(self):
        methods = self.accepts(self.valid).methods
        self.assertIsInstance(methods, list)
        self.assertEqual([type(method) for method in methods], [registry.Method, registry.Method])
        first, second = methods
        self.assertEqual((first.path, first.model, first.client_method),
                         (PREMIUM, f"{PKG}.FuturesMarkPriceInfo", "getMarkPrice"))
        self.assertEqual(first.args, {"symbol": "BTCUSDT"})
        self.assertIsNone(first.call)
        self.assertEqual((second.path, second.model, second.client_method),
                         (FUNDING, f"{PKG}.FuturesFundingRateInfo", "getFundingRates"))
        self.assertEqual(list(second.args.items()), [("symbol", "BTCUSDT"), ("limit", 3)])
        self.assertEqual([type(value) for value in second.args.values()], [str, int])
        self.assertEqual(second.call, FUNDING_CALL)

    def test_model_is_frozen_dataclasses_named_in_design(self):
        """design.md D1: наступні слайси беруть атрибути й незмінність, тож імена полів — контракт модуля."""
        self.assertEqual([item.name for item in dataclasses.fields(registry.Registry)],
                         ["lib", "verify_cmd", "base_url", "status", "credentials", "methods"])
        self.assertEqual([item.name for item in dataclasses.fields(registry.Method)],
                         ["path", "model", "client_method", "args", "call"])
        bare = registry.Method(path=SCHEDULE, model=f"{PKG}.TradingScheduleResponse", client_method="getTradingSchedule")
        self.assertEqual((bare.args, bare.call), ({}, None))
        self.assertIsNot(bare.args, registry.Method(path=SCHEDULE, model="m", client_method="c").args)
        loaded = self.accepts(self.valid)
        for target, name in ((loaded, "base_url"), (loaded.methods[0], "path")):
            with self.subTest(type(target).__name__), self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(target, name, "changed")


class OptionalStatusAndCredentials(RegistryCase):
    """Вимога «Необов'язкові поля status і credentials» (FR-3): будь-яке значення TOML, типове `status` —
    `active`, шлях `credentials` не перевіряється, решта реєстру від них не залежить."""

    def test_default_and_any_toml_value(self):
        base = self.accepts(self.valid)
        cases = (
            ("без рядка status", self.variant((STATUS, "")), "active", None),
            ('status = "paused", credentials = "/no/such/keys.properties"',
             self.variant((STATUS, 'status = "paused"\ncredentials = "/no/such/keys.properties"\n')),
             "paused", "/no/such/keys.properties"),
            ("status = 5, credentials = true", self.variant((STATUS, "status = 5\ncredentials = true\n")), 5, True),
            # Поза трьома варіантами сценарію, з тексту вимоги «будь-яке значення TOML»: масив і таблиця.
            ('status = [1, 2], credentials = { file = "/no/such/keys.properties" }',
             self.variant((STATUS, 'status = [1, 2]\ncredentials = { file = "/no/such/keys.properties" }\n')),
             [1, 2], {"file": "/no/such/keys.properties"}),
        )
        for label, text, status, credentials in cases:
            with self.subTest(label):
                loaded = self.accepts(text)
                self.assertEqual(loaded.status, status)
                self.assertIs(type(loaded.status), type(status))
                self.assertEqual(loaded.credentials, credentials)
                self.assertIs(type(loaded.credentials), type(credentials))
                self.assertEqual((loaded.lib, loaded.verify_cmd, loaded.base_url, loaded.methods),
                                 (base.lib, base.verify_cmd, base.base_url, base.methods))


class RequiredTopLevelFields(RegistryCase):
    """Вимога «Обов'язкові поля верхнього рівня» (FR-2): поле, якого бракує чи яке `""`, названо з місцем."""

    def test_missing_or_empty_field_named_with_its_place(self):
        """Чотири варіанти сценарію «Бракує обов'язкового поля або воно порожнє»."""
        cases = (
            ("без рядка verify_cmd", self.variant((VERIFY_CMD, "")), "verify_cmd", TOP),
            ("без секції [live]", self.variant((LIVE_SECTION, "")), "base_url", LIVE),
            ('lib = ""', self.variant((self.lib_line, 'lib = ""\n')), "lib", TOP),
            ('base_url = ""', self.variant((BASE_URL, 'base_url = ""\n')), "base_url", LIVE),
        )
        for label, text, name, place in cases:
            with self.subTest(label):
                message = self.rejects(text)
                self.assertNames(message, name)
                self.assertIn(place, message)

    def test_other_combinations_from_the_requirement(self):
        cases = (
            ("без рядка lib", self.variant((self.lib_line, "")), "lib", TOP),
            ('verify_cmd = ""', self.variant((VERIFY_CMD, 'verify_cmd = ""\n')), "verify_cmd", TOP),
            ("секція [live] без base_url", self.variant((BASE_URL, "")), "base_url", LIVE),
        )
        for label, text, name, place in cases:
            with self.subTest(label):
                message = self.rejects(text)
                self.assertNames(message, name)
                self.assertIn(place, message)


class UnknownFields(RegistryCase):
    """Вимога «Невідоме поле робить реєстр непридатним» (FR-4): поле й місце на кожному рівні."""

    def test_unknown_field_on_every_level(self):
        """Чотири варіанти сценарію «Невідоме поле на кожному рівні»."""
        cases = (
            ('whoops = "typo" на верхньому рівні', self.variant(top('whoops = "typo"')), "whoops", TOP),
            ("секція [foo] з bar = 1 у кінці файлу", self.valid + "\n[foo]\nbar = 1\n", "foo", TOP),
            ("timeout = 5 у секції [live]", self.variant((BASE_URL, BASE_URL + "timeout = 5\n")), "timeout", LIVE),
        )
        for label, text, name, place in cases:
            with self.subTest(label):
                message = self.rejects(text)
                self.assertNames(message, name)
                self.assertIn(place, message)
        with self.subTest('extra_field = "typo" у записі /fapi/v1/premiumIndex'):
            message = self.rejects(self.variant((PREMIUM_CLIENT, PREMIUM_CLIENT + 'extra_field = "typo"\n')))
            self.assertNames(message, "extra_field")
            self.assertRecord(message, 1, PREMIUM)

    def test_unknown_field_in_second_record_names_that_record(self):
        message = self.rejects(self.variant((FUNDING_CLIENT, FUNDING_CLIENT + 'extra_field = "typo"\n')))
        self.assertNames(message, "extra_field")
        self.assertRecord(message, 2, FUNDING)
        self.assertNotRecord(message, 1, PREMIUM)


class FieldTypes(RegistryCase):
    """Вимога «Тип поля реєстру» (FR-4, FR-9, NFR-11): хибний тип TOML — `RegistryError` з полем і місцем,
    а не `TypeError` чи мовчазна згода, як у v1."""

    def test_wrong_type_named_with_its_place(self):
        """П'ять варіантів сценарію «Поле не того типу»."""
        with self.subTest('args = "symbol=BTCUSDT" у записі /fapi/v1/premiumIndex'):
            message = self.rejects(self.variant((PREMIUM_ARGS, 'args = "symbol=BTCUSDT"\n')))
            self.assertNames(message, "args")
            self.assertRecord(message, 1, PREMIUM)
        with self.subTest("lib = 5"):
            message = self.rejects(self.variant((self.lib_line, "lib = 5\n")))
            self.assertNames(message, "lib")
            self.assertIn(TOP, message)
        with self.subTest('секцію [live] замінено рядком live = "x"'):
            message = self.rejects(self.variant((LIVE_SECTION, ""), top('live = "x"')))
            self.assertNames(message, "live")
            self.assertIn(TOP, message)
        with self.subTest("call = 5 у записі /fapi/v1/fundingRate"):
            message = self.rejects(self.variant((FUNDING_CALL_LINE, "call = 5\n")))
            self.assertNames(message, "call")
            self.assertRecord(message, 2, FUNDING)
            self.assertNotRecord(message, 1, PREMIUM)
        with self.subTest("обидва записи замінено рядком method = [5]"):
            self.assertRegex(self.rejects(self.without_records(top("method = [5]"))), r"#1(?!\d)")

    def test_every_typed_field_from_the_requirement(self):
        """Решта полів із тексту вимоги: рядки, таблиця `args`, масив `method` і його елемент."""
        cases = (
            ("verify_cmd = 5", self.variant((VERIFY_CMD, "verify_cmd = 5\n")), "verify_cmd", TOP, None),
            ("base_url = 5", self.variant((BASE_URL, "base_url = 5\n")), "base_url", LIVE, None),
            ('method = "x" замість масиву', self.without_records(top('method = "x"')), "method", TOP, None),
            # Без придатного `path` запис називають номером (спека: «запис без path — номером»).
            ("path = 5 у записі #1", self.variant((PREMIUM_PATH, "path = 5\n")), "path", None, (1, None)),
            ("model = 5 у записі #1", self.variant((PREMIUM_MODEL, "model = 5\n")), "model", None, (1, PREMIUM)),
            ("client_method = true у записі #1", self.variant((PREMIUM_CLIENT, "client_method = true\n")),
             "client_method", None, (1, PREMIUM)),
            ("args = [1] у записі #1", self.variant((PREMIUM_ARGS, "args = [1]\n")), "args", None, (1, PREMIUM)),
        )
        for label, text, name, place, record in cases:
            with self.subTest(label):
                message = self.rejects(text)
                self.assertNames(message, name)
                if place:
                    self.assertIn(place, message)
                if record:
                    self.assertRecord(message, *record)
        with self.subTest("елемент method = [true] — ні таблиця, ні рядок"):
            self.assertRegex(self.rejects(self.without_records(top("method = [true]"))), r"#1(?!\d)")

    def test_values_inside_args_are_not_checked(self):
        """Сценарій «Значення всередині args не перевіряються»: типи `tomllib`, порядок запису."""
        loaded = self.accepts(self.variant(
            (PREMIUM_ARGS, 'args = { symbol = "BTCUSDT", day = 2026-09-30, ids = [1, 2], anyParam = "x" }\n')))
        args = loaded.methods[0].args
        self.assertEqual(list(args), ["symbol", "day", "ids", "anyParam"])
        self.assertEqual(list(args.values()), ["BTCUSDT", datetime.date(2026, 9, 30), [1, 2], "x"])
        self.assertEqual([type(value) for value in args.values()], [str, datetime.date, list, str])


class RegistryFile(RegistryCase):
    """Вимога «Файл реєстру існує і розбирається як TOML» (FR-5) і випадки design.md D5 (NFR-11): повідомлення
    містить шлях до файлу, а для помилки розбору — ще й текст помилки `tomllib`."""

    def test_missing_file_named_by_its_path(self):
        missing = "/no/such/registry.toml"
        self.assertFalse(os.path.exists(missing), f"передумова: файлу {missing} не має бути")
        self.assertIn(missing, self.rejects_path(missing))

    def test_unparsable_file_named_with_the_tomllib_error(self):
        cases = (
            ('lib = "unterminated', self.variant((self.lib_line, 'lib = "unterminated\n')), "Illegal character"),
            ("рядок lib записано двічі", self.variant((self.lib_line, self.lib_line * 2)), "Cannot overwrite a value"),
        )
        for label, text, prefix in cases:
            with self.subTest(label):
                with self.assertRaises(tomllib.TOMLDecodeError) as parsed:
                    tomllib.loads(text)
                expected = str(parsed.exception)  # оракул: текст tomllib саме цього Python
                self.assertTrue(expected.startswith(prefix), f"tomllib цього Python каже інакше: {expected!r}")
                path = self.write(text)
                message = self.rejects_path(path)
                self.assertIn(path, message)
                self.assertIn(expected, message)

    def test_directory_instead_of_file(self):
        self.assertIn(str(self.tmp), self.rejects_path(str(self.tmp)))

    def test_unreadable_file(self):
        if os.geteuid() == 0:
            self.skipTest("root читає файл і без прав — відмову в доступі тут не відтворити")
        path = self.write(self.valid)
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        self.assertIn(path, self.rejects_path(path))

    def test_file_not_in_utf8(self):
        """Реєстр, збережений редактором у cp1251: v1 падав `UnicodeDecodeError`, тобто трасуванням."""
        path = self.tmp / "cp1251.toml"
        path.write_bytes(self.valid.encode("utf-8") + "# коментар у cp1251\n".encode("cp1251"))
        self.assertIn(str(path), self.rejects_path(str(path)))


class LibraryRepository(RegistryCase):
    """Вимога «Цільова бібліотека lib — наявний git-репозиторій» (FR-6): відносний шлях — від поточного каталогу
    процесу, `~` — від `HOME`, реєстр віддає `lib` як записано, лише з розгорнутим `~`."""

    def test_relative_lib_checked_from_cwd_and_returned_as_written(self):
        cwd, elsewhere = self.tmp / "A", self.tmp / "B"
        git_init(cwd / "sidecar-lib")
        elsewhere.mkdir()
        self.assertFalse((elsewhere / "sidecar-lib").exists(), "передумова: поруч із файлом реєстру sidecar-lib немає")
        path = self.write(self.variant((self.lib_line, 'lib = "sidecar-lib"\n')), directory=elsewhere)
        self.enterContext(contextlib.chdir(cwd))
        loaded = self.accepts_path(path)
        self.assertEqual(loaded.lib, pathlib.Path("sidecar-lib"))
        self.assertFalse(loaded.lib.is_absolute())

    def test_tilde_expands_to_home(self):
        home = self.tmp / "H"
        git_init(home / "homelib")
        self.set_env("HOME", str(home))
        loaded = self.accepts(self.variant((self.lib_line, 'lib = "~/homelib"\n')))
        self.assertEqual(loaded.lib, home / "homelib")

    def test_missing_or_non_git_lib_named_by_its_value(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        regular = self.tmp / "not-a-directory"
        regular.write_text("x\n", encoding="utf-8")
        cases = (
            ('lib = "/no/such/library"', "/no/such/library"),
            ("наявний каталог без .git", str(plain)),
            ("звичайний файл замість каталогу", str(regular)),
        )
        for label, value in cases:
            with self.subTest(label):
                self.assertIn(value, self.rejects(self.variant((self.lib_line, f"lib = {toml_string(value)}\n"))))

    def test_tilde_of_unknown_user_is_a_registry_error(self):
        """design.md D5, NFR-11: `expanduser()` на `~` неіснуючого користувача кидає RuntimeError (v1 — трасування)."""
        user = f"method-sync-no-such-user-{uuid.uuid4().hex[:8]}"
        with self.assertRaises(KeyError, msg=f"передумова: користувача {user} не має бути"):
            pwd.getpwnam(user)
        value = f"~{user}/lib"
        self.assertIn(value, self.rejects(self.variant((self.lib_line, f"lib = {toml_string(value)}\n"))))

    def set_env(self, key, value):
        old = os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.pop(key, None) if old is None else os.environ.__setitem__(key, old))


class NoMethods(RegistryCase):
    """Вимога «Реєстр без жодного методу непридатний» (FR-7)."""

    def test_registry_without_any_method(self):
        cases = (("без записів [[method]]", self.without_records()),
                 ("method = [] на верхньому рівні", self.without_records(top("method = []"))))
        for label, text in cases:
            with self.subTest(label):
                self.assertIn("немає жодного методу", self.rejects(text))


class MethodRecords(RegistryCase):
    """Вимога «Запис методу — path, model, client_method, args, call» (FR-8)."""

    def test_optional_args_and_call_can_be_omitted(self):
        """Сценарій «Необов'язкові поля можна пропустити»: `args` — порожня таблиця, `call` дослівно, навіть `""`."""
        for label, text, call in (("без args і call", self.valid + THIRD, None),
                                  ('call = ""', self.valid + THIRD + 'call = ""\n', "")):
            with self.subTest(label):
                methods = self.accepts(text).methods
                self.assertEqual([method.path for method in methods], [PREMIUM, FUNDING, SCHEDULE])
                self.assertEqual(methods[2].args, {})
                self.assertIsInstance(methods[2].args, dict)
                if call is None:
                    self.assertIsNone(methods[2].call)
                else:
                    self.assertEqual(methods[2].call, call)

    def test_missing_or_empty_record_field_named_with_its_record(self):
        """Три варіанти сценарію «Бракує обов'язкового поля запису або воно порожнє»."""
        with self.subTest("із запису /fapi/v1/premiumIndex прибрано model"):
            message = self.rejects(self.variant((PREMIUM_MODEL, "")))
            self.assertNames(message, "model")
            self.assertRecord(message, 1, PREMIUM)
        with self.subTest('client_method = "" у записі /fapi/v1/premiumIndex'):
            message = self.rejects(self.variant((PREMIUM_CLIENT, 'client_method = ""\n')))
            self.assertNames(message, "client_method")
            self.assertRecord(message, 1, PREMIUM)
        with self.subTest("із другого запису прибрано path"):
            message = self.rejects(self.variant((FUNDING_PATH, "")))
            self.assertNames(message, "path")
            self.assertRegex(message, r"#2(?!\d)")

    def test_other_combinations_from_the_requirement(self):
        with self.subTest('path = "" у записі #1'):
            message = self.rejects(self.variant((PREMIUM_PATH, 'path = ""\n')))
            self.assertNames(message, "path")
            self.assertRegex(message, r"#1(?!\d)")
        with self.subTest("із запису #1 прибрано client_method"):
            message = self.rejects(self.variant((PREMIUM_CLIENT, "")))
            self.assertNames(message, "client_method")
            self.assertRecord(message, 1, PREMIUM)
        with self.subTest('model = "" у записі #2'):
            message = self.rejects(self.variant((FUNDING_MODEL, 'model = ""\n')))
            self.assertNames(message, "model")
            self.assertRecord(message, 2, FUNDING)


class ShortForm(RegistryCase):
    """Вимога «Коротка форма запису методу» (FR-10): синтаксично приймається, але без `model` і `client_method`
    працювати нема з чим."""

    def test_short_form_stops_with_an_explanation(self):
        message = self.rejects(self.without_records(top('method = ["/fapi/v1/premiumIndex"]')))
        self.assertIn(PREMIUM, message)
        self.assertNames(message, "model", "client_method")
        self.assertIn("працювати нема з чим", message)


class StopsBeforeFirstMethod(RegistryCase):
    """Вимога «Непридатний реєстр зупиняє прогін до першого методу»: вада будь-якого запису відхиляє весь
    реєстр, тож прогін не отримує жодного методу; `load()` не чіпає робочої копії `lib`. Код `2`, stdout і
    незмінні `runs/` на процесі CLI — `add-run-cli`."""

    def test_defect_in_second_record_rejects_the_first_too(self):
        lib = git_init(self.tmp / "lib")
        (lib / "untracked.txt").write_text("некомічена правка людини\n", encoding="utf-8")
        before = git_status(lib)
        message = self.rejects(self.variant((FUNDING_CLIENT, ""), (self.lib_line, f"lib = {toml_string(lib)}\n")))
        self.assertNames(message, "client_method")
        self.assertRecord(message, 2, FUNDING)
        self.assertNotRecord(message, 1, PREMIUM)
        self.assertEqual(git_status(lib), before)


if __name__ == "__main__":
    unittest.main()
