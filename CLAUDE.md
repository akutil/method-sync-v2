@AGENTS.md

## Claude Code

- Оркестрація — скіл `project-factory` (плагін). Рецензія слайсу — workflow `review-gate`;
  process-auditor — лише звичайним субагентом, не Workflow.
- Рецензент правок у цільовій бібліотеці — субагент `.claude/agents/method-sync-reviewer.md`,
  read-only; викликає його не та сесія, що писала правку.
- Журнал дій агента пише хук `.claude/hooks/log-action.mjs` у `.agent-log/actions.jsonl`;
  зведення — `npm run agent:log`.
