# Current State

> Persistent handoff file for future agent windows. A quick map, not a
> replacement for source-of-truth artifacts. Always verify with OpenSpec,
> tests, and the repo.

## Last Updated

- **Date and time:** 2026-09-30 10:46:10 (Europe/Kyiv)
- **Current phase:** Phase 3
- **Last completed gate:** G3
- **Active change:** none
- **Progress:** G0–G2 як раніше. Checkpoint 2: власник схвалив план із 5 слайсів і всі 7 покращень фабрики —
  застосовані комітами `Refs: PD-1…7` (`docs/qa/improvements/`). E2E-механізм `npm run test:e2e`
  (`tests/e2e/evidence.py`, 12 сценаріїв, 75 перевірок) написав `test-engineer` до коду інструмента; він червоний
  з правильної причини (`No module named method_sync.__main__`), звіт — `docs/qa/e2e-report.md`.
- **Next task:** Phase 4, слайс 1 `add-input` (registry + live-capture): spec-writer → test-engineer (червоні)
  → capability-implementer (зелені) → `review-gate` → архів (після архіву повернути заголовок і Purpose, які
  OpenSpec 1.x замінює на TBD).
- **Claims:**
  - Кожен заявлений спосіб приймання має механізм — evidence: `node scripts/check-acceptance-methods.mjs --mode=existence` → 124 контракти, 0 провалів
  - E2E-харнес червоний до коду — evidence: `docs/qa/e2e-report.md` (`Result: FAIL`, `No module named method_sync.__main__`)
  - Integrity-lock чистий після PD-4/PD-5 — evidence: `node scripts/check-factory-integrity.mjs` → PASS, 28 файлів
  - Специфікації валідні — evidence: `OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict` → 7 passed

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
- `gate-status` (locked) жорстко включає `recordings` і `visual` у G6/G7: для CLI без UI вони
  назавжди NOT-EARNED, тож G6/G7 чесно не пройти. Кандидат у process-defect (improve-PD-x через
  механізм фабрики, з дозволу людини), а не тиха правка locked-скрипта.
- `gate-status` на G0 показав G2 і G8 PASS при нулі специфікацій і нулі FR (traceability зелений над
  порожнечею) — той самий vacuous pass, проти якого урок `vacuous-pass-not-earned`. Кандидат у PD.
- Do not archive OpenSpec changes before implementation and smoke test.
