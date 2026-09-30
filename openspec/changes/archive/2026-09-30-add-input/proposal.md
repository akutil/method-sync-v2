# Proposal: add-input — реєстр методів і живий виклик

## Why

Кожен наступний слайс бере на вхід дві речі: перевірений запис методу з реєстру і фікстуру живої відповіді цього
прогону (принцип II). Тому `add-input` іде першим, а решта слайсів чекає на нього (`docs/mvp-capability-plan.md`, §2–3).

v1 робив те саме, але на поганому вході або падав із traceback, або мовчки приймав погане. Проби на коді v1
(2026-09-30, деталі — design.md, «Що v1 робив інакше»):

- реєстр: `lib = 5`, `~` неіснуючого користувача в `lib` і файл не в UTF-8 дають traceback; `call = 5` і `path = 5`
  приймаються без слова; на короткій формі v1 не пояснює, що без `model` і `client_method` працювати нема з чим;
- живий виклик: `file://` читає локальний файл; 301 іде за перенаправленням другим запитом; пробіл у шляху і тіло
  не в UTF-8 дають traceback; тіло `[]` приймається; ліміт 15 с діє на одну операцію сокета, а не на весь виклик.

Базові специфікації `registry` і `live-capture` (Phase 2) кажуть, як має бути; цей слайс доводить це тестами і кодом.

## What Changes

- `src/method_sync/registry.py` (новий): читання TOML через `tomllib` і сувора валідація FR-1–FR-10; повідомлення
  називає поле і місце. `Registry` і `Method` — dataclass, як у v1.
- `src/method_sync/live.py` (новий): рівно один живий GET на `base_url` + `path` + `args`, лише `http`/`https`,
  без перенаправлень, 15 с на весь виклик (FR-23, NFR-4). Відповідь пишеться у фікстуру `runs/<slug>/fixture.json`
  (FR-24, FR-25); коли вона недоступна за FR-26 і FR-29, власної фікстури не лишається (FR-28).
- Типізовані винятки `RegistryError`, `LiveUnavailable`, `FixtureWriteError`; слайс `add-run-cli` зіставить їх із
  кодами `2`, `3` і `1`.
- Тести `tests/registry_test.py` і `tests/live_test.py` пишуться зі сценаріїв до коду: спершу червоні, потім зелені.

## Capabilities

### New Capabilities

- `registry` — базова специфікація переїжджає в зміну як `## ADDED Requirements` (Option B); архів повертає її в
  `openspec/specs/`.
- `live-capture` — так само.

### Modified Capabilities

Немає. Текст вимог перенесено дослівно; змінено лише заголовок розділу `## Requirements`.

## Impact

- **Специфікації:** поки слайс відкритий, `openspec/specs/registry/spec.md` і `openspec/specs/live-capture/spec.md`
  лежать у `openspec/changes/add-input/specs/`. Архів OpenSpec 1.13.2 губить заголовок, порожній рядок після
  `## Purpose` і розділ «Поза обсягом» (проба на копії репо), тому після архіву їх повертають із design.md.
- **Код:** `src/method_sync/registry.py`, `src/method_sync/live.py`.
- **Тести:** `tests/registry_test.py`, `tests/live_test.py`.
- **Залежності:** нових немає, лише stdlib Python 3.14. Тест імпортів проти `sys.stdlib_module_names` (NFR-14)
  з'явиться в `add-run-cli`.
- **Не в цьому слайсі:** командний рядок, коди виходу, stderr і рядки stdout (`add-run-cli`); сирий запит раннера з
  FR-30 (`add-field-verification`); заборона документації в брифі з FR-30 (`add-sync-loop-and-report`).
