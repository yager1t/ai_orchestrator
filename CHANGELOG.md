# Changelog

## Unreleased

## 0.5.1 — PyPI package channel

- Changed the public PyPI distribution name to `ai-orch` because
  `ai-orchestrator` is already owned by a different PyPI project. The Python
  import package remains `ai_orchestrator`, and the console command remains
  `ai-orch`.

## 0.5.0 — Typed Action Broker and policy tiers

- Added the v0.5 typed action broker envelope and action journal enrichment for
  brokered actions, including request, risk, provenance, policy decision,
  approval reference, execution outcome, and redacted stdout/stderr previews.

- Hardened action policy tiers so dangerous and secret-sensitive action
  classifications are denied before executor invocation, and approved retries
  cannot override those denials.

- Routed legacy approval retry execution through the action broker, added
  replay-safe handling for completed broker actions by idempotency key, and
  expanded recovery to detect stale started actions without active leases.

- Extended JSON trace exports with normalized `action_journal` entries and
  improved Markdown reports with readable action request, risk, decision,
  outcome, preview, and provenance details.

## 0.4.0 — AgentTrace and durability core

- Added v0.4 AgentTrace durability metadata to task events, including run,
  session, iteration, correlation, actor, summary, payload preview, and
  idempotency fields with a schema migration for existing state stores.

- Instrumented supervisor runs with durable lifecycle events and checkpoints for
  task creation/resume, iteration start/finish, agent calls/results,
  verification start/finish, supervisor decisions, terminal task states, and
  interrupted execution inspection.

- Added policy/tool audit events for brokered approvals, denials, command
  starts, and command finishes, and expanded task reports with
  recovery/checkpoint summaries.

## 0.3.0 — first-run wizard and product commands

- Added `ai-orch onboard`, a beginner-facing first-run wizard with text and
  JSON output for config, state/report directories, worker CLI detection,
  mock-vs-real mode, recommended next steps, and scenario commands.

- Added product commands over the existing supervisor loop: `ai-orch fix`,
  `ai-orch task`, `ai-orch analyze`, `ai-orch review`, and `ai-orch docs`.
  They apply beginner role templates while preserving verification-gated
  completion.

- Improved first-run error guidance for missing config, missing verification,
  and unavailable worker setup by printing concrete next commands.

- Improved end-of-run CLI summaries with task id, result, files changed,
  verification status, report path when written, and follow-up commands.

- Updated v0.3 documentation and release checks so onboarding wizard and
  product-command docs are release-gated.

## 0.2.6 — product-ready onboarding

- Added `ai-orch demo`, a safe first-value command that runs the bundled
  docs-only quickstart through the real supervisor, verification, report, and
  next-step flow without requiring external AI credentials.

- Added setup presets with `--profile` for `codex-safe`, `python-project`,
  `node-project`, `docs-project`, and `readonly-review`, plus clearer setup and
  doctor readiness summaries that distinguish mock demo mode from real-worker
  readiness and external CLI login expectations.

- Reworked first-run documentation around two user paths: "try it safely" with
  `ai-orch demo`, and "use it on my project" with Codex-first setup, doctor,
  and start commands.

- Added package-channel guidance for `pipx`, a dedicated macOS install guide,
  and release checks that require the onboarding docs and key install/demo
  content.

## 0.2.5 — connector diagnostics and Linux install

- Added `ai-orch doctor agents` with text and JSON connector diagnostics for
  configured/enabled state, CLI availability, auth model, and native API-adapter
  status.

- Documented the `0.2.5` connector support matrix: Codex, Claude, Gemini, Kimi,
  Generic, and Mock are CLI/headless or wrapper-based; native provider API
  adapters remain post-0.2.5 work.

- Added operator-facing progress output for `ai-orch start` and `resume`,
  including run headers, supervisor progress milestones, mock-agent smoke-test
  warnings, final result status, and next commands.

- Added `INSTALL_LINUX.sh`, `scripts/install_linux.sh`, and
  `docs/LINUX_INSTALL.md` for Ubuntu/Linux installs that regenerate local config,
  create state/report directories, offer an opt-in Python 3.12 `apt` bootstrap,
  and fall back to `mock` when real worker CLIs are unavailable.

