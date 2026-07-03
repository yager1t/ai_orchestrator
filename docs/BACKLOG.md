# Backlog

This backlog tracks future work after the current local MVP hardening pass.
Completed MVP items are kept in project history, review notes, and the changelog.

## P0

No open P0 items.

## P1

No open P1 items.

## P2

- Add a read-only `--merged-only` filter to
  `ai-orch autopilot worktree-overview` so operators can focus cleanup review
  on worktree branches that strict-ancestry reports as merged into review repo
  HEAD, without deleting or pruning anything.

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
