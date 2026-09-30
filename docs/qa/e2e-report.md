# Наскрізні докази (e2e) — method-sync-v2

Result: PASS

- Прогін: 2026-09-30 17:42 за Києвом (14:42 UTC), тривалість 6.5 хв; вибір: усі сценарії.
- Команда: `npm run test:e2e` → `python3 tests/e2e/evidence.py`; CLI у кожному сценарії — `PYTHONPATH=src python3 -m method_sync --registry <реєстр> [...]` з кореня репозиторію; реєстр — TOML у тимчасовому каталозі, його копія — у доказах сценарію.
- Середовище (NFR-15): macOS 27.0 (Darwin, arm64) · Python 3.14.0 · Java 21.0.2 · Maven 3.9.10 (на JDK 25) · Claude Code CLI 2.1.267.
- Цільова бібліотека: `~/src/binancefutures` @ `cee6585f89a45af1cfd648b923b1c3830937dafa` (гілка `stable`) — лише джерело клонів; кожен сценарій іде по свіжому `git clone` у `.sandbox/e2e/<сценарій>/`, жива біржа — `https://fapi.binance.com`, `verify_cmd` — `mvn -q -DskipTests test-compile`.
- Інструмент: method-sync-v2 @ `a14272ecc53e`; відбиток коду `b3d065828e658325` (src/method_sync, цей harness, коміт бібліотеки, версії середовища).

## Примітки

- Maven працює на JDK 25 (JAVA_HOME не задано), а javac і java з PATH — 21.0.2.
- harness запущено зсередини сесії Claude Code (CLAUDECODE задано): агент інструмента успадкує змінні хост-сесії; доказовий прогін — з термінала власника.

## Сценарії

