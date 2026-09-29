# Project Context — method-sync-v2

## Purpose

CLI над Java-бібліотеками біржових конекторів. Людина перелічує в TOML-реєстрі вже реалізовані
публічні методи біржі; інструмент знімає живу відповідь, звіряє з нею верхній рівень response-DTO
(поля в обидва боки) і енамні поля (живі значення ⊆ константи), і жене `claude -p` до зеленої
команди перевірки. Правка лишається некомічена в робочій копії бібліотеки, поряд — звіт прогону.

## Tech Stack

- Інструмент: Python 3.14, лише stdlib (`tomllib`, `urllib.request`, `json`, `subprocess`,
  `pathlib`, `unittest`).
- Цільова бібліотека: Java 21, Maven 3.9, Retrofit, Jackson 2.10.1 — стек бібліотеки, не наш.
- Кодуючий агент: Claude Code CLI у headless-режимі (`claude -p`).
- Процес: Project Factory 2.0.0 (`koldovsky/project-factory@0d7286a`), OpenSpec CLI 1.13.2.

## Project Conventions

### Code Style

Модуль на відповідальність у `src/method_sync/`; докстрінги пояснюють «чому», з посиланням на
принцип конституції або вимогу. Код і коміти англійською, документи українською.

### Architecture Patterns

Детерміноване робить Python (реєстр, живий виклик, фікстура, класпас, раннер, звіряння, лог
ітерацій, звіт); Java-правку робить агент за письмовим стандартом бібліотеки. Сторонній світ
(мережа, Maven, агент) передається в цикл параметрами — так тести ганяють логіку без біржі.

### Testing Strategy

- Unit: `python3 -m unittest discover -s tests -p '*_test.py'`, кожен файл з `@trace FR-x`.
- Integration: згенерований раннер проти справжньої бібліотеки і живої біржі.
- End-to-end: CLI по реєстру проти одноразової копії бібліотеки в `.sandbox/`; доказ —
  `runs/<метод>/` і `docs/qa/e2e-report.md`.

### Git Workflow

Гілка `main`; коміт слайсу несе трейлери `Slice: add-<capability>` і `Refs: FR-x`
(`scripts/hooks-commit-msg.mjs`). Стейдж — поіменними шляхами.

## Domain Context

- **Реєстр** — TOML: `lib`, `verify_cmd`, `[live] base_url`, список `[[method]]` з `path`, `model`,
  `client_method`, `args`, `call`.
- **Фікстура** — жива відповідь цього прогону, `runs/<метод>/fixture.json`.
- **Розходження полів** — `extra` (у моделі, нема в живій відповіді) і `missing` (навпаки).
- **Розходження енамів** — живе значення енамного поля, якого нема серед констант енама.
- **Стійкий енам** — енам бібліотеки з `@JsonEnumDefaultValue UNKNOWN`: невідоме значення мовчки
  стає `UNKNOWN` (research R-009).

## Important Constraints

Принципи — `docs/constitution.md`. Коротко: відповідь лише з живого виклику; одна команда
перевірки, яка червоніє на будь-якому розходженні; maker ≠ checker; людина мерджить; межі запису і
секрети; ідемпотентність (порожній diff без розходжень).

## External Dependencies

- `https://fapi.binance.com` — публічні ендпоінти, без ключів.
- Цільова бібліотека `binancefutures` (приватне GitLab-репо) — доказові прогони йдуть по її
  локальній одноразовій копії.
