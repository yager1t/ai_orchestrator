# Architectural Decisions

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
