# Post-MVP Roadmap

This roadmap records the development direction after the current local MVP
baseline. It is based on the reviewed product research from 2026-07-01 and the
current repository architecture.

## Product Position

`ai-orch` is a local developer control plane for CLI agents.

The core promise is:

```text
AI agents execute; the supervisor decides done.
```

The project should not compete as a broad agent framework or hosted coding
platform. Its strongest niche is trusted local execution for real repositories:
bounded agent loops, policy-gated commands, persisted state, and independent
verification before completion.

## Guardrails

- Keep the supervisor as the only owner of final task status.
- Keep verification as the source of truth for `done`.
- Keep execution local-first and subprocess-based.
- Keep security decisions explicit and auditable.
- Keep dependencies minimal until a dependency removes clear product risk.
- Prefer CLI-first flows before TUI, web, MCP, or multi-agent surfaces.

## Phase 1. Trust And Launch

Goal: make the project understandable, installable, and credible.

- Publish a clear release and install path.
- Tighten README positioning around verification-gated completion.
- Add comparative documentation for adjacent tools.
- Add three quick-start examples.
- Add strict verification mode.
- Add verified report wording to Markdown reports.

Exit criteria:

- a new user can install and run the demo path in minutes;
- the README clearly explains why `ai-orch` exists;
- release checks cover packaging readiness.

## Phase 2. Approval UX

Goal: turn existing policy approval mechanics into a daily workflow.

- Add a persisted approval request model.
- Add `approvals list`, `approvals show`, `approvals approve`,
  `approvals reject`, and `approvals retry`.
- Integrate verification approval requests with the state store.
- Integrate Codebase Memory approval requests with the same model.
- Render approval timelines in status, TUI, and Markdown reports.
- Keep deny rules stronger than approvals.

Exit criteria:

- a user can resolve pending approvals without copying exact command strings;
- approval decisions are visible in reports;
- tests cover approve, reject, retry, deny precedence, and stale approvals.

## Phase 3. Isolation And Extensibility

Goal: reduce repository risk and make adapters easier to extend.

- Add opt-in git worktree execution for task runs.
- Add structured adapter output fields:
  `summary`, `files_changed`, `tool_actions`, `exit_reason`, and
  `uncertainty`.
- Add YAML-configured generic adapters before introducing a plugin runtime.
- Add basic metrics:
  iterations-to-done, verification pass rate, approval frequency, and adapter
  failure counts.

Exit criteria:

- a failed task can leave the main repository clean;
- reports can use structured adapter signals rather than raw text only;
- common custom CLI adapters do not require source changes.

## Phase 4. Ecosystem

Goal: expose `ai-orch` to other local tools without weakening the core model.

- Add headless CI mode with stable exit codes.
- Add a no-server MCP/ACP operation boundary and a stable local operator client
  for `start_task`, `get_status`, approvals, retry, and trace export.
- Defer MCP server mode until the local client contract is stable and reviewed.
- Improve Codebase Memory preflight into a more automatic context layer.
- Add optional JSON trace export.

Exit criteria:

- CI can run `ai-orch` without interactive prompts;
- external tools can drive the same supervisor and approval semantics;
- trace output remains local and redacted.

## Phase 5. Multi-Agent

Goal: add multi-agent behavior only after trust, audit, and isolation are solid.

- Add agent fallback scoring.
- Add agent roulette for retrying blocked tasks with another configured agent.
- Add parallel subtask execution only after worktree isolation is reliable.
- Add cross-agent voting only when structured outputs are available.

Exit criteria:

- agent choice is based on stored verification outcomes;
- parallel work cannot corrupt the main checkout;
- multi-agent features remain optional.

## Immediate Implementation Track

The next bounded work should follow this sequence:

- [x] Record ADR-0003 for trusted completion and approvals.
- [x] Add approval persistence to the state store.
- [x] Add a guarded autopilot mode that can select the next plan item and
  dry-run it through the supervisor.
- [x] Add approval CLI commands.
- [x] Wire verification `needs_approval` results into stored approval requests.
- [x] Render approval history in reports and TUI.
- [x] Add strict mode and verified report wording.

## Next Autopilot Track

The next bounded work should make unattended development practical while keeping
the supervisor conservative:

- [x] Add `approvals retry` for approved requests.
- [x] Persist Codebase Memory approval requests through the shared approval model.
- [x] Add a real-agent execution profile before autopilot execution.
- [x] Add opt-in git worktree isolation for autopilot runs.
- [x] Add an autopilot operator runbook with dry-run, execute, approval, retry, and report commands.

## Next Development Track

The next bounded work should move `ai-orch` from guarded autopilot mechanics to
repeatable real-agent operation:

- [x] Add stale approval detection and clearer retry result history.
- [x] Add a real-agent smoke-run fixture and documented operator script.
- [x] Add structured adapter output fields:
  `summary`, `files_changed`, `tool_actions`, `exit_reason`, and `uncertainty`.
- [x] Add YAML-configured generic adapter profiles.
- [x] Add a local metrics summary for iterations, verification pass rate,
  approvals, and adapter failures.
- [x] Prepare the release and install path.

## Explicit Non-Goals For The Next Iteration

- Web dashboard.
- Parallel agent swarm.
- Auto-merge.
- Organization policy server.
- New production dependencies for TUI or YAML parsing.
