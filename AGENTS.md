# method-sync-v2 — Agent Rules

CLI над Java-бібліотеками біржових конекторів: людина перелічує в реєстрі вже реалізовані
методи біржі, інструмент знімає живу відповідь і жене кодуючого агента, доки DTO і енами не зійдуться
з нею. Перша ціль — `binancefutures`. Вимоги — `docs/requirements.md`; канонічні принципи —
`docs/constitution.md` (мають пріоритет над цим файлом).

## Project Factory

Проєкт ведеться фабрикою Project Factory (плагін `project-factory` у `.claude/settings.json`):
фази 0–8 і гейти G0–G8, субагенти в `.claude/agents/`, Workflow-скрипти в `.claude/workflows/`
(`spec-pipeline`, `review-gate`, `eval-suite`, `trajectory-eval`, `uat-triage`). Детерміновані
перевірки — `scripts/check-*.mjs` (Node + git); адаптації під Python — `docs/adr/ADR-0001-stack.md`.

## Project Handoff Protocol

Перед плануванням чи правкою прочитай:

1. `docs/current-state.md` — остання передача і наступний крок.
2. `docs/mvp-capability-plan.md` — послідовність слайсів і їхній обсяг.
3. `openspec/project.md` і потрібні `openspec/specs/*/spec.md`.
4. `docs/adr/` — прийняті рішення.

Онови `docs/current-state.md` при кожній віхі (зміна OpenSpec створена/реалізована/архівована,
гейт пройдено, ADR прийнято): дата й час за Києвом і поточна фаза. Це підказка, не джерело правди:
при розбіжності з кодом, спеками чи тестами перевір репо і виправ файл.

## Context architecture

Цей файл — статичний контекст, оплачується щоходу; бюджет ≤ 4k токенів. Деталі — у динамічному шарі
(спеки, конституція, research, скіл бібліотеки). Див. `docs/context-architecture.md`.

## Module conventions (Python)

- Лише stdlib Python 3.14. Залежність у інструмент — тільки з дозволу людини.
- Один модуль на відповідальність: `src/method_sync/<module>.py`; CLI —
  `PYTHONPATH=src python3 -m method_sync --registry registry.toml`.
- Тести — `tests/<module>_test.py`, `unittest`, кожен файл має коментар `@trace FR-x` із
  вимогами, які доводить. Без моків поведінки біржі чи бібліотеки: сторонній світ підміняється
  лише на межі (`open_url`, `verify`, `agent` як параметри), як у v1.
- Код і коміти — англійською, Conventional Commits; документи — українською.

## Correctness rules (вивчені на прогонах v1)

- Раннер перевірки генерується поза цільовою бібліотекою і завершує JVM через `System.exit`.
- Звіт показує розходження, яке прогін **застав**, а не те, що лишилось після правки.
- Агентові в циклі: фікстура через `--add-dir`, рівно одна дозволена команда (перевірка з реєстру)
  через `--allowedTools`, порожній stdin. Інакше він повертає правку неперевіреною.
- Правка в режимі актуалізації чіпає лише склад полів і константи енамів — не анотації, не імпорти,
  не порядок наявних рядків.

## Boundaries

- Інструмент ніколи не комітить, не пушить і не мерджить у цільову бібліотеку.
- У цьому репо коміти — лише в межах процесу фабрики (гейт, слайс, доказ); push — тільки з явного
  дозволу людини в поточній сесії; merge — ніколи.
- Стейдж — лише поіменними шляхами; `git add .`/`-A`/каталог рубає PreToolUse-хук
  `.claude/hooks/block-unsafe-stage.py` у будь-якому режимі дозволів.
- Не читати файли з секретами (`config.properties`, `.env*`). Чужі тести не запускати й не правити.
- Доказові прогони йдуть по одноразовій копії бібліотеки в `.sandbox/`, не по робочій копії людини.

## Test-first (per slice)

Тести слайсу пишуться зі спеки ПЕРШИМИ й мусять упасти з правильної причини; потім реалізація до
зеленого. Тест, що суперечить спеці, змінюють свідомо й окремим рядком у звіті, а не мовчки.

