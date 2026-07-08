# ai-orch User Guide

This guide is the shortest practical path for using `ai-orch` as a local
supervisor for CLI AI agents.

`ai-orch` runs an executor agent, verifies the result independently, and only
then decides whether the task is `done`, should continue, or is `blocked`.

```text
plan -> execute -> verify -> decide -> continue | done | blocked
```

The executor agent is never the authority for completion. The supervisor and
verification checks are.

## 1. Install

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
ai-orch --version
```

For a non-editable local install:

```bash
python -m pip install .
ai-orch --help
```

On Windows, the easiest path is:

```cmd
INSTALL_WINDOWS.cmd
```

The Windows installer refreshes `.ai-orch/config.yaml` for the current machine
creates local state directories, writes an install log, and creates
`ai-orch.cmd` in the project root. See `docs/WINDOWS_INSTALL.md` for PowerShell
options, including `-KeepConfig`, and troubleshooting.

## 2. Initialize Local State

For the simplest first run, let `ai-orch` create a safe local config:

```bash
ai-orch setup
ai-orch doctor
```

`setup` detects `codex`, `claude`, `kimi`, and `gemini` on `PATH`, chooses the
first available real CLI as `default_agent`, falls back to `mock` when no real
CLI is found, and writes `.ai-orch/config.yaml`. It does not read, ask for, or
store API keys. Authenticate the worker CLIs with their own native login flow,
for example `codex login` or `claude login`, before using them as real workers.

Use an explicit worker when you already know what should run:

```bash
ai-orch setup --agent codex
ai-orch setup --agent claude
ai-orch setup --agent mock
```

Preview without writing files:

```bash
ai-orch setup --dry-run
```

Overwrite an existing generated config only when you mean it:

```bash
ai-orch setup --force
```

`doctor` explains whether the local config, state directories, default agent,
and verification commands are ready:

```bash
ai-orch doctor
ai-orch doctor --json
```

The lower-level initializer is still available when you only want state
directories and plan to manage config yourself:

```bash
ai-orch init
```

This creates the local `.ai-orch` state directories. Runtime state is stored in
SQLite under `.ai-orch/state/`.

On Windows after running `scripts\install_windows.cmd`, use the root launcher:

```cmd
.\ai-orch.cmd doctor
.\ai-orch.cmd agents --check
.\ai-orch.cmd start --task "Check setup"
```

In PowerShell, keep the leading `.\`. In Command Prompt, `ai-orch.cmd doctor`
also works. Running `.\ai-orch.cmd` without arguments prints common commands
and runs diagnostics.

## 3. Configure Agents And Verification

Most users should start with `ai-orch setup`. Edit `.ai-orch/config.yaml` only
when you need custom commands, flags, timeouts, policies, or verification.

Do not put API keys in `.ai-orch/config.yaml`. Worker authentication should
come from the worker CLI itself, environment variables, or your operating
system/CI secret store. `ai-orch` passes control to the configured CLI command;
it does not need to know the raw key.

Typical auth paths:

- Codex CLI: run the native Codex login/setup flow, or set the environment
  variables expected by that CLI outside `ai-orch`.
- Claude Code: run the native Claude login/setup flow, or set provider
  environment variables outside `ai-orch`.
- Generic OpenAI/Anthropic/etc. wrappers: set provider keys in your shell,
  user profile, service manager, or CI secret store, then point `ai-orch` at the
  wrapper command.

Examples:

```bash
# One-shell-session only
export OPENAI_API_KEY="..."

# PowerShell current user profile, if you intentionally want a user-level env var
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "...", "User")
```

Prefer native CLI login when available. Prefer a secret manager or CI secrets
for shared/production machines. Use environment variables for local developer
machines when a CLI requires raw provider keys.

`ai-orch setup` intentionally does not create or manage `.env` files. If you
use a `.env` loader in your own shell or wrapper, keep the file out of git and
load it before starting `ai-orch`; the project config should still reference
only the command to run.

Minimum safe shape:

```yaml
orchestrator:
  default_agent: "mock"
  max_iterations: 2
  max_no_change_iterations: 2
  max_runtime_sec: 1800

agents:
  mock:
    enabled: true
    type: "mock"

verification:
  strict: true
  commands:
    - name: "compile"
      run: "python -m compileall ai_orchestrator"
      timeout_sec: 120
    - name: "tests"
      run: "python -m pytest"
      timeout_sec: 300

policy:
  deny:
    - "rm -rf /"
    - "cat ~/.ssh"
    - "cat ~/.codex/auth.json"
  require_approval:
    - "git push"
    - "rm -rf"
    - "pip install"
    - "npm install"
