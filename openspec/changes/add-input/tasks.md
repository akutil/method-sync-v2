# Tasks: add-input

Порядок — згори вниз; рядок відмічає той, хто його виконав. Тести (розділ 2) пише `test-engineer` до коду, реалізацію
(розділ 3) — `capability-implementer`, не змінюючи тестів. API, рішення й покриття сценаріїв описано в `design.md`.

## 1. Залежності

- [x] 1.1 Нових залежностей немає: `package.json` не змінено, модулі слайсу імпортують лише stdlib Python 3.14
  (`tomllib`, `pathlib`, `dataclasses`, `os`, `urllib.request`, `urllib.parse`, `urllib.error`, `http.client`, `json`,
  `datetime`, `threading`). Автоматичний тест імпортів проти `sys.stdlib_module_names` (NFR-14) з'явиться в
  `add-run-cli`, не тут.

## 2. Тести спершу (червоні)

- [x] 2.1 `tests/registry_test.py`: докстрінг і рядок `# @trace FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, FR-10, NFR-11`;
  коментар, що `--registry` (FR-1) і stderr без трасування (NFR-11) доводить `add-run-cli`. `method_sync` імпортується
  через `sys.path` на `src`, як у v1. `lib` — тимчасовий каталог після справжнього `git init`; «придатний реєстр» —
  дослівно зі сценарію «Базовий придатний реєстр приймається»; варіант — заміна названого рядка чи секції. Робоча
  копія людини (`/Users/akutil/humex/binancefutures`) у тестах не згадується, хоча тести v1 на неї посилались.
- [x] 2.2 Вимоги «Вхід прогону», «Обов'язкові поля верхнього рівня», «Необов'язкові поля status і credentials»:
  базовий реєстр (усі поля, `credentials is None`, порядок і типи `args`); чотири варіанти відсутнього чи порожнього
  поля, у тексті `RegistryError` підрядки зі сценарію; три варіанти `status`/`credentials` — значення з тими самими
  типами, решта реєстру та сама, `load()` нічого не пише в stderr (`contextlib.redirect_stderr`).
- [x] 2.3 Вимоги «Невідоме поле», «Тип поля реєстру»: чотири варіанти невідомого поля; п'ять варіантів хибного типу,
  виняток саме `RegistryError`; `args` з датою, масивом і рядком — ключі в порядку запису, значення з типами `tomllib`.
- [x] 2.4 Вимоги «Файл реєстру існує і розбирається», «lib — наявний git-репозиторій», «Реєстр без жодного методу»:
  файлу немає, незакритий рядок (`Illegal character`), двічі `lib` (`Cannot overwrite a value`) — у повідомленні шлях
  файлу; відносний `lib` від cwd і `~` від `HOME` (cwd і `HOME` міняються з поверненням через `addCleanup`), `lib`
  повертається як записано, з розгорнутим `~`; `lib` не існує чи без `.git`; без записів і `method = []`.
- [x] 2.5 Вимоги «Запис методу», «Коротка форма», «Непридатний реєстр зупиняє прогін», «Повідомлення називає
  винуватця»: запис без `args` і `call` (`args == {}`, `call` — `None`, а з `call = ""` — `""`); три варіанти
  відсутнього чи порожнього поля запису; коротка форма; вада другого запису кидає виняток, хоч перший придатний;
  випадки з design.md D5 — файл не в UTF-8 і `~` неіснуючого користувача дають `RegistryError`, а не інший клас.
- [x] 2.6 `tests/live_test.py`: докстрінг і рядок `# @trace FR-23, FR-24, FR-25, FR-26, FR-28, FR-29, FR-30, NFR-4, NFR-11`;
  коментар, що FR-30 тут доведено частково (один запит на метод, свіжий `captured_at`), решту доводять слайси 2 і 3, а
  FR-27 — `add-run-cli` і e2e. Механіка: `http.server.ThreadingHTTPServer` на `127.0.0.1` з ефемерним портом за
  шляхом віддає статус, тіло, затримку чи перенаправлення і записує кожен запит (метод, шлях із рядком запиту,
  заголовки); сервер закривається в `tearDown`. Шов `open_url` приймає лише шпигуна, що делегує в
  `live.no_redirect_open` і рахує виклики. Відповіді біржі в Python-об'єктах не підробляються.
