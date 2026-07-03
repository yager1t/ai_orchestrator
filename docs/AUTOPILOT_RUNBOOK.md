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

Inspect the persisted queue without starting work:

```bash
python -m ai_orchestrator autopilot queue status --repo . --plan docs/BACKLOG.md
```

Completed queue items show `report=...` when their Markdown task report exists.
Use repeated `--status` filters and `--limit` for focused queue history views:

```bash
python -m ai_orchestrator autopilot queue status --repo . --plan docs/BACKLOG.md --status blocked --status done --limit 10
python -m ai_orchestrator autopilot queue list --repo . --plan docs/BACKLOG.md --status created --limit 5
```

Preview the next queued batch without starting work:

```bash
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 3
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
