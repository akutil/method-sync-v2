# Improvement Proposal: improve-PD-3

- **Defect:** PD-3 (`docs/qa/process-defects.json`): gate-status still keys G6 on `recordings` and `visual`, and G7 on `recordings` plus `check-traceability --strict-recordings`, although ADR-0001 (owner-accepted) removed recordings and visual-fidelity from the qa-verify battery. For a CLI all four are red forever: `--strict-recordings` fails every MVP FR that has no recording manifest (`check-traceability.mjs:181-186`, class `recording-evidence`). G6/G7 cannot be passed honestly, which leaves only forged manifests or an unapproved edit.
- **Class / severity:** label-drift / P1
- **Status:** landed (approved by the owner at checkpoint 2, 2026-09-30)

## Scope

Changes:
- Removes `recordings` and `visual` from `GATE_COMMANDS` and from the G6/G7 key lists, mirroring the G0 qa-verify adaptation. They have to leave `GATE_COMMANDS` too, because `anyCheckFail` (`gate-status.mjs:478`) scans every executed check, including ones that back no gate.
- Drops `--strict-recordings` from G7's `traceabilityRelease` command, which becomes `check-traceability --release --strict-tests`.

Nothing replaces the flag. Its intent, that every MVP FR is covered by evidence, is already enforced for this project in two ways:
- `--strict-tests` for local-verifiable FRs (Python traces are recognised by check-traceability since G0).
- The e2e token in `acceptance --mode=artifact`, which improve-PD-6 makes cite each FR.

Does NOT change: G4, the three-valued logic, `--release`/`--strict-tests`, the scripts `check-recordings.mjs`/`check-visual-fidelity.mjs` (left installed, just not gate constituents), or check-traceability itself (the flag still exists for anyone who passes it).

