# Backlog

This backlog tracks future work after the current local MVP hardening pass.
Completed MVP items are kept in project history, review notes, and the changelog.

## P0

No open P0 items.

## P1

- Complete the remaining trusted approval inbox pieces described in ADR-0003:
  Codebase Memory approval integration and stale approval handling.
- Harden the guarded autopilot path so it can execute real configured agents
  unattended after approval and dirty-worktree safeguards are satisfied.
- Prepare the release and install path described in
  `docs/POST_MVP_ROADMAP.md`.

## P2

- Add quick-start examples for Python, Node, and docs-only repositories.
- Add opt-in git worktree isolation for task runs.
- Add structured adapter output fields for reports and future agent fallback
  scoring.
- Add basic local metrics for iterations, verification pass rate, approvals,
  and adapter failures.

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