| Сценарій | Доводить | Очікується | Спостерігалось | Вердикт | Докази |
|---|---|---|---|---|---|
| `environment` | NFR-15 | Середовище власника за NFR-15: macOS; Python, Java, Maven і Claude Code CLI тих версій, що записані у вимозі (версії читаються з рядка NFR-15). | пройшли всі перевірки (5); Maven працює на JDK 25 (JAVA_HOME не задано), а javac і java з PATH — 21.0.2; harness запущено зсередини сесії Claude Code (CLAUDECODE задано): агент інструмента успадкує змінні хост-сесії; доказовий прогін — з термінала власника | PASS | `docs/qa/e2e/environment/` |
| `premium-clean` | FR-19, FR-23, FR-24, FR-33, FR-34, FR-36, FR-39, FR-42, FR-44, FR-56, FR-63, FR-64, FR-77, FR-78, FR-79, FR-81, FR-90, FR-93, NFR-6, NFR-8, NFR-9, NFR-10 | Метод без розходжень: код 0, одна ітерація, агента немає; фікстура живої відповіді; вердикт раннера зелений — поля моделі — 8 властивостей Jackson `FuturesMarkPriceInfo`, extra і missing порожні, client_error null; звіт із порожніми розходженнями; `git status` копії як до прогону; другий прогін поспіль — `ітерацій=1` і той самий порожній `git diff`. | пройшли всі перевірки (38); run-1: код 0, 10 с, сесій агента 0; run-2: код 0, 10 с, сесій агента 0 | PASS | `docs/qa/e2e/premium-clean/` |
| `funding-dry-run` | FR-18, FR-19, FR-24, FR-39, FR-64, FR-77, FR-79, FR-90, FR-93, NFR-6, NFR-10 | `--dry-run` на справжньому розходженні `/fapi/v1/fundingRate`: код 1; одна перевірка — `перевірка=red`; агента немає; фікстура, `iteration-1.log` і звіт записані, `verify_result` — «dry-run: агента не кликали», `mismatch` — бракує markPrice, rateType; копія без змін. | пройшли всі перевірки (18); run: код 1, 12 с, сесій агента 0 | PASS | `docs/qa/e2e/funding-dry-run/` |
| `live-unavailable` | FR-19, FR-23, FR-26, FR-27, FR-28, FR-90, FR-93, NFR-6, NFR-10 | `base_url = "http://127.0.0.1:9"` (порт ніхто не слухає): код 3; рядок методу — «жива відповідь недоступна» з URL виклику; цей прогін не лишив ні фікстури, ні логів, ні звіту; агента немає; копія без змін. | пройшли всі перевірки (12); run: код 3, 0 с, сесій агента 0 | PASS | `docs/qa/e2e/live-unavailable/` |
| `live-scheme` | FR-19, FR-23, FR-26, FR-27, FR-28, FR-90, FR-93, NFR-6, NFR-10 | `base_url` зі схемою `file://` на каталог, де за шляхом методу лежить придатний JSON: адресу відхилено до відкриття — код 3, «жива відповідь недоступна» з URL, фікстури й перевірки немає, агента немає, копія без змін. | пройшли всі перевірки (12); run: код 3, 0 с, сесій агента 0 | PASS | `docs/qa/e2e/live-scheme/` |
| `mixed-run` | FR-14, FR-15, FR-19, FR-21, FR-23, FR-26, FR-28, FR-29, FR-90, FR-93, NFR-6, NFR-7, NFR-10 | Один реєстр: зелений `/fapi/v1/premiumIndex`, `/xapi/v1/nothing` (невідомий префікс, код 2) і `/fapi/v1/fundingRate` з `NOSUCHSYMBOL` (біржа віддає `[]` — жива відповідь недоступна, код 3): усі три оброблено в порядку реєстру, рядок на кожен і підсумок; код процесу — найгірший за шкалою 0 < 1 < 3 < 2 < 4, тобто 2. | пройшли всі перевірки (13); run: код 2, 14 с, сесій агента 0 | PASS | `docs/qa/e2e/mixed-run/` |
| `premium-bogus` | FR-19, FR-39, FR-60, FR-64, FR-70, FR-73, FR-77, FR-79, FR-81, FR-90, FR-93, NFR-6, NFR-10 | У копії до `FuturesMarkPriceInfo` дописано `bogusExtraField` (поле `String`, гетер, сетер, рядок у `toString`, як сусідні): код 0 після циклу з агентом; `mismatch` — «зайві в моделі: bogusExtraField», `removed` — `bogusExtraField`; поле зникло; змінено лише цей файл і лише вилученням рядків; індекс порожній. | пройшли всі перевірки (22); run: код 0, 79 с, сесій агента 1; FuturesMarkPriceInfo.java після прогону збігся з HEAD байт у байт | PASS | `docs/qa/e2e/premium-bogus/` |
| `funding-drift` | FR-19, FR-34, FR-39, FR-60, FR-64, FR-69, FR-73, FR-77, FR-79, FR-81, FR-90, FR-93, NFR-6, NFR-10 | Справжнє розходження: у копії `FuturesFundingRateInfo` немає `markPrice` і `rateType`, які віддає `/fapi/v1/fundingRate`; виклик — `call = '"BTCUSDT", 3, null, null'`: код 0 після циклу з агентом; `mismatch` — «бракує в моделі: markPrice, rateType»; обидва поля додано з гетером, сетером і рядком у `toString`; змінено лише цей файл і лише доданими рядками. | пройшли всі перевірки (24); run: код 0, 63 с, сесій агента 1 | PASS | `docs/qa/e2e/funding-drift/` |
| `strict-missing` | FR-19, FR-39, FR-42, FR-44, FR-46, FR-60, FR-64, FR-69, FR-73, FR-77, FR-79, FR-90, FR-93, NFR-6, NFR-10 | У копії з `FuturesMarkPriceInfo` (без `ignoreUnknown`, мапер бібліотеки строгий) прибрано `time` з гетером, сетером і рядком у `toString`: клієнт кидає виняток, а звіряння все одно йде — у першому лозі `client_error` з `Unrecognized field "time"` і `missing = time`, раннер завершився сам; агент повертає поле; остання перевірка зелена; змінено лише цей файл і лише доданими рядками. Поле — `time`, а не `interestRate` з підписаного набору: гетер `interestRate` (як і решти шести полів) викликає тест бібліотеки `BinanceFuturesApiRestClientImplTest.java:261`, тож `verify_cmd` (`test-compile`) упав би на стадії `compile` і до клієнта справа не дійшла б; `getTime()` тести не викликають (перевірено компіляцією і пробою 2026-09-30). | пройшли всі перевірки (25); run: код 0, 58 с, сесій агента 1; FuturesMarkPriceInfo.java після прогону збігся з HEAD байт у байт | PASS | `docs/qa/e2e/strict-missing/` |
| `schedule-fx` | FR-19, FR-51, FR-55, FR-56, FR-58, FR-60, FR-64, FR-73, FR-77, FR-79, FR-90, FR-93, NFR-6, NFR-10 | `/fapi/v1/tradingSchedule` віддає в `marketSchedules` ключ `FX`, якого немає в `MarketType`: код 0 після циклу з агентом; перша перевірка — розходження енаму `marketSchedules` (`MarketType`: `FX`); `enum_mismatch` у звіті називає його; `MarketType.java` оголошує кожне значення, якого бракувало, — лише доданими рядками після останньої справжньої константи й перед запасником `UNKNOWN`; інших файлів не змінено. | пройшли всі перевірки (22); run: код 0, 48 с, сесій агента 1 | PASS | `docs/qa/e2e/schedule-fx/` |
| `schedule-unseen` | FR-19, FR-51, FR-53, FR-55, FR-57, FR-58, FR-60, FR-64, FR-73, FR-77, FR-90, FR-93, NFR-6, NFR-10 | Як `schedule-fx`, але в копії перед запасником дописано вигадану константу `ZZ_INVENTED`: перша перевірка — `FX` бракує, `ZZ_INVENTED` невидима; остання перевірка зелена попри невидиму константу; `enum_unseen` у звіті — `ZZ_INVENTED` з позначкою «не видалено»; `FX` дописано, `ZZ_INVENTED` лишилась; `MarketType.java` — без жодного вилученого рядка. | пройшли всі перевірки (22); run: код 0, 62 с, сесій агента 1 | PASS | `docs/qa/e2e/schedule-unseen/` |
| `boundary` | TC-7 | Робоча копія людини `~/src/binancefutures` після всіх сценаріїв така сама, як до першого: HEAD, відбитки `git status --porcelain` і `git diff` (читання з `--no-optional-locks`). | пройшли всі перевірки (3) | PASS | `docs/qa/e2e/boundary/` |