## Validation cadence

```bash
npm run lint && npm run test:run && npm run build
npx openspec validate --all --strict
npm run test:integration   # коли шар з'явиться
npm run test:e2e           # коли шар з'явиться
```

`OPENSPEC_TELEMETRY=0` перед викликами OpenSpec — телеметрія в нього увімкнена за замовчуванням.

## Process honesty (non-negotiable)

- Відсутність доказу ніколи не успіх: порожня перевірка при наявному коді — NOT-EARNED, не PASS.
- Не заглушувати скрипт батареї (`echo … && exit 0`); чого нема — має падати з поясненням.
- Кожне «зроблено/перевірено» має шлях до доказу (звіт, лог прогону, вивід команди).
- Коли людина заперечує заявлений результат — `npm run correct -- "<її слова>"`.

## Evals

Кейси — `evals/cases/*_eval.py` (сценарій, `produce()`, рубрика, `@trace`); оцінює workflow
`eval-suite` свіжим `eval-judge`; `node scripts/check-eval-ratchet.mjs` стереже бал у CI.

<!-- Тримати файл у бюджеті. Правило додавати тоді, коли агент помилився двічі. -->

<!-- BEGIN-FACTORY-LESSONS -->
<!--
  Managed region: `project-factory:init` / `:onboard` upsert cross-project
  lesson blocks here, each wrapped in its own BEGIN-LESSON:<id> /
  END-LESSON:<id> markers. Manual edits INSIDE a lesson block are preserved
  per-block on upsert; blocks are only replaced when the lesson itself is
  updated upstream. Do not remove the outer FACTORY-LESSONS markers —
  without them, upserts re-append lessons at the end of the file.
-->
<!-- BEGIN-LESSON-vacuous-pass-not-earned -->
### Lesson: a PASS over zero evidence is NOT-EARNED (vacuous-pass-not-earned, v1)

