# v1.0 Goal Plan: Stable Local Operator Client

Date: 2026-07-16
Status: released as v1.0.0 on 2026-07-17
Baseline: v0.9.0 Local Operator Compatibility released and published

## Progress

- 2026-07-16: Started the v1.0 GOAL from clean `main` after v0.9.0 GitHub and
  PyPI publication. Initial direction: turn the v0.9 no-server MCP/ACP boundary
  into a small stable local operator client while preserving supervisor-owned
  completion.
- 2026-07-16: Implemented the first P0 slice: `LocalOperatorClient`,
  focused fake-runner tests, user-guide workflow docs, changelog note, and a
  v1.0 release-check gate.
- 2026-07-16: Completed P0 hardening: the client now exposes the full P0
  operation set, reports process failures, invalid JSON, incompatible
  control-envelope schema versions, and `ok: false` payloads explicitly, and
  `ai-orch verify` fails closed when policy denies a configured verification
  command.
- 2026-07-17: Added focused local operator JSON payload examples for status,
  missing-task errors, approval inbox reads, and policy-denied approval retries.
- 2026-07-17: Added CI packaged install smoke coverage using a clean local venv,
  `pip install . --no-deps`, and `ai-orch` console script checks;
  `release-check` gates the workflow content without running networked install
  work locally.
- 2026-07-17: Reviewed queue JSON coverage and closed additional queue client
  wrappers as not needed for v1.0. Queue inspection remains available through
  the documented CLI JSON surface; the stable Python client stays focused on
  the normal local operator workflow.
- 2026-07-17: Added the future MCP/ACP runtime proposal. The proposal keeps
  v1.0 no-server, requires future protocol adapters to preserve
  supervisor-owned completion and policy deny precedence, and gates any runtime
  implementation behind a separate review.
- 2026-07-17: Completed pre-release readiness sync. No open P0/P1 items
  remained in the v1.0 plan or backlog before the release-prep handoff.
- 2026-07-17: Applied P1 client hardening from architecture/security review:
  the client now pins the repository path at creation time and rejects
  malformed control JSON envelopes before reporting success.
- 2026-07-17: Closed the `start_task` RC gap: `ai-orch start --json` now emits
  a stable control envelope and `LocalOperatorClient.start_task` parses the
  machine-readable task identity instead of relying on human stdout.
- 2026-07-17: Released v1.0.0, tagged `v1.0.0`, published the GitHub Release,
  and published `ai-engineering-supervisor 1.0.0` to PyPI through the trusted
  GitHub Actions release workflow.

## Release Outcome

v1.0.0 is released. The P0/P1 Stable Local Operator Client scope is complete:

- `LocalOperatorClient` is the supported Python wrapper for the local operator
  workflow.
- `ai-orch start --json` returns a stable control envelope with task identity
  and supervisor result metadata.
- Status reads, approval list/approve/reject/retry, and trace export remain on
  the existing CLI control surface.
- Completion authority remains supervisor-owned; the client has no direct
  state mutation or direct `done` method.
- MCP/ACP runtime implementation remains out of scope and gated by the future
  runtime proposal in `docs/MCP_ACP_RESEARCH.md`.
- Release verification passed with `688` tests before tagging, and the PyPI
  publication workflow completed successfully.

## Positioning

v1.0 should be the first stable local automation milestone. The project already
has durable state, approvals, recovery, trace export, worktree/sandbox
provenance, JSON contracts, and a no-server MCP/ACP operation boundary.

The v1.0 control question is:

> Can a local editor/tool/script use a supported Python client to drive the
> documented control surface without parsing human text, bypassing policy, or
> gaining authority to mark work done?

The product promise remains:

```text
AI agents execute; the supervisor decides done.
```

## Product Goal

Provide a stable, documented, local-first operator client around the existing
CLI control surface. The client should make the v0.8/v0.9 JSON contracts easier
to consume while keeping all execution, approval, recovery, and completion
semantics inside the existing `ai-orch` CLI and supervisor loop.

## P0 Scope Status

P0 is implemented and covered by the local quality gate. Remaining v1.0 work
should avoid expanding authority or adding a runtime server; it should focus on
P1 documentation, smoke coverage, and release readiness.

1. [x] Add a standard-library-only local operator client.
   - Provide typed request/result structures.
   - Execute through `python -m ai_orchestrator ...` or an injectable runner.
   - Parse JSON payloads for stable start/read/control operations.
   - Return explicit failure results for process failures and invalid JSON.
   - Do not mutate state except by calling the same existing CLI commands that a
     human operator would review.

