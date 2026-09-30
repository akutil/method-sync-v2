# Research — факти, на яких стоїть method-sync-v2

Кожен рядок нижче підтверджений пробою. R-001…R-008 перенесено з
`method-sync/specs/001-sync-named-method/research.md` (2026-09-23): код v1 не публічний, тож
висновки переписано сюди, щоб v2 був самодостатнім. R-009…R-012 зняті 2026-09-29 для v2.

## Перенесено з method-sync v1

| # | Факт | Чим доведено в v1 | Наслідок для v2 |
|---|---|---|---|
| R-001 | `FuturesMarkPriceInfo` (`/fapi/v1/premiumIndex`, 8 полів) і `FuturesFundingRateInfo` (`/fapi/v1/fundingRate`) оголошені повністю всередині бібліотеки; `FuturesTickerPrice`, `FuturesBookTicker`, `FuturesTickerStatistics` успадковують класи з артефакту `binance-api-client` | grep `extends` по `binanceFutures/response/` | демо-методи — лише ті, чиї поля живуть у цільовому репо |
| R-002 | Реєстр — TOML через stdlib `tomllib`; PyYAML у системі нема | `python3 -c "import yaml"` → `ModuleNotFoundError` | той самий формат реєстру |
| R-003 | Бібліотека тягне Jackson 2.10.1 (через `converter-jackson:2.9.0`); на ньому працюють `introspect(...).findProperties()` і `getPrimaryMember().getDeclaringClass()`; строга десеріалізація НЕ ловить зайве поле моделі | `mvn dependency:tree`, проба з `bogusExtraField` | звіряння множин — окремий крок, не властивість десеріалізації |
| R-004 | Перевірка живе ПОЗА бібліотекою: раннер генерується в тимчасовому каталозі, компілюється проти `target/classes` + класпасу з `mvn dependency:build-classpath` | наскрізна проба `VerifyProbe` без ключів | прогін без розходжень не лишає файлів у бібліотеці |
| R-005 | Раннер зобов'язаний викликати `System.exit`: клієнт бібліотеки тримає не-демонські потоки | проба висіла, `timeout 90` → `exit=124` | цикл не висить на зеленій ітерації |
| R-006 | Поля-конверт `requestSent`/`responseRecv` класу `com.example.delays.Response` біржа не віддає ніколи | читання класу | виключаються зі звіряння; на реальному нащадку не перевірено |
| R-007 | Агент — `claude -p` окремим процесом на ітерацію; `acceptEdits` не схвалює Bash, тому команда перевірки дозволяється явно через `--allowedTools`; фікстуру агент бачить лише через `--add-dir`; stdin — порожній | три живі прогони v1 | той самий виклик агента |
| R-008 | Python 3.14 + stdlib, тести `python3 -m unittest discover -s tests -p '*_test.py'` | `python3 --version` | той самий стек |

## Нове для v2 (2026-09-29)

### R-009. Енами бібліотеки «стійкі»: невідоме значення мовчки стає `UNKNOWN`

Коміт `644fbfd` (2026-07-23) у `binancefutures`: енами отримали константу `@JsonEnumDefaultValue UNKNOWN`,
а `Util` вмикає `READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`. Для ключів мапи є окремий
`MarketTypeKeyDeserializer` (фіча Jackson ключі мапи не покриває). Наслідок: нове значення біржі не
ламає десеріалізацію, а тихо губиться — строга десеріалізація його теж не побачить.

### R-010. Енами доповнюють руками, регулярно

`git log` бібліотеки: `MarketType.KR_EQUITY` (2026-05-28), `HK_EQUITY` (2026-07-16), `CN_EQUITY`
(2026-09-08), `SideEffectType.AUTO_BORROW_REPAY` (2026-04-17),
`PMUserDataUpdateEventType.POSITION_HISTORY_UPDATE` (2026-05-08). Кожен — окремий ручний коміт.

### R-011. Живий дрейф енама є прямо зараз

`GET https://fapi.binance.com/fapi/v1/tradingSchedule` → `marketSchedules` має ключі
`CN_EQUITY, COMMODITY, EQUITY, FX, HK_EQUITY, KR_EQUITY`; у `MarketType` константи
`EQUITY, COMMODITY, KR_EQUITY, HK_EQUITY, CN_EQUITY, UNKNOWN`. **`FX` бракує** — сьогодні розклад
FX-ринку десеріалізується під ключем `UNKNOWN`. Модель `TradingScheduleResponse` має верхній рівень
`updateTime`, `marketSchedules` — рівно як жива відповідь.

### R-012. Де ще енами у публічних відповідях `fapi`

`/fapi/v1/exchangeInfo` (919 символів): `orderTypes`, `timeInForce` — `List<FuturesOrderType>`,
`List<FuturesTimeInForce>` у вкладеному `symbols[]`; живі значення зараз у межах енамів
(`LIQUIDATION` і `RPI` є в енамах, але живо не трапились — приклад, чому невидиме не видаляють).
`status`, `contractType` у моделі — `String`, не енами. Це вкладений рівень — поза обсягом v2.

### R-013. Інтроспекція Jackson 2.10.1 бачить енамні поля в усіх трьох формах

