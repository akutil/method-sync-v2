# Improvement Proposal: improve-PD-4

- **Defect:** PD-4 (`docs/qa/process-defects.json`): the integrity lock seals `.githooks/pre-commit` and `.githooks/commit-msg`, but those are one-line `exec node scripts/hooks-*.mjs` wrappers. The hook logic is unlocked, and so are `correct.mjs` (decides gate-status's UNRECORDED-CORRECTION red) and `ledger.mjs`/`ledger-report.mjs` (write the process-defects fallback that G7 keys on). Editing any of them produces no red and not even a WARN.
- **Class / severity:** check-too-weak / P1
- **Status:** landed (approved by the owner at checkpoint 2, 2026-09-30)

## Scope

Changes: `collectLockTargets()` also collects `scripts/hooks-*.mjs` and `scripts/{correct,ledger,ledger-report}(.reference).mjs` at the existing hard tier, and the lock is resealed so the 5 files present today become tamper-evident.

Does NOT change: tiers, the verify logic, or the Refs: PD rule. `record-demos.mjs` and `agent-log-summary.mjs` stay out, since neither is gate-bearing for a no-UI CLI.

## Target file

`scripts/check-factory-integrity.mjs` (the diff), plus `factory-lock.json`, which the `--init-lock` command below regenerates. They must land together: new targets only become tamper-evident once sealed, and until then the check WARNs "NOT in factory-lock.json".

## Exact diff

```diff
--- a/scripts/check-factory-integrity.mjs
+++ b/scripts/check-factory-integrity.mjs
@@ -100,3 +100,11 @@
       if (statSync(join(scriptsDir, e)).isDirectory()) continue;
-      if (/^check-.*\.mjs$/.test(e) || /^(qa-verify|gate-status)(\.reference)?\.mjs$/.test(e)) {
+      // PD-4: .githooks/* are one-line `exec node scripts/hooks-*.mjs` wrappers, so the hook LOGIC
+      // lives in scripts/hooks-*.mjs; correct.mjs decides gate-status's UNRECORDED-CORRECTION red;
+      // ledger.mjs + ledger-report.mjs produce the digest and the process-defects fallback G7 keys on.
+      if (
+        /^check-.*\.mjs$/.test(e) ||
+        /^(qa-verify|gate-status)(\.reference)?\.mjs$/.test(e) ||
+        /^hooks-.*\.mjs$/.test(e) ||
+        /^(correct|ledger|ledger-report)(\.reference)?\.mjs$/.test(e)
+      ) {
         files.push(`scripts/${e}`);
```

### Reseal (same commit, after the diff is applied)

1. Run `node scripts/check-factory-integrity.mjs`. The expected output has exactly these items:
   - a FAIL on `scripts/check-factory-integrity.mjs` (no Refs commit yet);
   - a "NOT in factory-lock.json" WARN for exactly `scripts/correct.mjs`, `scripts/hooks-commit-msg.mjs`, `scripts/hooks-pre-commit.mjs`, `scripts/ledger-report.mjs` and `scripts/ledger.mjs`;
   - WARNs for drift already covered by landed `Refs: PD-<n>` commits;
   - the existing hook-presence WARNs.

   **Any other drift: STOP.** Resealing would launder it.
2. Reseal. This re-passes all 7 existing adaptation notes verbatim, because `--init-lock` erases any it is not given (PD-11):

```text
node scripts/check-factory-integrity.mjs --init-lock \
  --adaptation "qa-verify battery: recordings and visual-fidelity removed (no UI); db-integration-tests -> integration-tests, browser-e2e-tests -> e2e-evidence-run (ADR-0001)" \
  --adaptation "check-traceability: *_test.py and *_eval.py count as test files (ADR-0001)" \
  --adaptation "check-trajectory: slice module scope = src/method_sync/<module>.py (ADR-0001)" \
  --adaptation "hooks-pre-commit: ESLint + tsc replaced by python3 -W error -m py_compile on staged .py (ADR-0001)" \
  --adaptation "ci.yml: Python 3.14 + Node, no Playwright/DB/tsc/coverage; integration + e2e run locally (private target library); --release expression parenthesised (template bug: evaluates to true on main)" \
  --adaptation "quality/telemetry.config.json: acceptance token e2e = CLI evidence run, artifact docs/qa/e2e-report.md, no Playwright" \
  --adaptation "tool adapters: claude only (--tools=claude); visual-parity config not installed (no pixel requirement)" \
  --adaptation "PD-4: lock extended to scripts/hooks-*.mjs, correct.mjs, ledger.mjs, ledger-report.mjs"
```

3. Run `node scripts/check-factory-integrity.mjs` again. It must end with `Result: PASS` (plus the pre-existing hook-presence warnings, if any). Commit both files with `Refs: PD-4`.

## Expected metric movement

- **Metric:** unlocked gate-bearing scripts.
- **Current:** 5 (hooks-pre-commit, hooks-commit-msg, correct, ledger, ledger-report).
- **Expected after fix:** 5 -> 0. The locked file count in the check's `Scope:` line goes 23 -> 28.
- **Verified by:** the next retro. No movement means auto-flag for revert.

## EXECUTED red→green proof

**EXECUTED 2026-09-30 by the orchestrator** (output below). The auditor has no shell. Run inside the repo before approval and paste the output. Fixtures are in `mktemp -d` and are not git repos, so there is no Refs escape hatch.

```bash
bash <<'PROOF'
REPO=$(git rev-parse --show-toplevel); T=$(mktemp -d)
awk '/^```diff$/{f=1;next} /^```$/{f=0} f' "$REPO/openspec/changes/improve-PD-4/proposal.md" > "$T/pd.patch"
mkfx() { mkdir -p "$1/scripts" "$1/.githooks"
  cp "$REPO/scripts/check-factory-integrity.mjs" "$1/scripts/"
  printf '#!/bin/sh\nexec node scripts/hooks-pre-commit.mjs\n' > "$1/.githooks/pre-commit"
  printf 'console.log("hook logic v1");\n' > "$1/scripts/hooks-pre-commit.mjs"; }
tamper() { (cd "$1" && node scripts/check-factory-integrity.mjs --init-lock >/dev/null 2>&1
            printf 'process.exit(0); // every check removed\n' > scripts/hooks-pre-commit.mjs
            node scripts/check-factory-integrity.mjs >/dev/null 2>&1; echo $?); }
mkfx "$T/before"; echo "BEFORE: hook logic tampered after lock -> exit $(tamper "$T/before")   (defect: 0)"
mkfx "$T/after"; (cd "$T/after" && patch -s -p1 < "$T/pd.patch") || { echo "PATCH FAILED"; exit 1; }
R=$(tamper "$T/after"); echo "AFTER:  hook logic tampered after lock -> exit $R"
mkfx "$T/green"; (cd "$T/green" && patch -s -p1 < "$T/pd.patch" && node scripts/check-factory-integrity.mjs --init-lock >/dev/null 2>&1)
G=$(cd "$T/green" && node scripts/check-factory-integrity.mjs >/dev/null 2>&1; echo $?); echo "AFTER:  hook logic untouched -> exit $G"
(cd "$T/after" && node scripts/check-factory-integrity.mjs 2>&1 | grep -E '^FAIL')
if [ "$R" = 1 ] && [ "$G" = 0 ]; then echo "PROOF OK"; else echo "PROOF FAILED"; exit 1; fi
PROOF
```

Expected: `BEFORE … exit 0`, `AFTER … tampered … exit 1`, `AFTER … untouched … exit 0`, a `FAIL [scripts/hooks-pre-commit.mjs] gate-bearing file drift …` line, and `PROOF OK`.

```text
# executed by the orchestrator 2026-09-30 from the repo root: bash <the block above>; exit 0
BEFORE: hook logic tampered after lock -> exit 0   (defect: 0)
AFTER:  hook logic tampered after lock -> exit 1
AFTER:  hook logic untouched -> exit 0
FAIL  [scripts/hooks-pre-commit.mjs] gate-bearing file drift (hash drift) vs factory-lock.json with NO commit touching it whose message contains "Refs: PD-<n>". Gate scripts may only change through an approved improvement (executed red-to-green proof + human approval). Restore the locked file or land the approved "Refs: PD-<n>" commit.
PROOF OK
```

## Rollback (one revert)

- **Single commit:** yes. `git revert <sha>` restores both the script and the previous `factory-lock.json`.
- **State to clean up on revert:** none.
- **Ladder position:** hard (existing tier; no new check).
- **Independence:** improve-PD-5 edits the same file at lines 250-253. Either order applies cleanly. If PD-5 lands first, this reseal commit already satisfies it because it carries `Refs: PD-4`.

## Approval & trailer convention

- Human approver: Andrii Kutil (owner), checkpoint 2 in the Claude Code session · Date: 2026-09-30
- The commit containing this diff and the resealed `factory-lock.json` MUST end with the trailer line `Refs: PD-4`.
