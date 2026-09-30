# Improvement Proposal: improve-PD-2

- **Defect:** PD-2 (`docs/qa/process-defects.json`): in artifact mode, check-acceptance-methods cannot see `tests/*_test.py`. The G0 adaptation reached check-traceability but not this copy of the same predicate, and the unadapted version was then locked.
- **Class / severity:** skipped-convention / P1
- **Status:** landed (approved by the owner at checkpoint 2, 2026-09-30)

## Scope

Changes: the `trace-test` artifact check (local-verifiable) accepts `*_test.py` and `*_eval.py`, as check-traceability has done since G0 (ADR-0001, `factory-lock.json` adaptation 2).

Deliberately does NOT copy check-traceability's third clause `/integration|e2e/.test(f)`. Here `f` is the full relative path, so that clause would count any product module or directory named `*integration*`/`e2e` as a test, which weakens the check.

Does not touch existence mode, other tokens, or waivers.

## Target file

`scripts/check-acceptance-methods.mjs`

## Exact diff

```diff
--- a/scripts/check-acceptance-methods.mjs
+++ b/scripts/check-acceptance-methods.mjs
@@ -436,3 +436,5 @@
   const re = new RegExp(`@trace\\s+[^\\n]*\\b${id}\\b`);
-  const isTestFile = (f) => /\.(test|spec|eval)\.(ts|tsx|js|mjs)$/.test(f);
+  // PD-2, method-sync-v2 adaptation (ADR-0001), the spelling check-traceability.mjs got at G0:
+  // Python tests are `*_test.py`, eval cases `*_eval.py`; the JS/TS spellings stay recognised.
+  const isTestFile = (f) => /\.(test|spec|eval)\.(ts|tsx|js|mjs)$/.test(f) || /(_test|_eval)\.py$/.test(f);
   for (const dir of ["tests", "test", "lib", "app", "src", "components", "evals", "e2e"]) {
```

## Expected metric movement

- **Metric:** acceptanceCoverage, artifact mode, local-verifiable.
- **Current:** 0 Python-traced tests recognised. The orchestrator reports 98 local-verifiable contracts; the auditor did not reconcile this with the digest's 124 declared / 30 e2e.
- **Expected after fix:** every `tests/*_test.py` / `*_eval.py` carrying `@trace <id>` is recognised. At the first G4 run, local-verifiable failures equal the FRs that truly lack a traced test, with no decoy `.test.mjs` files and no mass waivers.
- **Verified by:** the next retro. No movement means auto-flag for revert.

## EXECUTED red→green proof

**EXECUTED 2026-09-30 by the orchestrator** (output below). The auditor has no shell. Run the block inside the repo before approval and paste the output. The fixtures live in `mktemp -d` (PD-8), and the diff is extracted from this file.

```bash
bash <<'PROOF'
REPO=$(git rev-parse --show-toplevel); T=$(mktemp -d)
awk '/^```diff$/{f=1;next} /^```$/{f=0} f' "$REPO/openspec/changes/improve-PD-2/proposal.md" > "$T/pd.patch"
for d in red green; do
  mkdir -p "$T/$d/scripts" "$T/$d/docs" "$T/$d/src" "$T/$d/tests"
  cp "$REPO/scripts/check-acceptance-methods.mjs" "$T/$d/scripts/"
  printf '| ID | Phase | Requirement | Verification |\n|---|---|---|---|\n| FR-1 | MVP | does a thing | verify: local-verifiable |\n' > "$T/$d/docs/requirements.md"
  printf 'def f():\n    return 1\n' > "$T/$d/src/a.py"
done
printf 'import unittest\n# @trace FR-1\nclass T(unittest.TestCase):\n    def test_f(self):\n        pass\n' > "$T/green/tests/a_test.py"
printf 'import unittest\nclass T(unittest.TestCase):\n    def test_f(self):\n        pass\n' > "$T/red/tests/a_test.py"
run() { (cd "$T/$1" && node scripts/check-acceptance-methods.mjs --mode=artifact >/dev/null 2>&1; echo $?); }
echo "BEFORE red=$(run red) green=$(run green)   (defect: green exits 1 although tests/a_test.py carries @trace FR-1)"
for d in red green; do (cd "$T/$d" && patch -s -p1 < "$T/pd.patch") || { echo "PATCH FAILED"; exit 1; }; done
R=$(run red); G=$(run green); echo "AFTER  red=$R green=$G"
(cd "$T/green" && node scripts/check-acceptance-methods.mjs --mode=artifact 2>&1 | grep -E '^Result:')
if [ "$R" = 1 ] && [ "$G" = 0 ]; then echo "PROOF OK"; else echo "PROOF FAILED"; exit 1; fi
PROOF
```

Expected: `BEFORE red=1 green=1`, `AFTER red=1 green=0`, `Result: PASS`, `PROOF OK`.

```text
# executed by the orchestrator 2026-09-30 from the repo root: bash <the block above>; exit 0
BEFORE red=1 green=1   (defect: green exits 1 although tests/a_test.py carries @trace FR-1)
AFTER  red=1 green=0
Result: PASS
PROOF OK
```

## Rollback (one revert)

- **Single commit:** yes. `git revert <sha>`.
- **State to clean up on revert:** none. `trace/acceptance-contracts.json` is rewritten on the next run.
- **Ladder position:** unchanged (hard from day one per the script header).
- **Integrity lock:** WARN "covered by an approved improvement commit" after landing. If you reseal, re-pass all 7 adaptation notes (PD-11).
- **Independence:** does not overlap improve-PD-6, which touches the same file at lines 404-433 and 468-470. Either can land first; `patch`/`git apply` absorb the line offset.

## Approval & trailer convention

- Human approver: Andrii Kutil (owner), checkpoint 2 in the Claude Code session · Date: 2026-09-30
- The commit containing this diff MUST end with the trailer line `Refs: PD-2`.
