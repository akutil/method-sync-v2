#!/usr/bin/env node
// Summarize .agent-log/actions.jsonl (written by the Claude Code hooks) per tool:
//   proposed  = PreToolUse lines ("the agent asked to do X")
//   executed  = PostToolUse + PostToolUseFailure lines ("X actually ran")
//   blocked   = proposed lines with no matching executed line (same id) — denied by a hook, a rule or the human
//   failed    = executed lines with a non-zero exit
// Usage: pnpm agent:log            (or: node scripts/agent-log-summary.mjs [path/to/actions.jsonl])
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const file = process.argv[2] ?? join(process.cwd(), ".agent-log", "actions.jsonl");
if (!existsSync(file)) {
  console.error(`No log at ${file}. Are the hooks in .claude/settings.json active? Run one Edit and check again.`);
  process.exit(2);
}
const lines = readFileSync(file, "utf8")
  .split(/\r?\n/)
  .filter(Boolean)
  .flatMap((l) => {
    try {
      return [JSON.parse(l)];
    } catch {
      return [];
    }
  });

const executedIds = new Set(lines.filter((e) => e.event !== "PreToolUse" && e.id).map((e) => e.id));
const byTool = {};
const blocked = [];
const failed = [];
for (const e of lines) {
  const s = (byTool[e.tool] ??= { proposed: 0, executed: 0, blocked: 0, failed: 0, ms: 0, files: new Set() });
  if (e.event === "PreToolUse") {
    s.proposed++;
    if (e.id && !executedIds.has(e.id)) {
      s.blocked++;
      blocked.push(e);
    }
  } else {
    s.executed++;
    s.ms += e.ms ?? 0;
    if (e.exit !== 0) {
      s.failed++;
      failed.push(e);
    }
  }
  if (e.path) s.files.add(e.path);
}
const rows = Object.entries(byTool)
  .sort((a, b) => b[1].proposed + b[1].executed - (a[1].proposed + a[1].executed))
  .map(([tool, s]) => ({ tool, proposed: s.proposed, executed: s.executed, blocked: s.blocked, failed: s.failed, "time (s)": +(s.ms / 1000).toFixed(1), files: s.files.size }));

const sessions = new Set(lines.map((e) => e.session).filter(Boolean));
const executedTotal = lines.filter((e) => e.event !== "PreToolUse").length;
console.log(
  `Agent actions: ${executedTotal} executed, ${blocked.length} proposed but not executed, ${failed.length} failed — ${sessions.size} session(s), ${lines[0]?.ts ?? "-"} .. ${lines.at(-1)?.ts ?? "-"}`,
);
console.table(rows);
if (blocked.length) {
  console.log("Proposed but not executed (blocked by a hook, a rule or you):");
  for (const b of blocked) console.log(`  ${b.ts}  ${b.tool}  ${b.cmd ?? b.path ?? b.pattern ?? ""}`);
}
if (failed.length) {
  console.log("Failed:");
  for (const f of failed) console.log(`  ${f.ts}  ${f.tool}  exit=${f.exit}  ${f.cmd ?? f.path ?? ""}`);
}