- [x] 2.7 Вимоги «Живий виклик методу», «Лише http чи https»: `build_url` дає рівно
  `https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3`; локальний сервер отримав один GET без
  `X-MBX-APIKEY`, без `timestamp`, `recvWindow` і `signature`; без `args` і з `args = {}` адреса без `?`, `args` у
  фікстурі — `{}`. `file://<T>`, `ftp://127.0.0.1:9` і `fapi.binance.com` дають `LiveUnavailable` з URL, фікстури немає,
  шпигуна не кликали. Хук `sys.addaudithook` не знімається, тому стоїть у дочірньому `python3`; той кличе `fetch` для
  трьох адрес і не бачить ні `open` файлу `<T>/fapi/v1/tradingSchedule`, ні `socket.connect` на `127.0.0.1:9`.
- [x] 2.8 Вимога «Ліміт часу живого виклику» (рішення оркестратора 2026-09-30): у типовому прогоні — механізм із
  коротким лімітом (0,3 с; співвідношення 10/15 збережено: 0,5 с проти 0,75 с) плюс перевірка, що
  `TIMEOUT_SECONDS == 15` і `fetch`/`capture` мають його типовим; буквальні 15 с / 10 с — клас `LiteralTimeLimits`,
  лише з `METHOD_SYNC_LITERAL_NFR4=1` (2 тести, ≈25 с). Так число зі спеки перевірене, а юніт-набір лишається
  секундним.
- [x] 2.9 Вимоги «Фікстура живої відповіді», «Slug»: п'ять полів, `body` дорівнює розбору сирого тіла,
  `captured_at` — ISO-8601 зі зсувом UTC і не раніше старту тесту, у `runs_dir` більше нічого не записано. Дочірній
  процес із cwd у тимчасовому каталозі друкує `live.RUNS_DIR`, і це `<корінь репо>/runs`. `args` з датою дають
  `"2026-09-30"`. Для `path` з `/fapi/v1/` і 300 літер `a` — `FixtureWriteError` із `runs/fapi-v1-aaa` у повідомленні, а
  наступний `capture` для `/fapi/v1/premiumIndex` у той самий `runs_dir` пише фікстуру. Каталоги `fapi-v1-premiumIndex`
  (з великою `I`) і `fapi-v1-tradingSchedule` (для шляху з кінцевою `/`) не мають `-` на краях.
- [x] 2.10 Вимоги «Недоступна жива відповідь зупиняє метод», «Відповідь без ключів об'єкта»:
  - Сім випадків: `https://fapi.binance.invalid`; `http://127.0.0.1:9`; `path` із пробілом; 400 з тілом
    `{"code":-1121,"msg":"Invalid symbol."}`; 204 без тіла; 200 з тілом нульової довжини і з самих пробілів; 200 з HTML.
    Щоразу в повідомленні URL і причина, а сервер, якого досягла спроба, отримав рівно один запит.
  - 301 на `/elsewhere/ok`: рівно один запит, у повідомленні `301`.
  - Тіла `[]`, `{}`, `[1, "a", null]`, `[{}, {}]`, `42`: «немає жодного ключа», фікстури немає.
  - `[{}, {"symbol": "BTCUSDT"}]`: відповідь доступна, фікстура має все тіло.
- [x] 2.11 Вимоги «Недоступна відповідь не лишає фікстури», «Джерело — лише живі виклики цього прогону» (частина без
  раннера й брифу): після мережевої помилки, 400 і `[]` фікстури немає; наявна фікстура після недоступної відповіді
  байт у байт та сама. Один `capture` дає рівно один запит на `path` і рядок запиту з `build_url`; `captured_at` нової
  фікстури не раніший за старт тесту, хоча стара вже лежала в `runs/<slug>/`.
