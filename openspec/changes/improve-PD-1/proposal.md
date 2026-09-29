# Improvement Proposal: improve-PD-1

- **Defect:** PD-1 (`docs/qa/process-defects.json`): G2 "baseline specs" and G8 render PASS while `openspec/specs/` holds zero specs. check-traceability prints no `Scope:`/`Result:` line on stdout, so gate-status's three-valued parser falls through to PASS on exit 0.
- **Class / severity:** vacuous-pass / P0
- **Status:** draft

## Scope

Changes: `check-traceability` emits the stdout convention that gate-status (`gate-status.mjs:157-165`) and qa-verify (`qa-verify.mjs:249-254`) already parse. It reports `SKIP-pending` rather than `PASS` when the requirements file is missing or no spec exists. The markdown report's `Result:` line uses the same word.

Does NOT change: any failure rule, the `--release`/`--strict-*` semantics, gate-status itself, or the pre-Phase-2 warning texts.

Visible effect on approval: G2, G4 and G8 read `NOT-EARNED` (product code exists) until the first spec cites the FRs, and the computed frontier drops from G2 to G1. If `docs/current-state.md` claims `Last completed gate: G2`, gate-status will then raise its hard DIVERGENCE. That is intended. The auditor did not read that file.

## Target file

`scripts/check-traceability.mjs`. The pre-commit hook (`hooks-pre-commit.mjs:74-75`) regenerates and stages `docs/qa/traceability-report.md` and `trace/trace.json` in the same commit, so CI `--check-fresh` stays green.

## Exact diff

```diff
--- a/scripts/check-traceability.mjs
+++ b/scripts/check-traceability.mjs
@@ -223,3 +223,3 @@
 Scope: ${mvpFRs.length} MVP functional requirements.
-Result: ${failures.length === 0 ? "PASS" : `FAIL (${failures.length} failure${failures.length === 1 ? "" : "s"})`}${warnings.length ? `, ${warnings.length} warning(s)` : ""}
+Result: ${failures.length === 0 ? resultWord() : `FAIL (${failures.length} failure${failures.length === 1 ? "" : "s"})`}${warnings.length ? `, ${warnings.length} warning(s)` : ""}
 
@@ -272,3 +272,15 @@
   if (!flags.has("--check-fresh")) console.log(`wrote ${PATHS.reportOut} and ${PATHS.jsonOut}`);
+  // PD-1: print the stdout convention gate-status and qa-verify parse. Without a "Scope:" and a
+  // final "Result:" line, gate-status fell through to PASS on exit 0 (G2 "baseline specs"
+  // rendered PASS while openspec/specs/ was empty).
+  console.log(`Scope: ${mvpFRs?.length ?? 0} MVP functional requirement(s)`);
+  console.log(`Result: ${resultWord()}${warnings.length ? `, ${warnings.length} warning(s)` : ""}`);
   process.exit(failures.length ? 1 : 0);
 }
+
+// PD-1: a missing requirements file or zero specs is pending evidence, never a pass. gate-status
+// renders SKIP-pending as not earned (NOT-EARNED over product code), so the frontier stops at G1.
+function resultWord() {
+  if (failures.length) return "FAIL";
+  return requirementsPresent && specsStarted ? "PASS" : "SKIP-pending";
+}
```

## Expected metric movement

- **Metric:** gate-level vacuous passes. The digest cannot see these yet (PD-9), so the next retro reads gate-status output directly.
- **Current:** 2 rows (G2, G8) PASS over 0 specs; computed frontier G2.
- **Expected after fix:** 2 -> 0. The frontier is G1 until at least one spec cites the MVP FRs; after that G2 can PASS again on real evidence.
- **Verified by:** the next retro. No movement means this improvement is auto-flagged for revert.

## EXECUTED red→green proof

**EXECUTED 2026-09-30 by the orchestrator** (output below). The auditor has no shell. Run the block from anywhere inside the repo before approval and paste the full output below. It builds fixtures in `mktemp -d`, not under `tests/`, because fixture `@trace` lines there would count as real traces (PD-8). It applies the exact diff above, extracted from this file, so the tested text is the text that lands. It touches nothing in the repo.

```bash
bash <<'PROOF'
REPO=$(git rev-parse --show-toplevel); T=$(mktemp -d)
awk '/^```diff$/{f=1;next} /^```$/{f=0} f' "$REPO/openspec/changes/improve-PD-1/proposal.md" > "$T/pd.patch"
for d in red green; do
  mkdir -p "$T/$d/scripts" "$T/$d/docs" "$T/$d/openspec/specs"
  cp "$REPO/scripts/check-traceability.mjs" "$REPO/scripts/gate-status.mjs" "$T/$d/scripts/"
  printf '| ID | Phase | Requirement |\n|---|---|---|\n| FR-1 | MVP | does a thing |\n' > "$T/$d/docs/requirements.md"
done
mkdir -p "$T/green/openspec/specs/cap"; printf '# cap\n\nImplements FR-1.\n' > "$T/green/openspec/specs/cap/spec.md"
row() { (cd "$T/$1" && node scripts/gate-status.mjs 2>&1 | grep -E '^  G2 '); }
echo "== BEFORE (current script) =="; echo "red   (0 specs): $(row red)"; echo "green (1 spec):  $(row green)"
for d in red green; do (cd "$T/$d" && patch -s -p1 < "$T/pd.patch") || { echo "PATCH FAILED"; exit 1; }; done
echo "== AFTER (proposal diff) =="; echo "red   (0 specs): $(row red)"; echo "green (1 spec):  $(row green)"
(cd "$T/red" && node scripts/check-traceability.mjs 2>/dev/null | grep -E '^(Scope|Result):')
if row red | grep -q ' PASS '; then echo "PROOF FAILED: G2 still PASS with 0 specs"; exit 1; fi
if ! row green | grep -q ' PASS '; then echo "PROOF FAILED: G2 not PASS with a citing spec"; exit 1; fi
echo "PROOF OK"
PROOF
```

Expected: BEFORE shows `G2  PASS` for both fixtures (red = the defect). AFTER shows red `G2  SKIP-pending` (no product code in the fixture) and green `G2  PASS`, then `Scope: 1 …` / `Result: SKIP-pending, …`, then `PROOF OK`.

```text
# executed by the orchestrator 2026-09-30 from the repo root: bash <the block above>; exit 0
== BEFORE (current script) ==
red   (0 specs):   G2  PASS           baseline specs  [traceability]
green (1 spec):    G2  PASS           baseline specs  [traceability]
== AFTER (proposal diff) ==
red   (0 specs):   G2  SKIP-pending   baseline specs  [traceability]
green (1 spec):    G2  PASS           baseline specs  [traceability]
Scope: 1 MVP functional requirement(s)
Result: SKIP-pending, 4 warning(s)
PROOF OK
```

## Rollback (one revert)

- **Single commit:** yes. `git revert <sha>`. The revert commit's pre-commit hook regenerates and stages the report again.
- **State to clean up on revert:** none beyond the auto-regenerated `docs/qa/traceability-report.md` and `trace/trace.json`.
- **Ladder position:** unchanged (check-traceability renders `[experimental]` in gate-status).
- **Integrity lock:** after landing, `check-factory-integrity` WARNs "covered by an approved improvement commit". If you reseal, re-pass all 7 adaptation notes verbatim (PD-11; see the command in improve-PD-4).

## Approval & trailer convention

- Human approver: ________ · Date: ________
- The commit containing this diff MUST end with the trailer line `Refs: PD-1`.
