# ADR-0001: Python stdlib для інструмента, Node лише для інструментів фабрики

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** оркестратор (Claude Code) + власник (Andrii Kutil)

## Context

Типовий стек Project Factory — Next.js · Postgres · Better Auth · Playwright. method-sync-v2 — CLI
без UI, без БД і без автентифікації: він читає TOML-реєстр, робить живий HTTP-виклик до біржі,
генерує Java-раннер, ганяє `claude -p` і пише звіт. Попередня версія (method-sync v1) довела цей
стек пробами: Python 3.14 + stdlib, `unittest` (див. `docs/research.md`, R-002, R-008). Правило
v1, яке лишається: залежність у сам інструмент — лише з дозволу людини.

Фабрика ж приносить власні інструменти на Node: `scripts/check-*.mjs`, git-хуки, OpenSpec CLI.

## Decision

- **Інструмент:** Python 3.14, лише stdlib. Пакет `src/method_sync/`, тести `tests/*_test.py`,
  запуск `python3 -m unittest discover -s tests -p '*_test.py'`.
- **Інструменти фабрики:** Node 20+, devDependency `@fission-ai/openspec` 1.13.2 (єдина залежність,
  потрібна для `openspec validate/archive`). Скрипти фабрики — без змін, крім адаптацій нижче.
- **Цільовий код:** Java 21 + Maven 3.9 — це стек бібліотеки, не наш; інструмент його лише викликає.
- **Мапінг батареї фабрики:** `lint` → `python3 -W error -m compileall` (синтаксис і попередження як
  помилки, лінтера зі сторони немає — stdlib); `build` → байткомпіляція пакета; `test:run` →
  unittest інструмента + селф-тест хука стейджу; `test:integration` → раннер проти справжньої
  бібліотеки і живої біржі; `test:e2e` → CLI по реєстру проти одноразової копії бібліотеки.

## Адаптації фабрики (записані й у `factory-lock.json`)

| Що | Чому |
|---|---|
| `qa-verify`: прибрано `recordings` і `visual-fidelity`; `db-integration-tests` → `integration-tests`, `browser-e2e-tests` → `e2e-evidence-run` | немає UI і БД; доказ роботи — прогони в `runs/` і `docs/qa/e2e-report.md` |
| `check-traceability`: тестами вважаються й `*_test.py`, `*_eval.py` | інакше жоден `@trace` у Python не рахувався б |
| `check-trajectory`: модуль — `src/method_sync/<module>.py` | інакше скоуп слайсів завжди порожній |
| `hooks-pre-commit`: ESLint + `tsc` → `python3 -W error -m py_compile` для staged `.py` | немає JS/TS |
| PostToolUse-хук Claude Code: ESLint → `py_compile` на кожну правку `.py` | та сама петля зворотного зв'язку, інша мова |
| CI: Python + Node, без Playwright/БД; інтеграція й e2e — локально | цільова бібліотека приватна, у публічному CI її нема |
| `quality/telemetry.config.json`: токен `e2e` без Playwright, артефакт `docs/qa/e2e-report.md` | e2e тут — CLI-прогін |
| адаптери Cursor/Codex/Copilot не ставились (`--tools=claude`) | працюємо лише в Claude Code |

**Знайдено в шаблоні CI:** вираз `github.ref_name == 'main' || github.ref_name == 'master' && '--release' || ''`
на гілці `main` дає `true`, а не `--release` (`&&` сильніший за `||`), тож release-перевірки на `main`
не вмикались. У нашому `ci.yml` вираз узято в дужки.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| Python stdlib (обрано) | доведено v1; нуль залежностей у інструмента | немає лінтера й coverage «з коробки» |
| Переписати інструмент на Node/TS під типовий стек фабрики | усі скрипти фабрики без адаптацій | викидає доведений v1 і його пробні знахідки; стек, якого власник не просив |
| Python + ruff/coverage.py/pytest | повноцінний lint і coverage-ratchet | залежності без дозволу людини — порушує правило v1 |

## Consequences

- Coverage-ratchet фабрики (`coverage/coverage-summary.json`) без coverage.py не має джерела — це
  відкрите питання до checkpoint 1.
- Інтеграційні й e2e-докази не відтворюються в CI; вони комітяться як артефакти прогонів.
- OpenSpec збирає анонімну телеметрію за замовчуванням; у CI вимкнено `OPENSPEC_TELEMETRY=0`,
  локально — змінною оточення або `openspec config set telemetry.enabled false` (рішення людини).
