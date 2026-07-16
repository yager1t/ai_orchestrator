# v0.8 Goal Plan: Ecosystem Control Surface

Date: 2026-07-16
Status: active goal plan
Baseline: v0.7.0 Worktree + Sandbox Isolation released and published

## Progress

- 2026-07-16: Started the first bounded slice. Added the initial JSON contract
  inventory in `docs/V0_8_JSON_CONTRACTS.md` and focused baseline tests for
  `export`, `timeline --json`, and `recover --json`.
- 2026-07-16: Added v0.8 control-envelope JSON for `status`,
  `approvals list/show/approve/reject/retry`, and `autopilot queue status`;
  added focused contract/error tests, operator workflow docs, changelog notes,
  and a release-check gate for the v0.8 control surface.
- 2026-07-16: Completed the P1 disposition pass. Existing coverage already
  handles read-only memory preflight, batch `--summary-json`, metrics, and
  adapter contract tests; added `docs/V0_8_MCP_ACP_DESIGN_SPIKE.md` for the
  future MCP/ACP adapter shape without making server runtime a v0.8 blocker.

## Positioning

v0.8 moves `ai-orch` from a strong local CLI supervisor toward a stable local
control surface that other tools can drive without parsing human-oriented text.
The goal is not to add a broad agent framework, web dashboard, or agent swarm.
The goal is to make the existing supervisor loop usable as a reliable,
machine-readable control plane.

The v0.8 control question is:

> Can an external local tool start supervised work, inspect state, resolve
> approvals, recover safely, and export an auditable trace while preserving the
> rule that the supervisor, not the worker agent, decides done?

## Current Inventory

- `ai-orch` already has a verification-gated supervisor loop and durable SQLite
  task state.
- Approval requests, action records, task events, PlanGraph nodes, queue items,
  memory lessons, worktree provenance, sandbox decisions, reports, and JSON
  trace exports are persisted locally.
- Many commands already expose `--json`, including setup/onboard, timeline,
  recover, eval, worktree inspection, loop history, PlanGraph, queue, and
  selected autopilot operations.
- `ai-orch export` already produces a local task trace with metadata,
  timeline, action journal, approvals, verification results, redaction mode,
  and unsafe action accounting.
- `ai-orch ci` already provides a headless verification and release-check entry
  point with stable success/failure exit behavior.
- v0.7 added worktree and sandbox provenance, giving external callers enough
  context to understand where work happened and which runtime actions were
  denied.

## Product Goal

Make `ai-orch` safe to call from local automation, editor integrations,
worktree managers, shell scripts, and future MCP/ACP adapters by stabilizing a
small set of CLI JSON contracts before introducing a server runtime.

The product promise remains:

```text
AI agents execute; the supervisor decides done.
```

## P0 Scope

1. Define the v0.8 JSON contract policy.
   - Identify stable, experimental, and internal JSON outputs.
   - Add a common top-level envelope convention for new stable JSON outputs:
     `schema_version`, `command`, `generated_at`, `ok`, and `error`.
   - Mark free-form payload fields as extensible instead of freezing internal
     storage shapes accidentally.
   - Decide and document path handling for local absolute paths, repo-relative
     paths, and redacted user paths.

2. Stabilize task trace export as the canonical artifact.
   - Treat `ai-orch export <task_id> --repo <repo> [--output PATH] [--redact]`
     as the primary external trace contract.
   - Require top-level sections for metadata, task, timeline, task events,
     action records, action journal, iterations, verification runs, approvals,
     replan decisions, memory influence, PlanGraph context when present, and
     sandbox/worktree provenance when present.
   - Keep `metadata.schema_version`, `exported_at`, `task_id`, `run_id`,
     `redaction_mode`, and `unsafe_action_count` stable.
   - Preserve the `--redact` guarantee for bulky raw agent output and
     verification streams.

3. Stabilize read-only replay and status inspection.
   - Treat `ai-orch timeline <task_id> --json` as the replayable task timeline
     contract.
   - Add or document machine-readable status output for task status if the
     current human `status` command remains text-only.
   - Keep approval, verification, policy, action, sandbox, worktree, and
     recovery events visible enough for external operators to understand why a
     task is `done`, `blocked`, or waiting.

