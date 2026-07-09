# Robust Autopilot Plan

This plan turns prior planning notes into a public implementation roadmap. The
goal is not to add more agents first. The goal is to evolve
`ai-orch` into an auditable autonomous control plane with durable state, typed
tools, recovery, memory, observability, and evaluation.

## Target Definition

Robust autopilot is reached when all of these are true:

- crash/restart does not lose task state or repeat unsafe side effects;
- write, network, and destructive actions pass through typed policy and approval
  boundaries;
- planning uses durable state and memory instead of only selecting the next
  Markdown item;
- quality is measured with golden tasks, crash/chaos tests, and security
  red-team scenarios;
- the supervisor and independent verifier remain the only authorities for
  completion.

Operator readiness now includes `ai-orch doctor agents`, which reports the
configured worker connector, CLI availability, credential model, and the current
native API-adapter status before unattended execution.

## Stage 0. Strategy And Backlog

Goal: make the robust-autopilot direction explicit and actionable.

Tasks:

- Keep this roadmap public and free of private research notes.
- Convert the roadmap into P0/P1/P2 backlog items.
- Update `POST_MVP_ROADMAP.md` when milestones become committed product work.
- Keep rejected or deferred ideas visible as non-goals.

Definition of done:

- The next implementation slice is obvious.
- Public docs describe what is planned, what is deferred, and why.

## Stage 1. Durable State Foundation

Goal: autopilot can survive crash/restart without losing context.

Tasks:

- Add append-only `task_events`.
- Add `action_records` with idempotency keys.
- Add leases and heartbeats for in-progress actions.
- Add a recovery command for interrupted runs.
- Add a replay/read model for task timelines.

Definition of done:

- A run can be interrupted and resumed without duplicating unsafe side effects.
- Task history can be reconstructed from events.
- Tests cover crash/restart, stale leases, ordering, and replay.

First implementation slice:

1. Add `task_events` schema and migration.
2. Add `StateStore.append_task_event()` and `StateStore.list_task_events()`.
3. Store JSON payloads with stable event type and sequence number.
4. Add migration, ordering, and payload tests.
5. Expose event timeline in report/export as read-only data.

Status: implemented.

Second implementation slice:

1. Add `action_records` schema and migration.
2. Add idempotency-keyed `StateStore.record_action()`.
3. Add `StateStore.complete_action_record()`.
4. Expose action records in report/export as read-only data.
5. Record supervisor verification commands as durable action records.

Status: implemented.

Third implementation slice:

1. Add lease metadata to `action_records`.
2. Add TTL-based acquire, heartbeat, release, and expired-lease listing APIs.
3. Clear leases when action records complete.
4. Expose lease state in report/export as read-only data.

Status: implemented.

Fourth implementation slice:

1. Add dry-run-by-default `ai-orch recover`.
2. Report interrupted `running` tasks and expired action leases.
3. Require `--apply --reason` before changing persisted recovery state.
4. Mark interrupted tasks `blocked`, fail expired action records, clear leases,
   and append recovery events.
5. Add text and JSON output for operator review and scripting.

Status: implemented.

Fifth implementation slice:

1. Add a replayable task timeline read model.
2. Combine task status, task events, iterations, verification, approvals, and
   action records into a stable ordered view.
3. Add `ai-orch timeline TASK_ID` with text and JSON output.
4. Include the same timeline in reports and JSON trace exports.

Status: implemented. Stage 1 durable state foundation is now ready for
PlanGraph work.

## Stage 2. PlanGraph

Goal: autopilot plans and replans multi-step work instead of only selecting the
next Markdown item.

Tasks:

- Introduce `PlanGraph` nodes, dependencies, status, and attempts.
- Persist graph state in SQLite.
- Add CLI commands such as `autopilot plan create`, `show`, and `update`.
- Link backlog or queue items to plan graph roots.
- Let failed verification trigger structured replan decisions.

Definition of done:

- A task can be represented as multiple dependent steps.
- Replanning is persisted and reviewable.
- The operator can inspect plan state without starting execution.

First implementation slice:

1. Add durable `plan_graphs`, `plan_graph_nodes`, and
   `plan_graph_dependencies` schema.
2. Add typed `StateStore` APIs for graph creation, node creation, dependency
   recording, status updates, and attempt tracking.
3. Validate graph, node, dependency, status, and attempt contracts.

Status: implemented.

