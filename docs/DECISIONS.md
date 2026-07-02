# Architectural Decisions

## ADR-0004: Autopilot Queue And Batch Execution Model

Date: 2026-07-02

### Context

The MVP supervisor can already run a single task, verify it, and decide
`continue` / `done` / `blocked`. The post-v0.1.0 autopilot work needs a
repeatable, operator-safe way to advance a roadmap plan: read items from a
Markdown plan, pick the next unstarted one, run it through the supervisor, and
finish with a report before moving on. Several concerns must fit together:

- **Persisted plan queues.** Roadmap items live in checked-in Markdown files.
  Autopilot must translate those items into supervisor tasks and remember which
  ones have already started so a run does not pick the same item twice.
- **Loop mode.** The operator should be able to run one item, then stop and
  review, rather than having autopilot silently churn through a whole roadmap.
- **Worktree isolation.** Unattended or experimental runs should be able to
  execute in an existing linked git worktree so the main repo stays clean and
  reviewable.
- **Approvals and blockers.** Policy-gated commands, verification steps, and
  memory indexing must still route through the persisted approval inbox; a
  blocked item must not advance until the operator resolves it.
- **Per-run reports.** Each autopilot run must leave behind a Markdown report
  that records what was attempted, what changed, what was verified, and what the
  final supervisor decision was.

The existing pieces already point in this direction:

- `AutopilotTask` and `load_plan_tasks` parse Markdown checkbox and numbered
  items into queue entries;
- `next_task` skips items already represented in the SQLite state store;
- the CLI supports `--worktree` for execution in a separate linked git
  worktree;
- the approval inbox persists requests and supports approve / reject / retry /
  stale workflows;
- task reports render verification outcomes, approval history, and final
  supervisor decisions.

The missing layer is a single documented model that ties these pieces together
and explains how autopilot scales from one bounded step to a repeatable batch
loop.

### Decision

Record the autopilot queue and batch execution model as the execution pattern
for roadmap-driven autopilot runs:

1. **Plan queue.** A plan is a Markdown file with checkbox or numbered items.
   Autopilot loads the items in file order and treats them as a persistent
   queue. The queue itself is the checked-in plan file; state about which items
   have started lives in the SQLite state store.
2. **Selection.** Autopilot selects the first plan item whose source label and
   text are not already represented by a stored task. It does not re-order,
   skip, or auto-complete items; the operator controls progression.
3. **Single-step loop.** Each `autopilot run` invocation selects one item,
   executes it through the supervisor, and stops. The operator reviews the diff,
   report, and approvals before invoking the next run. True unattended loop mode
   remains opt-in and guarded by the same dry-run, approval, and dirty-repo
   checks.
4. **Worktree isolation.** `--worktree PATH` runs the agent in an existing
   separate git worktree linked to the main repo. The state store and approval
   inbox remain under the main `--repo`; only the agent execution context moves
   to the worktree. Dirty checks apply to the worktree.
5. **Approvals and blockers.** Any policy-gated command, verification command,
   or memory step that requires approval records a request in the approval
   inbox. Autopilot blocks execution of the guarded action until the operator
   approves or rejects. Deny rules are stronger than approvals. Retries are
   explicit and audited.
6. **Per-run reports.** Each run writes a Markdown report from the stored task
   history, including the selected plan item, agent profile, iterations,
   verification results, approval requests, and the final supervisor decision.
   Reports are the primary hand-off artifact between autopilot and the operator.

### Consequences

Pros:

- Roadmap plans remain human-readable Markdown with ordinary checkboxes.
- Progress survives process restarts because started items are tracked in
  SQLite.
- Worktree isolation keeps the main repo clean without inventing a custom
  sandbox format.
- Approval and deny semantics stay consistent with the rest of the supervisor.
- Per-run reports make autopilot output reviewable and auditable.

Cons:

- Plan files and SQLite state can drift if items are edited after they have
  started;
- worktree setup is manual outside `ai-orch`;
- one-item-at-a-time default is slower than a fully unattended batch mode;
- reports depend on the existing Markdown reporter shape and may need extension
  as autopilot grows.

### Deferred

- Unattended multi-item loop mode without operator review between items.
- Parallel or concurrent autopilot runs over different plan items.
- Automatic worktree creation, pruning, or merge-back.
- Plan file auto-rewriting (checking off completed items in the Markdown file).
- Web dashboard or CI-driven batch scheduling.

