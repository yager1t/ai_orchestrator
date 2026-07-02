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
