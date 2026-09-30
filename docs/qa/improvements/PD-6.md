# Improvement Proposal: improve-PD-6

- **Defect:** PD-6 (`docs/qa/process-defects.json`): under `exists-passed`, a Markdown artifact passes on mere existence (`check-acceptance-methods.mjs:429-432`). This project's e2e evidence is `docs/qa/e2e-report.md` (factory-lock adaptation 6; the path is also a built-in e2e glob at line 135). So any non-empty, fresh file with any content satisfies all 30 e2e contracts. It does not have to report a pass or cite them.
- **Class / severity:** check-too-weak / P1
- **Status:** landed (approved by the owner at checkpoint 2, 2026-09-30)

## Scope

Changes: a `.md` artifact validated as `exists-passed` must (1) carry a final `Result:`/`Status:` line whose verdict is pass/passed/ok/green, the same last-line-wins rule gate-status uses, and (2) cite the requirement id it vouches for. The id is threaded into `validateArtifact`.

Also affected, deliberately: any other token whose artifact is a `.md` under `exists-passed` (a11y-report.md, deploy-verification.md) needs the same verdict line and citation.

Does NOT change: JSON artifacts (status field logic as before), HTML reports, `score`/`vision-met`/`recording-clips`, freshness, or waivers.

Why now: the e2e report format does not exist yet (pre-Phase 4). Fixing the contract before anyone builds the generator costs one format rule, for example `Result: PASS` plus a `| FR-15 | pass |` row per requirement.

## Target file

`scripts/check-acceptance-methods.mjs`

## Exact diff

```diff
--- a/scripts/check-acceptance-methods.mjs
+++ b/scripts/check-acceptance-methods.mjs
@@ -402,7 +402,7 @@
 }
 
 // ---------- artifact validation ----------
-function validateArtifact(rel, kind, threshold) {
+function validateArtifact(rel, kind, threshold, id = null) {
   const raw = read(rel);
   if (raw === null || raw.length === 0) return { ok: false, msg: `${rel} is empty` };
   const isJson = rel.endsWith(".json");
@@ -429,6 +429,15 @@
   // exists-passed
   if (data && typeof data.status === "string" && !["passed", "pass", "ok", "green"].includes(data.status.toLowerCase()))
     return { ok: false, msg: `${rel}: status is "${data.status}", not passed` };
+  // PD-6: a Markdown report is not self-validating; its mere existence passed every requirement
+  // declaring the method (30 e2e contracts here). It must carry a final "Result:"/"Status:"
+  // verdict AND cite the requirement it vouches for.
+  if (rel.endsWith(".md")) {
+    const verdict = [...raw.matchAll(/^\s*\**\s*(?:result|status)\s*\**\s*:\s*\**\s*([A-Za-z-]+)/gim)].pop()?.[1]?.toLowerCase();
+    if (!verdict) return { ok: false, msg: `${rel}: no "Result:"/"Status:" line; a Markdown report's existence is not a pass` };
+    if (!["passed", "pass", "ok", "green"].includes(verdict)) return { ok: false, msg: `${rel}: verdict is "${verdict}", not passed` };
+    if (id && !new RegExp(`\\b${id}\\b`).test(raw)) return { ok: false, msg: `${rel} does not cite ${id}; it does not vouch for this requirement` };
+  }
   return { ok: true, msg: "artifact present" };
 }
 
