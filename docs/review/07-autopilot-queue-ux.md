# Autopilot Queue UX Review

Date: 2026-07-06

## Scope

This review covers `ai-orch autopilot queue` operator workflows after the JSON
output hardening pass through `queue show --json`.

## Current operator model

The queue CLI has settled into four command groups:

- Intake: `sync`, `sync-backlog`, `refresh-created-refs`
- Read-only inspection: `list`, `status`, `readiness`, `preflight`, `show`
- Recovery and reconciliation: `reconcile`, `recover-in-progress`
- Execution and manual state changes: `run-next`, `run-batch`, `requeue`, `skip`

The safe daily loop is now coherent:

1. Seed exactly one bounded backlog item when P0/P1/P2 is empty.
2. Sync backlog into the queue.
3. Inspect readiness and the selected queue item.
4. Run a dry-run batch with an explicit item id.
5. Execute in a clean worktree.
6. Review report and diff before PR/CI/merge.
7. Sync backlog again after the completed bullet is removed.

## JSON coverage

Machine-readable output already exists for the most important read/recovery
paths:

- `queue readiness --json`
- `queue preflight --json`
- `queue reconcile --json`
- `queue recover-in-progress --json`
- `queue refresh-created-refs --json`
- `queue show --json`
- `queue run-batch --summary-json PATH`

The remaining operator-facing consistency gap is the manual state-change pair:

- `queue requeue`
- `queue skip`

Both commands are guarded, dry-run-by-default, and support `--apply`. Both also
share the same plan ownership validation pattern as `queue show`. Scripts can
currently use them, but must parse text to confirm selected item refs, dry-run
versus apply mode, resulting status, and preserved or cleared metadata.

## Recommended order

1. Add `--json` to `queue requeue` dry-run and `--apply`.
2. Add `--json` to `queue skip` dry-run and `--apply`.
3. Do a final runbook/changelog consistency cleanup after the mutation commands
   have matching text and JSON behavior.

This order keeps the risk small: `requeue` is narrower because it only accepts
`blocked` items and clears known metadata when applied. `skip` is slightly
broader because it accepts both `created` and `blocked` items and requires an
operator reason.

## Constraints

- Keep JSON output opt-in.
- Preserve existing text output by default.
- Preserve dry-run-by-default behavior.
- Preserve plan ownership validation.
- Preserve exit-code semantics.
- Do not add automatic execution, deletion, pruning, pushing, or cleanup.
- Keep each backlog item small enough for one autopilot run and one review pass.

## Next backlog item

Seed `queue requeue --json` first. After it merges and the queue is synced,
run it through the existing autopilot batch flow.
