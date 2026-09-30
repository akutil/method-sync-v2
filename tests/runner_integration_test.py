# @trace FR-31, FR-33, FR-34, FR-35, FR-36, FR-38, FR-39, FR-41, FR-42, FR-44, FR-46, FR-47, FR-48, FR-49, FR-50, FR-51, FR-52, FR-53, NFR-2
"""Раннер перевірки проти справжньої бібліотеки і живої біржі (capability `field-verification`,
`enum-verification`, зміна `add-core`): інтеграційний шар, unittest зі stdlib.

Запуск: METHOD_SYNC_LIVE=1 python3 -m unittest discover -s tests -p '*_test.py'   (npm run test:integration)

Без METHOD_SYNC_LIVE=1 кожен клас видимо пропускається з причиною: юніт-набір і CI не мусять залежати від Java,
Maven і стану біржі. З нею відсутня зібрана копія чи недосяжна біржа — провал із поясненням, а не пропуск.

Бібліотека — лише одноразова копія `.sandbox/binancefutures` (TC-7), ніколи робоча копія людини:
- `RunnerOnTheClone` — сама копія (лише читання: `verify.run` не пише в `lib`, FR-44). Живі ключі — з біржі; де
  сценарій задає сирий JSON, його віддає локальний `LocalServer` з `live_test.py` за URL методу, а клієнт
  бібліотеки й далі ходить на справжню біржу.
- `RunnerOnAModifiedCopy` — тимчасова копія клону: з `FuturesMarkPriceInfo` прибрано властивість `time` (сценарій
  «Клієнт працює зі строгою конфігурацією бібліотеки») і додано тестові моделі пакета `methodsync.fixture` для
  сценаріїв енамів, порядку за кодовими точками і `@JsonProperty`/`@JsonIgnore`. Копія збирається
  `mvn -q -DskipTests test-compile` один раз; тести тестових моделей далі беруть `verify_cmd = "true"`.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from live_test import LocalServer, Reply  # noqa: E402
from method_sync import live, verify  # noqa: E402
from method_sync.registry import Method  # noqa: E402

LIVE = os.environ.get("METHOD_SYNC_LIVE") == "1"
SKIP = ("інтеграційний шар раннера: потрібні METHOD_SYNC_LIVE=1, Java, Maven, жива біржа і зібрана копія "
        ".sandbox/binancefutures (npm run test:integration)")
CLONE = REPO / ".sandbox" / "binancefutures"
EXCHANGE = "https://fapi.binance.com"
VERIFY_CMD = "mvn -q -DskipTests test-compile"
PKG = "com.example.binanceFutures.response"
MARK_MODEL = f"{PKG}.FuturesMarkPriceInfo"
FUNDING_MODEL = f"{PKG}.FuturesFundingRateInfo"
SCHEDULE_MODEL = f"{PKG}.TradingScheduleResponse"
TRADES_MODEL = f"{PKG}.FuturesTradeHistoryItem"
MARKET_ENUM = f"{PKG}.MarketType"
ORDER_ENUM = "com.example.binanceFutures.request.FuturesOrderType"
MARK_FIELDS = ["estimatedSettlePrice", "indexPrice", "interestRate", "lastFundingRate", "markPrice",
               "nextFundingTime", "symbol", "time"]
MARKET_DECLARED = ["CN_EQUITY", "COMMODITY", "EQUITY", "HK_EQUITY", "KR_EQUITY"]
ORDER_DECLARED = sorted(["LIMIT", "MARKET", "STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET",
                         "TRAILING_STOP_MARKET", "LIQUIDATION"])
VERDICT_KEYS = {"green", "model", "live", "extra", "missing", "owners", "client_error", "enums"}
MARK_JAVA = "src/main/java/com/example/binanceFutures/response/FuturesMarkPriceInfo.java"
WITHOUT_TIME = (  # сценарій FR-44: властивість `time` прибрано повністю — поле, гетер, сетер і рядок у toString
    "    private Long time;\n\n",
    "    public Long getTime() {\n        return time;\n    }\n\n",
    "    public void setTime(Long time) {\n        this.time = time;\n    }\n\n",
    '                ", time=" + time +\n',
)
STRICT_CLIENT_ERROR = ('com.binance.api.client.exception.BinanceApiException: '
                       'com.fasterxml.jackson.databind.exc.UnrecognizedPropertyException: Unrecognized field "time"')

FIXTURE_PACKAGE = "methodsync.fixture"
TEST_MODELS = {
    "EnumModel": f"""package {FIXTURE_PACKAGE};