- Updated generated Windows and Linux launchers to prepend the local virtual
  environment to `PATH`, so verification commands that invoke `python` work
  without manually activating `.venv`.

## 0.2.4 — double-click Windows installer

- Added a root `INSTALL_WINDOWS.cmd` entry point for downloaded release ZIPs and
  changed the Windows `.cmd` installer to keep the console window open after
  success or failure, including explicit next commands and log guidance.

- Improved the missing-Python path with a concrete
  `INSTALL_WINDOWS.cmd /install-python` command and an opt-in winget-based
  Python 3.12 bootstrap before continuing setup.

- Changed the missing-Python flow to offer the winget Python install
  interactively in the same installer window before failing.

## 0.2.3 — clearer Windows first-run UX

- Improved the Windows installer with install transcripts under
  `.ai-orch/install-logs/`, clearer failure output, a final next-steps summary,
  and a root `ai-orch.cmd` launcher that prints common commands and runs
  diagnostics when called without arguments.

## 0.2.2 — Windows installer config refresh

- Changed the Windows installer to create local state/report directories and
  refresh `.ai-orch/config.yaml` for the current machine by default, with
  `-KeepConfig` available for developers who intentionally want to preserve an
  existing config.

## 0.2.1 — Windows installer and onboarding

- Added `docs/USER_GUIDE.md` as a practical operator guide covering install,
  task runs, verification, approvals, TUI views, memory, autopilot, PlanGraph,
  evaluations, recovery, and safety rules.

- Added beginner-friendly `ai-orch setup` and `ai-orch doctor` commands to
  generate safe local config, detect installed worker CLIs, and diagnose setup
  readiness without storing secrets.

- Clarified API key onboarding guidance: `ai-orch` setup does not collect
  credentials, worker CLIs should authenticate through their native login flows
  when possible, and raw provider keys belong in external environment or secret
  stores rather than `.ai-orch/config.yaml`.

- Added a simple Windows installer pair, `scripts/install_windows.ps1` and
  `scripts/install_windows.cmd`, plus `docs/WINDOWS_INSTALL.md` for
  one-command local setup.

## 0.2.0 — robust autopilot

- Added durable SQLite `task_events` with append/list state-store APIs and
  exposed the task timeline in Markdown reports and JSON trace exports.

- Added durable SQLite `action_records` with idempotency keys, completion
  updates, report/export visibility, and supervisor audit records for
  verification commands.

- Added action-record leases and heartbeats with TTL-based expiry, reacquire,
  release, stale-lease listing, and report/export visibility.

- Added dry-run-by-default `ai-orch recover` to find interrupted `running`
  tasks and expired action leases, with `--apply --reason` recovery that blocks
  tasks, fails expired actions, clears leases, and writes recovery events.

- Added a replayable task timeline read model, exposed through
  `StateStore.list_task_timeline()`, `ai-orch timeline`, Markdown reports, and
  JSON trace exports.

- Added durable PlanGraph storage with graph, node, dependency, status, and
  attempt APIs as the first Stage 2 foundation slice.

- Added `ai-orch autopilot plan` CLI commands for listing, creating, showing,
  updating, and extending durable PlanGraphs with JSON output.

- Added durable links from autopilot queue items to PlanGraph roots, including
  `ai-orch autopilot queue link-plan-graph` dry-run/apply flows and JSON output.

- Added durable replan decisions for failed verification retries, with supervisor
  persistence plus timeline, Markdown report, and JSON trace export visibility.

- Linked autopilot queue execution to PlanGraph root node lifecycle: execution
  start marks the node `in_progress` and increments attempts, completion marks
  it `done` or `blocked`, and unlinked replan decisions are attached to the
  graph/node references.

- Added idempotent PlanGraph follow-up node creation from linked replan
  decisions, producing pending `replan-{id}` nodes that depend on the failed
  root node.

- Added ready PlanGraph node selection with dependency gating and
  `ai-orch autopilot plan ready` text/JSON output.

- Added dry-run-by-default `ai-orch autopilot plan run-next` to claim a ready
  PlanGraph node, run it through the supervisor, update node status and
  attempts, write reports, and materialize replan follow-up nodes.