## Вимоги з тегом e2e

| Вимога | Сценарії | Вердикт |
|---|---|---|
| FR-15 | mixed-run | PASS |
| FR-18 | funding-dry-run | PASS |
| FR-23 | premium-clean, live-unavailable, live-scheme, mixed-run | PASS |
| FR-26 | live-unavailable, live-scheme, mixed-run | PASS |
| FR-27 | live-unavailable, live-scheme | PASS |
| FR-33 | premium-clean | PASS |
| FR-34 | premium-clean, funding-drift | PASS |
| FR-36 | premium-clean | PASS |
| FR-39 | premium-clean, funding-dry-run, premium-bogus, funding-drift, strict-missing | PASS |
| FR-42 | premium-clean, strict-missing | PASS |
| FR-44 | premium-clean, strict-missing | PASS |
| FR-46 | strict-missing | PASS |
| FR-51 | schedule-fx, schedule-unseen | PASS |
| FR-53 | schedule-unseen | PASS |
| FR-56 | premium-clean, schedule-fx | PASS |
| FR-57 | schedule-unseen | PASS |
| FR-58 | schedule-fx, schedule-unseen | PASS |
| FR-63 | premium-clean | PASS |
| FR-69 | funding-drift, strict-missing | PASS |
| FR-70 | premium-bogus | PASS |
| FR-73 | premium-bogus, funding-drift, strict-missing, schedule-fx, schedule-unseen | PASS |
| FR-77 | premium-clean, funding-dry-run, premium-bogus, funding-drift, strict-missing, schedule-fx, schedule-unseen | PASS |
| FR-79 | premium-clean, funding-dry-run, premium-bogus, funding-drift, strict-missing, schedule-fx | PASS |
| FR-81 | premium-clean, premium-bogus, funding-drift | PASS |
| FR-93 | premium-clean, funding-dry-run, live-unavailable, live-scheme, mixed-run, premium-bogus, funding-drift, strict-missing, schedule-fx, schedule-unseen | PASS |
| NFR-6 | premium-clean, funding-dry-run, live-unavailable, live-scheme, mixed-run, premium-bogus, funding-drift, strict-missing, schedule-fx, schedule-unseen | PASS |
| NFR-8 | premium-clean | PASS |
| NFR-9 | premium-clean | PASS |
| NFR-10 | premium-clean, funding-dry-run, live-unavailable, live-scheme, mixed-run, premium-bogus, funding-drift, strict-missing, schedule-fx, schedule-unseen | PASS |
| NFR-15 | environment | PASS |

Сценарії спостерігають і вимоги без тегу e2e (їхній основний доказ — unit-тести `tests/*_test.py`): FR-14, FR-19, FR-21, FR-24, FR-28, FR-29, FR-55, FR-60, FR-64, FR-78, FR-90, NFR-7, TC-7.

## Як читати

- Вердикт сценарію — PASS лише тоді, коли пройшли всі його перевірки; кожна перевірка з очікуваним і спостереженим, з вимогами, які вона доводить, — у `docs/qa/e2e/<сценарій>/result.json`.
- Докази прогону CLI — у `docs/qa/e2e/<сценарій>/<прогін>/`: `registry.toml`, `command.txt`, `cli-stdout.txt`, `cli-stderr.txt`, `runs/<slug>/` (файли, які записав саме цей прогін), `lib-status-before.txt`, `lib-status-after.txt`, `lib-cached-before.txt`, `lib-cached-after.txt`, `lib-before.diff`, `lib.diff`, `agent-sessions.json`.
- Чи кликали агента, свідчать транскрипти Claude Code, чий `cwd` — клон сценарію, а не слова самого інструмента.
- NOT RUN ніколи не зараховується як PASS. Сценарій, що не запускався цього разу, зараховується лише з результатом попереднього запуску з тим самим відбитком коду і позначається «перенесено».
- Сценарії з агентом ідуть лише після зеленого `premium-clean` з тим самим відбитком коду: це береже бюджет агента, коли зламано сам шлях перевірки (`--no-gate` знімає обмеження).
