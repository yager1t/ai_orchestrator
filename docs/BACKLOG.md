# Backlog

This backlog tracks future work after the current local MVP hardening pass.
Completed MVP items are kept in project history, review notes, and the changelog.

## P0

No open P0 items.

## P1

No open P1 items.

## P2

- Monitor real local operator client usage and collect candidates for a v1.0.1
  stabilization release.
- Prepare a MCP/ACP runtime proposal spike only after the evidence listed in
  `docs/MCP_ACP_RESEARCH.md` can be answered in implementation-ready terms.
- Improve Codebase Memory preflight into a more automatic context layer without
  making memory output authoritative for completion.
- Design read-only queue client methods only if external integrations need a
  stable Python API beyond the documented CLI JSON queue surface.

## P3 / Deferred

- Replace the minimal YAML parser with PyYAML only if broader YAML
  compatibility is needed; see ADR-0002 in `docs/DECISIONS.md`.
- Add deeper provider-specific adapter contract tests when provider behavior
  diverges from the shared adapter contract.
- Expand TUI beyond read-only views when interactive workflows are needed; see
  the expansion gate in `docs/ARCHITECTURE.md`.
- Defer MCP server mode, web dashboard, parallel agent swarm, and auto-merge
  until the trusted approval, audit, and isolation foundations are in place.

## Documentation Cleanup

- Keep internal review findings and local scratch notes out of public git; see
  `docs/PUBLICATION_POLICY.md`.
