# @trace FR-31, FR-32, FR-33, FR-34, FR-35, FR-36, FR-37, FR-41, FR-42, FR-43, FR-44, FR-46, FR-52, NFR-2, NFR-5, NFR-11, NFR-13
"""Тести команди перевірки (capability `field-verification`, зміна `add-core`): unittest зі stdlib.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Як у v1, тут не запускається ні JVM, ні справжня бібліотека: перевіряється те, що ламається мовчки, — текст
згенерованого раннера, розбір його виводу і стадії, які перевірка проходить до раннера (`verify_cmd`, каталог
раннера, класпас) на справжніх процесах ОС. Щоб стадія `classpath` падала швидко і без Maven, `PATH` звужено до
`/usr/bin:/bin`: там є `pwd`, `true`, `false`, `sleep`, але немає `mvn` (сценарій «Програму кроку не вдалося
запустити»). Раннер проти справжньої бібліотеки і живої біржі — `tests/runner_integration_test.py`
(`METHOD_SYNC_LIVE=1`).

Відмінності від v1 (design.md, таблиця): виняток клієнта перехоплюється і йде в `client_error`; вердикт має `enums`;
збій стадії — вердикт `{green, stage, reason[, limit_s]}`, а не виняток (`parse_result` більше не кидає
`VerifyError`); кожна стадія має свій ліміт часу.
"""
import contextlib
import inspect
import io
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

from method_sync import verify  # noqa: E402
from method_sync.registry import Method  # noqa: E402

PKG = "com.example.binanceFutures.response"
MARK_MODEL = f"{PKG}.FuturesMarkPriceInfo"
PREMIUM = "/fapi/v1/premiumIndex"
PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
VERDICT_KEYS = {"green", "model", "live", "extra", "missing", "owners", "client_error", "enums"}
STAGE_KEYS = {"green", "stage", "reason"}
CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
TRACEBACK = "Traceback (most recent call last)"
NO_MAVEN_PATH = "/usr/bin:/bin"  # pwd, true, false, sleep — є; mvn — немає
CATCH_THROWABLE = re.compile(r"catch\s*\(\s*(?:final\s+)?Throwable\b")

VERDICT = {"green": True, "model": ["symbol", "time"], "live": ["symbol", "time"], "extra": [], "missing": [],
           "owners": {"symbol": MARK_MODEL, "time": MARK_MODEL}, "client_error": None, "enums": []}


def runner(**overrides):
    fields = dict(model=MARK_MODEL, client_method="getMarkPrice", args={"symbol": "BTCUSDT"}, url=PREMIUM_URL)
    fields.update(overrides)
    return verify.render_runner(**fields)


def premium_method():
    return Method(path=PREMIUM, model=MARK_MODEL, client_method="getMarkPrice", args={"symbol": "BTCUSDT"})


def files_under(root):
    return sorted(str(path.relative_to(root)) for path in pathlib.Path(root).rglob("*"))


class StageAssertions(unittest.TestCase):
    def assertStage(self, verdict, stage, limit=None):
        """Вердикт стадії (FR-43): рівно `green`, `stage`, непорожній `reason` і `limit_s` лише на ліміті."""
        expected = STAGE_KEYS | ({"limit_s"} if limit is not None else set())
        self.assertEqual(set(verdict), expected, verdict)
        self.assertIs(verdict["green"], False)
        self.assertEqual(verdict["stage"], stage, verdict)
        self.assertIsInstance(verdict["reason"], str)
        self.assertTrue(verdict["reason"].strip(), verdict)
        if limit is not None:
            self.assertEqual(verdict["limit_s"], limit)


class VerifyRunCase(StageAssertions):
    """Справжній `verify.run` на тимчасовому каталозі замість бібліотеки: стадії до раннера без Java."""

    def setUp(self):
        self.lib = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-lib-"))
        self.addCleanup(shutil.rmtree, self.lib, ignore_errors=True)

    def narrow_path(self, value=NO_MAVEN_PATH):
        old = os.environ.get("PATH")
        os.environ["PATH"] = value
        self.addCleanup(os.environ.__setitem__, "PATH", old)

    def run_verify(self, verify_cmd, **limits):
        out, err = io.StringIO(), io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            verdict, output = verify.run(self.lib, premium_method(), PREMIUM_URL, verify_cmd, **limits)
        self.elapsed = time.monotonic() - started
        self.assertNotIn(TRACEBACK, out.getvalue() + err.getvalue())
        return verdict, output


# ----------------------------------------------------------------------------------------------------------
# Текст раннера
# ----------------------------------------------------------------------------------------------------------

class RunnerExitsTheJvmOnEveryPath(unittest.TestCase):
    """FR-42: клієнт тримає не-демонські потоки, тож кожен вихід — `System.exit`; Throwable перехоплюється
    і навколо виклику клієнта (FR-46), і поза ним (FR-43)."""

    def test_green_and_red_paths_exit(self):
        source = runner()
        self.assertIn("System.exit(0)", source)
        self.assertIn("System.exit(1)", source)

    def test_throwable_is_caught_around_the_client_and_outside_it(self):
        self.assertGreaterEqual(len(CATCH_THROWABLE.findall(runner())), 2, "потрібні обидва перехоплення Throwable")