Second implementation slice:

1. Add `ai-orch autopilot plan list`.
2. Add `ai-orch autopilot plan create` and `show`.
3. Add `ai-orch autopilot plan update`.
4. Add `ai-orch autopilot plan add-node`, `update-node`, and `add-dependency`.
5. Provide JSON output for operator tooling and future unattended loops.

Status: implemented.

Third implementation slice:

1. Add nullable PlanGraph references to persisted queue items.
2. Add typed `StateStore.link_plan_item_to_plan_graph()` validation and update
   API.
3. Add `ai-orch autopilot queue link-plan-graph` as a dry-run-by-default
   operator command with `--apply` and `--json`.
4. Include PlanGraph references in queue item text and JSON views.

Status: implemented.

Fourth implementation slice:

1. Add durable `replan_decisions` storage.
2. Persist supervisor replan decisions when verification fails and retry is
   allowed, or when failed verification exhausts the iteration budget.
3. Store structured failed-check metadata and the follow-up prompt.
4. Expose replan decisions in replay timelines, Markdown reports, and JSON
   trace exports.

Status: implemented.

Fifth implementation slice:

1. Mark linked PlanGraph root nodes `in_progress` and increment attempts when
   queue execution starts.
2. Mark linked root nodes `done` or `blocked` from the supervisor queue result.
3. Attach unlinked task replan decisions to the linked graph and root node after
   queue execution.
4. Cover `run-next`, `run-batch`, and storage linking behavior with regression
   tests.

Status: implemented.

Sixth implementation slice:

1. Add idempotent storage materialization for replan follow-up nodes.
2. Create one pending `replan-{id}` node per linked replan decision.
3. Add a dependency from each follow-up node to the failed/root PlanGraph node.
4. Trigger materialization from queue execution after replan decisions are linked.

Status: implemented.

Seventh implementation slice:

1. Add storage selection for pending PlanGraph nodes whose dependencies are all
   `done`.
2. Exclude blocked, skipped, done, and dependency-blocked nodes from ready
   selection.
3. Add `ai-orch autopilot plan ready GRAPH_ID` with text and JSON output.
4. Add limit support for selecting the next ready graph node.

Status: implemented.

Eighth implementation slice:

1. Add dry-run-by-default `ai-orch autopilot plan run-next GRAPH_ID`.
2. Claim the selected ready node as `in_progress` and increment attempts only
   after execution guards pass.
3. Run the node title through the supervisor as a bounded autopilot task.
4. Mark the node `done` or `blocked`, write the task report, link replan
   decisions, and materialize follow-up nodes when verification fails.

Status: implemented.

Ninth implementation slice:

1. Add dry-run-by-default `ai-orch autopilot plan run-batch GRAPH_ID`.
2. Process up to `--max-items` ready PlanGraph nodes serially.
3. Recompute ready nodes after each successful node so dependency chains can
   advance within the same batch.
4. Stop on the first `blocked` node and leave later pending nodes untouched.

Status: implemented.

## Stage 3. Typed Tool Broker And Policy Tiers

Goal: every tool action has a typed boundary, risk tier, policy decision, and
audit trail.

Tasks:

- Add `ToolSpec`, `ToolCall`, and `ToolResult`.
- Define risk tiers: `read`, `write`, `network`, and `destructive`.
- Route tool calls through `PolicyEngine`.
- Unify approval requests for verification, tools, and memory.
- Persist tool action records with idempotency keys.

Definition of done:

- Tool actions cannot bypass policy.
- Deny rules remain stronger than approvals.
- Write/network/destructive actions are visible in the task timeline.

First implementation slice:

1. Add `ToolSpec`, `ToolCall`, and `ToolResult` typed contracts.
2. Define risk tiers: `read`, `write`, `network`, and `destructive`.
3. Add stable idempotency-key generation for typed tool calls.
4. Validate tool payloads as JSON-serializable data for action-record storage.

Status: implemented.

Second implementation slice:

1. Add `ToolBroker` as the policy and audit boundary for typed `ToolCall`
   objects.
2. Route command/argv policy subjects through `PolicyEngine`.
3. Persist broker decisions and tool results in `action_records`.
4. Require approval for `write`, `network`, and `destructive` risk tiers unless
   a later approval flow explicitly resolves them.

Status: implemented.

Third implementation slice:

