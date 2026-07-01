# Changelog

## Unreleased

- Added state-store persistence and migrations for approval requests.
- Added a guarded `ai-orch autopilot` command for selecting and dry-running
  roadmap items through the supervisor.
- Added an autopilot agent execution profile and pre-execution availability
  check for non-mock agents.
- Added opt-in `--worktree` isolation for autopilot execution in an existing
  linked git worktree.
- Added an autopilot operator runbook covering dry-run, execute, approval,
  retry, report, and stop-condition workflows.
- Added `ai-orch approvals list/show/approve/reject` for persisted approval
  requests.
- Added `ai-orch approvals retry` for rerunning approved request commands while
  preserving deny-rule precedence.
- Persisted supervisor verification `needs_approval` results into the approval
  inbox.
- Persisted Codebase Memory `needs_approval` results into the shared approval
  inbox.
- Rendered approval request history in Markdown reports and read-only TUI
  approval/status views.
- Added `verification.strict` to disable default verification fallback and make
  missing checks fail closed.
- Added explicit verified/not-verified wording to Markdown task reports.
- Added ADR-0003 for the trusted completion and approval model.
- Added the post-MVP roadmap for approval UX, launch, isolation, ecosystem, and
  multi-agent development phases.
- Updated the backlog with the next approval inbox and trust-building work.
- Marked selected PM workflow adaptations as implemented.
- Normalized the legacy CLI-supervisor ADR text.
- Added `ai-orch release-check` for release packaging readiness checks.
- Added opt-in `ai-orch start --use-memory` prompt enrichment from read-only memory preflight context.
- Added `ai-orch memory preflight --area supervisor|adapter|release` for read-only planning context.
- Added manual Codebase Memory playbooks for supervisor, adapter, and release review work.
- Documented the manual Codebase Memory workflow before supervisor planning automation.
- Added CLI and config support for the optional Codebase Memory provider.
- Added an optional Codebase Memory client wrapper behind `ProcessRunner` and policy approval.
- Added Codebase Memory MCP research notes for optional external memory integration.
- Added a shipping packet template for reviewer-ready release handoffs.
- Added PM-derived task template sections for intent, assumptions, negative scenarios, and verification mapping.
- Added mypy type checking to the development dependencies and CI.
- Refreshed README project descriptions, runtime notes, and documentation map.
- Kept root `REVIEW.md` as a local ignored review note.
- Updated review notes to mark minor P3 follow-ups as addressed.
- Replaced the legacy mojibake backlog with a current deferred-work list.
- Replaced the legacy mojibake MVP implementation plan with a current status plan.
- Replaced the legacy mojibake architecture notes with a current component overview.
- Changed internal ProcessRunner callers to use `RunOptions`.
- Added Python 3.12/3.13 CI matrix coverage.
- Added normalized round 2 review notes under `docs/review/`.
- Added Ruff linting to the development dependencies and CI.
- Added `RunOptions` for ProcessRunner runtime controls.
- Added pip dependency caching to GitHub Actions CI.
- Added configurable scripted results for the mock agent.
- Documented PolicyEngine scope as defense-in-depth and added redaction guidance.
- Improved follow-up prompts with original task context and tail-focused failure excerpts.
- Added redaction for secret-like tokens in stored agent and verification outputs.
- Hardened built-in policy matching against wrapper commands and newline-separated commands.
- Updated project status docs for runtime controls, event logs, and migration guidance.
- Added an explicit version-to-version SQLite migration dispatcher.
- Documented the decision to defer PyYAML until broader YAML compatibility is needed.
- Added cancellation polling so running agent subprocesses can be terminated after `ai-orch cancel`.
- Added stable `event=...` fields to supervisor and process runner logs.
- Added `orchestrator.max_runtime_sec` as a cooperative supervisor runtime budget.
- Added supervisor cancellation checks between agent and verification steps.
- Documented task cancellation and log-level runtime controls.
- Added `ai-orch cancel <task_id>` for marking stored tasks as cancelled.
- Added supervisor agent session cleanup on completion and keyboard interruption.
- Added subprocess cleanup on keyboard interruption.
- Changed process timeout handling to terminate subprocesses before force-killing them.
- Added `--log-level` to enable safe metadata logs from the CLI.
- Added adapter metadata logging without prompt or output capture.
- Added state store metadata logging without task prompt or output capture.
- Added supervisor metadata logging without task prompt or agent output capture.
- Added verification runner metadata logging without command output capture.
- Added subprocess runner metadata logging without command output capture.
- Added a lightweight SQLite migration helper for state store schema version checks.
- Added a post-review backlog for deferred architecture and runtime follow-ups.
- Documented MVP secret storage guidance.
- Documented agent and verification timeout defaults.
- Added a SQLite schema version marker for the state store.
- Improved supervisor no-change detection so noisy agent logs do not reset the counter.
- Changed fallback verification compile command to avoid hardcoding the package directory.
- Improved built-in policy command matching to avoid substring false positives.
- Added read-only `ai-orch tui logs` iteration log view.
- Added read-only `ai-orch tui current` latest iteration view.
- Added MCP/ACP research notes for future adapter spikes.
- Added read-only `ai-orch tui approvals` pending approval view.
- Added release checklist documentation.
- Added read-only `ai-orch tui tasks` task list.
- Added dedicated Kimi and Gemini CLI adapter wrappers with native defaults.
- Added read-only `ai-orch tui status` task view.
- Added structured verification `argv` config support alongside legacy `run` strings.
- Documented verification approval rules and CLI usage.
- Added exact-command approval support for `ai-orch verify --approve-command`.
- Added `ai-orch --version` for release/version visibility.
- Changed verification command execution to use parsed argv without `shell=True`.
- Improved markdown task report summaries with iteration, verification, and final decision totals.
- Added GitHub Actions CI for pytest, compileall, ai-orch verification, and whitespace checks.
- Documented the current MVP project status and language policy for English project docs/logs with Russian user-facing replies.
- Added a minimal decision engine for supervisor `done` / `continue` / `blocked` outcomes.
- Added supervisor retry flow that sends a follow-up prompt after failed verification.
- Added SQLite state storage for tasks, iterations, and verification runs.
- Added `ai-orch status <task_id>` for reading stored task history.
- Added `ai-orch resume <task_id>` for rerunning a stored task from SQLite context.
- Added config-driven verification commands for `start`, `resume`, and `verify`.
- Added policy checks before executing configured verification commands.
- Added config-driven policy deny and require-approval patterns.
- Added markdown task reports from stored SQLite task history.
- Added failed verification output excerpts to markdown reports.
- Added a minimal generic CLI adapter backed by a central process runner.
- Added config-driven agent selection for mock and generic CLI agents.
- Added policy checks before executing configured generic CLI agent commands.
- Added a minimal Codex exec adapter with policy checks before subprocess execution.
- Added Codex exec JSON and JSONL output normalization.
- Added Codex exec resume support for adapter continuations.
- Added a minimal Claude headless adapter with policy checks and JSON output normalization.
- Added starter config examples and CLI integration coverage for Codex and Claude agents.
- Added fallback agent routing from project config.
- Added `ai-orch agents --check` availability diagnostics.
- Added stored blocked iterations for unavailable agents so status and reports show the blocker.
- Changed supervisor flow to skip verification when an agent step is already blocked or failed.
- Added configurable no-change detection in the supervisor loop.
- Included repository status snapshots in supervisor no-change detection.
- Ignored local runtime/cache artifacts in supervisor repository snapshots.
- Skipped supervisor no-change blocking when repository snapshots are unavailable.
- Added config-driven Kimi and Gemini CLI agent aliases.
- Added CLI integration coverage for Kimi and Gemini agent aliases.
- Added policy coverage for Kimi and Gemini agent aliases.
- Added availability diagnostics coverage for Kimi and Gemini agent aliases.
- Documented supported MVP agent config types.
- Preserved explicit empty args for Kimi and Gemini CLI aliases.
- Added CLI start coverage for Kimi and Gemini default alias argv rendering.
- Preserved built-in hard-deny policy rules when custom deny rules are configured.
- Preserved explicit empty args for Codex and Claude headless adapters.

## 0.1.0 — bootstrap

- Добавлен стартовый комплект проекта.
- Добавлены правила Codex в `AGENTS.md`.
- Добавлено агентское распределение задач.
- Добавлен минимальный Python-каркас.
