# Autopilot Operator Runbook

This runbook describes the safe operator loop for using `ai-orch autopilot` to
advance one roadmap item at a time through the supervisor.

Autopilot is intentionally conservative:

- it selects the next unstarted Markdown checklist item;
- it dry-runs by default;
- it blocks mock-agent execution unless explicitly allowed;
- it blocks dirty execution repos unless explicitly allowed;
- it routes approvals through the persisted approval inbox;
- it does not push, publish, deploy, auto-merge, or delete worktrees.

## 1. Preflight

Start from a clean main repo:

```bash
git status --short
python -m ai_orchestrator release-check --repo .
python -m ai_orchestrator verify --repo .
```

Check the configured agents and make sure the intended real agent is available:

```bash
python -m ai_orchestrator agents --repo . --check
```

Run the local real-agent smoke fixture before unattended work:

```bash
python scripts/run_real_agent_smoke.py
```

Show the next roadmap item without starting work:

```bash
python -m ai_orchestrator autopilot next --repo . --plan docs/POST_MVP_ROADMAP.md
```

Load open P0/P1/P2 backlog items directly into the persisted queue:

```bash
python -m ai_orchestrator autopilot queue sync-backlog --repo . --backlog docs/BACKLOG.md
```

Use `--priority P1 --priority P2` when the operator wants an explicit subset.
Deferred `P3 / Deferred` items are not included by default.

### 1.1 Empty backlog handoff

When `docs/BACKLOG.md` has no open P0/P1/P2 items, do not start
`queue run-batch` until exactly one bounded P2 item has been seeded, merged to
`main`, and synced to the queue.

1. Confirm the backlog has no open P0/P1/P2 bullets and the queue has no
   pending created item for the backlog:

   ```bash
   git status --short
   python -m ai_orchestrator autopilot queue status --repo . --plan docs/BACKLOG.md
   python -m ai_orchestrator autopilot queue list --repo . --plan docs/BACKLOG.md --status created --limit 10
   ```

   The queue can still show historical `done` or `skipped` items; proceed only
   when the created-item view shows `filtered: 0 status=created`.

2. Create a short-lived branch from `main`:

   ```bash
   git switch -c codex/seed-bounded-p2-item
   ```

3. Add exactly one bounded P2 item to `docs/BACKLOG.md` under `## P2`,
   replacing the `No open P2 items.` placeholder. Keep the task small enough
   to complete in a single `queue run-batch` cycle.

4. Commit the seed:

   ```bash
   git add docs/BACKLOG.md
   git commit -m "docs(backlog): seed bounded P2 item"
   ```

5. Merge the seed into `main` through your normal review path (for example, a
   pull request or a local fast-forward merge). `ai-orch` does not merge or
   push automatically.

6. Sync the backlog to the persisted queue:

   ```bash
   python -m ai_orchestrator autopilot queue sync-backlog --repo . --backlog docs/BACKLOG.md
   ```

   Verify the output shows `new: 1`. The `existing` count may be non-zero when
   the queue already has historical items for the same backlog.

7. Confirm exactly one queue item is `created`:

   ```bash
   python -m ai_orchestrator autopilot queue list --repo . --plan docs/BACKLOG.md --status created --limit 10
   ```

   Expected output shows `filtered: 1 status=created` and `by status: created=1`.

8. Only then preview or execute `queue run-batch`:

   ```bash
   python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 1 --worktree ../ai-orch-worktrees/<task-worktree>
   python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 1 --execute --worktree ../ai-orch-worktrees/<task-worktree>
   ```

This procedure does not change CLI behavior; it is a manual operator gate to
ensure `queue run-batch` has one well-defined item before it starts.

Inspect the persisted queue without starting work:

```bash
python -m ai_orchestrator autopilot queue status --repo . --plan docs/BACKLOG.md
```

For a single preflight view before choosing whether to execute, reconcile, or
recover queue items, use the read-only readiness summary:

```bash
python -m ai_orchestrator autopilot queue readiness --repo . --plan docs/BACKLOG.md
python -m ai_orchestrator autopilot queue readiness --repo . --all-plans --limit 10
python -m ai_orchestrator autopilot queue readiness --repo . --all-plans --json
python -m ai_orchestrator autopilot queue readiness --repo . --plan docs/BACKLOG.md --fail-on-risk
```

The readiness view summarizes total queue counts, created items that are still
ready versus stale, blocked/in-progress risk, stale created items whose source
plan task is no longer open, and in-progress items that may need recovery. It
does not execute queue items or change queue state. Add `--fail-on-risk` when a
scripted preflight should return a non-zero exit code for stale created,
blocked, or in-progress queue items; without that flag, readiness remains
informational. Add `--json` when scripts or reports need the same readiness
counts, stale refs, and problem summary as a machine-readable object.

