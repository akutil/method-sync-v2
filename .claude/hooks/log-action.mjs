#!/usr/bin/env node
// Claude Code hook for PreToolUse, PostToolUse and PostToolUseFailure.
// Appends ONE JSON line per event to .agent-log/actions.jsonl:
//   PreToolUse         -> { ts, event, id, session, mode, tool, path | cmd | pattern | url }   = "agent proposed"
//   PostToolUse        -> { ..., exit: 0, ms }                                                  = "agent did"
//   PostToolUseFailure -> { ..., exit: N | "error" | "interrupted", ms }                        = "agent tried, it failed"
// A PreToolUse line without a matching Post line (same id) = proposed but never executed (blocked or denied).
// The hook never blocks the agent: any error -> exit 0 silently.
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

let raw = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) raw += chunk;

let ev = {};
try {
  ev = JSON.parse(raw || "{}");
} catch {
  process.exit(0);
}

const root = process.env.CLAUDE_PROJECT_DIR || ev.cwd || process.cwd();
const event = ev.hook_event_name ?? "unknown";
const ti = ev.tool_input ?? {};
const tool = ev.tool_name ?? "unknown";

// Normalize Windows (`D:\x`), POSIX (`/d/x`, Git Bash) and mixed paths so the log stores repo-relative paths.
const norm = (p) =>
  String(p)
    .replace(/\\/g, "/")
    .replace(/^\/([a-zA-Z])\//, (_, d) => `${d.toUpperCase()}:/`)
    .replace(/^([a-zA-Z]):\//, (_, d) => `${d.toUpperCase()}:/`)
    .replace(/\/$/, "");
const roots = [root, ev.cwd].filter(Boolean).map((r) => norm(r) + "/");
const rel = (p) => {
  if (typeof p !== "string") return undefined;
  const n = norm(p);
  const hit = roots.find((r) => n.startsWith(r));
  return hit ? n.slice(hit.length) : n;
};

const entry = {
  ts: new Date().toISOString(),
  event,
  id: ev.tool_use_id,
  session: String(ev.session_id ?? "").slice(0, 8),
  mode: ev.permission_mode,
  tool,
  ...(ti.file_path ? { path: rel(ti.file_path) } : {}),
  ...(ti.notebook_path ? { path: rel(ti.notebook_path) } : {}),
  ...(ti.command ? { cmd: String(ti.command).slice(0, 200) } : {}),
  ...(ti.pattern ? { pattern: ti.pattern } : {}),
  ...(ti.url ? { url: ti.url } : {}),
};

if (event === "PostToolUse") {
  entry.exit = 0;
} else if (event === "PostToolUseFailure") {
  const m = /^Exit code (\d+)/.exec(ev.error ?? "");
  entry.exit = m ? Number(m[1]) : ev.is_interrupt ? "interrupted" : "error";
}
if (typeof ev.duration_ms === "number") entry.ms = ev.duration_ms;

try {
  const dir = join(root, ".agent-log");
  mkdirSync(dir, { recursive: true });
  appendFileSync(join(dir, "actions.jsonl"), JSON.stringify(entry) + "\n");
} catch {
  /* logging must never fail the session */
}
process.exit(0);