- [x] 2.12 Передумови (`127.0.0.1:9` відмовляє в з'єднанні, `fapi.binance.invalid` не резолвиться) перевіряються
  першими. Якщо не виконано — тест падає з поясненням, а не пропускається.
- [x] 2.13 `npm run test:run` — нові файли червоні з правильної причини: `ModuleNotFoundError` на
  `method_sync.registry` і `method_sync.live`, а не синтаксис чи помилка в самому тесті. Число тестів і вивід — у звіт
  `test-engineer`.

## 3. Доменна логіка (зелені)

- [x] 3.1 `src/method_sync/registry.py` за design.md D1–D5: `RegistryError`, `slug_for`, `Method`, `Registry`,
  `load`; докстрінги пояснюють «чому» з посиланням на FR і принцип конституції.
- [x] 3.2 `src/method_sync/live.py` за design.md D6–D11: `TIMEOUT_SECONDS`, `RUNS_DIR`, `LiveUnavailable` (`url`,
  `reason`), `FixtureWriteError` (`path`), `build_url`, `no_redirect_open`, `fetch`, `capture`.
- [x] 3.3 `npm run test:run` — усі тести слайсу зелені, жоден не послаблено, не пропущено й не видалено. Тест, що
  суперечить спеці, — окремим рядком оркестраторові, а не правкою тесту.

## 4. CLI — не в цьому слайсі

Коду тут немає: CLI ще не існує, а винятки на коди виходу зіставляє `add-run-cli`. Частини сценаріїв, які видно лише
на процесі CLI, перелічено в design.md, розділ «Покриття сценаріїв у цьому слайсі». Їх беруть тести `add-run-cli`, а на
живій біржі вже перевіряє `npm run test:e2e`.

## 5. Перевірка, документи й підготовка до архіву

- [x] 5.1 `npm run lint`
- [x] 5.2 `npm run test:run`
- [x] 5.3 `npm run build`
- [x] 5.4 `OPENSPEC_TELEMETRY=0 npx openspec validate add-input --strict`
- [x] 5.5 `OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict`
- [ ] 5.6 Workflow `review-gate`: `scope` — `"add-input"`, `focus` — файли слайсу (`src/method_sync/registry.py`,
  `src/method_sync/live.py`, `tests/registry_test.py`, `tests/live_test.py`, `openspec/changes/add-input/`), `baseRef`
  — `cf8cdd9`: слайс закомічено (`aa4e2a9`, `9531134`, `115a1f4`), тож рецензія йде на `git diff cf8cdd9..HEAD`.
  За ADR-0003 виправити кожну підтверджену major/critical знахідку (решта — у беклог), а також спірну, якщо вона не очевидно хибна; після правок повторити 5.1–5.5.
  До архіву `openspec/changes/add-input/review-findings.json` має містити `"clean": true`.
- [x] 5.7 Smoke на справжніх входах. Драйвер `docs/qa/smoke/add-input/driver.py` (stdlib і `method_sync`) виходить із
  ненульовим кодом на першій розбіжності; вивід зберігається в `docs/qa/smoke/add-input/output.txt`. Запуск — з
  cwd поза репо, `PYTHONPATH=<корінь репо>/src`. Кроки:
  1. `git -C .sandbox/binancefutures rev-parse --git-dir` успішний; зберегти вивід
     `git -C .sandbox/binancefutures status --porcelain`.
  2. Скопіювати `/Users/akutil/humex/method-sync/registry.toml` у тимчасовий файл, замінивши лише рядок `lib`
     абсолютним шляхом до `.sandbox/binancefutures`. `registry.load()` віддає `verify_cmd`
     `mvn -q -DskipTests test-compile`, `base_url` `https://fapi.binance.com`, `status` `active`, `credentials`
     `None` і два методи: `/fapi/v1/premiumIndex` з `args` `{"symbol": "BTCUSDT"}` без `call`; `/fapi/v1/fundingRate`
     з `args` `{"symbol": "BTCUSDT", "limit": 3}` і `call` `"BTCUSDT", 3, null, null`.
  3. `<корінь репо>/runs/fapi-v1-premiumIndex/fixture.json` немає (якщо є — зупинитись і з'ясувати, чия вона).
     `capture("http://127.0.0.1:9", "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})` кидає `LiveUnavailable`, у
     повідомленні `жива відповідь недоступна` і `http://127.0.0.1:9/fapi/v1/premiumIndex?symbol=BTCUSDT`; фікстури
     після нього немає.
  4. `capture(reg.base_url, "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})` з типовим `runs_dir` пише
     `<корінь репо>/runs/fapi-v1-premiumIndex/fixture.json`: `http_status` `200`, `path` і `args` як у виклику,
     `captured_at` цього запуску, у `body` рівно 8 ключів — `estimatedSettlePrice`, `indexPrice`, `interestRate`,
     `lastFundingRate`, `markPrice`, `nextFundingTime`, `symbol`, `time`.
  5. Знову `http://127.0.0.1:9`, потім справжня біржа з `args` `{"symbol": "NOSUCHSYMBOL"}` (400). Обидва виклики
     кидають `LiveUnavailable`, у другому є `400`; SHA-256 фікстури з кроку 4 до й після однаковий.
  6. `capture(reg.base_url, "/fapi/v1/fundingRate", {"symbol": "NOSUCHSYMBOL", "limit": 3})`: біржа віддає `[]`, звідси
     `LiveUnavailable` зі словами «немає жодного ключа», а `runs/fapi-v1-fundingRate/fixture.json` не з'являється.
  7. `git -C .sandbox/binancefutures status --porcelain` такий самий, як на кроці 1.
  8. Фікстуру з кроку 4 скопіювати в `docs/qa/smoke/add-input/fixture.json`, прибрати `runs/fapi-v1-premiumIndex/`, а
     також `runs/`, якщо до smoke його не було.

  Smoke не пройшов — архіву немає.
- [ ] 5.8 `docs/current-state.md`: дата й час за Києвом, Phase 4, активна зміна `add-input`, стан слайсу. Кожне
  твердження з доказом: вивід 5.1–5.5, `openspec/changes/add-input/review-findings.json`,
  `docs/qa/smoke/add-input/output.txt`. README в репо немає, тож оновлюється лише цей файл.
- [ ] 5.9 `OPENSPEC_TELEMETRY=0 npx openspec archive add-input --yes` — лише коли 5.1–5.8 пройшли: smoke завершився з
  кодом `0`, а `review-findings.json` має `"clean": true`.
- [ ] 5.10 `git diff cf8cdd9 -- openspec/specs/registry/spec.md openspec/specs/live-capture/spec.md` показує лише три
  відомі відмінності: заголовок, порожній рядок після `## Purpose` і відсутній розділ «Поза обсягом». Будь-яка інша
  відмінність — зупинитись і розібратись. Повернути заголовок, Purpose і «Поза обсягом» із design.md, розділ «Baseline
  title and Purpose to restore after archive». Після цього той самий `git diff` нічого не друкує.
- [ ] 5.11 `OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict` (7 passed) і `npm run check:trace` зелені.
  Рядки 5.9–5.11 відмічаються вже в архівному `openspec/changes/archive/<дата>-add-input/tasks.md`; до коміту в ньому
  не лишається жодного `- [ ]`, бо `check-traceability` валить архівну зміну з невідміченими задачами.

## 6. Рецензія, раунд 1 (`review-round-1.md`) — рішення оркестратора

Регресійні тести (`test-engineer`) пишуться першими і падають на коді `115a1f4`; потім виправлення
(`capability-implementer`). Нумерація — як у `review-round-1.md`.

- [x] 6.1 R1-01, R1-10 — фікстура кодується в UTF-8 до відкриття файлу; тіло, яке не кодується (непарний сурогат),
  дає `LiveUnavailable` з URL; запис атомарний (тимчасовий файл у тому ж каталозі + `os.replace`), тож жоден збій не
  спустошує наявну фікстуру (D10 оновити). Тести: тіло з `\ud800` → типізований виняток, стара фікстура байт-у-байт;
  гілка запису `FixtureWriteError` (`fixture.json` — каталог).
- [x] 6.2 R1-11, R1-16 — перед записом `capture()` резолвить шлях фікстури і вимагає, щоб він лежав під резолвленим
  `runs_dir` (FR-91, принцип VII), інакше `FixtureWriteError` з назвою шляху. Тести: `path="/.."` (slug `..`) і
  `runs/<slug>` — симлінк назовні; поза `runs_dir` нічого не записано.
- [x] 6.3 R1-03, R1-08, R1-14 — після вердикту таймауту основний потік закриває з'єднання, і робочий потік
  завершується (D8 виправити). Тест: сервер крапає байти; після `LiveUnavailable` робочий потік зникає за ≤ 1 с.
- [x] 6.4 R1-04 — тіло з `NaN`/`Infinity`/`-Infinity` не є JSON (RFC 8259) → `LiveUnavailable` «тіло не
  розбирається як JSON»; `args` зі значеннями, яких JSON не представляє (`nan`, `inf`), пишуться у фікстуру рядком
  (D-20). Тести на обидва.
- [x] 6.5 R1-05 — `ValueError` із розбору TOML (ціле понад 4300 цифр) → `RegistryError` з назвою файлу. Тест.
- [x] 6.6 R1-06 — типи не міняються (v1 теж мав frozen dataclass із `dict`); design D1 виправити: «frozen — поля не
  переприсвоюються; вміст `args` і `methods` — звичайні `dict`/`list`, як у v1». Тест не потрібен.
- [x] 6.7 R1-07 — `PermissionError` при перевірці `lib` → `RegistryError` «немає доступу до <шлях>», а не «не
  існує». Тест (каталог без права входу; видимий пропуск, якщо процес — root).
- [x] 6.8 R1-09 — у причині з тіла чи статус-рядка сервера керівні символи замінено escape-послідовностями, довжина
  ≤ 200 символів. Тест з ESC, CR/LF і довгим тілом.
- [x] 6.9 R1-02 — тест із живою біржею — лише з `METHOD_SYNC_LIVE=1` (інакше видимий пропуск із причиною);
  `package.json`: `"test:integration": "METHOD_SYNC_LIVE=1 python3 -m unittest discover -s tests -p '*_test.py'"`.
  Юніт-набір і CI не мусять залежати від стану біржі (обмежені локації, збої).
- [x] 6.10 R1-12 — докази FR-27 (агент не кличеться, `lib` не змінюється за недоступної відповіді) — у слайсі
  `add-run-cli` (тест CLI) і в e2e `live-unavailable`; план §4.4 доповнено (оркестратор).
- [x] 6.11 R1-13 — заборона документації в брифі (друга половина FR-30) — тест у слайсі `add-sync-loop-and-report`;
  план §4.3 доповнено (оркестратор).
- [x] 6.12 R1-15 — формулювання 5.6 виправити: слайс закомічено, `review-gate` іде з `baseRef`.
- [ ] 6.13 R1-17 — сценарії реєстру, видимі лише на процесі CLI: уже задокументовано в design.md «Покриття сценаріїв»,
  власник — `add-run-cli`. Дії не треба.
- [x] 6.14 R1-18 — уривок тіла в причині не-200 лишається: це «причина» з FR-26 і NFR-11 (`Invalid symbol.` називає
  винуватця). Design D9 доповнити цим обґрунтуванням; тест лишається.
- [ ] 6.15 Повторний `review-gate` на диф виправлень (`baseRef` — коміт після 6.1–6.14); `review-findings.json` →
  `"clean": true`.

## 7. Рецензія, раунд 2 (`review-round-2.md`) — рішення оркестратора

- [x] 7.1 R2-01, R2-10 — перевірка вміщення дивиться на каталог, у якому справді йде запис: `fixture.parent.resolve()`
  мусить лежати під резолвленим `runs_dir` (slug `''`/`.` — у самому `runs_dir`, як дозволяє D10); помилка називає
  `<каталог>/fixture.json`. Регресія: `runs/<slug>` → каталог поза `runs_dir` плюс `fixture.json` там → посилання
  назад у `runs_dir`; і `path="/.."` плюс посилання `fixture.json` у корені інструмента → `FixtureWriteError`, посилання
  лишаються, поза `runs_dir` нічого не записано.
- [x] 7.2 R2-02 — `RecursionError`/`ValueError` із серіалізації фікстури → `LiveUnavailable` з URL (тіло надто глибоко
  вкладене). Регресія: глибоко вкладене тіло, яке `fetch()` приймає.
- [x] 7.3 R2-03, R2-07, R2-09 — у design.md D9 буквальний U+202E замінено текстом `\u202e` (оркестратор).
- [x] 7.4 R2-04 — кожна причина від клієнта (зокрема відмова проксі на CONNECT) іде через `_server_text`. Регресія:
  проксі відповідає на CONNECT статусом із ESC/BEL і 60 КБ тексту → причина без сирих керівних символів, ≤ 200.
- [x] 7.5 R2-05 — сокет реєструється до тунелю проксі, тож вердикт таймауту обриває й CONNECT. Регресія: проксі
  крапає відповідь на CONNECT → робочий потік зникає за ≤ 1 с після вердикту.
- [x] 7.6 R2-06, R2-08 — тіло читається з межею `MAX_BODY_BYTES` = 32 МБ (у тисячі разів більше за будь-яку відповідь
  REST Binance); більше — `LiveUnavailable` «тіло більше за 32 МБ»; заголовок із завеликим `Content-Length` не дає
  сирого `MemoryError`/`OverflowError`. Регресія: локальний сервер віддає більше за межу (межа — константа модуля).
- [ ] 7.7 Раунд 3 `review-gate` на диф 7.x; за ADR-0003 блокують лише major/critical, решта — у `docs/qa/review-backlog.md`.