import {ORDER_ENUM};
import {MARKET_ENUM};
import java.util.List;
import java.util.Map;
import java.util.Set;

public class EnumModel {{
    private FuturesOrderType type;
    private List<FuturesOrderType> orderTypes;
    private Set<FuturesOrderType> orderTypeSet;
    private FuturesOrderType[] orderTypeArray;
    private Map<MarketType, String> markets;

    public FuturesOrderType getType() {{ return type; }}
    public void setType(FuturesOrderType type) {{ this.type = type; }}
    public List<FuturesOrderType> getOrderTypes() {{ return orderTypes; }}
    public void setOrderTypes(List<FuturesOrderType> orderTypes) {{ this.orderTypes = orderTypes; }}
    public Set<FuturesOrderType> getOrderTypeSet() {{ return orderTypeSet; }}
    public void setOrderTypeSet(Set<FuturesOrderType> orderTypeSet) {{ this.orderTypeSet = orderTypeSet; }}
    public FuturesOrderType[] getOrderTypeArray() {{ return orderTypeArray; }}
    public void setOrderTypeArray(FuturesOrderType[] orderTypeArray) {{ this.orderTypeArray = orderTypeArray; }}
    public Map<MarketType, String> getMarkets() {{ return markets; }}
    public void setMarkets(Map<MarketType, String> markets) {{ this.markets = markets; }}
}}
""",
    "PlainModel": f"""package {FIXTURE_PACKAGE};

import {MARKET_ENUM};
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

public class PlainModel {{
    private String rateType;
    private Map<String, MarketType> byValue;
    @JsonProperty("bar")
    private String foo;
    @JsonIgnore
    private String hidden;

    public String getRateType() {{ return rateType; }}
    public void setRateType(String rateType) {{ this.rateType = rateType; }}
    public Map<String, MarketType> getByValue() {{ return byValue; }}
    public void setByValue(Map<String, MarketType> byValue) {{ this.byValue = byValue; }}
    public MarketType getMarket() {{ return null; }}
    public String getFoo() {{ return foo; }}
    public void setFoo(String foo) {{ this.foo = foo; }}
    public String getHidden() {{ return hidden; }}
    public void setHidden(String hidden) {{ this.hidden = hidden; }}
}}
""",
    "OrderModel": f"""package {FIXTURE_PACKAGE};

import {ORDER_ENUM};
import com.fasterxml.jackson.annotation.JsonProperty;

public class OrderModel {{
    @JsonProperty("z")
    private FuturesOrderType z;
    @JsonProperty("A")
    private FuturesOrderType a;

