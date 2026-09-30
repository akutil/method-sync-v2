# Improvement Proposal: improve-PD-7

- **Defect:** PD-7 (`docs/qa/process-defects.json`): ADR-0001:58 records the owner's checkpoint-1 decision that "G5 показує його явно як WAIVED, не PASS". gate-status has no WAIVED state (`SEVERITY`, line 178; `Result:` parser, line 159). A check that passes only because a waiver suppressed its failures (for example check-acceptance-methods' `WAIVED [...]` lines followed by `Result: PASS, N warning(s)`) renders plain PASS. This matters at checkpoint 2 if any of the 30 e2e contracts is waived.
- **Class / severity:** wrong-claim / P1
- **Status:** landed (approved by the owner at checkpoint 2, 2026-09-30)

## Scope

Changes: gate-status gains a `WAIVED` status.
- A check whose output would render PASS but carries `WAIVED` lines becomes WAIVED.
- In `worst()` it ranks just above PASS, so a gate containing it shows WAIVED.
- It counts as earned for the frontier: the owner signed it, and correct.mjs already keeps the overall result red until the waiver's auto-correction is dispositioned.
- Each WAIVED gate adds one to the warning count.

Does NOT change:
- check-coverage-ratchet. For G5 to actually show WAIVED, that script must print `WAIVED` lines when a waiver applies. The auditor could not verify whether it does (outside the read set). If it does not, that is a follow-up proposal against `scripts/check-coverage-ratchet.mjs`.
- G1/G3 `needs sign-off` precedence. At G3 the row still reads `needs sign-off`, and WAIVED shows in the checks list.

Not a gate change but required by the ADR: the checkpoint-1 coverage waiver has no artifact (`process-health.md:13`, waivers 0). Someone must record it under `docs/qa/waivers/` and have the owner disposition the resulting correction.

## Target file

`scripts/gate-status.mjs`

## Exact diff

```diff
--- a/scripts/gate-status.mjs
+++ b/scripts/gate-status.mjs
@@ -167,2 +167,5 @@
   if (status === "SKIP-pending" && productCode) status = "NOT-EARNED";
+  // PD-7: a PASS that holds only because a waiver suppressed failures renders WAIVED, never PASS
+  // (ADR-0001: the owner's checkpoint-1 coverage waiver must show as WAIVED at G5).
+  if (status === "PASS" && /^WAIVED\b/m.test(out)) status = "WAIVED";
   return { status, out, scopeN };
@@ -178,2 +181,2 @@
-const SEVERITY = ["PASS", "SKIP-pending", "needs sign-off", "NOT-EARNED", "FAIL"];
+const SEVERITY = ["PASS", "WAIVED", "SKIP-pending", "needs sign-off", "NOT-EARNED", "FAIL"];
 function worst(...statuses) {
@@ -264,2 +267,2 @@
-const earnedStatus = (s) => s === "PASS" || s === "needs sign-off";
+const earnedStatus = (s) => s === "PASS" || s === "WAIVED" || s === "needs sign-off";
 let frontier = -1;
@@ -492,2 +495,3 @@
-const warnings = advisories.length + (boundaryWarn ? 1 : 0) + (detectorWarn ? 1 : 0);
+const waivedGates = gateRows.filter((r) => r.status === "WAIVED").length;
+const warnings = advisories.length + (boundaryWarn ? 1 : 0) + (detectorWarn ? 1 : 0) + waivedGates;
 console.log(`\nScope: ${gateRows.length} gate(s)`);
```

## Expected metric movement

- **Metric:** waivers (rendered).
- **Current:** a waived check renders PASS, and 0 gate-status states can express WAIVED.
- **Expected after fix:** waived-but-PASS rows stay at 0 as waivers appear. Every waiver-backed pass reads WAIVED in the gate-status output.
- **Verified by:** the next retro, once a waiver exists. No movement means auto-flag for revert.

## EXECUTED red→green proof

**EXECUTED 2026-09-30 by the orchestrator** (output below). The auditor has no shell. Run inside the repo before approval and paste the output. Fixtures are in `mktemp -d`. It uses check-acceptance-methods' existing waiver path, not coverage (see Scope).

```bash
bash <<'PROOF'
REPO=$(git rev-parse --show-toplevel); T=$(mktemp -d)
awk '/^```diff$/{f=1;next} /^```$/{f=0} f' "$REPO/openspec/changes/improve-PD-7/proposal.md" > "$T/pd.patch"
fx() { mkdir -p "$T/$1/scripts" "$T/$1/docs"
  cp "$REPO/scripts/gate-status.mjs" "$REPO/scripts/check-acceptance-methods.mjs" "$T/$1/scripts/"
  printf '| ID | Phase | Requirement | Verification |\n|---|---|---|---|\n| FR-1 | MVP | does a thing | verify: local-verifiable |\n' > "$T/$1/docs/requirements.md"; }
fx waived; mkdir -p "$T/waived/docs/qa/waivers"
printf '# Waiver\n\nStatus: open\nFR-1: mechanism deferred (owner decision)\n' > "$T/waived/docs/qa/waivers/fr-1.md"
fx bare
fx clean; printf '{"scripts":{"test":"python3 -m unittest discover -s tests -p *_test.py"}}\n' > "$T/clean/package.json"
row() { (cd "$T/$1" && node scripts/gate-status.mjs 2>&1 | grep -E '^  acceptanceExistence '); }
echo "== BEFORE =="; for d in waived bare clean; do echo "$d: $(row $d)"; done
for d in waived bare clean; do (cd "$T/$d" && patch -s -p1 < "$T/pd.patch") || { echo "PATCH FAILED"; exit 1; }; done
echo "== AFTER =="; for d in waived bare clean; do echo "$d: $(row $d)"; done
if row waived | grep -q ' WAIVED ' && row bare | grep -q ' FAIL ' && row clean | grep -q ' PASS '; then echo "PROOF OK"; else echo "PROOF FAILED"; exit 1; fi
PROOF
```

Expected: BEFORE `waived` shows PASS (the defect), `bare` FAIL, `clean` PASS. AFTER `waived` shows WAIVED, `bare` FAIL (still able to fail), `clean` PASS (WAIVED does not leak into clean passes), then `PROOF OK`.

```text
# executed by the orchestrator 2026-09-30 from the repo root: bash <the block above>; exit 0
== BEFORE ==
waived:   acceptanceExistence  PASS           [experimental]  Scope: 1
bare:   acceptanceExistence  FAIL           [experimental]  Scope: 1
clean:   acceptanceExistence  PASS           [experimental]  Scope: 1
== AFTER ==
waived:   acceptanceExistence  WAIVED         [experimental]  Scope: 1
bare:   acceptanceExistence  FAIL           [experimental]  Scope: 1
clean:   acceptanceExistence  PASS           [experimental]  Scope: 1
PROOF OK
```

## Rollback (one revert)

- **Single commit:** yes. `git revert <sha>`.
- **State to clean up on revert:** none. Ledger events already emitted with `WAIVED` in `meta.gates` stay as history.
- **Ladder position:** unchanged (rendering change inside the dashboard).
- **Independence:** improve-PD-3 edits lines 61-68 and 195-198 of the same file. Either order applies cleanly with an offset.

## Approval & trailer convention

- Human approver: Andrii Kutil (owner), checkpoint 2 in the Claude Code session · Date: 2026-09-30
- The commit containing this diff MUST end with the trailer line `Refs: PD-7`.