- Added dry-run-by-default `ai-orch autopilot plan run-batch` to process
  multiple ready PlanGraph nodes serially, recompute dependency readiness after
  each success, and stop on the first blocked node.

- Added the first typed tool broker foundation with `ToolSpec`, `ToolCall`,
  `ToolResult`, explicit risk tiers, stable idempotency keys, and
  JSON-serializable action payload helpers.

- Added `ToolBroker` to route typed tool calls through `PolicyEngine`, persist
  policy decisions and tool results in `action_records`, and require approval
  for non-read risk tiers.

- Routed supervisor verification action audit through `ToolBroker` while
  preserving durable `verification_command` records and idempotency keys.

- Added durable approval request creation for brokered `needs_approval` tool
  calls, including `approval_id`/`action_id` correlation in action results while
  keeping policy denies as hard stops.

- Added approved retry execution for brokered command/argv tool calls through
  `ai-orch approvals retry`, with separate durable retry action records and
  deny-rule rechecks before execution.

- Added a typed `ToolExecutorRegistry` with exact and namespace-prefix lookup,
  plus a reusable process command/argv executor used by brokered approval
  retries.

- Added concrete `fs.read` and `fs.write` executors with repository-root path
  containment and registered the `fs.` namespace for approved broker retries.

- Added a brokered `memory.` executor namespace backed by `CodebaseMemoryClient`,
  including exact-command approval reuse for approved Codebase Memory retries.

- Added typed `ToolCall` factory helpers for `fs.*`, `process.*`, `memory.*`,
  and verification audit calls, and moved supervisor verification audit to the
  verification factory.

- Replaced remaining production broker retry `ToolCall` restoration with a
  typed factory path while preserving durable fs/process/memory action-record
  and timeline visibility.

- Added durable memory lessons, blocked-run and failed-verification reflection
  records, stale-memory filtering, memory influence logs, non-authoritative
  lesson injection into supervisor planning context, report/export/timeline
  visibility, and read-only `ai-orch memory lessons`, `ai-orch memory
  influence`, `ai-orch tui memory-lessons`, and `ai-orch tui memory-influence`
  inspection commands.

- Ranked supervisor memory lesson selection by active task text relevance and
  added configurable `memory.max_lessons` without introducing new production
  dependencies.

- Added stable run ids to Markdown reports, replay timelines, and JSON trace
  exports, extended traces with unsafe action accounting, and added a local
  golden/chaos/security evaluation suite exposed through `ai-orch eval golden`
  with text and JSON summaries.

- Made local evaluation suites executable through the supervisor and split them
  into `ai-orch eval golden`, `eval chaos`, `eval redteam`, and `eval all`
  commands with text and JSON summaries.

- Added dry-run-by-default `ai-orch autopilot loop` for guarded unattended queue
  execution with `--execute`, `--max-items`, `--stop-on-risk`, runtime/attempt/
  action budget ledgers, durable dead-letter records for blocked loop items,
  and batch summary/report reuse without adding auto-push, auto-merge, deploy,
  or destructive cleanup behavior.

- Persisted autopilot loop budget ledgers in SQLite with selected/processed
  item counts, runtime/action/attempt budgets, dead-letter counts, stop reason,
  result code, selected item ids, and `ai-orch autopilot loop-history`
  inspection.

- Moved internal review notes, local operator logs, completed autopilot plans,
  and exploratory research reports out of the public docs tree into the ignored
  local `.private/docs/` archive, and added `docs/PUBLICATION_POLICY.md`.

- Added `.github/CODEOWNERS` and a local `.pre-commit-config.yaml` with
  `ruff check` and `ruff format` hooks for review and formatting hygiene.

- Documented the migration no-op contract with a regression test for matching
  current and target schema versions.

- Reused CLI state-store instances per repository DB path and extracted the
  repeated `--max-runtime-sec` parser option into a helper.

- Added a SQLite `plan_items(status, plan_item_id)` index for status-only queue
  scans, including a schema migration for existing state stores.

- Fixed CLI runtime-budget validation so every parsed `--max-runtime-sec` option
  is rejected consistently when it is zero or negative.

