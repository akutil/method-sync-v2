# Current State

> Persistent handoff file for future agent windows. A quick map, not a
> replacement for source-of-truth artifacts. Always verify with OpenSpec,
> tests, and the repo.

## Last Updated

- **Date and time:** 2026-09-29 23:15:19 (Europe/Kyiv)
- **Current phase:** Phase 0
- **Last completed gate:** G0
- **Active change:** none
- **Progress:** Цикл фабрики встановлено й адаптовано під Python CLI (ADR-0001): агенти, workflow,
  `scripts/check-*`, git-хуки, PostToolUse-хук, CI, OpenSpec, уроки в `AGENTS.md`, integrity-lock.
  Із method-sync перенесено гейт стейджу з селф-тестом, рецензента `method-sync-reviewer`, принципи
  конституції і факти research. Коду інструмента ще немає.
- **Next task:** Phase 1 — `requirements-analyst` складає `docs/product-brief.md` і
  `docs/requirements.md` з method-sync і рішення власника про обсяг; далі checkpoint 1 (sign-off).
- **Claims:**
  - Хуки git спрацьовують — evidence: коміт `f393beb chore: verify hooks fire` (вивід pre-commit у сесії)
  - Integrity-lock на 23 файли, PASS — evidence: `factory-lock.json`, `node scripts/check-factory-integrity.mjs`
  - Селф-тест гейта стейджу зелений, 12 тестів — evidence: `python3 -m unittest discover -s .claude/hooks -p '*_test.py'`

## Source Of Truth

1. `AGENTS.md` — project agent rules.
2. `docs/current-state.md` — this handoff.
3. `docs/requirements.md` — canonical FR/NFR/TC/BC requirements.
4. `docs/product-brief.md` — product narrative.
5. `docs/mvp-capability-plan.md` — change sequence and scope.
6. `openspec/project.md` + `openspec/specs/` — accepted behavior.
7. `docs/adr/` — architecture decisions.
8. `docs/qa/` — QA proof pack and evidence runs.

## OpenSpec Status

```bash
OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict   # expected: all pass
OPENSPEC_TELEMETRY=0 npx openspec list                      # expected: No active changes (between slices)
```

Archived changes: none yet.

## Validation Commands

```bash
npm run lint
npm run test:run
npm run build
OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict
```

Current test expectation: 12 tests (stage-gate selftest); tool tests arrive with Phase 4.

## Environment / Deployment

- macOS, Python 3.14.0 (homebrew), Node 20.10, Java 21.0.2, Maven 3.9.10, Claude Code CLI 2.1.267.
- Цільова бібліотека: `/Users/akutil/humex/binancefutures` (приватна). Доказові прогони — лише по
  її копії в `.sandbox/` (gitignored); робоча копія людини має власну некомічену правку.
- Ключі біржі не потрібні (публічні ендпоінти).

## Agent Rules / Gotchas

- OpenSpec 1.x шле телеметрію за замовчуванням — `OPENSPEC_TELEMETRY=0`.
- `python3 -m compileall` на відсутньому каталозі друкує «Can't list» і повертає 0 — саме тому
  скелет пакета створено на G0 (`08ed7c2`): інакше lint/build зелені над порожнечею.
- `factory-lock.json` хешує `.githooks/*` (обгортки), але не `scripts/hooks-*.mjs`, де живе логіка
  хуків: правка хука не червонить integrity. Кандидат у process-defect для ретро.
- `openspec init` 1.x не створює `openspec/project.md` — його дописано вручну під протокол фабрики.
- Do not archive OpenSpec changes before implementation and smoke test.