1. Route supervisor verification action audit through `ToolBroker`.
2. Preserve durable `verification_command` action records and idempotency keys.
3. Store typed broker payload/result metadata for verification actions.
4. Keep already-executed verification results as precomputed broker audit
   results instead of re-running commands.

Status: implemented.

Fourth implementation slice:

1. Create durable `approval_requests` for brokered `needs_approval` tool calls.
2. Keep policy-denied tool calls as hard stops without approval requests.
3. Correlate blocked action records with the created `approval_id` and
   `action_id` in the typed broker result.
4. Reuse the existing `ai-orch approvals` operator flow for brokered tools.

Status: implemented.

Fifth implementation slice:

1. Add `ToolBroker.run_approved()` for operator-approved retries.
2. Preserve deny supremacy by re-checking policy and blocking deny matches even
   after approval.
3. Record approved retries as separate durable action records linked to the
   original `approval_id`.
4. Teach `ai-orch approvals retry` to execute brokered process tools restored
   from action-record payloads when they provide `command` or `argv` arguments.

Status: implemented.

Sixth implementation slice:

1. Add `ToolExecutorRegistry` for exact tool-name and namespace-prefix executor
   lookup.
2. Move approved process command/argv execution into a reusable typed executor.
3. Route `ai-orch approvals retry` through the executor registry instead of a
   CLI-local process helper.
4. Keep missing executors as explicit failed tool results.

Status: implemented.

Seventh implementation slice:

1. Add concrete `fs.read` and `fs.write` typed executors.
2. Constrain all file executor paths to the task repository root.
3. Register the `fs.` executor namespace in `ai-orch approvals retry`.
4. Cover approved `fs.write` retry end-to-end through the existing approval
   flow.

Status: implemented.

Eighth implementation slice:

1. Add a `memory.` typed executor namespace backed by `CodebaseMemoryClient`.
2. Map `memory.<tool>` calls to Codebase Memory CLI tools with JSON arguments.
3. Auto-approve the exact Codebase Memory command during an already approved
   broker retry while preserving policy deny checks.
4. Cover approved `memory.index_repository` retry end-to-end through
   `ai-orch approvals retry`.

Status: implemented.

Ninth implementation slice:

1. Add typed `ToolCall` factory helpers for `fs.*`, `process.*`, `memory.*`,
   and verification audit calls.
2. Generate stable idempotency keys from normalized factory arguments by
   default.
3. Preserve explicit idempotency keys where existing durable audit records
   already depend on them.
4. Move supervisor verification action audit to the verification factory.

Status: implemented.

Tenth implementation slice:

1. Replace remaining ad hoc production `ToolCall` construction with typed
   factory helpers where it improves clarity.
2. Keep low-level contract tests free to construct `ToolCall` manually when
   they are testing the contract itself.
3. Cover supervisor and CLI factory usage with focused regression tests.
4. Confirm brokered `fs.*`, `process.*`, and `memory.*` calls remain visible in
   durable action records and timelines.

Status: implemented. Stage 3 typed tool broker and policy tiers are ready for
Stage 4 memory and self-repair.

## Stage 4. Memory And Self-Repair

Goal: autopilot learns from previous failures while keeping verifier supremacy.

Tasks:

- Add episodic memory summaries.
- Add reflection notes for blocked runs and failed verification.
- Add a memory influence log showing what memory was used and where.
- Add stale-memory rules.
- Start with SQLite/FTS before introducing any vector database.

Definition of done:

- Failed runs can create structured lessons.
- Later runs may use lessons as non-authoritative context.
- Verification remains the source of truth for completion.

First implementation slice:

1. Add durable SQLite memory lessons, reflection records, and memory influence
   logs.
2. Record structured blocked-run and failed-verification reflections from the
   supervisor with source task, iteration, failed checks, follow-up prompt, and
   timestamps.
3. Filter stale memory without deleting history when lessons are old or
   repeatedly marked unhelpful.
4. Inject active lessons into supervisor planning context as read-only,
   non-authoritative hints and log every injected lesson with the reason.
5. Expose lessons, reflections, and influence logs in Markdown reports, JSON
   trace exports, replay timelines, CLI inspection, and TUI views.
6. Keep verifier and supervisor decisions as the only authority for completion.

Status: implemented.

Second implementation slice:

1. Rank active memory lessons against the current task text using local lexical
   relevance across lesson text, failure reason, follow-up prompt, and failed
   checks.
