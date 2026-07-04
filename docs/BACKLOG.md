# Backlog

This backlog tracks future work after the current local MVP hardening pass.
Completed MVP items are kept in project history, review notes, and the changelog.

## P0

No open P0 items.

## P1

No open P1 items.

## P2

- Add a read-only cleanup candidate report to
  `ai-orch autopilot worktree-overview` that labels shown worktrees as
  candidate, needs_review, or do_not_remove for operator review, without
  deleting or pruning anything.

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
