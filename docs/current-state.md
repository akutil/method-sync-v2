# Current State

> Persistent handoff file for future agent windows. A quick map, not a
> replacement for source-of-truth artifacts. Always verify with OpenSpec,
> tests, and the repo.

## Last Updated

- **Date and time:** 2026-09-30 18:10 (Europe/Kyiv)
- **Current phase:** Phase 4 завершено швидким шляхом (`docs/mvp-capability-plan.md` §2a); Phase 5–7 не робились
- **Last completed gate:** G4 (WAIVED: evals NFR-11/NFR-12 — `docs/qa/waivers/2026-09-30-evals-NFR-11-NFR-12.md`)
- **Active change:** none
- **Progress:** слайс 1 `add-input` і злитий слайс `add-core` (verify + loop + agent + report + library + CLI)
  реалізовані тестами першими, пройшли рецензію `review-gate` і заархівовані
  (`openspec/changes/archive/2026-09-30-*`). Інструмент працює end-to-end зі справжнім агентом.
- **Next task:** рішення власника — диспозиція COR-1 і спосіб здачі capstone (лише знеособлений експорт,
  жодного push; див. `AGENTS.md` → Boundaries). Сценарій відео — `docs/capstone/video-script.md`.
- **Claims:**
  - Інструмент робить свою роботу на живій біржі — evidence: `docs/qa/e2e-report.md` (`Result: PASS`, 12/12; агент дописав `FX` у `MarketType`, `docs/qa/e2e/schedule-fx/run/lib.diff`)
  - Юніти зелені — evidence: `npm run test:run` → 229 тестів OK (21 skipped — живі, під `METHOD_SYNC_LIVE=1`) + 12 селф-тестів хука
  - Специфікації валідні — evidence: `OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict` → 7 passed
  - Integrity-lock чистий — evidence: `node scripts/check-factory-integrity.mjs` → PASS, 28 файлів, 2 warnings

## Not claimed (свідомо, швидкий шлях)

- **G5/G6 NOT-EARNED:** coverage — waiver (лише stdlib); evals і `trajectory-eval` не робились.
- **G7 FAIL:** `check-traceability --release --strict-tests` — FR-58/69/70 доведені лише e2e-сценаріями, без
  юніта з `@trace`; `check-trajectory --release` — обидва слайси заархівовані з `review-findings.json`
  `clean: false` (blocking-знахідки виправлені, повторного чистого раунду не було), `trajectory-report.md` застарів.
- **COR-1 OPEN:** автоматична корекція на waiver evals — диспозицію ставить лише власник.
- Мінорні знахідки рецензій — `docs/qa/review-backlog.md`.

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

Archived changes: `2026-09-30-add-input`, `2026-09-30-add-core`.

## Validation Commands

```bash
npm run lint
npm run test:run
npm run build
OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict
```

Current test expectation: 229 unit tests (21 skipped without `METHOD_SYNC_LIVE=1`) + 12 stage-gate selftests.
`npm run test:integration` — живий Java-раннер; `npm run test:e2e` — CLI зі справжнім агентом.

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
