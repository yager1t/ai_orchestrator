# v0.5 GOAL Plan: Typed Action Broker + Policy Tiers

## Goal

Make every external effect in `ai-orch` pass through one typed, durable, and
policy-aware action boundary before execution.

The release should preserve the existing CLI behavior while making shell, git,
file, verification, memory, and future network actions inspectable through a
single action journal.

## Implementation Status

First implementation pass is complete in the working tree:

- typed action envelope dataclasses are exported from `ai_orchestrator.tools`;
- broker-created action records include request, decision, result, provenance,
  approval, and redacted output-preview metadata;
- dangerous and secret-sensitive action classifications are hard-denied before
  executor invocation;
- verification, tool broker retries, file/memory/process tool retries, and
  legacy approval retries are represented in the action broker journal;
- completed broker actions are replay-safe by idempotency key and do not rerun
  their executor;
- JSON trace exports include normalized `action_journal` entries;
- Markdown reports render requested action, risk, decision, outcome, preview,
  and provenance;
- recovery detects expired leases and stale started actions without active
  leases.

## Scope

- Build on the existing `ToolCall`, `ToolResult`, `ToolBroker`, `PolicyEngine`,
  approval requests, and `action_records` table.
- Keep the supervisor loop, verification runner, and adapters intact unless a
  small routing change is required to remove a direct external-effect bypass.
- Prefer typed dataclasses and JSON-serializable payloads over broad schema
  rewrites.
- Do not add production dependencies.
- Do not add a new multi-agent framework abstraction.
- Do not change public CLI flags unless a command only exposes existing
  journal/report data more clearly.

## P0 Work

### 1. Typed Action Envelope

Introduce typed records for:

- `ActionRequest`
- `ActionResult`
- `ActionRisk`
- `ActionDecision`
- `ActionProvenance`

Classify brokered actions as:

- `read`
- `write`
- `shell`
- `git`
- `network`
- `verification`
- `dangerous`
- `secret_sensitive`

Exit criteria:

- Existing `ToolCall` and `ToolResult` can produce the typed action envelope.
- Existing broker payloads remain backward-compatible.
- Tests cover classification, serialization, and validation.

### 2. Durable Action Journal Enrichment

Extend stored action payloads/results so each record can reconstruct:

- original typed request;
- policy decision;
- approval reference when present;
- execution result summary;
- redacted stdout/stderr preview where command output exists;
- provenance: task, iteration, broker/tool source, idempotency key.

Exit criteria:

- `action_records` continues to load older rows.
- New broker-created records contain action envelope metadata.
- Denied and approval-required actions are visible without executing.

### 3. Policy Tier Integration

Make the broker the canonical policy boundary for typed actions:

- `allow`;
- `ask`;
- `deny`;
- approval-required risk tiers;
- approved retry;
- deny-overrides-approval.

Exit criteria:

- Dangerous or secret-sensitive actions are blocked before executor invocation.
- Approval cannot override `deny`.
- Tests cover allowed, denied, approval-required, and approved retry actions.

### 4. Route External Effects

Audit direct external-effect paths and route small, high-value paths through the
broker:

- verification commands;
- CLI helper process actions;
- file read/write helpers;
- git/shell retry paths already represented as approval requests.

Exit criteria:

- No duplicated action records for a single completed brokered action.
- Backward-compatible CLI output.
- Existing supervisor and verification tests remain green.

## P1 Work

### 5. Reporting and Trace Export

Improve trace exports and markdown reports with:

- requested action;
- action category and risk;
- policy decision;
- approval needed/used/denied;
- execution outcome;
- redacted output preview;
- provenance and idempotency key.

Exit criteria:

- Reports explain why a command was allowed, denied, requested approval, or
  executed after approval.
- JSON export can reconstruct the action journal in chronological order.

### 6. Recovery and Replay Safety

Use typed action metadata to make interrupted action state explicit:

- stale started action detection;
- safe replay rules by idempotency key;
- inspection of interrupted brokered actions.

Exit criteria:

- Recovery reports a clear state instead of silently duplicating started work.
- Tests cover at least one stateful replay path.

### 7. Documentation and Release Gate

Update user-facing docs only where behavior is visible:

- action broker description;
- policy/approval examples;
- reporting/export notes;
- changelog for v0.5.

Exit criteria:

- `release-check` covers v0.5 docs when release prep begins.
- Required checks pass before tagging.

## First Bounded Slice

Implement P0.1 and the metadata part of P0.2:

- add typed action dataclasses and classification helpers;
- export them from `ai_orchestrator.tools`;
- enrich broker-created `action_records` with `action_request`,
  `action_decision`, and `action_result` metadata while preserving old keys;
- add tests for classification, serialization, and broker journal enrichment.

## Required Checks

```bash
python -m pytest
python -m compileall ai_orchestrator
ruff check .
mypy ai_orchestrator
python -m ai_orchestrator.cli.app release-check
git diff --check
```

If any check fails, switch to REPAIR mode and apply the smallest targeted fix.
