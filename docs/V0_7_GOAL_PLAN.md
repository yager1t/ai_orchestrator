# v0.7 Goal Plan: Worktree + Sandbox Isolation

Date: 2026-07-12
Status: completed for v0.7.0 release on 2026-07-13
Baseline: v0.6.0 PlanGraph v1 released and published

## Progress

- Completed first bounded slice: policy-level `SandboxProfile`,
  `WorktreeExecutionProfile`, `PathScopePolicy`, and file-tool path enforcement.
- Completed second bounded slice: autopilot worktree execution profile capture as
  durable task events, with Markdown report provenance lines.
- Completed third bounded slice: top-level read-only `worktree status`,
  `worktree inspect`, and dry-run `worktree cleanup` CLI surface.
- Completed fourth bounded slice: config-level `sandbox.writable_paths` and
  `sandbox.forbidden_paths` applied to brokered file-tool retries.
- Completed fifth bounded slice: denied sandbox decisions are recorded as
  durable `sandbox.decision` task events with action/result provenance.
- Completed sixth bounded slice: read-only worktree recovery recommendations
  are surfaced in overview JSON and table output.
- Completed seventh bounded slice: `recover` detects stale running
  worktree-backed executions and can mark durable recovery recommendations.
- Completed eighth bounded slice: stale worktree recovery candidates are linked
  back to queue items and PlanGraph nodes with operator recommendations.
- Completed ninth bounded slice: stale worktree recovery candidates include an
  explicit dry-run action plan with advisory commands; broad recovery actions
  remain manual when a task-specific apply path is not implemented.
- Completed tenth bounded slice: `recover --apply-recommendation requeue` can
  dry-run or explicitly apply the safe queue requeue recovery path.

## Positioning

v0.7 continues the AI Engineering Supervisor direction. The goal is not to add
another multi-agent execution framework. The goal is to make supervised agent
execution safer, more auditable, and easier to recover by isolating where work
happens and what paths runtime actions may touch.

The v0.7 control question is:

> Did this agent run inside the intended worktree and sandbox scope, and can the
> supervisor explain, verify, recover, or clean up the resulting state?

## Current Inventory

- Supervisor/autopilot already supports an opt-in `--worktree` execution repo.
- Worktree validation blocks using the main repo as an isolated worktree and
  verifies that the candidate is a linked git worktree.
- Autopilot worktree overview provides read-only status, branch, dirty state,
  merge state, linked/unlinked state, and cleanup status.
- PlanGraph queue items can store `selected_worktree_path`, and Markdown reports
  show queue worktree provenance when it exists.
- PolicyEngine already gates dangerous shell patterns, secret auth paths, package
  installs, and `git push`.
- ToolBroker provides typed action policy, approval, idempotency, and action
  journal records.
- ProcessRunner centralizes subprocess execution with timeout, cancellation, and
  progress metadata.
- File tools already constrain paths to the repository root, but do not yet have
  a reusable sandbox profile, configured writable scopes, or default secret path
  denial for all local file actions.

## P0 Scope

1. Formalize local sandbox profile and path scope decisions.
   - Represent execution root, optional worktree provenance, writable paths, and
     forbidden/secret-like paths.
   - Default to a backward-compatible repository-root writable scope.
   - Deny secret-like paths by default.

2. Route local file tool read/write path checks through the sandbox profile.
   - Keep existing repository-root behavior for current callers.
   - Return policy-denied results for sandbox/path-scope violations.
   - Cover read denial, write denial, and allowed write tests.

3. Connect worktree execution provenance to supervisor/autopilot reporting.
   - Preserve `selected_worktree_path`.
   - Add room for branch/base-ref/dirty/cleanup metadata without requiring a DB
     migration in the first slice.

4. Add worktree execution profile capture for queued/autopilot runs.
   - Track worktree path, branch, base ref when available, task id, dirty state,
     and cleanup eligibility.
   - Keep capture read-only and failure-tolerant.

5. Add CLI inspection surface for sandbox/worktree status.
   - Start from read-only inspection.
   - Cleanup must show candidates before any removal.
   - Destructive cleanup remains out of automatic execution unless explicitly
     approved later.

6. Update reports and trace payloads with sandbox/worktree provenance.
   - Include execution root/worktree path and branch when available.
   - Include denied sandbox decisions in action records.

7. Add release-check coverage for the fast v0.7 safety path.
   - Path-scope enforcement tests.
   - Worktree provenance/reporting tests.

## P1 Scope

- Config-level readable path scopes under `.ai-orch/config.yaml`.
- Richer read scopes, including explicit allowlists for generated artifacts.
- Worktree cleanup command with dry-run by default and explicit execution gate.
- Allow/success sandbox decision events in the durable task timeline, if needed
  after denial audit proves useful.
- Recovery helpers for additional queue/PlanGraph recommendations beyond the
  first explicit `requeue` path.
- Batch/autopilot rotation integration that records sandbox profile metadata per
  PlanGraph node or queue item.

## Out Of Scope

- Container, VM, or OS-level sandboxing.
- Automatic deletion of worktrees.
- Automatic merge or git push.
- Parallel agent execution.
- New production dependencies.
- Broad CLI rewrites or a new multi-agent framework abstraction.

## Recovery And Audit Consequences

- Every worktree-backed execution must be attributable to task id, plan item or
  PlanGraph node, branch, base ref when known, execution root, and dirty state.
- Sandbox denials should be recorded as policy outcomes, not silent file-tool
  failures. Denied file-tool sandbox decisions are now emitted as durable
  `sandbox.decision` task events.
- Recovery must distinguish between:
  - clean and cleanup-eligible worktrees;
  - dirty worktrees requiring review;
  - in-progress or stale executions;
  - unlinked or invalid worktree directories.
- Cleanup candidates must be visible before removal. Removal is a later explicit
  action and should pass through policy/approval.

## Migration Strategy

- Default behavior remains compatible: current CLI flows execute in the repo root
  unless the user opts into worktree execution.
- The first sandbox profile defaults to the current repository root as the only
  writable scope, so existing file-tool callers do not need new config.
- Secret-like paths are denied by default for file tools, which is intentionally
  stricter and aligned with existing security policy.
- Writable scopes and forbidden path markers are now configurable under
  `.ai-orch/config.yaml`; omitted config keeps the repository-root writable
  default for existing workflows.

## Testable P0 Tasks

- Unit: sandbox profile allows writes inside the default root.
- Unit: sandbox profile denies writes outside configured writable paths.
- Unit: sandbox profile denies secret-like reads and writes.
- Tool executor: `fs.read` returns `policy_denied` for `.env`.
- Tool executor: `fs.write` returns `policy_denied` outside configured writable
  paths and does not create the file.
- CLI/reporting: worktree provenance remains visible for queued/autopilot runs.
- Release gate: full test suite, compileall, ruff, mypy, release-check, and
  `git diff --check`.

## First Bounded Slice

Implement a policy-level sandbox/path-scope foundation:

- add `SandboxProfile`, `WorktreeExecutionProfile`, and `PathScopePolicy`;
- route file tool path checks through that policy;
- add focused negative tests for secret reads and writes outside writable scope;
- document the v0.7 plan in this file.
