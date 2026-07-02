# Next Autopilot Plan

Use this plan for the first post-v0.1.0 real-agent autopilot development run.

## Post-v0.1.0 Development

- [x] Add a docs-only quick-start example as the first bounded slice of the `docs/BACKLOG.md` P2 quick-start examples item.
- [x] Add a Python quick-start example as the next bounded slice of the `docs/BACKLOG.md` P2 quick-start examples item.
- [x] Add a Node quick-start example as the final bounded slice of the `docs/BACKLOG.md` P2 quick-start examples item.
- [x] Add opt-in `ai-orch start --worktree PATH` isolation for task runs by reusing the existing autopilot worktree validation behavior.
- [x] Record ADR-0004 for the autopilot queue and batch execution model covering persisted plan queues, loop mode, worktree isolation, approvals/blockers, and per-run reports.
- [x] Add the first persisted autopilot queue model slice: SQLite schema, StateStore helpers, and tests for recording and listing plan items without batch execution.
- [x] Add `ai-orch autopilot queue sync/list` commands that load Markdown plan items into the persisted queue without duplicates and display queue status without running batch execution.
- [x] Add `ai-orch autopilot queue run-next` as the first guarded loop slice: select the next persisted queue item, dry-run by default, execute at most one item, update queue status, and stop on the supervisor result.
- [x] Add per-run Markdown report generation for `ai-orch autopilot queue run-next --execute` using the existing task report renderer and print the report path.
- [x] Add `ai-orch autopilot queue status` to summarize persisted queue counts and recent started/done/blocked/skipped items without starting batch execution.
- [x] Add `ai-orch autopilot queue run-batch` as a guarded serial loop that dry-runs by default, executes up to a configurable max item count, stops on approvals/blockers/failures, and writes a report for each executed queue item.
- [x] Record the first guarded `ai-orch autopilot queue run-batch --execute --max-items 1` real-agent smoke result in `docs/AUTOPILOT_BATCH_RUN_LOG.md`.
- [x] Show generated task report paths in `ai-orch autopilot queue list/status` for queue items with completed reports.
- [x] Record ADR-0005 for optional per-task worktree rotation in autopilot batch runs, covering the CLI contract, safety guardrails, stop conditions, and deferred automation.