About `checklists/quality-gates.md`, which gate-status names as its sync partner (`gate-status.mjs:57,71`): the file does not exist in this repo. `checklists/`, `**/quality-gates*.md` and `.project-factory/` are all empty, and `--strict-recordings` occurs only in `scripts/`. There is no in-repo checklist text to keep in sync, so for this project `GATE_COMMANDS` is the only definition of G7 and this diff is complete for the repo. If the owner keeps a checklist copy outside the repo (for example the upstream factory's), its G7 block needs the same one-flag change and its G6 block the recordings/visual removal. That text is outside this proposal and outside the lock.

## Target file

`scripts/gate-status.mjs`

## Exact diff

```diff
--- a/scripts/gate-status.mjs
+++ b/scripts/gate-status.mjs
@@ -59,12 +59,13 @@
 const GATE_COMMANDS = {
   traceability: { script: "check-traceability", args: [] },
   trajectory: { script: "check-trajectory", args: [] },
-  recordings: { script: "check-recordings", args: [] },
   coverage: { script: "check-coverage-ratchet", args: [] },
   evals: { script: "check-eval-ratchet", args: [] },
   acceptanceExistence: { script: "check-acceptance-methods", args: ["--mode=existence"] },
   acceptanceArtifact: { script: "check-acceptance-methods", args: ["--mode=artifact"] },
-  visual: { script: "check-visual-fidelity", args: [] },
+  // PD-3, method-sync-v2 adaptation (ADR-0001: CLI, no UI), the one qa-verify got at G0:
+  // check-recordings and check-visual-fidelity are not gate constituents here. CLI evidence is
+  // the e2e token (docs/qa/e2e-report.md), audited by acceptanceArtifact in G4/G6/G7.
   // EXPERIMENTAL per RULES-CHANGELOG.md — no --strict until promoted there.
   processRatchet: { script: "check-process-ratchet", args: [] },
   integrity: { script: "check-factory-integrity", args: [] },
@@ -73,7 +74,8 @@
   // (release strictness over an empty scaffold is pending, not broken).
   traceabilityRelease: {
     script: "check-traceability",
-    args: ["--release", "--strict-tests", "--strict-recordings"],
+    // PD-3 (ADR-0001): no --strict-recordings; a CLI has no recording manifests (e2e evidence: acceptanceArtifact).
+    args: ["--release", "--strict-tests"],
     releaseTier: true,
   },
   trajectoryRelease: {
@@ -193,8 +195,8 @@
   { g: "G3", desc: "capability plan + acceptance methods exist", keys: ["acceptanceExistence"], fixed: (fold) => worst(has("docs/mvp-capability-plan.md") ? "needs sign-off" : "FAIL", fold) },
   { g: "G4", desc: "per-slice", keys: ["traceability", "trajectory", "acceptanceArtifact", "integrity"] },
   { g: "G5", desc: "hardening (coverage)", keys: ["coverage"] },
-  { g: "G6", desc: "QA proof", keys: ["recordings", "evals", "acceptanceArtifact", "visual"] },
-  { g: "G7", desc: "release", keys: ["traceabilityRelease", "trajectoryRelease", "recordings", "acceptanceArtifact", "integrity"] },
+  { g: "G6", desc: "QA proof", keys: ["evals", "acceptanceArtifact"] },
+  { g: "G7", desc: "release", keys: ["traceabilityRelease", "trajectoryRelease", "acceptanceArtifact", "integrity"] },
   { g: "G8", desc: "UAT (trace regressions)", keys: ["traceability"] },
 ];
 const gateRows = GATES.map((gate, idx) => {
```

## Expected metric movement

- **Metric:** structural never-earnable constituents.
- **Current:** 4 (G6: recordings, visual; G7: recordings, `--strict-recordings`). `docs/qa/recordings-report.md`: `Scope: 0 clip(s)` → `Result: NOT-EARNED`.
- **Expected after fix:** 4 -> 0. G6/G7 still go red whenever e2e evidence is missing, and G7's traceability constituent still fails on missing specs, plan or test traces (proved below).
- **Verified by:** the next retro reads the G6/G7 key lists in gate-status output. No movement means auto-flag for revert.

## EXECUTED red→green proof

**EXECUTED 2026-09-30 by the orchestrator (rev 2; rev 1 failed its proof).** The auditor has no shell. Run inside the repo before approval and paste the output. Fixtures are in `mktemp -d`.

The fixture is a complete FR-1 chain: spec, plan, traced Python test, product code, and an `e2e` tag, but no recording manifest and no e2e report.
- Red property: G6 must still fail, because the e2e evidence is missing.
- Green property: recordings and visual are no longer executed or keyed, and G7's release traceability constituent flips from FAIL (missing recording manifest only) to PASS.

```bash
bash <<'PROOF'
REPO=$(git rev-parse --show-toplevel); T=$(mktemp -d); F="$T/fx"
awk '/^```diff$/{f=1;next} /^```$/{f=0} f' "$REPO/openspec/changes/improve-PD-3/proposal.md" > "$T/pd.patch"
mkdir -p "$F/scripts" "$F/docs" "$F/src" "$F/tests" "$F/openspec/specs/cap"
for s in gate-status check-recordings check-visual-fidelity check-acceptance-methods check-traceability; do cp "$REPO/scripts/$s.mjs" "$F/scripts/"; done
printf '| ID | Phase | Requirement | Verification |\n|---|---|---|---|\n| FR-1 | MVP | does a thing | verify: e2e |\n' > "$F/docs/requirements.md"
printf '# MVP capability plan\n\n| Slice | Owns |\n|---|---|\n| add-core | FR-1 |\n' > "$F/docs/mvp-capability-plan.md"
printf '# cap\n\nImplements FR-1.\n' > "$F/openspec/specs/cap/spec.md"
printf 'import unittest\n# @trace FR-1\nclass T(unittest.TestCase):\n    def test_f(self):\n        pass\n' > "$F/tests/a_test.py"
printf 'x = 1\n' > "$F/src/a.py"
show() { (cd "$F" && node scripts/gate-status.mjs 2>&1 | grep -E '^  (G6|G7) |^  (recordings|visual|traceabilityRelease) '); }
echo "== BEFORE =="; show
(cd "$F" && patch -s -p1 < "$T/pd.patch") || { echo "PATCH FAILED"; exit 1; }
echo "== AFTER =="; show
OUT=$(cd "$F" && node scripts/gate-status.mjs 2>&1)
if echo "$OUT" | grep -E '^  (G6|G7) ' | grep -qE 'recordings|visual'; then echo "PROOF FAILED: G6/G7 still keyed on UI checks or --strict-recordings"; exit 1; fi
if echo "$OUT" | grep -qE '^  (recordings|visual) '; then echo "PROOF FAILED: UI checks still executed"; exit 1; fi
if ! echo "$OUT" | grep -E '^  traceabilityRelease ' | grep -q ' PASS '; then echo "PROOF FAILED: release traceability still red on a complete chain"; exit 1; fi
if echo "$OUT" | grep -E '^  G6 ' | grep -q ' PASS '; then echo "PROOF FAILED: G6 PASS without e2e evidence"; exit 1; fi
if [ -e "$REPO/checklists/quality-gates.md" ]; then echo "NOTE: checklists/quality-gates.md exists; it needs the same edit (return to auditor)"; else echo "checklists/quality-gates.md: absent in repo (nothing to sync)"; fi
echo "PROOF OK"
PROOF
```

Expected:
- BEFORE: G6 `[recordings · eval-ratchet · acceptance-methods --mode=artifact · visual-fidelity]`; G7 containing `--strict-recordings · … · recordings`; rows `recordings NOT-EARNED`, `visual NOT-EARNED` and `traceabilityRelease FAIL`.
- AFTER: G6 `[eval-ratchet · acceptance-methods --mode=artifact]` with FAIL; G7 `[traceability --release --strict-tests · trajectory --release --check-fresh · acceptance-methods --mode=artifact · factory-integrity]`; `traceabilityRelease PASS`; no recordings/visual rows.
- Then the "checklist absent" line and `PROOF OK`.

```text
# executed by the orchestrator 2026-09-30 from the repo root; exit 0.
# The first draft of this proposal failed its own proof (PD-3: --strict-recordings left in G7;
# PD-6: a hunk with no trailing context was anchored to EOF and did not apply); the auditor
# revised it, and this is the run of the revised block.
== BEFORE ==
  G6  FAIL           QA proof  [recordings · eval-ratchet · acceptance-methods --mode=artifact · visual-fidelity]
  G7  FAIL           release  [traceability --release --strict-tests --strict-recordings · trajectory --release --check-fresh · recordings · acceptance-methods --mode=artifact · factory-integrity]
  recordings           NOT-EARNED     [experimental]  Scope: 0
  visual               NOT-EARNED     [experimental]  Scope: 0
  traceabilityRelease  FAIL           [experimental]
== AFTER ==
  G6  FAIL           QA proof  [eval-ratchet · acceptance-methods --mode=artifact]
  G7  FAIL           release  [traceability --release --strict-tests · trajectory --release --check-fresh · acceptance-methods --mode=artifact · factory-integrity]
  traceabilityRelease  PASS           [experimental]
checklists/quality-gates.md: absent in repo (nothing to sync)
PROOF OK
```

## Rollback (one revert)

- **Single commit:** yes. `git revert <sha>`.
- **State to clean up on revert:** none (gate-status writes only a ledger event).
- **Ladder position:** unchanged.
- **Integrity lock:** WARN "covered by an approved improvement commit" after landing. If you reseal, re-pass all 7 adaptation notes (PD-11).
- **Independence:** improve-PD-7 edits other regions of this file (lines 167-168, 178-179, 264-265, 492-493). None of its hunks or 3-line contexts overlap these. Either order applies with an offset.

## Approval & trailer convention

- Human approver: Andrii Kutil (owner), checkpoint 2 in the Claude Code session · Date: 2026-09-30
- The commit containing this diff MUST end with the trailer line `Refs: PD-3`.