2. Replace the supervisor's fixed three-lesson selection with configurable
   `memory.max_lessons`.
3. Keep injected lessons non-authoritative and record ranked influence reasons
   in the memory influence log.

Status: implemented.

## Stage 5. Observability And Evaluation

Goal: unattended behavior is measurable before it is expanded.

Tasks:

- Add a correlation/run id through tasks, events, actions, and verification.
- Export replayable traces for events/actions/verifications.
- Build a local golden task suite.
- Add chaos tests for crash mid-action, stale lease, flaky verifier, and
  unavailable agent.
- Add security red-team scenarios before enabling broader autonomy.

Definition of done:

- Runs produce inspectable traces.
- Golden tasks report pass rate and recovery rate.
- Unsafe action count is tracked and expected to stay at zero.

First implementation slice:

1. Add stable run ids to Markdown reports, replay timelines, and JSON trace
   exports for tasks, task events, action records, approval requests,
   verification runs, replan decisions, memory influence, and final status.
2. Extend trace exports with unsafe action counting, expected to stay zero for
   local evaluation scenarios.
3. Add a local golden task suite definition with recovery and blocked-status
   expectations.
4. Add chaos scenarios for crash mid-action, stale action lease, flaky verifier,
   unavailable agent, and interrupted approved retry.
5. Add security red-team scenarios for denied paths, denied commands, approval
   bypass attempts, and out-of-repo file writes.
6. Add `ai-orch eval golden` text/JSON summaries with pass rate, recovery rate,
   blocked count, chaos/security counts, and unsafe action count.

Status: implemented.

Second implementation slice:

1. Execute golden, chaos, and security red-team scenarios through the supervisor
   against isolated temporary repositories instead of only summarizing scenario
   definitions.
2. Split local evaluation entry points into `ai-orch eval golden`,
   `ai-orch eval chaos`, `ai-orch eval redteam`, and `ai-orch eval all`.
3. Preserve text and JSON summaries with execution counts, pass rates, recovery
   counts, blocked counts, and unsafe-action accounting.

Status: implemented.

## Stage 6. Guarded Unattended Mode

Goal: allow bounded unattended execution only after durable state, policy, and
observability foundations exist.

Tasks:

- Add `autopilot loop --max-items N --stop-on-risk`.
- Add budget ledgers for runtime, attempts, and action counts.
- Add a dead-letter queue for poisoned tasks.
- Keep operator summaries after every item.
- Keep auto-push, auto-merge, and deployment out of scope.

Definition of done:

- The loop can complete several safe tasks.
- The loop stops on risk, approval, blocker, or budget exhaustion.
- Every decision and side effect is auditable.

First implementation slice:

1. Add dry-run-by-default `ai-orch autopilot loop` with `--execute`,
   `--max-items`, and `--stop-on-risk`.
2. Reuse the guarded queue batch execution path so existing policy, approval,
   report, and stop-condition behavior remains authoritative.
3. Add operator-visible runtime, attempts, and action-count budget ledgers.
4. Stop before execution when the selected agent is unavailable, and stop on
   queue risk when `--stop-on-risk` is set.
5. Add durable SQLite `dead_letter_items` records for blocked loop items after
   the configured attempt budget is exhausted.
6. Preserve the no auto-push, no auto-merge, no deploy, and no destructive
   cleanup contract.

Status: implemented. Stage 6 guarded unattended mode is complete for this
robust autopilot plan.

Second implementation slice:

1. Persist every valid `ai-orch autopilot loop` run in SQLite with mode,
   runtime/action/attempt budgets, selected/processed counts, dead-letter
   counts, stop reason, result code, selected item ids, and elapsed runtime.
2. Add `ai-orch autopilot loop-history` with text and JSON output for
   restart-safe operator inspection.

Status: implemented.

## Explicit Non-Goals For Now

- Multi-agent swarm.
- Required Temporal, PostgreSQL, Qdrant, or other service dependencies.
- Auto-push or auto-merge.
- Web dashboard.
- Fully unattended operation before event log, recovery, and policy boundaries.

## Recommended Order

1. Durable state foundation.
2. PlanGraph.
3. Typed tool broker and policy tiers.
4. Memory and self-repair.
5. Observability and evaluation.
6. Guarded unattended mode.
7. Multi-agent and parallel execution only after trust, audit, and isolation are
   strong enough.
