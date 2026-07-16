# v0.8 MCP/ACP Design Spike

Date: 2026-07-16
Status: design spike, not a release-blocking server implementation

## Goal

Prepare a future local MCP/ACP adapter around the v0.8 CLI control surface
without introducing a server runtime in v0.8.

The adapter must preserve the product rule:

```text
AI agents execute; the supervisor decides done.
```

## Proposed Operations

### start_task

Purpose: start one bounded supervised task.

Inputs:

- `task`: task text.
- `repo`: repository path.
- `role`: optional product-command role.
- `worktree`: optional existing linked worktree.
- `use_memory`: optional read-only memory preflight.

Output:

- `task_id`
- `status`
- `repo_path`
- `report_path`
- `trace_command`

Notes:

- Does not mark work done.
- Uses the existing supervisor loop and verification policy.
- Does not push, publish, deploy, merge, or delete worktrees.

### get_status

Purpose: return the current task state.

CLI backing:

```bash
ai-orch status <task-id> --repo <repo> --json
```

Stable fields:

- envelope: `schema_version`, `command`, `generated_at`, `ok`, `error`
- `task`
- `iteration_count`
- `iterations[].verification_runs`

### list_approvals

Purpose: show operator actions waiting for approval.

CLI backing:

```bash
ai-orch approvals list --repo <repo> --json
```

Stable fields:

- envelope fields
- `status_filter`
- `task_id`
- `count`
- `approvals[]`

### approve_action

Purpose: approve or reject an existing approval request.

CLI backing:

```bash
ai-orch approvals approve <approval-id> --repo <repo> --resolution "..." --json
ai-orch approvals reject <approval-id> --repo <repo> --resolution "..." --json
```

Stable fields:

- envelope fields
- `approval`
- `resolution`

Security rule:

- Approval does not override deny rules. A later retry may still return
  `policy_denied`.

### retry_approval

Purpose: retry an approved action through the policy and tool broker path.

CLI backing:

```bash
ai-orch approvals retry <approval-id> --repo <repo> --json
```

Stable fields:

- envelope fields
- `approval_id`
- `task_id`
- `retry_status`
- `exit_code`
- `retry_count`
- `last_retry_status`
- `last_retry_exit_code`
- `retry_error`
- `stdout`
- `stderr`

Security rule:

- `retry_status=policy_denied` is a failed operation and must remain non-zero.

### export_trace

Purpose: export an auditable task trace.

CLI backing:

```bash
ai-orch export <task-id> --repo <repo> --redact
```

Stable fields:

- `metadata`
- `task`
- `timeline`
- `task_events`
- `action_records`
- `action_journal`
- `replan_decisions`
- `plan_graph`
- `memory_lessons`
- `reflection_records`
- `memory_influence`
- `iterations`
- `verification_runs`
- `approvals`

## Error Shape

New stable JSON outputs should use:

```json
{
  "schema_version": "1.0",
  "command": "string",
  "generated_at": "ISO-8601 timestamp",
  "ok": false,
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

## Non-Goals For v0.8

- No long-running MCP server.
- No cloud multi-user deployment.
- No parallel worker execution.
- No autonomous push, merge, publish, deploy, or worktree deletion.
- No completion authority outside the supervisor.

## Existing P1 Coverage

- `start --use-memory` already supports read-only memory preflight hints, and
  tests cover non-authoritative memory context.
- `autopilot queue run-batch --summary-json PATH` and
  `autopilot loop --summary-json PATH` already write machine-readable batch
  artifacts.
- Local metrics already summarize tasks, iterations, verification pass rate,
  approvals, policy denials, sandbox denials, and adapter failures.
- Shared adapter contract tests already cover runner-backed adapters, policy
  enforcement, session behavior, and mock adapter behavior.