4. Stabilize approval and recovery operator contracts.
   - Define JSON behavior for approval listing/showing and, where practical,
     approve/reject/retry outcomes.
   - Treat `ai-orch recover --json` as the recovery preflight/apply contract.
   - Include running tasks, expired action leases, stale started actions,
     worktree recovery candidates, dry-run/apply mode, and applied recovery
     counts.
   - Keep deny rules stronger than approvals, and make that visible in JSON
     outcomes.

5. Stabilize autopilot queue and PlanGraph read surfaces used by external
   tools.
   - Treat `autopilot queue show <plan_item_id> --json` as the canonical queue
     item lookup.
   - Stabilize common queue item fields: `plan_item_id`, `plan_path`,
     `line_number`, `text`, `status`, `task_id`, `selected_worktree_path`,
     `blocked_reason`, `plan_graph_id`, `plan_graph_root_node_id`, and
     `report_path`.
   - Stabilize read-only queue status/readiness/preflight JSON enough for
     external tools to select the next safe operator action.
   - Keep PlanGraph JSON stable only for the fields needed by queue execution
     and readiness; mark deeper graph payloads experimental unless they are
     covered by tests.

6. Add contract tests and release gates.
   - Add focused tests for stable JSON shapes and error shapes.
   - Add redaction regression tests for trace exports and error payloads.
   - Add negative scenarios for missing task ids, denied approval retries,
     blocked verification, policy denial, stale recovery, and invalid queue
     item ids.
   - Extend release-check coverage so v0.8 cannot ship without the documented
     control surface.

7. Document the external operator workflow.
   - Add a concise runbook section explaining how a local tool should:
     start work, poll status, inspect approvals, approve or reject, retry,
     recover stale work, and export a trace.
   - Keep the workflow CLI-first and local-first.
   - Explicitly state that external tools must not mark tasks done without
     supervisor verification.

## P1 Scope

- Add `--json` to selected human-only commands if required by the P0 workflow,
  such as `status`, `report`, or approval mutations.
- Add a stable `--summary-json PATH` contract for queue batch runs if the
  existing batch summary is not sufficient for external callers.
- Improve Codebase Memory preflight as an optional context layer for
  `start --use-memory`, while keeping memory hints non-authoritative.
- Add richer local metrics summaries for iterations-to-done, verification pass
  rate, approval frequency, policy denials, sandbox denials, and adapter
  failures.
- Prepare an MCP/ACP design spike for `start_task`, `get_status`,
  `list_approvals`, `approve_action`, and `export_trace`, without requiring
  server runtime implementation in v0.8.
- Expand adapter contract tests only where provider-specific behavior diverges
  from the shared adapter contract.

## Stable Surface Candidates

These commands are candidates for stable v0.8 JSON contracts:

- `ai-orch export <task_id> --repo <repo> [--output PATH] [--redact]`
- `ai-orch status <task_id> --repo <repo> --json`
- `ai-orch timeline <task_id> --repo <repo> --json`
- `ai-orch recover --repo <repo> --json`
- `ai-orch approvals list --repo <repo> --json`
- `ai-orch approvals show <approval_id> --repo <repo> --json`
- `ai-orch approvals approve|reject|retry <approval_id> --repo <repo> --json`
- `ai-orch autopilot queue show <plan_item_id> --repo <repo> --json`
- `ai-orch autopilot queue list|status|readiness|preflight --repo <repo> --json`
- `ai-orch autopilot queue reconcile|recover-in-progress|requeue|skip --json`
- `ai-orch autopilot plan list|show|ready --repo <repo> --json`
- `ai-orch worktree status|inspect|cleanup --repo <repo> --base-dir DIR --json`

Human stdout remains allowed to evolve unless a command is explicitly promoted
to stable JSON.

## Experimental Or Internal In v0.8

- Human-oriented output from `verify`, `release-check`, `ci`, `agents`,
  `metrics`, `report`, and `tui`.
- `memory *` command payloads, unless a P0 workflow explicitly depends on them.
- Deep PlanGraph internals beyond readiness, linked queue item ids, node status,
  dependency status, and report/trace references.