Before starting `queue run-batch`, use the read-only preflight command when you
want queue readiness and the selected agent profile in one view:

```bash
python -m ai_orchestrator autopilot queue preflight --repo . --plan docs/BACKLOG.md
python -m ai_orchestrator autopilot queue preflight --repo . --plan docs/BACKLOG.md --fail-on-risk
python -m ai_orchestrator autopilot queue preflight --repo . --plan docs/BACKLOG.md --json
```

The preflight command reports the selected agent profile (`name`, `type`,
`mode`, configured command, and availability) next to the queue readiness
summary. It does not execute queue items or change queue state. Add
`--fail-on-risk` when a scripted gate should fail on readiness risk or an
unavailable selected agent. The `next_action` hint in text and JSON output is
read-only and reports one of `run_batch`, `reconcile_stale_created`,
`recover_in_progress`, `review_blocked`, `fix_agent`, or `none`.

Completed queue items show `report=...` when their Markdown task report exists.
Each history row also includes the persisted queue item id as `id=...`. Copy that
id into `queue show`, `queue requeue`, or `queue skip`; the id is stable across
commands and does not change CLI behavior.

Use repeated `--status` filters and `--limit` for focused queue history views:

```bash
python -m ai_orchestrator autopilot queue status --repo . --plan docs/BACKLOG.md --status blocked --status done --limit 10
python -m ai_orchestrator autopilot queue list --repo . --plan docs/BACKLOG.md --status created --limit 5
```

Use `--all-plans` when reviewing all persisted queue sources together. This is
read-only; execution commands still require a specific `--plan`.

```bash
python -m ai_orchestrator autopilot queue status --repo . --all-plans --status blocked --status done --limit 10
python -m ai_orchestrator autopilot queue list --repo . --all-plans --status created --limit 20
```

Show a single queue item before deciding whether to requeue, skip, or continue
operator review. This is read-only and prints the item status, source, task
text, task id, report path, selected worktree, and blocker or skip reason:

```bash
python -m ai_orchestrator autopilot queue show --repo . <plan_item_id>
python -m ai_orchestrator autopilot queue show --repo . --json <plan_item_id>
```

Use `--json` when scripts need the selected queue item status, source, task
text, task id, report path, selected worktree, and blocker or skip reason
without parsing the operator text output.

Use `--plan PLAN` when you want `queue show` to validate that the selected item
belongs to the same plan you were reviewing:

```bash
python -m ai_orchestrator autopilot queue show --repo . --plan docs/BACKLOG.md <plan_item_id>
```

`queue show --plan`, `queue requeue --plan`, and `queue skip --plan` all share
the same plan ownership guard: when `--plan` is supplied, the command rejects the
item before displaying or changing it if the persisted queue item does not belong
to that plan. This does not change CLI behavior when `--plan` is omitted.

Reconcile stale `created` queue items after a plan or backlog item is completed,
removed, or rewritten. The command is a dry run unless `--apply` is present:

```bash
python -m ai_orchestrator autopilot queue reconcile --repo . --all-plans
python -m ai_orchestrator autopilot queue reconcile --repo . --all-plans --json
python -m ai_orchestrator autopilot queue reconcile --repo . --all-plans --apply
```

Use `--json` when scripts need the selected plan scope, all-plans mode, total
item count, stale created item refs, skipped count, and apply mode without
parsing the operator text output.

When completed backlog bullets were removed and the remaining open text is
unchanged, refresh shifted `created` source refs before running
`sync-backlog` again. This preserves the existing queue item id and is a dry run
unless `--apply` is present:

```bash
python -m ai_orchestrator autopilot queue refresh-created-refs --repo . --backlog docs/BACKLOG.md
python -m ai_orchestrator autopilot queue refresh-created-refs --repo . --backlog docs/BACKLOG.md --json
python -m ai_orchestrator autopilot queue refresh-created-refs --repo . --backlog docs/BACKLOG.md --apply
```

Add `--json` when scripts need matched and updated counts, selected priorities,
the backlog path, apply mode, and per-item old/new source refs without parsing
the default text output.

Recover interrupted or timed-out batch runs by reviewing `in_progress` queue
items and, when appropriate, marking them blocked with an operator reason. The
command is a dry run unless `--apply` is present:

