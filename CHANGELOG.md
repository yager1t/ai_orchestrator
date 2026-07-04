# Changelog

## Unreleased

- Allow `ai-orch autopilot queue show --plan PLAN <plan_item_id>` as a
  read-only compatibility form that validates the selected item belongs to the
  requested plan, so operators can reuse the same `--plan` habit from queue
  history commands without changing queue state.
- Show persisted queue item id in `ai-orch autopilot queue list` and `queue status`
  output so operators can copy the id for `queue show`, `queue requeue`, or
  `queue skip` directly from history views, without changing queue state.
- Show persisted queue item id in `ai-orch autopilot queue run-next` dry-run
  output so operators can immediately inspect the selected item with
  `queue show <plan_item_id>` before running `--execute`.
- Show persisted queue item ids in `ai-orch autopilot queue run-batch` dry-run
  output so operators can immediately inspect the selected item with
  `queue show <plan_item_id>` before executing.
- Show persisted queue item id at the start of `ai-orch autopilot queue run-next
  --execute` output so real-agent logs can be tied back to
  `queue show <plan_item_id>`, without changing execution behavior.
- Show persisted queue item id at the start of each item's output in `ai-orch
  autopilot queue run-batch --execute` so real-agent logs can be tied back to
  `queue show <plan_item_id>`, without changing execution behavior.
- Persist selected fixed worktree paths for `ai-orch autopilot queue run-batch
  --worktree PATH` runs so queue details, queue history views, and task reports
  identify the execution worktree.
- Added `ai-orch autopilot worktree-overview --cleanup-status STATUS` to show
  only git worktrees labeled `candidate`, `needs_review`, or `do_not_remove`,
  helping operators focus cleanup review without deleting or pruning anything.
- Added a read-only cleanup candidate report to `ai-orch autopilot worktree-overview`
  that labels each shown worktree as `candidate`, `needs_review`, or
  `do_not_remove` for operator review, and prints cleanup counts in the summary,
  without deleting or pruning anything.
- Documented a manual worktree cleanup checklist with review gates before an
  operator removes old worktrees; no cleanup automation was added.
- Added `ai-orch autopilot worktree-overview --merged-only` to show only git
  worktrees whose branch is merged into the review repo HEAD according to strict
  ancestry, helping operators focus cleanup review without deleting or pruning
  anything.
- Added `ai-orch autopilot worktree-overview --unlinked-only` to show only git
  worktrees not linked to the review repo, helping operators focus cleanup
  review on potentially orphaned worktrees without deleting or pruning anything.
- Added a read-only summary line to `ai-orch autopilot worktree-overview` that
  shows total, shown, dirty, and unlinked counts after filters so operators can
  quickly understand review scope without deleting or pruning anything.
- Added `ai-orch autopilot worktree-overview --dirty-only` to show only git
  worktrees with uncommitted or untracked changes, making cleanup review more
  focused without deleting or pruning anything.
- Added `ai-orch autopilot worktree-overview --branch-filter TEXT` to show only
  git worktrees whose branch name contains TEXT, helping operators focus cleanup
  review on matching branches without deleting or pruning anything.
- Added a review hint to `ai-orch autopilot worktree-overview` explaining that
  strict ancestry can keep `merged=no` after squash merges and pointing
  operators to read-only follow-up commands before cleanup.
- Added `ai-orch autopilot worktree-overview --base-dir DIR` to inspect git
  worktrees under a base directory, including linked branch, whether the branch
  is merged into the review repo, merge-in-progress state, dirty state, and
  last modified time, without creating, deleting, or pruning anything.
- Added `ai-orch autopilot queue show <plan_item_id>` to display a selected
  queue item's status, source, task text, task id, report path, selected
  worktree, and blocker/skip reason without changing queue state.
- Added `ai-orch autopilot queue skip` to mark a selected `created` or `blocked`
  queue item as `skipped` with a required operator reason after review. The
  command is dry-run by default and never executes or deletes the item.
- Added `ai-orch autopilot queue requeue` to move a selected `blocked` queue
  item back to `created` after operator review, clear stale blocker metadata,
  and leave the item ready for a future queue run without executing it
  automatically.
- Added `--max-runtime-sec` to `ai-orch autopilot queue run-next` and
  `run-batch` so operators can optionally override the configured supervisor
  runtime budget per run; when the budget is exhausted the queue item is
  recorded as `blocked` with reason `Runtime budget exhausted` and a report is
  still written, without changing default execution semantics.
- Added `ai-orch autopilot queue recover-in-progress` to review interrupted
  queue runs and mark stale `in_progress` items blocked with an operator reason.
- Added `ai-orch memory preflight` summary line showing total, passed, and failed
  step counts while preserving existing provider execution semantics.
- Added `ai-orch export <task_id>` to export an existing task's stored summary,
  iterations, verification results, and approvals as local JSON without changing
  supervisor execution semantics.
- Added `--redact` flag for `ai-orch export` to omit bulky raw agent output and
  verification streams from the exported JSON without changing stored task state.
- Added top-level trace metadata (`schema_version`, `exported_at`, `task_id`,
  `redaction_mode`) to `ai-orch export` JSON output without changing stored task state.
- Added `ai-orch ci` headless CI entry point that runs configured verification
  commands and release readiness checks with stable exit codes for CI environments.
- Changed queue sync to create a fresh `created` item when a plan or backlog
  line is rewritten with different task text instead of reusing stale history.
- Added `ai-orch autopilot queue reconcile` to find stale `created` queue items
  whose source plan task is no longer open and, with `--apply`, mark them
  `skipped`.
- Added `--all-plans` views for `ai-orch autopilot queue list/status` so
  operators can review every persisted queue source without selecting one plan
  file at a time.
- Added queue history filters for `ai-orch autopilot queue list/status`,
  including repeated `--status` filters and display limits for focused operator
  review.
- Added `ai-orch autopilot queue sync-backlog` to load open P0/P1/P2 backlog
  bullets directly into the persisted queue without manually copying them into
  `docs/NEXT_AUTOPILOT_PLAN.md`.
- Enabled guarded `ai-orch autopilot queue run-batch --execute
  --rotate-worktrees BASE_DIR` execution, selecting one clean pre-created
  worktree per queue item and stopping on approvals/blockers/failures.
- Persist selected rotated worktree paths on autopilot queue items and display
  them in queue status/list output and task reports when present.
- Added `ai-orch autopilot queue run-batch --rotate-worktrees BASE_DIR` dry-run
  selection and validation, mutually exclusive with `--worktree`.
- Recorded ADR-0005 for optional per-task worktree rotation in autopilot batch
  runs.
- Show generated task report paths in `ai-orch autopilot queue list/status` for
  queue items with completed reports.
- Recorded the first guarded real-agent `ai-orch autopilot queue run-batch --execute --max-items 1` smoke result in `docs/AUTOPILOT_BATCH_RUN_LOG.md`.
- Added `ai-orch autopilot queue run-batch` as a guarded serial loop that
  dry-runs by default, executes up to a configurable `--max-items` count, stops
  on approvals/blockers/failures, and writes a Markdown report for each executed
  queue item.
- Added `ai-orch autopilot queue status` to summarize persisted queue counts and
  recent started/done/blocked/skipped items without starting batch execution.
- Added per-run Markdown report generation for `ai-orch autopilot queue run-next --execute`.
- Added `ai-orch autopilot queue run-next` to select the next persisted plan
  item, dry-run by default, execute at most one item, update the queue status,
  and stop on the supervisor result.
- Added `ai-orch autopilot queue sync/list` for loading Markdown plan items
  into the persisted queue without duplicates and displaying queue status.
- Added a persisted autopilot plan-item queue with `StoredPlanItem`, SQLite
  schema, `StateStore` helpers, and tests for recording and listing plan items
  without batch execution.
- Added a Python quick-start example for verification-gated Python repositories.
- Added a docs-only quick-start example for verification-gated documentation repositories.
- Added a Node quick-start example for verification-gated Node repositories.
- Added state-store persistence and migrations for approval requests.
- Added a guarded `ai-orch autopilot` command for selecting and dry-running
  roadmap items through the supervisor.
- Added an autopilot agent execution profile and pre-execution availability
  check for non-mock agents.
- Added opt-in `--worktree` isolation for autopilot execution in an existing
  linked git worktree.
- Added opt-in `ai-orch start --worktree PATH` isolation for task runs by
  reusing the autopilot worktree validation behavior.
- Added an autopilot operator runbook covering dry-run, execute, approval,
  retry, report, and stop-condition workflows.
- Added `ai-orch approvals list/show/approve/reject` for persisted approval
  requests.
- Added `ai-orch approvals retry` for rerunning approved request commands while
  preserving deny-rule precedence.
- Added stale approval detection and persisted retry result history for
  approval requests.
- Added a real-agent smoke fixture and operator script for exercising the
  `generic_cli` adapter without external AI credentials.
- Added structured adapter output fields on `AgentResult` and persisted them in
  iteration history, reports, status, and TUI views.
- Added YAML-configured generic adapter profiles for reusable CLI defaults.
- Added `ai-orch metrics` for local iteration, verification, approval, and
  adapter failure summaries.
- Added the `ai-orch` console script and install guide for local release smoke
  testing.
- Switched the project autopilot config to the available Claude real-agent path
  with mock fallback, and resolved CLI shims before subprocess execution.
- Added visible autopilot progress heartbeats for long-running real-agent
  subprocesses.
- Added per-agent CLI environment overrides and switched the local autopilot
  default agent to the configured Kimi Code CLI with Claude and mock fallbacks.
- Recorded a Kimi Code real-agent autopilot smoke run and read subprocess
  output as UTF-8 with replacement to avoid Windows locale decode noise.
- Persisted supervisor verification `needs_approval` results into the approval
  inbox.
- Persisted Codebase Memory `needs_approval` results into the shared approval
  inbox.
- Rendered approval request history in Markdown reports and read-only TUI
  approval/status views.
- Added `verification.strict` to disable default verification fallback and make
  missing checks fail closed.
- Added explicit verified/not-verified wording to Markdown task reports.
- Added ADR-0004 for the autopilot queue and batch execution model, covering
  persisted plan queues, single-step loop mode, worktree isolation,
  approvals/blockers, and per-run reports.
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