- Fixed `ai-orch verify` exit-code handling so policy-denied verification
  commands are reported but do not fail CI-style verification gates; commands
  that require approval still return a failing exit code.

- Fixed autopilot task de-duplication so started plan items are matched by the
  exact persisted `Source` line instead of substring matches against source or
  task text, avoiding false skips when line numbers or task text overlap.

- Fixed `ai-orch autopilot queue preflight` agent profile handling so a selected
  agent missing from `config.agents` is reported as unconfigured, marks preflight
  as risk, and returns `next_action=fix_agent` instead of showing unknown fields
  as if the profile were usable.

- Added read-only `--json` output to `ai-orch autopilot queue list` for selected
  plan and `--all-plans` views, including filtered queue rows, status counts,
  limit metadata, selected plan scope, and problem summary.

- Added read-only `--json` output to `ai-orch autopilot queue skip` dry-run and
  `--apply` flows so scripts can inspect the selected created or blocked item,
  plan ownership scope, skip reason, mode, and resulting status.

- Added read-only `--json` output to `ai-orch autopilot queue requeue`
  dry-run and `--apply` flows so scripts can inspect the selected blocked item,
  plan ownership scope, mode, resulting status, and cleared metadata.

- Added read-only `--json` output to `ai-orch autopilot queue show` so scripts
  can inspect selected queue item details without parsing text output.

- Added read-only `--json` output to `ai-orch autopilot queue reconcile`
  dry-run and `--apply` flows with selected plan scope, all-plans mode, total
  item count, stale created item refs, skipped count, and apply mode.

- Added read-only `--json` output to `ai-orch autopilot queue
  recover-in-progress` dry-run and `--apply` flows with selected plan scope,
  older-than-hours filter, stale item refs, blocked counts, and applied reason.

- Added read-only `--json` output to `ai-orch autopilot queue
  refresh-created-refs` dry-run and `--apply` flows with matched/updated
  counts, priorities, backlog path, apply mode, and old/new source refs.

- Added dry-run-by-default `ai-orch autopilot queue refresh-created-refs` for
  unchanged backlog items whose line numbers shifted after completed bullets
  were removed, preserving existing `created` queue item ids, status, task text,
  metadata, and execution semantics before a later `sync-backlog`.

- Added read-only `--older-than-days N` filtering to `ai-orch autopilot
  worktree-overview` so cleanup review can focus on worktrees whose displayed
  `last_modified` timestamp is at least the selected age.

- Added read-only `--older-than-hours N` filtering to `ai-orch autopilot queue
  recover-in-progress` so operators can dry-run or apply recovery only for
  interrupted `in_progress` queue items older than the selected threshold.

- Added opt-in `--batch-report PATH` to `ai-orch autopilot queue run-batch`
  dry-run and `--execute` flows so operators can persist the final batch
  summary, selected item refs, report paths, first non-done item context, and
  preflight snapshot as Markdown while preserving stdout, JSON artifact output,
  queue state transitions, and exit-code semantics.

- Added opt-in `--item-id PLAN_ITEM_ID` to `ai-orch autopilot queue run-batch`
  dry-run and `--execute` flows so operators can target one reviewed `created`
  queue item while preserving the default batch selection when omitted.

- Fixed `ai-orch autopilot queue readiness` and `queue preflight` so queue items
  created by `sync-backlog` from bare `BACKLOG.md` priority bullets remain ready
  while the source backlog bullet is still open, instead of being reported as
  stale by the plan-task parser.

- Extended `ai-orch autopilot queue run-batch --summary-json PATH` artifacts
  with `selected_item_refs` entries for selected or processed queue items,
  including queue item id, status, source plan location, task text, selected
  worktree path, task id, and report path when available, while preserving
  stdout output and exit-code semantics.

- Added read-only `--json` output option to `ai-orch autopilot
  worktree-overview`, reporting the shown worktree rows, cleanup labels,
  filtered count, and summary counts as a machine-readable object while
  preserving existing text output, filters, exit-code behavior, and the
  no-create/no-delete/no-prune safety contract.

