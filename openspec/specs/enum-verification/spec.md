# Enum Verification Specification

## Purpose

Звіряння енамних полів верхнього рівня зареєстрованої response-моделі з живою відповіддю за принципом IX «живе ⊆
оголошене»: значення, якого бракує, червонить вердикт і дописується константою, а константа, якої не було в живій
відповіді, лише називається у звіті (FR-47–FR-58). Енами бібліотеки «стійкі» — невідоме значення мовчки стає
запасником `UNKNOWN`, тож без цієї перевірки новий ключ `FX` у `/fapi/v1/tradingSchedule` губиться непомітно.
Множину властивостей моделі, з якої беруться енамні поля, визначає capability `field-verification` (FR-36).

Умовності сценаріїв: «сирий JSON» — тіло, яке раннер бере за URL методу (FR-35); якщо сценарій задає його, а жива
біржа віддає інше, той самий JSON підставляється через локальний `base_url`. «Тестова модель» і «тестовий енам» —
вигадані класи на класпасі раннера. «Копія `.sandbox/`» — одноразовий клон `binancefutures` на коміті `cee6585`
(TC-7).

## Requirements

### Requirement: Енамне поле моделі

Енамним полем MUST бути кожна властивість із множини полів моделі — тих самих властивостей із мутатором, що й для
звіряння полів (див. capability `field-verification`, FR-36), — тип якої: енам; колекція енамів — `List`, `Set` або
масив; мапа з енамними ключами (FR-47). Інші властивості MUST NOT бути енамними полями, зокрема мапа з енамними
значеннями, рядкове поле з енамоподібними значеннями (як `rateType`) і властивість лише з гетером.

#### Scenario: Мапа з енамними ключами

- **GIVEN** модель `TradingScheduleResponse` із властивостями `updateTime` типу `Long` і `marketSchedules` типу
  `Map<MarketType, MarketSchedule>`
- **WHEN** перевірка визначає енамні поля моделі
- **THEN** `enums` вердикту має рівно один запис: `field` — `marketSchedules`, `enum` —
  `com.example.binanceFutures.response.MarketType`

#### Scenario: Енам і колекції енамів

- **GIVEN** тестова модель із властивостями з гетером і сетером типів `FuturesOrderType`, `List<FuturesOrderType>`,
  `Set<FuturesOrderType>` і `FuturesOrderType[]`
- **WHEN** перевірка визначає енамні поля моделі
- **THEN** `enums` має чотири записи, по одному на властивість, і в кожному `enum` —
  `com.example.binanceFutures.request.FuturesOrderType`

#### Scenario: Інші властивості енамними полями не є

- **GIVEN** тестова модель лише з властивістю `rateType` типу `String`, властивістю `byValue` типу
  `Map<String, MarketType>` і гетером `getMarket()` типу `MarketType` без сетера й поля, а сирий JSON —
  `{"rateType": "FX", "byValue": {"a": "FX"}, "market": "FX"}`
- **WHEN** перевірка звіряє енами
- **THEN** `enums` вердикту — `[]`

### Requirement: Живі значення енамного поля

Живі значення енамного поля MUST братися із сирого JSON раннера (FR-35) за JSON-ім'ям поля (FR-48): для енама —
рядкове значення; для колекції — кожен рядковий елемент масиву; для мапи — кожен ключ об'єкта. `null`, відсутній
ключ і значення не того JSON-типу MUST NOT давати живих значень і MUST NOT зупиняти перевірку: поле без живих значень
доходить до вердикту з порожнім `live`.

#### Scenario: Значення енама, елементи колекції і ключі мапи

- **GIVEN** тестова модель з енамними полями `type` типу `FuturesOrderType`, `orderTypes` типу
  `List<FuturesOrderType>` і `markets` типу `Map<MarketType, String>`, а сирий JSON —
  `{"type": "LIMIT", "orderTypes": ["MARKET", "LIMIT", "MARKET"], "markets": {"FX": "a", "EQUITY": "b"}}`
- **WHEN** перевірка збирає живі значення
- **THEN** `live` — рівно `["LIMIT"]` для `type`, `["LIMIT", "MARKET"]` для `orderTypes` і `["EQUITY", "FX"]` для
  `markets`

#### Scenario: null, відсутній ключ і значення не того типу