    public FuturesOrderType getZ() {{ return z; }}
    public void setZ(FuturesOrderType z) {{ this.z = z; }}
    public FuturesOrderType getA() {{ return a; }}
    public void setA(FuturesOrderType a) {{ this.a = a; }}
}}
""",
}


def git_status(lib):
    return subprocess.run(["git", "-C", str(lib), "status", "--porcelain"], capture_output=True, text=True,
                          check=True).stdout


def require_built(lib):
    if not (lib / "target" / "classes").is_dir():
        raise AssertionError(f"немає зібраної копії бібліотеки: {lib}/target/classes — зберіть її "
                             f"`{VERIFY_CMD}` у {lib} (TC-7)")


class RunnerCase(unittest.TestCase):
    lib = CLONE

    def check(self, path, model, client_method, args=None, call=None, url=None, verify_cmd=VERIFY_CMD, **limits):
        method = Method(path=path, model=model, client_method=client_method, args=args or {}, call=call)
        verdict, output = verify.run(self.lib, method, url or live.build_url(EXCHANGE, path, method.args),
                                     verify_cmd, **limits)
        return verdict, output

    def serve(self, reply):
        server = LocalServer({}, default=reply)
        self.addCleanup(server.close)
        return server

    def assertCompared(self, verdict, output):
        self.assertEqual(set(verdict), VERDICT_KEYS, f"звіряння не відбулося: {verdict}\n{output[-4000:]}")

    def entry(self, verdict, field):
        found = [item for item in verdict["enums"] if item["field"] == field]
        self.assertEqual(len(found), 1, verdict["enums"])
        return found[0]


@unittest.skipUnless(LIVE, SKIP)
class RunnerOnTheClone(RunnerCase):
    @classmethod
    def setUpClass(cls):
        require_built(CLONE)

    def test_premium_index_is_green_and_the_clone_is_untouched(self):
        """FR-39, FR-42, FR-44: 8 властивостей, власник — сама модель, вердикт зелений, робоча копія та сама."""
        before = git_status(self.lib)
        verdict, output = self.check("/fapi/v1/premiumIndex", MARK_MODEL, "getMarkPrice", {"symbol": "BTCUSDT"})
        self.assertCompared(verdict, output)
        self.assertEqual(verdict["model"], MARK_FIELDS)
        self.assertEqual(verdict["owners"], {name: MARK_MODEL for name in MARK_FIELDS})
        self.assertEqual((verdict["extra"], verdict["missing"], verdict["enums"]), ([], [], []))
        self.assertIsNone(verdict["client_error"])
        self.assertIs(verdict["green"], True)
        self.assertEqual(git_status(self.lib), before)

    def test_funding_rate_misses_mark_price_and_rate_type(self):
        """FR-35, FR-38, FR-39: клієнт мовчки пропускає ключі (`ignoreUnknown`), сирий JSON їх показує."""
        verdict, output = self.check("/fapi/v1/fundingRate", FUNDING_MODEL, "getFundingRates",
                                     {"symbol": "BTCUSDT", "limit": 3}, call='"BTCUSDT", 3, null, null')
        self.assertCompared(verdict, output)
        self.assertIsNone(verdict["client_error"])
        self.assertEqual((verdict["missing"], verdict["extra"]), (["markPrice", "rateType"], []))
        self.assertIs(verdict["green"], False)

    def test_trading_schedule_misses_fx(self):
        """FR-47, FR-50, FR-51, FR-52: мапа з енамними ключами; запасник поза оголошеними; FX — розходження."""
        verdict, output = self.check("/fapi/v1/tradingSchedule", SCHEDULE_MODEL, "getTradingSchedule")
        self.assertCompared(verdict, output)
        self.assertEqual((verdict["extra"], verdict["missing"]), ([], []))
        self.assertEqual(len(verdict["enums"]), 1, verdict["enums"])
        entry = self.entry(verdict, "marketSchedules")
        self.assertEqual(set(entry), {"field", "enum", "declared", "live", "missing", "unseen"})
        self.assertEqual(entry["enum"], MARKET_ENUM)
        self.assertEqual(entry["declared"], MARKET_DECLARED)
        self.assertIn("FX", entry["live"], "біржа більше не віддає FX у marketSchedules — сценарій треба оновити")
        self.assertEqual(entry["missing"], sorted(set(entry["live"]) - set(MARKET_DECLARED)))
        self.assertEqual(entry["unseen"], sorted(set(MARKET_DECLARED) - set(entry["live"])))
        self.assertIs(verdict["green"], False)

    def test_client_error_does_not_stop_the_comparison(self):
        """FR-46: клієнт кидає виняток на 400, а звіряння йде із сирого JSON; вердикт червоний."""
        verdict, output = self.check("/fapi/v1/premiumIndex", MARK_MODEL, "getMarkPrice", {"symbol": "BTCUSDT"},
                                     call='"NOSUCHSYMBOL"')
        self.assertCompared(verdict, output)
        self.assertEqual((verdict["extra"], verdict["missing"]), ([], []))
        self.assertEqual(verdict["client_error"], "com.binance.api.client.exception.BinanceApiException: Invalid symbol.")
        self.assertIn(verdict["client_error"], output)
        self.assertIs(verdict["green"], False)

    def test_getter_only_properties_are_not_fields(self):
        """FR-36: `buyerMaker` і `rpitrade` лише з гетером полями моделі не є."""
        verdict, output = self.check("/fapi/v1/trades", TRADES_MODEL, "getTrades", {"symbol": "BTCUSDT"})
        self.assertCompared(verdict, output)
        self.assertEqual(verdict["model"], ["id", "isBuyerMaker", "isRPITrade", "price", "qty", "quoteQty", "time"])
        for name in ("buyerMaker", "rpitrade"):
            self.assertNotIn(name, verdict["extra"])

    def test_live_sentinel_name_counts_as_declared(self):
        """FR-51: живе `UNKNOWN` — ім'я запасника — оголошене; CRYPTO і FX — розходження."""
        server = self.serve(Reply(body=b'{"updateTime":1790150400000,"marketSchedules":'
                                       b'{"CRYPTO":{},"EQUITY":{},"FX":{},"UNKNOWN":{}}}'))
        verdict, output = self.check("/fapi/v1/tradingSchedule", SCHEDULE_MODEL, "getTradingSchedule",
                                     url=f"{server.url}/fapi/v1/tradingSchedule", verify_cmd="true")
        self.assertCompared(verdict, output)
        entry = self.entry(verdict, "marketSchedules")
        self.assertEqual(entry["live"], ["CRYPTO", "EQUITY", "FX", "UNKNOWN"])
        self.assertEqual(entry["missing"], ["CRYPTO", "FX"])
        self.assertIs(verdict["green"], False)

    def test_unseen_constants_do_not_redden(self):
        """FR-53: оголошені константи, яких не було в живій відповіді, лише названо в `unseen`."""
        server = self.serve(Reply(body=b'{"updateTime":1790150400000,"marketSchedules":{"EQUITY":{}}}'))
        verdict, output = self.check("/fapi/v1/tradingSchedule", SCHEDULE_MODEL, "getTradingSchedule",
                                     url=f"{server.url}/fapi/v1/tradingSchedule", verify_cmd="true")
        self.assertCompared(verdict, output)
        entry = self.entry(verdict, "marketSchedules")
        self.assertEqual(entry["missing"], [])
        self.assertEqual(entry["unseen"], ["CN_EQUITY", "COMMODITY", "HK_EQUITY", "KR_EQUITY"])
        self.assertIsNone(verdict["client_error"])
        self.assertIs(verdict["green"], True)

    def test_runner_over_the_time_limit(self):
        """NFR-2: сервер приймає запит раннера і мовчить — стадія `timeout` з `limit_s`."""
        server = self.serve(Reply(silent=True))
        verdict, _ = self.check("/fapi/v1/premiumIndex", MARK_MODEL, "getMarkPrice", {"symbol": "BTCUSDT"},
                                url=f"{server.url}/fapi/v1/premiumIndex?symbol=BTCUSDT", verify_cmd="true",
                                runner_timeout=5)
        self.assertEqual(set(verdict), {"green", "stage", "reason", "limit_s"}, verdict)
        self.assertEqual((verdict["stage"], verdict["limit_s"]), ("timeout", 5))
        self.assertIn("5 с", verdict["reason"])


