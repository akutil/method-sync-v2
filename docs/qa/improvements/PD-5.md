# Improvement Proposal: improve-PD-5

- **Defect:** PD-5 (`docs/qa/process-defects.json`): `factory-lock.json` is outside its own protection. Drift is measured against whatever the lock currently says (`check-factory-integrity.mjs:209`), and `--init-lock` only WARNs "not routine" before printing `Result: PASS` (lines 180, 185). One commit can weaken a gate script, reseal, and verify clean with no `Refs: PD-<n>`. Every other PD protection rests on this lock.
- **Class / severity:** check-too-weak / P1
- **Status:** landed (approved by the owner at checkpoint 2, 2026-09-30)

## Scope

Changes: verify mode walks `git log -- factory-lock.json`. Every commit that touched the lock, except the oldest one (the post-adaptation G0 lock), must contain `Refs: PD-<n>`, otherwise hard FAIL. A shallow clone or unavailable history gives a visible WARN, never a silent pass.

Does NOT change: `--init-lock` itself, tiers, hash logic, or `hasApprovedPdCommit`.

Known limitation: GitHub `actions/checkout` defaults to `fetch-depth: 1`, so CI will print the shallow-clone WARN until `ci.yml` checks out with `fetch-depth: 0`. That is a separate gate-config change, not included. The existing `hasApprovedPdCommit` already depends on the same history.

## Target file

`scripts/check-factory-integrity.mjs`

## Exact diff

```diff
--- a/scripts/check-factory-integrity.mjs
+++ b/scripts/check-factory-integrity.mjs
@@ -250,4 +250,26 @@
   }
 }
+
+// PD-5: the lock is the trust root, but factory-lock.json itself was never checked. A commit that
+// edits a gate script AND reseals with --init-lock verified clean without any "Refs: PD-<n>".
+// Every commit touching the lock after the first one (the post-adaptation G0 lock) must carry one.
+if (lock) {
+  if (git(["rev-parse", "--is-shallow-repository"]) === "true") {
+    warn("lock", "shallow clone: factory-lock.json reseal provenance cannot be verified (check out with fetch-depth: 0).");
+  } else {
+    const hist = git(["log", "--format=%H%x1f%B%x1e", "--", LOCK_PATH]);
+    if (hist === null) {
+      warn("lock", "git history unavailable: factory-lock.json reseal provenance cannot be verified.");
+    } else {
+      const commits = hist.split("\u001e").map((c) => c.trim()).filter(Boolean);
+      for (const c of commits.slice(0, -1)) {
+        const [sha, body = ""] = c.split("\u001f");
+        if (!/Refs:\s*PD-\d+/i.test(body)) {
+          fail("lock", `factory-lock.json was resealed in ${sha.slice(0, 7)} without a "Refs: PD-<n>" trailer; a reseal launders every gate-script drift it absorbs. Revert that reseal or re-land it inside an approved improvement.`);
+        }
+      }
+    }
+  }
+}
 
 // Echo-stub scan over the npm scripts the qa battery actually names.
```

## Expected metric movement

- **Metric:** unverified reseals of `factory-lock.json`.
- **Current:** not measured. Any reseal passes.
- **Expected after fix:** every reseal after the G0 lock carries `Refs: PD-<n>`, otherwise FAIL. The real repo should show exactly 1 commit touching the lock (see the last proof step). If it shows more, the owner decides before approval whether those early commits are exempt.
- **Verified by:** the next retro. No movement means auto-flag for revert.

## EXECUTED red→green proof

**EXECUTED 2026-09-30 by the orchestrator** (output below). The auditor has no shell. Run inside the repo before approval and paste the output. Fixtures are throwaway git repos in `mktemp -d` with hooks disabled.

```bash
bash <<'PROOF'
REPO=$(git rev-parse --show-toplevel); T=$(mktemp -d)
awk '/^```diff$/{f=1;next} /^```$/{f=0} f' "$REPO/openspec/changes/improve-PD-5/proposal.md" > "$T/pd.patch"
g() { git -c user.name=pd -c user.email=pd@example.invalid -c core.hooksPath=/dev/null "$@"; }
fx() { # $1 dir, $2 patched yes/no, $3 message of the reseal commit
  mkdir -p "$1/scripts"; cp "$REPO/scripts/check-factory-integrity.mjs" "$1/scripts/"
  ( cd "$1" || exit 9
    if [ "$2" = yes ]; then patch -s -p1 < "$T/pd.patch" || exit 9; fi
    printf 'export const v = 1;\n' > scripts/check-x.mjs
    g init -q; node scripts/check-factory-integrity.mjs --init-lock >/dev/null 2>&1
    g add -A; g commit -qm "chore: G0 lock"
    printf 'export const v = 2; // weakened\n' > scripts/check-x.mjs
    node scripts/check-factory-integrity.mjs --init-lock >/dev/null 2>&1
    g add -A; g commit -qm "$3"
    node scripts/check-factory-integrity.mjs >/dev/null 2>&1; echo $? )
}
echo "BEFORE: weakened gate + silent reseal -> exit $(fx "$T/b" no 'chore: tweak')   (defect: 0)"
R=$(fx "$T/r" yes 'chore: tweak'); echo "AFTER:  weakened gate + silent reseal -> exit $R"
G=$(fx "$T/g" yes "$(printf 'fix: approved\n\nRefs: PD-9')"); echo "AFTER:  reseal with Refs: PD-9 -> exit $G"
(cd "$T/r" && node scripts/check-factory-integrity.mjs 2>&1 | grep -E '^FAIL')
echo "Real repo, commits touching factory-lock.json (expect exactly 1, the G0 lock d876f4c):"
git -C "$REPO" log --format='  %h %s' -- factory-lock.json
if [ "$R" = 1 ] && [ "$G" = 0 ]; then echo "PROOF OK"; else echo "PROOF FAILED"; exit 1; fi
PROOF
```

Expected: BEFORE `exit 0`, silent reseal `exit 1`, approved reseal `exit 0`, a `FAIL [lock] factory-lock.json was resealed in <sha> …` line, one real-repo commit, and `PROOF OK`.

```text
# executed by the orchestrator 2026-09-30 from the repo root: bash <the block above>; exit 0
BEFORE: weakened gate + silent reseal -> exit 0   (defect: 0)
AFTER:  weakened gate + silent reseal -> exit 1
AFTER:  reseal with Refs: PD-9 -> exit 0
FAIL  [lock] factory-lock.json was resealed in 0ac37c4 without a "Refs: PD-<n>" trailer; a reseal launders every gate-script drift it absorbs. Revert that reseal or re-land it inside an approved improvement.
Real repo, commits touching factory-lock.json (expect exactly 1, the G0 lock d876f4c):
  d876f4c chore(factory): lock the gate-bearing files after adaptation (G0)
PROOF OK
```

## Rollback (one revert)

- **Single commit:** yes. `git revert <sha>`.
- **State to clean up on revert:** none.
- **Ladder position:** hard (a new rule inside an existing hard check). If the owner prefers the ladder, change `fail(` to `warn(` for two truthful runs before promoting. That would be a different diff and a different approval.
- **Independence:** improve-PD-4 edits lines 100-102 of the same file. Either order applies cleanly.

## Approval & trailer convention

- Human approver: Andrii Kutil (owner), checkpoint 2 in the Claude Code session · Date: 2026-09-30
- The commit containing this diff MUST end with the trailer line `Refs: PD-5`.