- **GIVEN** та сама тестова модель і сирий JSON `{"type": null, "orderTypes": [null, 1, {"x": "MARKET"}, "LIMIT"]}` без
  ключа `markets`
- **WHEN** перевірка збирає живі значення
- **THEN** `live` — `[]` для `type`, `["LIMIT"]` для `orderTypes` і `[]` для `markets`, і перевірка доходить до
  вердикту

### Requirement: Об'єднання живих значень по масиву

Якщо тіло живої відповіді — масив, живі значення кожного енамного поля MUST бути об'єднанням по всіх об'єктах
масиву, а не по першому (FR-49).

#### Scenario: Неоголошене значення лише в останньому елементі

- **GIVEN** енамне поле `type` типу `FuturesOrderType`, який не оголошує `BOGUS_TYPE`, і сирий JSON — масив із трьох
  об'єктів: `type` має `"LIMIT"` у першому, відсутнє в другому і має `"BOGUS_TYPE"` у третьому
- **WHEN** перевірка звіряє енами
- **THEN** `live` запису `type` — `["BOGUS_TYPE", "LIMIT"]`, `missing` — `["BOGUS_TYPE"]`, і вердикт червоний

### Requirement: Оголошені значення енама

Оголошені значення енама MUST бути іменами його констант так, як їх мапить Jackson — значення `@JsonValue`, ім'я з
`@JsonProperty` або ім'я константи, — без константи-запасника з `@JsonEnumDefaultValue` (FR-50).

#### Scenario: Запасник не входить до оголошених

- **GIVEN** енам `MarketType` з константами `EQUITY`, `COMMODITY`, `KR_EQUITY`, `HK_EQUITY`, `CN_EQUITY` і запасником
  `UNKNOWN` з `@JsonEnumDefaultValue`
- **WHEN** перевірка визначає оголошені значення
- **THEN** `declared` — рівно `["CN_EQUITY", "COMMODITY", "EQUITY", "HK_EQUITY", "KR_EQUITY"]`

#### Scenario: Імена з @JsonProperty і @JsonValue

- **GIVEN** тестовий енам із константою `FOO` з `@JsonProperty("foo")` і константою `BAR`, а також тестовий енам із
  константами `A` і `B`, чий метод `@JsonValue code()` повертає `alpha` і `beta`
- **WHEN** живі значення поля першого енама — `foo` і `FOO`, а поля другого — `alpha` і `A`
- **THEN** `declared` записів — `["BAR", "foo"]` і `["alpha", "beta"]`, а `missing` — `["FOO"]` і `["A"]`

### Requirement: Розходження енаму

Живе значення енамного поля, якого немає серед оголошених значень його енама за точним збігом рядків, MUST бути
розходженням енаму — однаково для значення, елемента колекції і ключа мапи (FR-51). Розходження стоїть у `missing`
запису поля, що називає поле і тип енама, і червонить вердикт, навіть коли розходжень полів немає. Живе значення,
що дорівнює JSON-імені запасника, MUST вважатися оголошеним: запасник у звірянні не бере участі (принцип IX).

#### Scenario: FX у /fapi/v1/tradingSchedule

- **GIVEN** копія `.sandbox/`, де `MarketType` не оголошує `FX`, і метод `/fapi/v1/tradingSchedule` з моделлю
  `com.example.binanceFutures.response.TradingScheduleResponse` і `client_method` `getTradingSchedule` без
  `args`
- **AND** сирий JSON має на верхньому рівні рівно ключі `updateTime` і `marketSchedules`, а в `marketSchedules` — рівно
  ключі `CN_EQUITY`, `COMMODITY`, `EQUITY`, `FX`, `HK_EQUITY`, `KR_EQUITY`, як віддавала жива біржа 2026-09-30
- **WHEN** перевірка звіряє модель із живою відповіддю
- **THEN** вердикт червоний, `extra` і `missing` верхнього рівня порожні, а запис `marketSchedules` має `enum`
  `com.example.binanceFutures.response.MarketType` і `missing` — рівно `["FX"]`

#### Scenario: Живе значення з іменем запасника

- **GIVEN** енам `MarketType` із запасником `UNKNOWN` і сирий JSON `/fapi/v1/tradingSchedule`, де `marketSchedules` має
  ключі `CRYPTO`, `EQUITY`, `FX` і `UNKNOWN`
