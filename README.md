# AI Task Finisher / ai-orch

`ai-orch` is a local supervisor for CLI-based AI agents. It runs an agent,
verifies the result, and decides whether the task should continue, finish, or be
marked blocked.

The core rule: executor agents do not decide that work is done. Completion is
accepted only after supervisor-controlled verification passes.

```text
plan -> execute -> verify -> decide -> continue | done | blocked
```

## Project Status

The MVP control plane is implemented in the current local branch.

Current working surface:

- CLI commands: `init`, `start`, `resume`, `cancel`, `status`, `report`, `verify`, `release-check`, `ci`, `agents`, `metrics`, `approvals`, `autopilot`, `tui`.
- Supervisor loop with verification-gated completion.
- SQLite task, iteration, verification, and schema-version storage.
- Policy checks for agent and verification commands.
- Cooperative cancellation and subprocess termination.
- Safe metadata logs with stable `event=...` fields.
- Markdown reports generated from stored task history.
- Read-only TUI status, task list, approval, current iteration, and logs views.
- Structured adapter output fields stored with each iteration:
  `summary`, `files_changed`, `tool_actions`, `exit_reason`, and `uncertainty`.
- Optional Codebase Memory CLI helpers for manual architecture, search, and impact context.

Supported agent types:

- `mock`
- `generic_cli`
- `codex_exec`
- `claude_headless`
- `kimi` / `kimi_cli`
- `gemini` / `gemini_cli`

Latest verified baseline:

- `ruff check .`: passed
- `mypy ai_orchestrator`: passed
- `python -m pytest`: 263 passed
- `python -m compileall ai_orchestrator`: passed
- `python -m ai_orchestrator verify --repo .`: passed
- `python -m ai_orchestrator release-check --repo .`: passed
- `git diff --check`: passed

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
ai-orch --help
ai-orch init
ai-orch start --task "Check the MVP scaffold" --repo .
python -m pytest
```

For a non-editable local install, run `python -m pip install .`. See
[`docs/INSTALL.md`](docs/INSTALL.md) for the install smoke path and release
verification commands.

## Configuration

Agent routing and verification commands are configured in `.ai-orch/config.yaml`.

Kimi and Gemini aliases use the same subprocess, policy, timeout, and
availability-check path as `generic_cli`. Keep their `command` and `args`
explicit in config when real CLI flags differ from defaults.

Verification commands can use structured `argv` config or legacy `run` strings.
Structured `argv` is preferred for new configs.

Reusable generic adapter profiles can be defined once and referenced by one or
more agents. Agent-level `command`, `args`, `timeout_sec`, and `env` values
override the profile defaults. `env` is merged with the inherited profile env,
with agent values taking precedence. Windows-style environment references such
as `%LOCALAPPDATA%` are expanded before subprocess execution.

```yaml
orchestrator:
  default_agent: "docs-agent"

adapter_profiles:
  python-echo:
    type: "generic_cli"
    command: "python"
    args:
      - "-c"
      - "import sys; print(sys.argv[1])"
      - "{prompt}"
    timeout_sec: 30
    env:
      PYTHONUNBUFFERED: "1"

agents:
  docs-agent:
    enabled: true
    profile: "python-echo"
```

Set `verification.strict: true` to require explicitly configured verification
commands. In strict mode, `ai-orch` will not fall back to the default compile
check when commands are missing; `verify` fails and supervisor tasks remain
blocked instead of being treated as verified.

```yaml
verification:
  strict: true
  commands:
    - name: "compile"
      run: "python -m compileall ai_orchestrator"
      timeout_sec: 120
```

Optional code memory provider config:

```yaml
memory:
  provider: "codebase-memory-mcp"
  command:
    - "codebase-memory-mcp"
    - "cli"
  project: "ai_orchestrator_starter"
  timeout_sec: 120
