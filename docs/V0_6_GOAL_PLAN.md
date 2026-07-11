# v0.6 GOAL Plan: PlanGraph v1

## Goal

Turn the existing PlanGraph groundwork into a durable, user-visible planning
layer for `ai-orch` runs.

`v0.6` should let an operator represent work as dependent task steps, inspect
which steps are ready or blocked, run one safe execution lane through the
supervisor, and explain node-level decisions in reports and exports.

This milestone is about dependable planning and recovery. It is not a
multi-agent or parallel-execution milestone.

## Current Baseline

The repository already contains a useful PlanGraph foundation:

- SQLite-backed plan graphs, graph nodes, and dependencies;
- graph/node status updates in `StateStore`;
- ready-node selection that respects dependencies;
- `ai-orch autopilot plan` commands for create/show/update/add-node/ready and
  dry-run/apply execution;
- queue-to-graph linking for autopilot queue items;
- replan decisions linked to plan graph nodes;
- tests for graph storage, dependency validation, ready-node listing, queue
  linking, and node lifecycle updates.

`v0.6` should harden that foundation into a coherent PlanGraph v1 product
surface instead of adding a second planning abstraction.

## Scope

- Build on the existing `PlanGraph`, plan item, replan, task event, action
  journal, and autopilot queue storage.
- Keep execution serial by default: one selected ready node enters the existing
  supervisor loop.
- Preserve existing CLI behavior and command names unless adding aliases or
  read-only output improves discoverability.
- Prefer SQLite and typed dataclasses already present in the project.
- Do not add production dependencies.
- Do not introduce a generic workflow engine, Temporal-style scheduler, or
  multi-agent framework layer.

## P0 Work

### 1. PlanGraph Model Hardening

Make graph and node records explicit enough to support recovery, reports, and
deterministic export.

Work items:

- define or consolidate typed dataclasses for graph, node, dependency, and
  node execution summary;
- ensure node fields cover title, task text, acceptance criteria, verification
  requirement, status, blocked reason, linked task id, linked queue item id,
  and timestamps;
- make status transitions explicit and validated;
- keep older stored rows readable.

Exit criteria:

- PlanGraph rows round-trip through typed objects.
- Invalid status transitions are rejected or reported clearly.
- Existing storage tests remain green.

### 2. Deterministic Readiness and Dependency Semantics

Make ready-node selection predictable and safe.

Work items:

- document the exact statuses that satisfy dependencies;
- ensure blocked/failed/skipped dependency behavior is explicit;
- add deterministic ordering for ready nodes;
- expose why a node is not ready in JSON and text output;
- prevent dependency cycles where possible without a large graph engine.

Exit criteria:

- Ready-node output is stable across runs.
- Blocked nodes do not unblock dependents accidentally.
- Tests cover dependency readiness, skipped nodes, blocked nodes, and ordering.

### 3. Node Execution Through Supervisor

Ensure each executable node runs through the existing verification-gated
supervisor path and records node-level decisions.

Work items:

- keep `run-next` and `run-batch` dry-run by default;
- when `--execute` is used, link task id, iterations, verification runs, and
  final decision back to the node;
- update node status from supervisor result: `done`, `blocked`, `failed`, or
  follow-up-ready;
- avoid duplicate node completion when a command is retried or resumed.

Exit criteria:

- A node cannot be marked done without supervisor-controlled verification.
- Re-running a completed node does not duplicate terminal records.
- Tests cover done, blocked, failed, and dry-run paths.

### 4. Replanning and Repair Nodes

Make blocked or failed nodes actionable without silently rewriting history.

Work items:

- record why a node was blocked or failed;
- allow creating repair/follow-up/manual-review nodes linked to the source node;
- ensure repair nodes inherit useful context but keep their own status;
- expose replan decisions in text and JSON output.

Exit criteria:

- Blocked node reports show an actionable next step.
- Repair/follow-up nodes are visible and linked to their source.
- Tests cover at least one failed-node-to-repair-node path.

## P1 Work

### 5. Operator CLI Surface

Expose PlanGraph v1 as a coherent operator workflow while preserving existing
autopilot commands.

Candidate commands or aliases:

- `ai-orch autopilot plan list`
- `ai-orch autopilot plan show <graph_id> --json`
- `ai-orch autopilot plan ready <graph_id> --json`
- `ai-orch autopilot plan run-next <graph_id>`
- `ai-orch autopilot plan run-batch <graph_id>`
- optional read-only aliases under `ai-orch plan ...` if they can be added
  without duplicating implementation.

Exit criteria:

- A user can list, inspect, select, dry-run, execute, and export a graph from
  the CLI.
- Text output is concise and operator-friendly.
- JSON output is stable enough for scripts.

### 6. Reports and Trace Export

Add graph-level and node-level visibility to existing reports/exports.

Work items:

- include graph summary in task reports when a task is linked to a node;
- include node status, dependencies, blocked reason, and verification summary;
- include repair/replan links;
- include graph progress in JSON export where applicable.

Exit criteria:

- Reports explain why a node is ready, done, blocked, skipped, or failed.
- Export output can reconstruct graph progress deterministically.

### 7. Recovery and Replay Safety

Make interrupted graph execution inspectable and safe to continue.

Work items:

- detect stale `running` graph nodes;
- surface linked task/action/verification state for interrupted nodes;
- provide dry-run recovery output before mutating graph state;
- keep replay idempotent for completed nodes and action records.

Exit criteria:

- Interrupted node execution can be inspected.
- Recovery produces a clear node state instead of silent corruption.
- Tests cover one interrupted or stale-node path.

### 8. Documentation and Release Gate

Update user-facing docs only where behavior is visible.

Work items:

- update `README.md` and `docs/USER_GUIDE.md` for the PlanGraph operator flow;
- update `CHANGELOG.md` during release preparation;
- update `docs/RELEASE.md` or release checks if PlanGraph docs become release
  requirements;
- keep roadmap language aligned with AI Engineering Supervisor positioning.

Exit criteria:

- Docs describe the exact supported commands.
- Release checks still pass.
- No docs suggest unsupported parallel/multi-agent execution.

## First Bounded Slice

Start with P0.1 and P0.2:

- inventory existing PlanGraph storage and CLI paths;
- add or consolidate typed graph/node/dependency serialization helpers;
- add readiness explanation fields for non-ready nodes;
- add deterministic ready-node ordering tests;
- preserve current CLI output unless adding optional JSON fields.

This slice should be small enough to review independently and should not touch
agent adapters, sandboxing, or policy execution paths unless a PlanGraph test
forces a narrow fix.

## Acceptance Criteria

- A task plan can be represented as dependent graph nodes.
- Ready-node selection is deterministic and dependency-aware.
- Blocked nodes do not unblock dependents unless an explicit skip or repair path
  says so.
- Supervisor decisions are recorded per node and per linked task.
- Graph export/reporting explains readiness, blocked reasons, verification
  state, and repair links.
- Interrupted node execution can be inspected and recovered without duplicating
  terminal records.
- Existing public CLI behavior remains backward-compatible.

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

## Out of Scope for v0.6

- Parallel agent execution.
- Worktree sandbox enforcement beyond existing hooks.
- New production dependencies.
- External schedulers or workflow engines.
- Web UI.
- Automatic git push, package publishing, or destructive cleanup.