- **WHEN** перевірка звіряє енами
- **THEN** `live` запису `marketSchedules` — `["CRYPTO", "EQUITY", "FX", "UNKNOWN"]`, а `missing` — рівно
  `["CRYPTO", "FX"]`

### Requirement: Розділ enums у вердикті раннера

Вердикт раннера MUST мати ключ `enums` — масив із рівно одним записом на кожне енамне поле моделі (FR-52). Запис —
об'єкт із ключами `field` (JSON-ім'я поля), `enum` (повне ім'я класу енама за `Class.getName()`), `declared`, `live`,
`missing` (розходження енаму поля) і `unseen` (значення з `declared`, яких немає в `live`). Модель без енамних полів
має `"enums": []`. Порядок записів і переліків — див. capability `field-verification`, FR-41.

#### Scenario: Запис для marketSchedules

- **GIVEN** перевірка `/fapi/v1/tradingSchedule` на копії `.sandbox/`, де `MarketType` не оголошує `FX`, а
  `marketSchedules` сирого JSON має рівно ключі `CN_EQUITY`, `COMMODITY`, `EQUITY`, `FX`, `HK_EQUITY`, `KR_EQUITY`
- **WHEN** раннер друкує вердикт
- **THEN** `enums` після розбору JSON дорівнює:
  `[{"field": "marketSchedules", "enum": "com.example.binanceFutures.response.MarketType", "declared": ["CN_EQUITY", "COMMODITY", "EQUITY", "HK_EQUITY", "KR_EQUITY"], "live": ["CN_EQUITY", "COMMODITY", "EQUITY", "FX", "HK_EQUITY", "KR_EQUITY"], "missing": ["FX"], "unseen": []}]`

### Requirement: Невидима константа не червонить і не видаляється

Оголошена константа, крім запасника, якої не було серед живих значень поля, MUST NOT червонити вердикт (FR-53):
вибірка не є покриттям (принцип IX). Інструмент MUST NOT видаляти її — у бібліотеку він не пише (FR-44), а агентові
видаляти наявні константи забороняє бриф (вимога «Бриф для розходження енаму»).

#### Scenario: Невидима константа не червонить

- **GIVEN** копія `.sandbox/`, де `MarketType`, крім запасника, оголошує рівно ключі, які біржа віддає в
  `marketSchedules` на момент прогону, і вигадану константу `BOGUS_MARKET`
- **WHEN** перевірка `/fapi/v1/tradingSchedule` звіряє енами
- **THEN** `missing` запису `marketSchedules` порожній, `unseen` — рівно `["BOGUS_MARKET"]`, і вердикт зелений

#### Scenario: Невидима константа переживає прогін з агентом

- **GIVEN** копія `.sandbox/`, де `MarketType` не оголошує `FX` і має вигадану константу `BOGUS_MARKET`, а жива
  відповідь має в `marketSchedules` ключ `FX` і кожну іншу константу `MarketType`, крім запасника й `BOGUS_MARKET`
- **WHEN** CLI проганяє `/fapi/v1/tradingSchedule` без `--dry-run`, і остання перевірка зелена
- **THEN** `BOGUS_MARKET` лишається в `MarketType`, а diff `MarketType.java` не має видалених рядків
- **AND** `enum_unseen` у звіті дорівнює рядку:
  «marketSchedules (com.example.binanceFutures.response.MarketType): BOGUS_MARKET — не видалено»

### Requirement: Звіряння лише верхнього рівня моделі

Звіряння енамів MUST іти лише по енамних полях верхнього рівня зареєстрованої моделі (FR-54): енамні поля вкладених
об'єктів і масивів записів у `enums` не мають і вердикт не червонять.

#### Scenario: Вкладені orderTypes і timeInForce у /fapi/v1/exchangeInfo

- **GIVEN** метод `/fapi/v1/exchangeInfo` з моделлю `FuturesExchangeInfo`: на її верхньому рівні енамних полів немає,
  а `orderTypes` (`List<FuturesOrderType>`) і `timeInForce` (`List<FuturesTimeInForce>`) стоять у вкладених об'єктах
  `symbols[]`
- **WHEN** перевірка звіряє енами
- **THEN** вердикт має `"enums": []`, а значення в `symbols[].orderTypes`, якого `FuturesOrderType` не оголошує,
  розходження енаму не дає

### Requirement: Бриф для розходження енаму

Коли хоч один запис `enums` має непорожній `missing`, бриф агента MUST для кожного такого запису називати поле, повне
ім'я класу енама з `enum` і кожне значення з `missing` і дозволяти лише дописати константи (FR-55). Бриф MUST
забороняти видаляти, перейменовувати й переставляти наявні константи, зокрема ті, яких не було в живій відповіді
(FR-53), і чіпати запасник `@JsonEnumDefaultValue`. Решту брифу — див. capability `sync-loop`, FR-71.

#### Scenario: Бриф для FX

- **GIVEN** вердикт `/fapi/v1/tradingSchedule`, де запис `marketSchedules` має `enum`
  `com.example.binanceFutures.response.MarketType`, `missing` `["FX"]` і `unseen` `["BOGUS_MARKET"]`
- **WHEN** інструмент складає бриф агента
- **THEN** бриф називає поле `marketSchedules`, клас `com.example.binanceFutures.response.MarketType` і
  значення `FX`, яке треба дописати константою
- **AND** бриф забороняє видаляти, перейменовувати й переставляти наявні константи і чіпати запасник, а прибрати
  `BOGUS_MARKET` не просить

### Requirement: Місце нової константи енама

Бриф MUST вимагати оформити нову константу як сусідні і ставити її після останньої наявної константи, а якщо в енамі
є запасник `@JsonEnumDefaultValue` — перед ним (FR-55). Якщо запасника немає, а остання наявна константа закінчується
`;`, нова константа MUST ставати після неї, а цей `;` — ставати `,`: це єдина дозволена зміна наявного рядка.

#### Scenario: Нова константа перед запасником

- **GIVEN** `MarketType` з константами `EQUITY`, `COMMODITY`, `KR_EQUITY`, `HK_EQUITY`, `CN_EQUITY` і запасником
  `UNKNOWN`, а бракує значення `FX`
- **WHEN** інструмент складає бриф агента
- **THEN** бриф вимагає оформити `FX` як сусідні константи і поставити її після останньої наявної константи, перед
  запасником

#### Scenario: Енам без запасника, остання константа з крапкою з комою

- **GIVEN** тестовий енам `Side` без запасника з рядками констант `X,` і `Y;`, а бракує значення `Z`
- **WHEN** інструмент складає бриф агента
- **THEN** бриф велить поставити `Z` після `Y` і дозволяє єдину зміну наявного рядка — `;` після `Y` стає `,`
- **AND** бриф забороняє будь-яку іншу зміну наявних рядків енама

### Requirement: Поле звіту enum_mismatch

Звіт MUST мати поле `enum_mismatch` (FR-56), складене з `enums` першої перевірки прогону, одним рядком (див.
capability `run-report`, FR-78). Значення — рівно одне з трьох:

- групи через «; », по одній на кожен запис із непорожнім `missing`; група — `field`, пробіл, `enum` у круглих дужках,
  «: » і значення з `missing` через «, »;
- «розходжень енамів немає», якщо жоден запис не має непорожнього `missing`;
- «звіряння не відбулося», якщо перша перевірка не дійшла до звіряння (FR-80).

#### Scenario: Звіт показує те, що прогін застав

- **GIVEN** перша перевірка дала записи `marketSchedules` з `enum` `com.example.binanceFutures.response.MarketType`
  і `missing` `["FX"]` та `type` з `enum` `com.example.binanceFutures.request.FuturesOrderType` і `missing`
  `["BOGUS_A", "BOGUS_B"]`, а після правки агента перевірка зелена
- **WHEN** інструмент пише звіт
- **THEN** `enum_mismatch` дорівнює рядку:
  «marketSchedules (com.example.binanceFutures.response.MarketType): FX; type (com.example.binanceFutures.request.FuturesOrderType): BOGUS_A, BOGUS_B»

#### Scenario: Розходжень енамів немає

- **GIVEN** прогін `/fapi/v1/premiumIndex`, модель якого не має енамних полів; другий варіант — прогін
  `/fapi/v1/tradingSchedule`, де `MarketType` оголошує кожен живий ключ `marketSchedules`
- **WHEN** інструмент пише звіт
- **THEN** `enum_mismatch` — «розходжень енамів немає»

### Requirement: Поле звіту enum_unseen

Звіт MUST мати поле `enum_unseen` (FR-57), складене з `enums` першої перевірки прогону, одним рядком. Значення — рівно
одне з трьох:

- групи через «; », по одній на кожен запис із непорожнім `unseen`; група — `field`, пробіл, `enum` у круглих дужках,
  «: », константи з `unseen` через «, » і незмінна позначка « — не видалено»;
- «невидимих констант немає», якщо жоден запис не має непорожнього `unseen`;
- «звіряння не відбулося», якщо перша перевірка не дійшла до звіряння.

#### Scenario: Невидимі константи названо з позначкою

- **GIVEN** перша перевірка дала запис `marketSchedules` з `enum` `com.example.binanceFutures.response.MarketType`
  і `unseen` `["BOGUS_A", "BOGUS_MARKET"]`
- **WHEN** інструмент пише звіт
- **THEN** `enum_unseen` дорівнює рядку:
  «marketSchedules (com.example.binanceFutures.response.MarketType): BOGUS_A, BOGUS_MARKET — не видалено»

#### Scenario: Невидимих констант немає

- **GIVEN** прогін `/fapi/v1/tradingSchedule`, де кожна оголошена константа `MarketType`, крім запасника, трапилась
  серед живих ключів `marketSchedules`
- **WHEN** інструмент пише звіт
- **THEN** `enum_unseen` — «невидимих констант немає», і `UNKNOWN` у полі не названо

#### Scenario: Звіряння енамів не відбулося

- **GIVEN** перша перевірка прогону скінчилась стадією `compile`, а пізніша ітерація дійшла до звіряння
- **WHEN** інструмент пише звіт
- **THEN** і `enum_mismatch`, і `enum_unseen` — «звіряння не відбулося»

### Requirement: Доказ на живому tradingSchedule

Після прогону CLI по реєстру з методом `/fapi/v1/tradingSchedule` на копії `.sandbox/`, з живою біржею і справжнім
агентом у середовищі власника (див. capability `run-cli`, NFR-15), кожне значення з `missing` першої перевірки,
зокрема `FX`, MUST бути оголошене константою `MarketType`, а остання перевірка MUST бути зеленою (FR-58). Доказ
спирається на `missing` першої перевірки, бо набір живих ключів біржа може змінити.

#### Scenario: FX дописано в MarketType

- **GIVEN** копія `.sandbox/` з чистою робочою копією, де `MarketType` оголошує `EQUITY`, `COMMODITY`, `KR_EQUITY`,
  `HK_EQUITY`, `CN_EQUITY` і запасник `UNKNOWN`, і реєстр із методом `/fapi/v1/tradingSchedule`: модель
  `com.example.binanceFutures.response.TradingScheduleResponse`, `client_method` `getTradingSchedule`, без
  `args`; жива відповідь має в `marketSchedules` ключ `FX`
- **WHEN** CLI проганяє реєстр проти цієї копії без `--dry-run`
- **THEN** `missing` запису `marketSchedules` першої перевірки містить `FX`, остання перевірка зелена, і `MarketType`
  оголошує кожне значення з цього `missing`
- **AND** diff `MarketType.java` має лише додані рядки констант — після `CN_EQUITY,`, перед запасником `UNKNOWN`
- **AND** `enum_mismatch` у звіті містить групу, що починається з
  «marketSchedules (com.example.binanceFutures.response.MarketType): », і серед її значень є `FX`

## Поза обсягом

Щоб тестувальник не приймав обсяг за дефект:

- Енамні поля вкладених об'єктів і масивів (FR-59; TC-12).
- Особлива обробка енамів із зовнішніх артефактів: їхнє розходження лише червонить вердикт, як для енама бібліотеки
  (FR-104; TC-13).
- Перевірка, що агент не видалив константу всупереч брифу: позначка «не видалено» незмінна (FR-57), а видалення
  видно в diff і рецензії `method-sync-reviewer` (BC-4; TC-18).
- Сценарії доступу: автентифікації й ролей у продукті немає.
