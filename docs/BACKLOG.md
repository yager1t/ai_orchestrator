# Backlog

This backlog tracks future work after the current local MVP hardening pass.
Completed MVP items are kept in project history, review notes, and the changelog.

## P0

No open P0 items.

## P1

- Add an opt-in batch or loop mode that selects the next queued item and stops
  on `done`, `blocked`, approval requirements, verification failure, or dirty
  execution state.
- Add per-run report generation for autopilot queue items.

## P2

- Add per-task worktree orchestration or strict serialized execution for
  multi-item autopilot batches.
- Add queue status and history views for started, done, blocked, and skipped
  autopilot items.

## P3 / Deferred

- Replace the minimal YAML parser with PyYAML only if broader YAML
  compatibility is needed; see ADR-0002 in `docs/DECISIONS.md`.
- Add deeper provider-specific adapter contract tests when provider behavior
  diverges from the shared adapter contract.
- Expand TUI beyond read-only views when interactive workflows are needed; see
  the expansion gate in `docs/ARCHITECTURE.md`.
- Continue MCP/ACP research spikes before adding runtime support; see the
  runtime proposal gate in `docs/MCP_ACP_RESEARCH.md`.
- Evaluate deeper supervisor planning integration after `start --use-memory`
  usage proves useful; see the planning criteria in
  `docs/CODEBASE_MEMORY_RESEARCH.md`.
- Defer MCP server mode, web dashboard, parallel agent swarm, and auto-merge
  until the trusted approval, audit, and isolation foundations are in place.

## Documentation Cleanup

- Keep review findings in `docs/review/` and local scratch notes out of git.