class RunnerCallsTheLibraryClient(unittest.TestCase):
    """FR-34: виклик через фабрику бібліотеки без ключів; аргументи — `call` дослівно або `args` як у v1."""

    def test_calls_through_the_factory(self):
        source = runner()
        self.assertIn("BinanceFuturesApiClientFactory", source)
        self.assertIn("newFuturesRestClient()", source)
        self.assertIn('.getMarkPrice("BTCUSDT")', source)

    def test_args_become_java_literals_like_v1(self):
        source = runner(client_method="getX", args={"note": 'a"b', "limit": 3, "reduceOnly": True, "ratio": 1e-7})
        self.assertIn('.getX("a\\"b", 3, true, 1e-07)', source)

    def test_call_wins_over_args(self):
        source = runner(client_method="getFundingRates", args={"symbol": "ETHUSDT", "limit": 7},
                        call='"BTCUSDT", 3, null, null')
        self.assertIn('.getFundingRates("BTCUSDT", 3, null, null)', source)
        self.assertNotIn("ETHUSDT", source)

    def test_empty_call_means_no_arguments(self):
        self.assertIn(".getTradingSchedule()", runner(client_method="getTradingSchedule",
                                                     args={"symbol": "BTCUSDT"}, call=""))

    def test_call_arguments_are_rendered_once(self):
        self.assertEqual(verify.call_arguments({"symbol": "BTCUSDT", "limit": 3}), '"BTCUSDT", 3')
        self.assertEqual(verify.call_arguments({"symbol": "BTCUSDT"}, call='"BTCUSDT", 3, null, null'),
                         '"BTCUSDT", 3, null, null')
        self.assertEqual(verify.call_arguments({"symbol": "BTCUSDT"}, call=""), "")
        self.assertEqual(verify.call_arguments({}), "")


class RunnerReadsRawJsonFromTheFixtureUrl(unittest.TestCase):
    """FR-35: сирий JSON — рівно за рядком URL фікстури, без файлу фікстури і без перенаправлень."""

    def test_url_is_embedded_verbatim(self):
        self.assertIn(f'"{PREMIUM_URL}"', runner())

    def test_fixture_file_is_not_a_source(self):
        self.assertNotIn("fixture.json", runner())

    def test_redirects_are_not_followed(self):
        source = runner()
        self.assertNotIn("Redirect.ALWAYS", source)
        self.assertNotIn("Redirect.NORMAL", source)


class RunnerIntrospectsJacksonProperties(unittest.TestCase):
    """FR-36, FR-37: множина полів — Jackson-інтроспекція, власник кожного поля, виключення полів-конверта."""

    def test_uses_introspection_not_field_reflection(self):
        source = runner()
        self.assertIn("introspect", source)
        self.assertIn("findProperties", source)
        self.assertNotIn("getDeclaredFields", source)

    def test_names_the_declaring_class(self):
        self.assertIn("getDeclaringClass", runner())

    def test_envelope_fields_are_excluded_only_for_the_envelope_class(self):
        self.assertEqual(verify.ENVELOPE_CLASS, "com.example.delays.Response")
        self.assertEqual(tuple(verify.ENVELOPE_FIELDS), ("requestSent", "responseRecv"))
        source = runner()
        for name in (verify.ENVELOPE_CLASS, *verify.ENVELOPE_FIELDS):
            with self.subTest(name=name):
                self.assertIn(name, source)

    def test_imports_the_model_from_the_registry(self):
        self.assertIn(MARK_MODEL, runner())


class RunnerPrintsEveryVerdictKey(unittest.TestCase):
    """FR-41, FR-46, FR-52: вердикт має `client_error` і `enums` поряд із ключами v1."""

    def test_every_key_is_in_the_source(self):
        source = runner()
        for key in sorted(VERDICT_KEYS):
            with self.subTest(key=key):
                self.assertIn(f'"{key}"', source)


# ----------------------------------------------------------------------------------------------------------
# Розбір виводу раннера
# ----------------------------------------------------------------------------------------------------------

class ParsesRunnerOutput(StageAssertions):
    """FR-41, FR-43: останній непорожній рядок — вердикт; інакше — вердикт стадії `runner`, а не виняток."""

    def test_verdict_after_human_log_and_blank_lines(self):
        stdout = ("клієнт бібліотеки повернув: FuturesMarkPriceInfo{...}\n"
                  "модель = [symbol, time]\n" + json.dumps(VERDICT) + "\n\n  \n")
        self.assertEqual(verify.parse_result(stdout), VERDICT)

    def test_client_error_verdict_is_read_as_is(self):
        red = dict(VERDICT, green=False, client_error="com.binance.api.client.exception.BinanceApiException: x")
        self.assertEqual(verify.parse_result(json.dumps(red)), red)

    def test_empty_stdout_is_runner_stage(self):
        for stdout in ("", "\n \n", None):
            with self.subTest(stdout=stdout):
                self.assertStage(verify.parse_result(stdout), "runner")

    def test_unusable_last_line_is_quoted_verbatim(self):
        no_enums = {key: value for key, value in VERDICT.items() if key != "enums"}
        for last in ('java.lang.IllegalArgumentException: Conflicting setter definitions for property "x"',
                     '["green", true]',
                     '{"model": [], "live": []}',
                     json.dumps(no_enums)):
            with self.subTest(last=last):
                verdict = verify.parse_result("людський лог\n" + last + "\n")
                self.assertStage(verdict, "runner")
                self.assertIn(last, verdict["reason"])