- Provider-specific adapter raw output shapes.

## Out Of Scope

- Web dashboard.
- Full MCP server runtime as a release blocker.
- Parallel agent execution, agent swarm, or cross-agent voting.
- Automatic merge, git push, package publication, or deployment.
- Automatic worktree deletion.
- Container, VM, or OS-level sandboxing.
- New production dependencies without a separate ADR.
- Rewriting supervisor FSM, `AgentAdapter`, PlanGraph, storage, or policy
  architecture.

## Subagent Workflow For GOAL Mode

Use subagents only for bounded sidecar work that can proceed in parallel with
the main critical path.

Recommended subagent roles:

- **Roadmap Explorer.** Reads roadmap, backlog, ADRs, and prior goal plans.
  Output: P0/P1 boundaries, non-goals, and release positioning.
- **Contract Explorer.** Reads CLI handlers, export/timeline/recover code, and
  tests. Output: candidate stable JSON contracts, required fields, gaps, and
  compatibility risks.
- **Verification Explorer.** Reads release checks, CI, test coverage, and
  regression suites. Output: v0.8 verification matrix, missing negative tests,
  and release gates.
- **Worker Agent.** May implement one bounded contract slice with an explicit
  write set. Workers must not edit the same files as each other and must not
  revert unrelated local changes.
- **Review Agent.** Reviews the final diff for behavioral regressions, missing
  tests, schema instability, and security/audit gaps.

Main-agent responsibilities:

- Keep the goal plan and final integration local.
- Own architecture decisions and scope cuts.
- Reconcile subagent outputs into one coherent contract.
- Run final checks and report what passed.
- Stop or re-scope if subagent findings reveal that a P0 item is too broad for
  one bounded release.

GOAL-mode stop conditions:

- pending approval;
- blocked node or blocked task;
- failed verification with no safe retry path;
- unavailable configured agent;
- dirty, invalid, or unlinked worktree when isolation is required;
- runtime or action budget exhaustion;
- unsafe action count greater than zero;
- missing trace, report, or provenance needed to audit completion.

Subagent trace expectations:

- Every delegated run should be attributable to role, assigned question or
  node, attempt, repo or worktree scope, budget, stop reason, and output
  summary.
- Execution remains serial-first for runtime-changing work. Parallel subagents
  may inspect, review, or implement disjoint write sets, but parallel task
  execution remains out of scope for v0.8.
- A subagent response is planning or implementation evidence, not proof that a
  task or release is done. Verification and release gates remain authoritative.

Hard release stops:

- new production dependency without a decision record;
- auto-push, auto-merge, deploy, publish, or delete behavior introduced without
  an explicit user-approved release decision;
- any path where a worker or subagent can mark work done without supervisor
  verification;
- approval bypass or deny-rule weakening;
- missing trace/report provenance for stable control-surface operations;
- JSON contract changes that are not covered by focused tests or documentation.

## Testable P0 Tasks

- Unit/CLI: stable trace export includes required metadata and sections.
- Unit/CLI: trace export redaction removes raw agent output and verification
  streams when `--redact` is used.
- Unit/CLI: timeline JSON keeps stable replay fields.
- Unit/CLI: recovery JSON includes stale action and worktree recovery sections.
- Unit/CLI: queue item JSON includes stable queue and PlanGraph references.
- Unit/CLI: JSON error outputs use a stable shape for missing task, missing
  approval, invalid queue item, and policy-denied retry cases.
- Release gate: docs mention the stable v0.8 control surface.
- Release gate: `docs/V0_8_GOAL_PLAN.md` remains present and describes the
  stable control surface, subagent workflow, and hard release stops.
- Release gate: full test suite, compileall, ruff, mypy, release-check, and
  `git diff --check`.

## First Bounded Slice

Create the v0.8 contract inventory and select the first stable control surface:

- audit current `--json` commands and classify each as stable, experimental, or
  internal;
- write a short JSON contract policy document or section;
- add tests for `export`, `timeline`, and `recover` JSON shapes;
- avoid changing runtime behavior beyond additive JSON fields or docs;
- update changelog only after a user-visible contract is implemented.
