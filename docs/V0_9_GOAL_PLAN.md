# v0.9 Goal Plan: Local Operator Compatibility

Date: 2026-07-16
Status: active goal plan
Baseline: v0.8.0 Ecosystem Control Surface released and published

## Progress

- 2026-07-16: Started the v0.9 GOAL from `main` after v0.8.0. Discovery
  confirmed that the post-v0.8 release-notes template gate is already in
  `Unreleased` and should ship with v0.9.0.
- 2026-07-16: Added v0.8 control-envelope compatibility assertions, normalized
  selected queue JSON missing-plan errors to the control error shape, added a
  safe external local operator smoke, introduced a no-server MCP/ACP boundary
  that maps future operations to existing CLI commands, and extended
  `release-check` with a v0.9 operator compatibility docs gate.

## Positioning

v0.9 hardens the v0.8 ecosystem control surface for real local operator tools.
The goal is compatibility, smoke validation, and adapter-boundary readiness,
not a new server runtime.

The v0.9 control question is:

> Can an external local operator client rely on the v0.8 JSON control surface,
> detect incompatible envelope or error changes, and exercise a safe smoke
> workflow without gaining authority to mark work done, push, merge, deploy, or
> run a long-lived MCP/ACP service?

The product promise remains:

```text
AI agents execute; the supervisor decides done.
```

## Current Inventory

- v0.8 documented the stable JSON control surface in
  `docs/V0_8_JSON_CONTRACTS.md`.
- v0.8 documented a future MCP/ACP adapter shape in
  `docs/V0_8_MCP_ACP_DESIGN_SPIKE.md` without adding a server runtime.
- `docs/USER_GUIDE.md` includes the external local operator workflow.
- `docs/RELEASE.md` and `docs/RELEASE_NOTES_TEMPLATE.md` define the expanded
  release-notes quality gate.
- `ai_orchestrator/verification/release.py` implements release readiness gates.
- Focused CLI contract tests live mostly in `tests/test_cli.py`.
- Existing real-agent smoke coverage lives in `tests/test_real_agent_smoke.py`.
- Shared adapter boundary coverage lives in `tests/test_adapter_contract.py` and
  `tests/test_agent_factory.py`.

## Product Goal

Make the documented v0.8 JSON control surface safer for external local
automation by adding compatibility tests, an operator-client smoke path, and a
clear adapter-boundary contract that can support future MCP/ACP integration
without starting a long-running server in v0.9.

## P0 Scope

1. Add a v0.8 JSON compatibility suite.
   - Freeze the common v0.8 control envelope for stable commands:
     `schema_version`, `command`, `generated_at`, `ok`, and `error`.
   - Cover representative success and error payloads for status, approvals, and
     autopilot queue control surfaces.
   - Keep existing trace/timeline/recovery shapes backward compatible unless a
     documented migration is added.
   - Treat additive fields as allowed, but fail on missing required envelope or
     error fields.

2. Add an external local operator integration smoke.
   - Exercise a safe local workflow through the public CLI, not private storage
     helpers.
   - Use mock or fixture-backed local execution only; do not require external AI
     credentials.
   - Validate that the workflow can inspect status, approvals or queue state,
     recovery preflight, and trace export without parsing human text.
   - Keep all operations local-first and dry-run-first where mutation is not
     required for the smoke.

3. Prepare the MCP/ACP adapter boundary without server runtime.
   - Define the boundary as an adapter/client contract around the existing CLI
     control surface.
   - Do not start a long-running MCP server, open network listeners, or add
     cloud/multi-user behavior.
   - Keep future operations mapped to supervisor-owned commands:
     `start_task`, `get_status`, `list_approvals`, `approve_action`,
     `retry_approval`, and `export_trace`.
   - Preserve the rule that MCP/ACP adapters can request work and inspect
     results, but cannot mark tasks done.

4. Improve release and operator workflow gates.
   - Extend `release-check` so v0.9 requires the v0.9 goal plan and the v0.8
     JSON contracts that external operators depend on.
   - Require docs to mention the local operator smoke and compatibility
     contract before release.
   - Keep release-check local and read-only; it must not push, publish, deploy,
     tag, merge, or delete.