```bash
python -m ai_orchestrator autopilot queue recover-in-progress --repo . --all-plans
python -m ai_orchestrator autopilot queue recover-in-progress --repo . --all-plans --older-than-hours 24
python -m ai_orchestrator autopilot queue recover-in-progress --repo . --all-plans --older-than-hours 24 --json
python -m ai_orchestrator autopilot queue recover-in-progress --repo . --all-plans --apply --reason "batch run timed out before supervisor report"
```

Use `--older-than-hours N` to limit the dry-run or `--apply` recovery to
`in_progress` queue items whose last status update is older than the selected
threshold. The command remains dry-run-by-default, and `--reason` is still
required with `--apply`.

Use `--json` when scripts need the selected plan scope, stale item refs,
older-than-hours filter, blocked count, and applied reason without parsing the
operator text output.

Stale rows from `queue reconcile` and `queue recover-in-progress` include
available refs such as `task=`, `worktree=`, `report=`, and `reason=` so
operators can inspect recovery context without immediately running `queue show`.

Requeue a blocked item back to `created` after operator review. The command is
a dry run unless `--apply` is present, and it never executes the item:

```bash
python -m ai_orchestrator autopilot queue list --repo . --all-plans --status blocked
python -m ai_orchestrator autopilot queue requeue --repo . <plan_item_id>
python -m ai_orchestrator autopilot queue requeue --repo . --json <plan_item_id>
python -m ai_orchestrator autopilot queue requeue --repo . --plan docs/BACKLOG.md <plan_item_id>
python -m ai_orchestrator autopilot queue requeue --repo . --apply <plan_item_id>
```

Use `--json` when scripts need the selected blocked item refs, plan ownership
scope, dry-run or apply mode, resulting status, and cleared metadata without
parsing the operator text output.

Skip a `created` or `blocked` item after operator review. The command records a
reason, is a dry run unless `--apply` is present, and never deletes the item:

```bash
python -m ai_orchestrator autopilot queue list --repo . --all-plans --status created --status blocked
python -m ai_orchestrator autopilot queue skip --repo . --reason "operator reviewed: out of scope" <plan_item_id>
python -m ai_orchestrator autopilot queue skip --repo . --reason "operator reviewed: out of scope" --json <plan_item_id>
python -m ai_orchestrator autopilot queue skip --repo . --reason "operator reviewed: out of scope" --plan docs/BACKLOG.md <plan_item_id>
python -m ai_orchestrator autopilot queue skip --repo . --reason "operator reviewed: out of scope" --apply <plan_item_id>
```

Use `--json` when scripts need the selected item refs, plan ownership scope,
supplied skip reason, dry-run or apply mode, and resulting status without
parsing the operator text output.

Preview the next queued item without starting work:

```bash
python -m ai_orchestrator autopilot queue run-next --repo . --plan docs/BACKLOG.md
```

Dry-run `run-next` output includes the selected persisted queue item id. Use
that id with `queue show <plan_item_id>` when you want to inspect the exact
queued item before adding `--execute`.

Preview the next queued batch without starting work:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 3
```

Dry-run batch output includes each selected persisted queue item id. Use that
id with `queue show <plan_item_id>` when you want to inspect the exact queued
item before adding `--execute`.

After reviewing one item with `queue show`, add `--item-id PLAN_ITEM_ID` to
target only that `created` queue item in dry-run or `--execute` mode. When
`--item-id` is omitted, `run-batch` keeps the default oldest ready item
selection up to `--max-items`.

Add `--summary-json PATH` when scripts or reports need the final batch summary
as a machine-readable artifact without changing the normal stdout summary:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 3 --summary-json .ai-orch/reports/batch-summary.json
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --execute --max-items 3 --worktree ../ai-orch-autopilot --summary-json .ai-orch/reports/batch-summary.json
```

The JSON summary includes the dry-run selected count or execute processed count,
per-status counts, first non-done queue item, report paths, and selected
worktree paths. It also includes `selected_item_refs` for the selected or
processed queue items, with item id, status, source plan location, task text,
selected worktree path, task id, and report path when available. The same
artifact includes a read-only `preflight_snapshot` captured before batch
selection, with queue readiness counts, blocked/in-progress risk, the selected
agent profile availability, `preflight_result`, and `next_action` for operator
review.

Add `--batch-report PATH` when operators need the same final batch summary as a
Markdown artifact for run logs or handoff notes:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 3 --batch-report .ai-orch/reports/batch-summary.md
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --execute --max-items 3 --worktree ../ai-orch-autopilot --batch-report .ai-orch/reports/batch-summary.md
```

Preview per-task worktree rotation from a pre-created worktree pool:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 3 --rotate-worktrees ../ai-orch-worktrees
```