### Revisit When

- operators ask for hands-off batch execution of a whole roadmap;
- worktree isolation becomes the default execution mode;
- plan items need richer metadata than Markdown checkboxes can express;
- external systems need to enqueue or query autopilot state through an API.

## ADR-0003: Trusted Completion And Approval Model

Date: 2026-07-01

### Context

Research and early MVP hardening both point to the same product position:
`ai-orch` should be a local supervisor for CLI agents, not another general
purpose agent framework. Its core promise is trusted completion: executor
agents may attempt work, but only the supervisor can mark a task as done after
independent verification passes.

The MVP already has the necessary pieces for this direction:

- supervisor-owned `continue` / `done` / `blocked` decisions;
- verification results persisted in SQLite;
- policy decisions before command execution;
- exact-command approval support for verification commands;
- read-only approval visibility in the TUI.

The missing product layer is an operator-friendly approval and audit workflow.

### Decision

Make the trusted completion and approval model the next product foundation:

- `done` means supervisor-controlled verification passed.
- Agent output alone must never mark a task as done.
- Approval grants permission to execute a specific action; it does not accept
  the task result and does not skip verification.
- Deny rules remain stronger than approvals and cannot be overridden by an
  approval request.
- Approval decisions must be persisted in the state store for auditability.
- CLI commands are the first interaction surface for approval handling.
- TUI actions may be added only as a thin layer over the same core approval
  operations.
- Strict verification mode and verified reports should reinforce the public
  product promise without changing the supervisor invariant.

The first implementation track is:

1. Add an approval request domain model and SQLite persistence.
2. Add CLI commands for listing, showing, approving, rejecting, and retrying
   approvals.
3. Integrate verification and Codebase Memory approval requests with the store.
4. Render approval timelines in status, TUI, and Markdown reports.
5. Add strict mode and verified report wording after the approval path is
   auditable.

### Consequences

Pros:

- strengthens the project's clearest differentiator;
- improves daily UX for policy-gated commands;
- creates an audit trail for risky actions;
- keeps the MVP local-first and CLI-first;
- avoids premature web dashboard or multi-agent complexity.

Cons:

- state schema and migration surface grows;
- approval semantics become security-critical;
- TUI work must avoid duplicating business logic from the CLI/core layer.

### Deferred

- MCP server mode;
- web dashboard;
- parallel multi-agent execution;
- auto-merge worktree workflows;
- marketplace or plugin ecosystem.

These remain valuable, but they should follow the trusted approval and
completion foundation.

### Revisit When

- users need organization-level policy sharing;
- approvals need to cover long-lived capabilities rather than single actions;
- worktree isolation becomes the default execution mode;
- external systems need to drive `ai-orch` through MCP or CI.

## ADR-0002: Defer PyYAML Until Config Needs Broader YAML Compatibility

Date: 2026-06-28

### Context

The MVP uses a small internal parser for `.ai-orch/config.yaml`. It supports the
current starter config shape and avoids adding a production dependency.

### Decision

Keep the minimal parser for now. Do not add PyYAML until the config format needs
broader YAML features such as anchors, nested arbitrary maps, multiline scalars,
or third-party generated YAML compatibility.

### Consequences

Pros:

- no new production dependency;
- predictable supported config subset;
- smaller packaging surface for the MVP.

Cons:

- config syntax remains intentionally limited;
- future YAML compatibility work may require a parser migration.

### Revisit When

- users need standard YAML features not supported by the minimal parser;
- config ownership moves beyond the starter schema;
- schema validation is introduced alongside a full YAML parser.

## ADR-0001: MVP Is a Supervisor over CLI Agents

Date: 2026-06-25

### Context

The project needs a local orchestrator for CLI-capable AI systems and coding
agents.

### Decision

The MVP core path is a control plane over CLI/headless interfaces, not a GUI
macro layer over application windows.

### Consequences

Pros:

- higher reliability;
- simpler logging;
- easier testing;
- easier task resume behavior;
- fewer UI dependencies.

Cons:

- some agents may need dedicated adapters;
- GUI automation remains only a fallback outside the MVP core path.

### Alternatives

- RPA-first automation over windows;
- full OpenHands integration;
- LangGraph/MAF as the first-day runtime.
