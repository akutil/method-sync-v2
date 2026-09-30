# Add core: verification, enums, loop, report, CLI

## Why

Швидкий шлях (рішення власника 2026-09-30): чотири слайси, що лишились за планом, — перевірка полів, цикл і звіт,
CLI, енами — зведено в один. Разом вони дають робочий інструмент: FR-14…FR-22, FR-31…FR-44, FR-46…FR-84,
FR-90…FR-93 і NFR-1…NFR-3, NFR-5…NFR-15.

## What Changes

- `src/method_sync/verify.py` — Java-раннер поза бібліотекою: `verify_cmd`, класпас, `javac`, виклик клієнта з
  перехопленням винятку (`client_error`), сирий JSON того самого URL, звіряння полів в обидва боки і енамів
  (живе ⊆ оголошене), вердикт JSON, `System.exit`, стадії й ліміти часу.
- `src/method_sync/loop.py`, `src/method_sync/agent.py` — цикл «перевірка → агент», headless `claude -p`, бриф.
- `src/method_sync/report.py` — `runs/<slug>/report.md` із полями FR-78 і енамними полями.
- `src/method_sync/library.py`, `src/method_sync/boundaries.py`, `src/method_sync/__main__.py` — CLI, коди виходу,
  межі запису; приклад `registry.toml` у корені.

## Impact

- Affected specs: field-verification, enum-verification, sync-loop, run-report, run-cli.
- Affected code: модулі вище; тести `tests/*_test.py`.
- Dependencies: немає нових (stdlib; Java 21 і Maven — стек бібліотеки).
