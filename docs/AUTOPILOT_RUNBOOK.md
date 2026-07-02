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