5. Update documentation and changelog.
   - Add v0.9 notes to `CHANGELOG.md`.
   - Update operator-facing docs only where behavior or release gates changed.
   - Keep project-facing docs in English.

## P1 Scope

- Promote additional queue `--json` commands from stable candidate to stable
  only if P0 tests reveal that external operator smoke requires them.
- Add a small operator-client helper module only if tests need a reusable
  boundary and it stays standard-library-only.
- Add richer docs for future MCP/ACP operation schemas if the boundary remains
  underspecified after P0.
- Add more provider-specific adapter tests only where behavior diverges from
  the shared adapter contract.

## Out Of Scope

- Long-running MCP/ACP server implementation.
- Web dashboard.
- Cloud multi-user deployment.
- Parallel agent swarm or cross-agent voting.
- Automatic git push, merge, tag, package publish, deploy, or destructive
  cleanup.
- New production dependency without a separate decision record.
- Rewriting supervisor FSM, `AgentAdapter`, storage, policy, or PlanGraph.

## Stable Compatibility Targets

v0.9 must preserve the v0.8 stable surfaces documented in
`docs/V0_8_JSON_CONTRACTS.md`:

- `ai-orch export <task_id> --repo <repo> [--output PATH] [--redact]`
- `ai-orch status <task_id> --repo <repo> --json`
- `ai-orch timeline <task_id> --repo <repo> --json`
- `ai-orch recover --repo <repo> --json`
- `ai-orch approvals list|show|approve|reject|retry --repo <repo> --json`
- `ai-orch autopilot queue status --repo <repo> --json`

Stable envelope fields for commands using the v0.8 control envelope:

```json
{
  "schema_version": "1.0",
  "command": "string",
  "generated_at": "ISO-8601 timestamp",
  "ok": true,
  "error": null
}
```

Stable error shape:

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

## Testable P0 Tasks

- Contract: stable v0.8 control-envelope success payloads keep required fields.
- Contract: stable v0.8 control-envelope error payloads keep required fields.
- Contract: trace export compatibility keeps required metadata and sections.
- Contract: redacted trace export still omits bulky raw agent and verification
  streams.
- Smoke: external local operator workflow can inspect machine-readable state
  without external AI credentials.
- Boundary: future MCP/ACP operations remain mapped to CLI/supervisor control
  and do not introduce server runtime behavior.
- Release gate: `release-check` requires v0.9 goal planning and v0.8/v0.9
  contract documentation.

## Subagent Workflow For GOAL Mode

Use subagents only for bounded sidecar work that can proceed in parallel with
the main critical path.

Recommended subagent roles:

- **Contract Explorer.** Identifies JSON compatibility anchors and gaps.
- **Docs Explorer.** Checks release/operator docs for missing v0.9 language.
- **Security Reviewer.** Reviews the final diff for policy, approval, secret,
  and unsafe automation regressions.
- **Review Agent.** Reviews tests, release gates, and compatibility risk before
  final verification.

Main-agent responsibilities:

- Own the v0.9 goal plan and final integration.
- Keep implementation local-first and standard-library-only unless a separate
  decision justifies otherwise.
- Reconcile subagent findings into one bounded release.
- Run final checks and report actual results.

## GOAL Stop Conditions

- A change would require push, merge, release publication, deployment, or
  destructive cleanup.
- A change would weaken deny-rule precedence or approval auditing.
- A change would allow an external operator client, MCP/ACP adapter, or worker
  agent to mark a task done without supervisor verification.
- A compatibility change removes or renames a documented v0.8 stable field
  without a migration.
- A long-running server runtime becomes necessary for P0.
- Tests fail with no scoped repair path.
- The diff expands beyond docs, focused tests, release gates, and minimal
  operator-boundary code.

## First Bounded Slice

Create this v0.9 goal plan and then implement the smallest P0 compatibility
slice:

1. Add helper assertions for the v0.8 control envelope in focused tests.
2. Cover representative success and error JSON outputs.
3. Extend release-check to require `docs/V0_9_GOAL_PLAN.md` and the operator
   compatibility docs.
4. Update changelog and docs after behavior is covered by tests.