2. [x] Keep completion authority inside the supervisor.
   - The client may call `start_task`, `get_status`, `list_approvals`,
     `approve_action`, `reject_action`, `retry_approval`, and `export_trace`.
   - The client must not expose a method that directly marks tasks `done`.
   - Approval and retry behavior must remain governed by existing policy and
     deny precedence.

3. [x] Preserve no-server MCP/ACP readiness.
   - Keep the v0.9 operation boundary.
   - Add client behavior around that boundary without opening listeners,
     starting a long-running service, or adding cloud/multi-user behavior.
   - Document that future protocol adapters should depend on the client/boundary
     instead of duplicating CLI argv construction.

4. [x] Add focused tests.
   - Unit-test client success with an injectable fake runner.
   - Unit-test non-zero process results.
   - Unit-test invalid JSON handling.
   - Unit-test malformed control-envelope rejection.
   - Unit-test repository path pinning across process working-directory changes.
   - Unit-test that `export_trace` can remain a non-JSON command result while
     preserving stdout/stderr/exit code.

5. [x] Add docs and release gates.
   - Document the v1.0 goal and client workflow.
   - Extend `release-check` only after the client contract exists.
   - Update `CHANGELOG.md` once user-visible behavior is implemented.

## P1 Scope

- [x] Promote more queue JSON commands to stable if the local operator client
  needs them for normal workflows. Decision: not needed for v1.0 because queue
  inspection remains a documented CLI JSON workflow, while the client normal
  workflow is covered by start/status/approval/retry/export operations.
- [x] Add packaged install smoke coverage to release-check or CI without making
  local release-check depend on network access.
- [x] Add optional schema examples for key JSON payloads in docs.
- [x] Add a future runtime proposal for MCP/ACP only after the local client is
  stable and reviewed.

## Release Verification Record

The v1.0.0 release was tagged only after the required quality gate passed:

```bash
python -m pytest
python -m compileall ai_orchestrator
ruff check .
mypy ai_orchestrator
python -m ai_orchestrator release-check --repo .
git diff --check
```

The release commit is `d04ec66` and the release tag is `v1.0.0`. GitHub Release
publication triggered the trusted PyPI publishing workflow for
`ai-engineering-supervisor 1.0.0`.

## Out Of Scope

- Long-running MCP/ACP server runtime.
- Web dashboard.
- Cloud multi-user deployment.
- Automatic git push, merge, tag, package publish, deploy, or destructive
  cleanup.
- Direct state-store mutation through the operator client.
- New production dependencies without a decision record.
- Parallel agent execution or multi-agent voting.

## Testable P0 Tasks

- [x] Client maps supported operations through the existing MCP/ACP boundary.
- [x] Client executes through an injectable runner and records argv/cwd/timeout.
- [x] Client parses control JSON payloads for start, status, and approvals.
- [x] Client returns explicit errors for command failure, invalid JSON,
  incompatible schema versions, and `ok: false` control payloads.
- [x] Client does not provide a direct completion/status mutation API.
- [x] Release gate requires v1.0 goal/client docs and focused client tests.

## Subagent Workflow For GOAL Mode

Use subagents for bounded sidecar work only:

- **Roadmap Explorer.** Confirm v1.0 product scope, non-goals, and release
  positioning from docs.
- **Control Explorer.** Inspect control boundary, ProcessRunner usage, CLI JSON
  surfaces, and focused test anchors.
- **Security Reviewer.** Review final diff for policy bypass, direct state
  mutation, unsafe subprocess behavior, and server/runtime creep.
- **Docs Reviewer.** Check v1.0 docs, changelog, and release gates.

Main-agent responsibilities:

- Own the goal plan and final integration.
- Keep P0 code in the local control boundary.
- Keep implementation standard-library-only.
- Run the required project checks before reporting completion.

## GOAL Stop Conditions

- A design requires a server, listener, network service, or protocol runtime.
- A client method would directly set task status or bypass supervisor
  verification.
- Approval retry, deny precedence, or policy behavior would need to be
  weakened.
- A production dependency is required.
- Tests fail without a scoped repair path.
- The diff expands beyond the local control client, focused tests, docs,
  changelog, and release gate.

## First Bounded Slice

Implement the smallest useful local operator client:

1. Add `ai_orchestrator.control.client`.
2. Reuse `McpAcpRequest` and `cli_args_for_operation`.
3. Add focused unit tests with a fake runner.
4. Document the slice in this plan and update `CHANGELOG.md`.
5. Run focused tests, then the required project checks if the slice is complete.