@unittest.skipUnless(LIVE, SKIP)
class RunnerOnAModifiedCopy(RunnerCase):
    @classmethod
    def setUpClass(cls):
        require_built(CLONE)
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="method-sync-copy-"))
        cls.lib = cls.tmp / "binancefutures"
        shutil.copytree(CLONE, cls.lib, ignore=shutil.ignore_patterns(".git"), symlinks=True)
        mark = cls.lib / MARK_JAVA
        text = mark.read_text(encoding="utf-8")
        for fragment in WITHOUT_TIME:
            if fragment not in text:
                shutil.rmtree(cls.tmp, ignore_errors=True)
                raise AssertionError(f"у {MARK_JAVA} копії немає очікуваного фрагмента {fragment!r}")
            text = text.replace(fragment, "", 1)
        mark.write_text(text, encoding="utf-8")
        package = cls.lib / "src/main/java" / FIXTURE_PACKAGE.replace(".", "/")
        package.mkdir(parents=True)
        for name, source in TEST_MODELS.items():
            (package / f"{name}.java").write_text(source, encoding="utf-8")
        built = subprocess.run(VERIFY_CMD.split(), cwd=cls.lib, capture_output=True, text=True, timeout=600)
        if built.returncode != 0:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise AssertionError(f"копія не зібралась ({built.returncode}):\n{built.stdout}\n{built.stderr}")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fixture_model(self, name, body, verify_cmd="true"):
        server = self.serve(Reply(body=body))
        return self.check("/fapi/v1/tradingSchedule", f"{FIXTURE_PACKAGE}.{name}", "getTradingSchedule",
                          url=f"{server.url}/fapi/v1/tradingSchedule", verify_cmd=verify_cmd)

    def test_strict_model_without_time(self):
        """FR-44, FR-46: клієнт працює зі строгою конфігурацією бібліотеки — `client_error`, а `missing` — time."""
        verdict, output = self.check("/fapi/v1/premiumIndex", MARK_MODEL, "getMarkPrice", {"symbol": "BTCUSDT"})
        self.assertCompared(verdict, output)
        self.assertEqual(verdict["missing"], ["time"])
        self.assertTrue(str(verdict["client_error"]).startswith(STRICT_CLIENT_ERROR), verdict["client_error"])
        self.assertIs(verdict["green"], False)

    def test_enum_value_collections_and_map_keys(self):
        """FR-47, FR-48: енам, List, Set, масив і мапа з енамними ключами; значення, елементи, ключі."""
        verdict, output = self.fixture_model("EnumModel", b'{"type":"LIMIT","orderTypes":["MARKET","LIMIT","MARKET"],'
                                                          b'"orderTypeSet":[],"orderTypeArray":[],'
                                                          b'"markets":{"FX":"a","EQUITY":"b"}}')
        self.assertCompared(verdict, output)
        self.assertEqual([item["field"] for item in verdict["enums"]],
                         ["markets", "orderTypeArray", "orderTypeSet", "orderTypes", "type"])
        self.assertEqual({item["field"]: item["enum"] for item in verdict["enums"]},
                         {"markets": MARKET_ENUM, "orderTypeArray": ORDER_ENUM, "orderTypeSet": ORDER_ENUM,
                          "orderTypes": ORDER_ENUM, "type": ORDER_ENUM})
        self.assertEqual(self.entry(verdict, "type")["live"], ["LIMIT"])
        self.assertEqual(self.entry(verdict, "type")["declared"], ORDER_DECLARED)
        self.assertEqual(self.entry(verdict, "orderTypes")["live"], ["LIMIT", "MARKET"])
        markets = self.entry(verdict, "markets")
        self.assertEqual((markets["live"], markets["missing"]), (["EQUITY", "FX"], ["FX"]))
        self.assertIs(verdict["green"], False)

    def test_null_absent_and_wrong_typed_values(self):
        """FR-48: `null`, відсутній ключ і значення не того типу живих значень не дають і перевірку не зупиняють."""
        verdict, output = self.fixture_model("EnumModel",
                                             b'{"type":null,"orderTypes":[null,1,{"x":"MARKET"},"LIMIT"]}')
        self.assertCompared(verdict, output)
        self.assertEqual(self.entry(verdict, "type")["live"], [])
        self.assertEqual(self.entry(verdict, "orderTypes")["live"], ["LIMIT"])
        self.assertEqual(self.entry(verdict, "markets")["live"], [])

    def test_union_over_array_bodies(self):
        """FR-49: неоголошене значення лише в останньому елементі масиву."""
        verdict, output = self.fixture_model("EnumModel", b'[{"type":"LIMIT"},{},{"type":"BOGUS_TYPE"}]')
        self.assertCompared(verdict, output)
        entry = self.entry(verdict, "type")
        self.assertEqual((entry["live"], entry["missing"]), (["BOGUS_TYPE", "LIMIT"], ["BOGUS_TYPE"]))
        self.assertIs(verdict["green"], False)

    def test_other_properties_are_not_enum_fields(self):
        """FR-47, FR-36: рядок, мапа з енамними значеннями і гетер без мутатора — не енамні поля;
        `@JsonProperty("bar")` дає ім'я, `@JsonIgnore` виключає."""
        verdict, output = self.fixture_model("PlainModel", b'{"rateType":"FX","byValue":{"a":"FX"},"market":"FX",'
                                                           b'"bar":"1"}')
        self.assertCompared(verdict, output)
        self.assertEqual(verdict["enums"], [])
        self.assertIn("bar", verdict["model"])
        for name in ("foo", "hidden", "market"):
            with self.subTest(name=name):
                self.assertNotIn(name, verdict["model"])

    def test_lists_and_enum_records_by_code_point(self):
        """FR-41: переліки і записи `enums` — за кодовими точками, а не за колацією локалі."""
        verdict, output = self.fixture_model("OrderModel",
                                             '{"b":1,"B":1,"a":1,"É":1,"Z":1}'.encode("utf-8"))
        self.assertCompared(verdict, output)
        self.assertEqual(verdict["live"], ["B", "Z", "a", "b", "É"])
        self.assertEqual(verdict["missing"], ["B", "Z", "a", "b", "É"])
        self.assertEqual((verdict["model"], verdict["extra"]), (["A", "z"], ["A", "z"]))
        self.assertEqual([item["field"] for item in verdict["enums"]], ["A", "z"])


if __name__ == "__main__":
    unittest.main()