@@ -466,7 +475,7 @@
   let staleOnly = null;
   for (const f of matches) {
     const ageH = (Date.now() - statSync(join(root, f)).mtimeMs) / 3_600_000;
-    const v = validateArtifact(f, spec.artifactCheck ?? "exists-passed", threshold);
+    const v = validateArtifact(f, spec.artifactCheck ?? "exists-passed", threshold, id);
     if (v.ok && ageH <= maxAgeHours) okFresh = okFresh ?? { f, msg: v.msg };
     else if (v.ok) staleOnly = staleOnly ?? { f, ageH };
     else if (ageH <= maxAgeHours) freshBad = freshBad ?? v;
```

## Expected metric movement

- **Metric:** acceptanceCoverage (e2e).
- **Current:** 30 e2e contracts (`process-health.md:38`) satisfiable by one verdict-less file.
- **Expected after fix:** 30 -> 0. An e2e contract turns green only when the report says pass and names that requirement.
- **Verified by:** the next retro, which re-runs `--mode=artifact` against the first real e2e report. No movement means auto-flag for revert.

## EXECUTED red→green proof

**EXECUTED 2026-09-30 by the orchestrator (rev 2; rev 1 failed its proof).** The auditor has no shell. Run inside the repo before approval and paste the output. Fixtures are in `mktemp -d`. The block is unchanged from rev 1; only the extracted diff changed.

```bash
bash <<'PROOF'
REPO=$(git rev-parse --show-toplevel); T=$(mktemp -d)
awk '/^```diff$/{f=1;next} /^```$/{f=0} f' "$REPO/openspec/changes/improve-PD-6/proposal.md" > "$T/pd.patch"
fx() { mkdir -p "$T/$1/scripts" "$T/$1/docs/qa" "$T/$1/src"
  cp "$REPO/scripts/check-acceptance-methods.mjs" "$T/$1/scripts/"
  printf '| ID | Phase | Requirement | Verification |\n|---|---|---|---|\n| FR-1 | MVP | does a thing | verify: e2e |\n' > "$T/$1/docs/requirements.md"
  printf 'x = 1\n' > "$T/$1/src/a.py"; }
fx noverdict; fx wrongid; fx green
printf '# E2E\n\nran the CLI\n' > "$T/noverdict/docs/qa/e2e-report.md"
printf '# E2E report\n\nResult: PASS\n\n| Req | Verdict |\n|---|---|\n| FR-2 | pass |\n' > "$T/wrongid/docs/qa/e2e-report.md"
printf '# E2E report\n\nResult: PASS\n\n| Req | Verdict |\n|---|---|\n| FR-1 | pass |\n' > "$T/green/docs/qa/e2e-report.md"
run() { (cd "$T/$1" && node scripts/check-acceptance-methods.mjs --mode=artifact >/dev/null 2>&1; echo $?); }
echo "BEFORE noverdict=$(run noverdict) wrongid=$(run wrongid) green=$(run green)   (defect: all 0)"
for d in noverdict wrongid green; do (cd "$T/$d" && patch -s -p1 < "$T/pd.patch") || { echo "PATCH FAILED"; exit 1; }; done
A=$(run noverdict); B=$(run wrongid); G=$(run green); echo "AFTER  noverdict=$A wrongid=$B green=$G"
for d in noverdict wrongid; do (cd "$T/$d" && node scripts/check-acceptance-methods.mjs --mode=artifact 2>&1 | grep -E '^FAIL'); done
if [ "$A" = 1 ] && [ "$B" = 1 ] && [ "$G" = 0 ]; then echo "PROOF OK"; else echo "PROOF FAILED"; exit 1; fi
PROOF
```

Expected: `BEFORE noverdict=0 wrongid=0 green=0`, `AFTER noverdict=1 wrongid=1 green=0`, two FAIL lines ("no Result:/Status: line", "does not cite FR-1"), `PROOF OK`.

```text
# executed by the orchestrator 2026-09-30 from the repo root; exit 0.
# The first draft of this proposal failed its own proof (PD-3: --strict-recordings left in G7;
# PD-6: a hunk with no trailing context was anchored to EOF and did not apply); the auditor
# revised it, and this is the run of the revised block.
BEFORE noverdict=0 wrongid=0 green=0   (defect: all 0)
AFTER  noverdict=1 wrongid=1 green=0
FAIL  [FR-1] e2e: docs/qa/e2e-report.md: no "Result:"/"Status:" line; a Markdown report's existence is not a pass
FAIL  [FR-1] e2e: docs/qa/e2e-report.md does not cite FR-1; it does not vouch for this requirement
PROOF OK
```

## Rollback (one revert)

- **Single commit:** yes. `git revert <sha>`.
- **State to clean up on revert:** none.
- **Ladder position:** unchanged (the script is hard from day one).
- **Integrity lock:** WARN "covered by an approved improvement commit" after landing. If you reseal, re-pass all 7 adaptation notes (PD-11).
- **Independence:** improve-PD-2 changes line 437 of the same file, with context lines 436 and 438. This proposal's nearest hunk ends its trailing context at line 434, so there is no overlap and either order applies with an offset.

## Approval & trailer convention

- Human approver: Andrii Kutil (owner), checkpoint 2 in the Claude Code session · Date: 2026-09-30
- The commit containing this diff MUST end with the trailer line `Refs: PD-6`.