Add `--execute` only after this preview selects the intended clean worktrees.
Batch execution persists the selected worktree path on each queue item and
includes it in the per-task Markdown report.

## 2. Dry Run

Run the selected item in dry-run mode first:

```bash
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md
```

Confirm the output shows:

- the expected source plan and section;
- the expected task text;
- the expected agent profile;
- `available: yes` for real agents;
- the expected execution repo.

Stop if the task, agent, or execution repo is not what the operator intended.

## 3. Optional Worktree Isolation

For unattended execution, prefer an existing separate git worktree:

```bash
git worktree add -b codex/autopilot-sandbox ../ai-orch-autopilot HEAD
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md --execute --worktree ../ai-orch-autopilot
```

`--worktree` must point at a linked git worktree root for `--repo`. Dirty checks
apply to the worktree, while the approval inbox and task state stay under the
main `--repo` state store.

Create, prune, or remove worktrees manually outside `ai-orch`:

```bash
git worktree list
git worktree prune
```

Review old worktrees before any cleanup with the read-only overview command:

```bash
python -m ai_orchestrator autopilot worktree-overview --repo . --base-dir ../ai-orch-worktrees
python -m ai_orchestrator autopilot worktree-overview --repo . --base-dir ../ai-orch-worktrees --older-than-days 14
python -m ai_orchestrator autopilot worktree-overview --repo . --base-dir ../ai-orch-worktrees --json
```

The overview reports each detected git worktree's branch, whether it is linked
to the review repo, whether that branch is already merged into the review repo
HEAD, whether a merge is in progress, dirty and untracked counts, last modified
time, and a read-only cleanup label (`candidate`, `needs_review`, or
`do_not_remove`). A summary line shows total discovered worktrees, filtered
rows, shown rows, dirty rows, and unlinked rows after filters and any display
limit, plus a cleanup summary line with candidate, needs_review, and
do_not_remove counts. Add `--older-than-days N` to focus the same read-only
table or JSON output on worktrees whose displayed `last_modified` timestamp is
at least the selected age. Add `--dirty-only` to focus the table on worktrees with
uncommitted or untracked changes, use `--branch-filter TEXT` to focus on
worktrees whose branch name contains TEXT, or use `--limit N` to show only the
first N filtered rows.
Use `--unlinked-only` to show worktrees that do not share the review repo's git
common directory. Use `--merged-only` to show worktrees whose branch is already
merged into the review repo HEAD according to strict ancestry. Use
`--cleanup-status STATUS` to show only worktrees labeled `candidate`,
`needs_review`, or `do_not_remove` for cleanup review. This command never
creates, deletes, prunes, or checks out worktrees; cleanup remains a separate
manual operator decision. Add `--json` when scripts or reports need the same
shown worktree rows, cleanup labels, filtered count, and summary counts as a
machine-readable object without changing the read-only safety contract.

### 3.1 Manual worktree cleanup checklist

Before removing any old worktree, walk through these gates manually. `ai-orch`
does not delete worktrees automatically; these gates are documentation only and
must be executed by the operator outside the tool.

1. **List candidate worktrees** with the read-only overview:

   ```bash
   python -m ai_orchestrator autopilot worktree-overview --repo . --base-dir ../ai-orch-worktrees
   ```

2. **Confirm branch merge status.** Only consider removing worktrees whose
   branch is already merged into the review repo HEAD, unless the branch was
   explicitly abandoned.

3. **Check for dirty or untracked state.** Do not remove worktrees with
   uncommitted changes or untracked files without first reviewing, stashing, or
   copying the work out.

4. **Check for active autopilot runs.** Verify no queue item is `in_progress`
   or `blocked` against the worktree path:

   ```bash
   python -m ai_orchestrator autopilot queue status --repo . --all-plans
   ```

5. **Confirm no local-only branches or commits are needed.** Compare the
   worktree branch against `origin` if the branch was ever pushed.

6. **Archive or record value before deletion.** If the worktree contains
   experiment results, logs, or reports that are not stored elsewhere, copy them
   to a durable location first.

7. **Use `git worktree remove`, not `rm -rf`.** Example:

   ```bash
   git worktree remove ../ai-orch-worktrees/<branch-name>
   ```

   If the worktree is already unlinked or corrupt, use
   `git worktree remove --force` only after the previous gates pass.

8. **Verify removal.** Confirm the worktree no longer appears:

   ```bash
   git worktree list
   python -m ai_orchestrator autopilot worktree-overview --repo . --base-dir ../ai-orch-worktrees
   ```

9. **Stop and escalate** if any gate is unclear. Do not delete worktrees that
   are dirty, unlinked, currently in use, or whose branch status is uncertain
   without operator review.