# ----------------------------------------------------------------------------------------------------------
# Стадії до раннера на справжніх процесах
# ----------------------------------------------------------------------------------------------------------

class VerifyCommandRunsInLibWithoutShell(VerifyRunCase):
    """FR-31: `shlex.split`, одна програма без шелу, робочий каталог — `lib`."""

    def test_runs_in_lib(self):
        self.narrow_path()
        verdict, output = self.run_verify("pwd")
        printed = [line.strip() for line in output.splitlines() if line.strip().startswith("/")]
        self.assertIn(os.path.realpath(self.lib), [os.path.realpath(line) for line in printed], output)
        # Далі — класпас, а `mvn` у PATH немає (FR-43: програма кроку не запустилася).
        self.assertStage(verdict, "classpath")
        self.assertIn("mvn", verdict["reason"])
        self.assertIn("No such file or directory", verdict["reason"])

    def test_shell_operators_are_plain_arguments(self):
        self.narrow_path()
        verdict, _ = self.run_verify("true && false")
        self.assertStage(verdict, "classpath")  # `true` з аргументами `&&` і `false` — код 0, compile пройдено


class FailedVerifyCommandIsCompileStage(VerifyRunCase):
    """FR-31, FR-43, NFR-11, NFR-13: червоний вердикт `compile` з командою і причиною; класпас не знімається."""

    def test_nonzero_exit(self):
        verdict, output = self.run_verify("false")
        self.assertStage(verdict, "compile")
        self.assertIn("false", verdict["reason"])
        self.assertRegex(verdict["reason"], r"\b1\b")
        self.assertRegex(verdict["reason"], CYRILLIC)
        self.assertNotIn("build-classpath", output)

    def test_unparsable_command(self):
        verdict, _ = self.run_verify("mvn -q 'unterminated")
        self.assertStage(verdict, "compile")
        self.assertIn("mvn -q 'unterminated", verdict["reason"])
        self.assertIn("No closing quotation", verdict["reason"])

    def test_missing_program(self):
        verdict, output = self.run_verify("mvnx -q compile")
        self.assertStage(verdict, "compile")
        self.assertIn("mvnx -q compile", verdict["reason"])
        self.assertIn("No such file or directory", verdict["reason"])
        self.assertNotIn("build-classpath", output)


class RunnerDirectoryOutsideLib(VerifyRunCase):
    """FR-32, FR-44: корінь тимчасових каталогів у `lib` — стадія `workdir` до створення будь-чого під `lib`.

    `TMPDIR` задано нерозкритим шляхом (`/var/...`, а реальний — `/private/var/...`), тож порівняння без розкриття
    символьних посилань цей випадок пропускає."""

    def test_tmpdir_inside_lib(self):
        inner = self.lib / "tmp"
        inner.mkdir()
        before = files_under(self.lib)
        old_env, old_cached = os.environ.get("TMPDIR"), tempfile.tempdir
        os.environ["TMPDIR"], tempfile.tempdir = str(inner), None
        try:
            verdict, _ = self.run_verify("true")
        finally:
            tempfile.tempdir = old_cached
            if old_env is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = old_env
        self.assertStage(verdict, "workdir")
        self.assertIn(os.path.realpath(inner), verdict["reason"])
        self.assertIn(os.path.realpath(self.lib), verdict["reason"])
        self.assertEqual(files_under(self.lib), before)


class EveryStepHasATimeLimit(VerifyRunCase):
    """NFR-2, NFR-5: ліміти кроків із типовими значеннями; на ліміті — стадія кроку з `limit_s`."""

    def test_default_limits(self):
        parameters = inspect.signature(verify.run).parameters
        expected = {"verify_timeout": 600, "classpath_timeout": 300, "javac_timeout": 300, "runner_timeout": 120}
        self.assertEqual({name: parameters[name].default for name in expected}, expected)

    def test_verify_cmd_over_the_limit(self):
        verdict, _ = self.run_verify("sleep 30", verify_timeout=0.5)
        self.assertStage(verdict, "compile", limit=0.5)
        self.assertIn("0.5 с", verdict["reason"])
        self.assertLess(self.elapsed, 2.0)

    @unittest.skipUnless(shutil.which("mvn"), "немає mvn у PATH")
    def test_classpath_over_the_limit(self):
        verdict, output = self.run_verify("true", classpath_timeout=0.01)
        self.assertStage(verdict, "classpath", limit=0.01)
        self.assertIn("0.01 с", verdict["reason"])
        self.assertNotIn("javac", output)


if __name__ == "__main__":
    unittest.main()