```

Use a real agent by setting `orchestrator.default_agent` to an enabled
`codex_exec`, `claude_headless`, `generic_cli`, `kimi_cli`, or `gemini_cli`
profile.

Check configured agents:

```bash
ai-orch agents --repo . --check
```

## 4. Run One Task

Start a task:

```bash
ai-orch start --task "Implement a small bounded change" --repo .
```

Inspect status:

```bash
ai-orch status <task-id> --repo .
```

Resume a blocked or unfinished task:

```bash
ai-orch resume <task-id> --repo .
```

Cancel a task:

```bash
ai-orch cancel <task-id> --repo .
```

Write a Markdown report:

```bash
ai-orch report <task-id> --repo .
```

Inspect a replayable timeline:

```bash
ai-orch timeline <task-id> --repo .
ai-orch timeline <task-id> --repo . --json
```

Export a JSON trace:

```bash
ai-orch export <task-id> --repo .
ai-orch export <task-id> --repo . --redact
```

## 5. Run Verification Directly

```bash
ai-orch verify --repo .
```

Run release readiness checks:

```bash
ai-orch release-check --repo .
```

Run the full local quality gate:

```bash
python -m pytest
python -m compileall ai_orchestrator
ruff check .
mypy ai_orchestrator
git diff --check
```

## 6. Handle Approvals

Commands matching `policy.require_approval` create approval requests or require
an exact command approval. Deny rules always win over approvals.

List approvals:

```bash
ai-orch approvals list --repo .
```

Inspect one approval:

```bash
ai-orch approvals show <approval-id> --repo .
```

Approve or reject:

```bash
ai-orch approvals approve <approval-id> --repo . --resolution "approved by operator"
ai-orch approvals reject <approval-id> --repo . --resolution "not safe"
```

Retry an approved request:

```bash
ai-orch approvals retry <approval-id> --repo .
```

Mark old pending approvals stale:

```bash
ai-orch approvals stale --repo . --older-than-hours 24
```

## 7. Use The Read-Only TUI Helpers

```bash
ai-orch tui tasks --repo .
ai-orch tui status <task-id> --repo .
ai-orch tui current <task-id> --repo .
ai-orch tui logs <task-id> --repo .
ai-orch tui approvals --repo .
ai-orch tui memory-lessons --repo .
ai-orch tui memory-influence --repo . --task-id <task-id>
```

These commands only render stored state. They do not execute agents.

## 8. Use Memory

External Codebase Memory is optional. It is useful for architecture search and
impact review before risky work.

```bash
ai-orch memory status --repo .
ai-orch memory search --repo . --pattern ".*Supervisor.*" --label Class
ai-orch memory architecture --repo .
ai-orch memory impact --repo .
```

Indexing is a write-like memory operation and requires explicit approval:

```bash
ai-orch memory index --repo . --approve
```

Inspect durable supervisor memory:

```bash
ai-orch memory lessons --repo .
ai-orch memory influence --repo . --task-id <task-id>
```

The supervisor may inject ranked active lessons into planning context as
read-only hints. Verification remains authoritative.

## 9. Use Autopilot Safely

Autopilot is dry-run-by-default. It does not push, merge, deploy, publish, or
delete worktrees.

Show the next Markdown checklist item:

```bash
ai-orch autopilot next --repo . --plan docs/POST_MVP_ROADMAP.md
```

Preview running the next item:

```bash
ai-orch autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md
```

Execute only after reviewing the dry run:

```bash
ai-orch autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md --execute --allow-dirty
```

Use the persisted queue:

```bash
ai-orch autopilot queue sync --repo . --plan docs/BACKLOG.md
ai-orch autopilot queue status --repo . --plan docs/BACKLOG.md
ai-orch autopilot queue readiness --repo . --plan docs/BACKLOG.md
ai-orch autopilot queue preflight --repo . --plan docs/BACKLOG.md
ai-orch autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 1
```

Execute a queue batch only after the preview selects the expected item:

```bash
ai-orch autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 1 --execute --allow-dirty
```

Use the guarded unattended loop:

```bash
ai-orch autopilot loop --repo . --plan docs/BACKLOG.md --max-items 1
ai-orch autopilot loop --repo . --plan docs/BACKLOG.md --max-items 1 --execute --allow-dirty
```

Inspect persisted loop ledgers:

```bash
ai-orch autopilot loop-history --repo . --plan docs/BACKLOG.md
```

For the full operator flow, see `docs/AUTOPILOT_RUNBOOK.md`.

## 10. Use PlanGraph

Create a durable graph:

```bash
ai-orch autopilot plan create --repo . --title "Release hardening"
```

List and show graphs:

```bash
ai-orch autopilot plan list --repo .
ai-orch autopilot plan show <graph-id> --repo .
```

Add nodes and dependencies:

```bash
ai-orch autopilot plan add-node <graph-id> --repo . --key release-checks --title "Run release checks"
ai-orch autopilot plan add-dependency <graph-id> --repo . --node-id <node-id> --depends-on-node-id <dependency-id>
```

Show ready nodes:

```bash
ai-orch autopilot plan ready <graph-id> --repo .
```

Preview or execute ready nodes:

```bash
ai-orch autopilot plan run-next <graph-id> --repo .
ai-orch autopilot plan run-next <graph-id> --repo . --execute --allow-dirty
```

## 11. Run Evaluations

```bash
ai-orch eval golden --repo .
ai-orch eval chaos --repo .
ai-orch eval redteam --repo .
ai-orch eval all --repo .
ai-orch eval all --repo . --json
```

Evaluation suites run local scenarios through the supervisor in isolated
temporary repositories. Unsafe action count should stay zero.

## 12. Recover Interrupted Work

Preview recovery:

```bash
ai-orch recover --repo .
ai-orch recover --repo . --json
```

Apply recovery only with an operator reason:

```bash
ai-orch recover --repo . --apply --reason "operator recovery after interrupted run"
```

Recovery can block interrupted running tasks and fail expired action records so
they do not look active forever.

## 13. Normal Operating Loop

Use this loop for real work:

1. `git status --short`
2. `ai-orch agents --repo . --check`
3. `ai-orch verify --repo .`
4. Start or preview one bounded task.
5. Resolve approvals if needed.
6. Inspect status, report, timeline, and diff.
7. Run the full quality gate.
8. Commit manually after review.

## 14. Safety Rules

- Deny rules are stronger than approvals.
- Keep execution dry-run-first for autopilot.
- Do not store secrets in `.ai-orch/config.yaml`.
- Do not run broad unattended loops until queue readiness and preflight are
  clean.
- Do not treat agent output as completion; verification must pass.
- Do not push, publish, deploy, or run destructive commands unless an operator
  explicitly chooses to do so.