## 4. Execute

Start the selected item only after the dry run is correct:

```bash
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md --execute
```

Use `--worktree` when executing in an isolated checkout:

```bash
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md --execute --worktree ../ai-orch-autopilot
```

Run a guarded serial queue batch only after the dry run is correct:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --execute --max-items 3 --worktree ../ai-orch-autopilot
```

Fixed `--worktree` batch runs persist the selected worktree path on the queue
item, so `queue show`, queue history views, and task reports identify the
execution checkout used for that item.

Use `--max-runtime-sec` when an operator wants a shorter per-item supervisor
runtime budget for a queue run. If the budget is exhausted, the queue item is
marked `blocked`, a task report is written, and the blocked reason is shown in
queue list/status output:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --execute --max-items 1 --worktree ../ai-orch-autopilot --max-runtime-sec 900
```

For per-item isolation, execute from a pre-created linked worktree pool:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --execute --max-items 3 --rotate-worktrees ../ai-orch-worktrees
```

Batch execution is serial and stops on the first non-`done` result. With
`--rotate-worktrees`, each selected item gets a distinct clean worktree from the
pool for that batch. Without rotation, repository changes from one item can make
the next item hit the dirty-worktree guard; use `--allow-dirty` only after
reviewing that state intentionally.

Use `--allow-mock-agent` only for smoke tests. A mock-agent run is not evidence
that real development was completed:

```bash
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md --execute --allow-mock-agent
```

Use `--allow-dirty` only when the operator has intentionally reviewed the dirty
execution repo:

```bash
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md --execute --allow-dirty
```

## 5. Approvals

If verification, memory indexing, or another guarded command needs approval,
autopilot blocks and records an approval request.

List pending requests:

```bash
python -m ai_orchestrator approvals list --repo .
```

Inspect a request:

```bash
python -m ai_orchestrator approvals show 1 --repo .
```

Approve a safe request with an operator note:

```bash
python -m ai_orchestrator approvals approve 1 --repo . --resolution "approved after reviewing command and scope"
```

Reject a request that is unsafe, unclear, or outside scope:

```bash
python -m ai_orchestrator approvals reject 1 --repo . --resolution "rejected: command is outside this bounded step"
```

Mark old pending requests stale when the task context has moved on:

```bash
python -m ai_orchestrator approvals stale --repo . --older-than-hours 24 --resolution "stale after newer run"
```

## 6. Retry After Approval

Retry only approved requests:

```bash
python -m ai_orchestrator approvals retry 1 --repo .
```

`approvals retry` records retry count, last retry status, exit code, and error
metadata on the approval request. If retry succeeds, run the normal verification
gate again:

```bash
python -m pytest
python -m compileall ai_orchestrator
ruff check .
mypy ai_orchestrator
python -m ai_orchestrator verify --repo .
python -m ai_orchestrator release-check --repo .
git diff --check
```

## 7. Reports

Find the latest task from status or logs, then write a Markdown report:

```bash
python -m ai_orchestrator tui tasks --repo .
python -m ai_orchestrator status TASK_ID --repo .
python -m ai_orchestrator report TASK_ID --repo .
```

Use TUI helpers for quick read-only inspection:

```bash
python -m ai_orchestrator tui current TASK_ID --repo .
python -m ai_orchestrator tui logs TASK_ID --repo .
python -m ai_orchestrator tui approvals --repo .
python -m ai_orchestrator tui status TASK_ID --repo .
python -m ai_orchestrator metrics --repo .
```

## 8. Finish The Iteration

Before marking the roadmap item complete, confirm:

- the diff is scoped to the bounded task;
- the verification gate passes;
- README, CHANGELOG, and relevant docs reflect behavior changes;
- the roadmap checkbox for the completed item is updated;
- no secrets, tokens, or user-local paths were added;
- the next `autopilot next` item is sensible.

Commands:

```bash
git diff --stat
git diff --check
python -m ai_orchestrator autopilot queue status --repo . --plan docs/BACKLOG.md
python -m ai_orchestrator autopilot next --repo . --plan docs/POST_MVP_ROADMAP.md
```

Commit only after review:

```bash
git add FILES_CHANGED
git commit -m "type(scope): short summary"
```

## 9. Stop Conditions

Stop and ask for operator input when:

- the selected roadmap task is ambiguous;
- a command requires secrets or private credentials;
- a command would push, publish, deploy, or delete data;
- the real agent is unavailable;
- the worktree is not linked to the main repo;
- tests fail for a reason outside the bounded task;
- the diff expands beyond the selected roadmap item.
