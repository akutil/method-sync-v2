# Спостереження оркестратора для ретро (2026-09-30)

> Вхід для `process-auditor`, не вердикт. Тут лише симптоми з командами відтворення і виводом;
> чи це дефект процесу, який клас, серйозність і виправлення — вирішує аудитор (maker ≠ checker:
> оркестратор не пише ретро-артефактів про власну роботу). Скрипти фабрики — з
> `koldovsky/project-factory@0d7286a`, адаптації проєкту — `docs/adr/ADR-0001-stack.md`.

## S1. `check-acceptance-methods` не бачить Python-тестів

`scripts/check-acceptance-methods.mjs:437` — `isTestFile = /\.(test|spec|eval)\.(ts|tsx|js|mjs)$/`.
Та сама регулярка в `check-traceability.mjs` була адаптована на G0 (коміт `f15b81a`), а тут — ні, і
скрипт уже під integrity-lock (`d876f4c`). Проєкт — stdlib-Python, тести `tests/*_test.py`.

Відтворення: дві однакові фікстури (рядок `| FR-1 | MVP | … | verify: local-verifiable |`, `src/a.py`),
різниця лише в тестовому файлі:

```
fixture red   (tests/a_test.py,  "# @trace FR-1")  -> FAIL [FR-1] local-verifiable: no test annotated "@trace FR-1" found
fixture green (tests/a.test.mjs, "// @trace FR-1") -> Result: PASS
```

Наслідок: з G4 кожен MVP-рядок `local-verifiable` (98 контрактів) червоний, хоч тести є.

## S2. `gate-status` жорстко включає UI-перевірки в G6/G7

`scripts/gate-status.mjs:196-197`: G6 = `recordings · evals · acceptanceArtifact · visual`,
G7 містить `recordings`. У проєкту немає UI (ADR-0001), тож `check-recordings` і
`check-visual-fidelity` при наявному `src/` назавжди NOT-EARNED, і G6/G7 чесно пройти неможливо.
`qa-verify` цих членів уже не має (адаптація на G0), `gate-status` — має.

## S3. `gate-status` показав PASS над порожнечею

Вивід `node scripts/gate-status.mjs` 2026-09-29 після G0, коли не було жодної специфікації і
жодного FR:

```
  G2  PASS           baseline specs  [traceability]
  G8  PASS           UAT (trace regressions)  [traceability]
  traceability         PASS           [experimental]
```

`check-traceability` на той момент: `0 MVP FRs checked — 0 failure(s), 2 warning(s)`.

## S4. Integrity-lock не покриває логіку git-хуків

`factory-lock.json` хешує `.githooks/pre-commit` і `.githooks/commit-msg`, але це обгортки в один
рядок (`exec node scripts/hooks-pre-commit.mjs`). Сама логіка — `scripts/hooks-pre-commit.mjs`,
`scripts/hooks-commit-msg.mjs` — у lock не входить (шаблон lock: `scripts/check-*.mjs`), тож правка
хука не червонить `check-factory-integrity`.

## S5. Шаблон CI не вмикає `--release` на `main`

`templates/ci/github-actions.yml`: `${{ github.ref_name == 'main' || github.ref_name == 'master' && '--release' || '' }}`
— `&&` сильніший за `||`, на `main` вираз дає `true`. У проєктному `ci.yml` виправлено на G0 (дужки);
це дефект шаблону фабрики, не проєкту.

## S6. Папка пропозиції `improve-PD-x` ламає `openspec validate --all --strict` на OpenSpec 1.x

Проба 2026-09-30 у пісочниці: `openspec/changes/improve-PD-1/proposal.md` без дельт →
`✗ [ERROR] Change must have at least one delta`. Лише `skip_specs: true` у `.openspec.yaml` →
`skip_specs is set but .openspec.yaml is not valid change metadata`. Метадані
`schema: spec-driven` + `skip_specs: true` → `✓ change/improve-PD-1`. Шаблон фабрики
(`templates/retro/improvement.template.md`) цього файла не згадує. Крім того, кожна така папка — активна
зміна для `openspec list`, а `check-traceability --release` червоніє на активних змінах.