- Added read-only `ai-orch autopilot queue preflight` command for a selected plan
  that combines queue readiness counts, stale items, and problem summary with the
  selected agent profile summary (`name`, `type`, `mode`, configured command, and
  availability), includes a read-only `next_action` hint telling the operator
  whether to run the batch, reconcile stale created items, recover in-progress
  items, review blocked items, or fix the selected agent, supports an opt-in
  `--fail-on-risk` non-zero exit when readiness risk or agent unavailability is
  present, and never executes queue items or changes queue state.

- Added read-only `--json` output option to `ai-orch autopilot queue readiness`
  for a selected plan or `--all-plans`, reporting total counts, created readiness,
  blocked/in-progress risk, stale created item refs, stale in-progress item refs,
  and a structured problem summary in a machine-readable object while preserving
  the default text output and existing `--fail-on-risk` exit-code behavior.

- Added opt-in `--fail-on-risk` flag to `ai-orch autopilot queue readiness`
  that keeps the command read-only but returns a non-zero exit code when stale
  created items, blocked items, or in-progress items are present, while
  preserving the default exit-code behavior and output for operators who only
  want an informational preflight.

- Added read-only `ai-orch autopilot queue readiness` command for a selected plan
  or `--all-plans` that summarizes queue counts, created readiness
  (ready vs stale), blocked/in-progress risk, stale created items whose source
  plan task is no longer open, and stale in-progress items in one operator
  preflight view, without executing queue items or changing queue state.

- Show existing queue item refs (`task=`, `worktree=`, `report=`, and
  `reason=` when available) in stale-row output from `ai-orch autopilot queue
  reconcile` and `queue recover-in-progress`, without changing dry-run/apply
  behavior, queue state transitions, filters, or exit-code semantics.

- Added read-only `ai-orch autopilot worktree-overview --limit N` output so
  large worktree directories can show only the first N filtered rows while the
  summary reports total discovered, filtered, and shown row counts, without
  creating, deleting, pruning, or checking out worktrees.

- Added a read-only problem summary to `ai-orch autopilot queue status` and
  `ai-orch autopilot queue list` output that groups `blocked` and `in_progress`
  items by reason, shows the count and latest affected queue item ids for each
  group, and preserves existing queue state, filters, limits, and exit-code
  semantics.

- Added an operator-facing final summary to `ai-orch autopilot queue run-batch`
  dry-run and `--execute` output with selected/processed counts, status counts,
  first active non-done queue item, selected worktrees, and report paths,
  without changing execution behavior or exit-code semantics.

- Added opt-in `--summary-json PATH` option to `ai-orch autopilot queue run-batch`
  dry-run and `--execute` flows that writes the same final batch summary as a
  machine-readable JSON artifact with selected/processed counts, per-status
  counts, the first non-done queue item, report paths, and selected worktree
  paths, plus a read-only `preflight_snapshot` captured before batch selection
  with queue readiness, selected agent availability, `preflight_result`, and
  `next_action`, while preserving existing stdout output and exit-code semantics.

- Documented the empty-backlog operator handoff for seeding exactly one
  bounded P2 item before running `queue run-batch`; no CLI behavior changed.

- Allow `ai-orch autopilot queue requeue --plan PLAN <plan_item_id>` as a
  guarded compatibility form that validates the selected blocked item belongs to
  the requested plan before dry-run or `--apply`, so operators can reuse the
  same `--plan` habit from queue history commands without changing queue state
  unless `--apply` is present.
- Allow `ai-orch autopilot queue show --plan PLAN <plan_item_id>` as a
  read-only compatibility form that validates the selected item belongs to the
  requested plan, so operators can reuse the same `--plan` habit from queue
  history commands without changing queue state.
- Allow `ai-orch autopilot queue skip --plan PLAN <plan_item_id>` as a
  guarded compatibility form that validates the selected created or blocked
  item belongs to the requested plan before dry-run or `--apply`, so operators
  can reuse the same `--plan` habit from queue history commands without
  changing queue state unless `--apply` is present.
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
  a one-off autopilot plan file.
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
- Recorded the first guarded real-agent `ai-orch autopilot queue run-batch --execute --max-items 1` smoke result.
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
- Added normalized round 2 review notes.
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