```

## Manual Code Memory Workflow

Code memory is currently an optional manual context tool. The supervisor does
not automatically use memory output for planning, and verification remains the
source of truth.

Suggested flow before a risky change:

```bash
python -m ai_orchestrator memory status --repo .
python -m ai_orchestrator memory index --repo . --approve
python -m ai_orchestrator memory architecture --repo .
python -m ai_orchestrator memory search --repo . --pattern ".*Supervisor.*" --label Class
python -m ai_orchestrator memory impact --repo .
```

Use the output as planning context for the next bounded task. Do not treat it as
proof that behavior is correct.

Write-like memory tools such as `memory index` create persisted approval
requests in the shared approval inbox when they are not explicitly approved.
Resolve them with `ai-orch approvals approve` and rerun the exact command with
`ai-orch approvals retry`.

See `docs/CODEBASE_MEMORY_RESEARCH.md` for supervisor/security, adapter, and
release/review playbooks.

## Runtime Controls

Use `ai-orch cancel <task_id>` to mark a stored task as `cancelled`. Running
supervisors observe cancellation between steps and request active subprocess
termination.

Use global `--log-level debug|info|warning|error` before the subcommand to enable
safe metadata logs on stderr.

Use `ai-orch metrics --repo .` to print a local execution summary covering task
and iteration counts, verification pass rate, approval request states, and
adapter failures.

Timeouts are configured per agent and verification command with `timeout_sec`.
Use `orchestrator.max_runtime_sec` as an outer cooperative budget for the
supervisor loop.

Default runtime values:

- generic, Kimi, and Gemini CLI aliases: `300` seconds
- Codex exec and Claude headless adapters: `1800` seconds
- fallback verification compile command: `120` seconds
- configured verification commands without `timeout_sec`: `300` seconds

## Autopilot

`ai-orch autopilot` is a guarded post-MVP helper for taking the next unstarted
item from a Markdown plan and routing it through the existing supervisor.

```bash
python -m ai_orchestrator autopilot next --repo . --plan docs/POST_MVP_ROADMAP.md
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md
python -m ai_orchestrator autopilot run --repo . --execute --worktree ../ai-orch-autopilot
```

`autopilot run` is a dry run unless `--execute` is passed. Execution is blocked
when the selected agent is `mock` unless `--allow-mock-agent` is passed, and it
is blocked on dirty repositories unless `--allow-dirty` is passed. These guards
keep unattended operation from pretending that mock output completed real work.
The command prints an agent execution profile before running, including the
selected agent name, type, command, mock/real mode, and availability. Unavailable
non-mock agents are blocked before supervisor execution starts.
Pass `--worktree` to run the supervisor inside an existing separate git worktree
linked to `--repo`; dirty checks then apply to that execution worktree.
See [docs/AUTOPILOT_RUNBOOK.md](docs/AUTOPILOT_RUNBOOK.md) for the operator
loop covering dry runs, execution, approvals, retry, reports, and stop
conditions.

Use the real-agent smoke fixture before unattended runs to confirm that a
non-mock adapter can execute through subprocesses and pass independent
verification:

```bash
python scripts/run_real_agent_smoke.py
```

## Verification Approvals

`ai-orch verify` blocks commands that match `policy.require_approval` unless the
user approves the exact configured command string:

```bash
python -m ai_orchestrator verify --repo . --approve-command "git push origin main"
```

Approvals are not stored in `.ai-orch/config.yaml`, do not override deny rules,
and apply only to verification commands.

Persisted approval requests can be inspected and resolved through the approval
inbox commands:

```bash
python -m ai_orchestrator approvals list --repo .
python -m ai_orchestrator approvals show 1 --repo .
python -m ai_orchestrator approvals approve 1 --repo . --resolution "approved by operator"
python -m ai_orchestrator approvals reject 1 --repo . --resolution "not safe"
python -m ai_orchestrator approvals stale --repo . --older-than-hours 24
python -m ai_orchestrator approvals retry 1 --repo .
```

Supervisor runs persist `needs_approval` verification results into the approval
inbox automatically. Approval still only grants permission to execute the exact
command; it does not mark the task as done.

`approvals retry` reruns the exact command from an approved request with the
task repository as the working directory. Deny rules still take precedence over
approved requests. Retry results are written back to the approval request as
`retry_count`, `last_retry_status`, `last_retry_exit_code`, and retry metadata.
Use `approvals stale` to close old pending approvals without treating them as
operator rejections.

Approval request history is shown in generated Markdown reports and in the
read-only `ai-orch tui approvals` and `ai-orch tui status <task_id>` views.

## Secrets

Do not put API keys, tokens, passwords, or private key material in
`.ai-orch/config.yaml`.

Use each agent CLI's native login flow or process environment variables for
credentials. Stored agent and verification outputs redact common secret-like
token formats before reports are rendered.

## State Migrations

The SQLite state store tracks schema version with `PRAGMA user_version`.
Future schema updates should add explicit version-to-version migration functions
in `ai_orchestrator/storage/migrations.py`.

## Documentation Map

- `docs/ARCHITECTURE.md`: current component overview.
- `docs/MVP_IMPLEMENTATION_PLAN.md`: implemented phases and deferred work.
- `docs/POST_MVP_ROADMAP.md`: post-MVP product and engineering roadmap.
- `docs/BACKLOG.md`: current backlog.
- `docs/SECURITY.md`: security model and secret handling.
- `docs/CODEBASE_MEMORY_RESEARCH.md`: optional Codebase Memory integration notes.
- `docs/review/`: normalized review findings and follow-up notes.
- `docs/RELEASE.md`: release checklist.
- `CHANGELOG.md`: project change log.

## Development Rules

- Work in small bounded steps.
- Prefer standard-library code until a dependency is justified.
- Run tests after code changes.
- Do not push, publish, deploy, or run destructive commands without explicit user approval.
- Keep project-facing docs and changelog entries in English.
