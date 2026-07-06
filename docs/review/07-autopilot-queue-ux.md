# Autopilot Queue UX Review

Date: 2026-07-06

## Scope

This review covers `ai-orch autopilot queue` operator workflows after the JSON
output hardening pass through the manual mutation commands.

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

Machine-readable output exists for the most important read, recovery, execution,
and manual mutation paths:

- `queue readiness --json`
- `queue preflight --json`
- `queue reconcile --json`
- `queue recover-in-progress --json`
- `queue refresh-created-refs --json`
- `queue show --json`
- `queue run-batch --summary-json PATH`
- `queue requeue --json`
- `queue skip --json`

The manual state-change pair is now covered as opt-in JSON while preserving the
operator text output by default. Both commands remain guarded,
dry-run-by-default, support `--apply`, and share the same plan ownership
validation pattern as `queue show`.

## Completed order

1. Added `--json` to `queue requeue` dry-run and `--apply`.
2. Added `--json` to `queue skip` dry-run and `--apply`.
3. Updated runbook/changelog coverage for matching text and JSON behavior.

This order kept the risk small: `requeue` was narrower because it only accepts
`blocked` items and clears known metadata when applied. `skip` was slightly
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

## Final snapshot

No additional backlog item is needed for this review. The queue mutation JSON
consistency pass is complete, and follow-up work should start from a fresh
operator need rather than extending this review by default.