- Never report a gate or check as PASS when its evidence scope is 0 ("Scope: 0
  clip(s)", empty archive, no eval results) while product code exists under
  `app/`, `src/`, `lib/`, `server/`, or `packages/`. Render it **NOT-EARNED**
  and exit non-zero.
- Before product code exists, an empty scope is **SKIP-pending**: print it
  explicitly; it is visible and never counted as PASS.
- Never fold SKIP / 0-scope results into an overall "Pass" summary
  (`qa-verify`, `gate-status`). Field evidence: `worst()` folded SKIP into
  PASS and G4–G8 rendered green over literally nothing
  (2026-07-02-pixel-perfect-forensics.md, RC2).
<!-- END-LESSON-vacuous-pass-not-earned -->
<!-- BEGIN-LESSON-declared-method-needs-mechanism -->
### Lesson: a declared acceptance method needs an executable mechanism (declared-method-needs-mechanism, v1)

- Every FR/NFR that declares a verification method (pixel-diff, e2e,
  recording, a11y, eval, ...) must resolve to a real, executable, non-stub
  mechanism BEFORE the build phase starts: an installed check script, or a
  package.json script whose body does not match
  `/^echo |^true$|not yet configured/i`.
- A spec file that restates the requirement is NOT a mechanism. Field
  evidence: NFR-19 encoded "≥ 99% pixel match" while no pixel-diff tool
  existed anywhere and `test:e2e` was an echo stub exiting 0
  (2026-07-02-pixel-perfect-forensics.md, RC1).
- If a declared method has no mechanism, do not proceed: implement the check,
  or record an explicit human waiver — never let the declaration float
  unverifiable into the build.
<!-- END-LESSON-declared-method-needs-mechanism -->
<!-- BEGIN-LESSON-done-claims-need-evidence -->
### Lesson: done-claims need evidence pointers (done-claims-need-evidence, v1)

- Never write strong completion language ("Convergence reached", "all gates
  pass", "verification-only", "Overall result: Pass", "ready for release /
  sign-off", "done", "complete") into current-state.md, PR bodies, or handoff
  docs unless the same line carries a resolvable evidence pointer — a path
  that exists on disk (e.g. `docs/qa/automated-verification-latest.md`) and
  is fresh — or an explicit "Scope NOT delivered" section.
- The verdict belongs to exit-coded checks, not narrative. Field evidence:
  "Convergence reached … verification-only" was written while the same file
  admitted the formal acceptance was never run
  (2026-07-02-pixel-perfect-forensics.md, RC6).
- When you catch an unbacked claim, treat it as a correction event: file it,
  do not silently rewrite it.
<!-- END-LESSON-done-claims-need-evidence -->
<!-- BEGIN-LESSON-sampling-blindness -->
### Lesson: verified samples are never continuum coverage (sampling-blindness, v1)

- Any check that samples a CONTINUOUS space (viewport width, the element set,
  a single measurement channel) must **declare its sampling dimension** and the
  sample points — and must never report `coverage: continuum` / "100%" / "all
  widths" from a discrete sample set. Coverage from N samples is `sampled`.
- Every sampled check must carry a **stricter-instrument escalation path**: the
  finer instrument that runs before a definition-of-done is claimed or when any
  sample lands near the floor (5-width matrix → fine-step continuum pixel sweep;
  geometry-only channel → pixel channel over the same sweep; fixed element
  matrix → full computed-style diff).
- Field evidence (abstractly, the multi-layer parity campaign): the SAME
  blindness recurred three times — the element matrix, the width matrix, and a
  geometry-only sweep that read 0 divergence bands while 100+ below-floor pixel
  residuals sat between its samples
  (2026-07-02-pixel-perfect-forensics.md + follow-on parity work).
<!-- END-LESSON-sampling-blindness -->
<!-- BEGIN-LESSON-block-conquest-doctrine -->
### Lesson: per-block definition-of-done beats page-average (block-conquest-doctrine, v1)

- Drive visual parity **block by block to a per-block definition-of-done**, not
  by chasing a page-average score. A block is done only when, independently:
  `unpaired = 0`, `geometry = 0`, `paint = 0`, `asset = 0`, and `pixel >= floor`.
  The page is done only when EVERY block is done.
- The full-page pixel scalar is **telemetry, not the gate** — a high average
  launders per-block debt (one block regresses as another improves and the mean
  barely moves). Field evidence: the campaign demoted the full-page scalar
  (~0.9449 desktop) to telemetry and made acceptance per-section overlay
  (2026-07-02-pixel-perfect-forensics.md + follow-on parity work).
- Use the **overlay / onion-skin feedback pattern** to converge each block: a
  difference-blend overlay plus a 50% onion-skin composite of the block on both
  sites, reviewed by eye/vision, localizes the residual so it can be taken to
  zero before conquering the next block.
<!-- END-LESSON-block-conquest-doctrine -->
<!-- BEGIN-LESSON-capture-determinism -->
### Lesson: neutralize the capture before trusting it (capture-determinism, v1)

- A parity capture is trustworthy only after every known non-determinism source
  is neutralized. A same-input re-capture must be byte-stable; an unstable
  capture is a HARNESS defect (file it), never a product parity finding.
- The gotchas ledger — check each before treating a below-floor sample as real:
  1. **Carousel free-run timers** survive `autoplay.stop` — clear the timers,
     not just the flag, or the slide advances mid-shot.
  2. **Sub-pixel clip origin** ghosts the raster — snap clip origin to integer.
  3. **`captureBeyondViewport`** duplicates `position:fixed` chrome down the
     page — disable it when fixed chrome is present.
  4. **Lazy third-party widgets** come back blank under fast capture — settle /
     render-gate them on BOTH sites first.
  5. **In-context persistence probes** (localStorage/cookies/state) leak between
     captures — clear persistence so each shot is context-independent.
- Field evidence (abstractly): a fresh sweep over-counted by 100+ samples plus
  phantom geometry bands purely because a lazy live widget rendered blank under
  the fast path (2026-07-02-pixel-perfect-forensics.md + follow-on parity work).
<!-- END-LESSON-capture-determinism -->
<!-- END-FACTORY-LESSONS -->