Проба `EnumProbe` (2026-09-29) проти класів `.sandbox/binancefutures` (коміт `cee6585`),
`jackson-databind = 2.10.1`: для кожної властивості з `introspect(...).findProperties()`
береться `getPrimaryType()`; енамний тип знаходиться як `isEnumType()` (значення),
`getContentType().isEnumType()` (елементи списку) або `getKeyType().isEnumType()` (ключі мапи).
Запасник — константа, поле якої має `@JsonEnumDefaultValue` (рефлексія `getField(name)`).

```
TradingScheduleResponse.marketSchedules -> MarketType [keys] declared=[EQUITY, COMMODITY, KR_EQUITY, HK_EQUITY, CN_EQUITY] sentinel=UNKNOWN
FuturesSymbolInfo.orderTypes -> FuturesOrderType [items] declared=[LIMIT, MARKET, STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET, LIQUIDATION] sentinel=UNKNOWN
FuturesSymbolInfo.timeInForce -> FuturesTimeInForce [items] declared=[GTC, IOC, FOK, GTX, GTD, RPI] sentinel=UNKNOWN
FuturesMarkPriceInfo: enum-typed properties = 0
```

Межа перевіреного: проба порівнювала константи за `name()`. Але 8 енамів бібліотеки мають
`@JsonProperty`/`@JsonValue`/`@JsonCreator` (grep 2026-09-29; напр.
`binanceFutures/request/ModifyPositionType`), тож для них `name()` ≠ JSON-значення. Наслідок для
дизайну: живе значення перевіряти так, як його прочитає бібліотека, — десеріалізацією Jackson із
`READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`; результат-запасник означає «значення не оголошене».

### R-014. Виняток клієнта бібліотеки в `main` раннера вішає JVM

Проба `ThrowProbe` (2026-09-29): `getMarkPrice("NOSUCHSYMBOL")` через клієнт бібліотеки кидає
`BinanceApiException: Invalid symbol`, стек друкується, але процес не завершується — `timeout 45` →
`exit=124` через 46 с. Причина та сама, що в R-005: не-демонські потоки клієнта. Наслідок: у
раннері v1 будь-який виняток клієнта (зокрема `UnrecognizedPropertyException`, коли модель без
`ignoreUnknown` не має нового поля, а мапер бібліотеки має `FAIL_ON_UNKNOWN_PROPERTIES=true`)
перетворюється на 120 с очікування і стадію `timeout` без жодного слова про поле. Звіряння в v1 вже
не залежить від клієнта (окремий HTTP-запит + інтроспекція класу), бракує лише перехоплення винятку.

### R-015. Нову константу енама кладуть після останньої справжньої, перед запасником

`git log -p -- MarketType.java`: `KR_EQUITY` (2026-05-28) і `HK_EQUITY` (2026-07-16) дописані в кінець
переліку; після `644fbfd` (запасник `@JsonEnumDefaultValue UNKNOWN`) `CN_EQUITY` (2026-09-08) вставлено
після `HK_EQUITY`, перед порожнім рядком і запасником.

### R-016. Headless-агент інструмента живе в середовищі власника

Проба 2026-09-30: `claude -p "Reply with exactly the word PONG…" --permission-mode acceptEdits < /dev/null`
з процесу всередині сесії Claude Code (`CLAUDECODE=1`) → `exit=0` за 10 с; з `env -u CLAUDECODE` → `exit=0`
за 5 с. Обидві відповіді закінчуються семирядковим чек-листом із глобального `~/.claude/CLAUDE.md` власника:
глобальні інструкції (і Stop-хук) діють і на агента, якого кличе інструмент. У логах ітерацій v1 так само.
Наслідок: вивід агента в `iteration-N.log` містить цей чек-лист; на вердикт він не впливає (вердикт дає
раннер). Ще одна деталь середовища: Maven без `JAVA_HOME` працює на JDK 25, а `java`/`javac` з PATH — 21.0.2
(помітив `test-engineer` під час e2e-харнесу); збірка і раннер від цього не ламаються.

### R-017. `acceptEdits` дає агентові більше, ніж одну команду; `dontAsk` — ні

Проба 2026-09-30 у пісочниці (git-репо `lib`, `runs/fixture.json`, `--add-dir runs`, дозволено `Bash(echo verifyok)`),
агентові велено виконати `touch t.txt`, `rm y.txt`, `echo verifyok`, правку `a.txt` і правку фікстури:
- `--permission-mode acceptEdits`: `t.txt` створено, `y.txt` ВИДАЛЕНО, `a.txt` змінено, фікстуру змінено;
- `--permission-mode dontAsk --allowedTools Read Edit(./**) Write(./**) "Bash(echo verifyok)"` (або `Edit(//<abs lib>/**)`):
  `t.txt` не створено, `y.txt` лишився, `a.txt` змінено, фікстура недоторкана, `echo verifyok` виконано;
- `Edit(/abs/path/**)` з одним `/` не дає правити нічого: шлях читається відносно файлу налаштувань.
Наслідок: FR-65 змінено на `dontAsk` з явним переліком (розділ 5.8 вимог).
