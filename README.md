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

- CLI commands: `init`, `start`, `resume`, `cancel`, `status`, `report`, `verify`, `release-check`, `agents`, `tui`.
- Supervisor loop with verification-gated completion.
- SQLite task, iteration, verification, and schema-version storage.
- Policy checks for agent and verification commands.
- Cooperative cancellation and subprocess termination.
- Safe metadata logs with stable `event=...` fields.
- Markdown reports generated from stored task history.
- Read-only TUI status, task list, approval, current iteration, and logs views.
- Optional Codebase Memory CLI helpers for manual architecture, search, and impact context.

Supported agent types:

- `mock`
- `generic_cli`
- `codex_exec`
- `claude_headless`
- `kimi` / `kimi_cli`
- `gemini` / `gemini_cli`

Latest verified baseline:

- `python -m ruff check ai_orchestrator tests`: passed
- `python -m mypy`: passed
- `python -m pytest`: 212 passed
- `python -m compileall ai_orchestrator`: passed
- `python -m ai_orchestrator verify --repo .`: passed
- `python -m ai_orchestrator release-check --repo .`: passed
- `git diff --check`: passed

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m ai_orchestrator --help
python -m ai_orchestrator init
python -m ai_orchestrator start --task "Check the MVP scaffold" --repo .
python -m pytest
```

## Configuration

Agent routing and verification commands are configured in `.ai-orch/config.yaml`.

Kimi and Gemini aliases use the same subprocess, policy, timeout, and
availability-check path as `generic_cli`. Keep their `command` and `args`
explicit in config when real CLI flags differ from defaults.

Verification commands can use structured `argv` config or legacy `run` strings.
Structured `argv` is preferred for new configs.

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

See `docs/CODEBASE_MEMORY_RESEARCH.md` for supervisor/security, adapter, and
release/review playbooks.

## Runtime Controls

Use `ai-orch cancel <task_id>` to mark a stored task as `cancelled`. Running
supervisors observe cancellation between steps and request active subprocess
termination.

Use global `--log-level debug|info|warning|error` before the subcommand to enable
safe metadata logs on stderr.

Timeouts are configured per agent and verification command with `timeout_sec`.
Use `orchestrator.max_runtime_sec` as an outer cooperative budget for the
supervisor loop.

Default runtime values:

- generic, Kimi, and Gemini CLI aliases: `300` seconds
- Codex exec and Claude headless adapters: `1800` seconds
- fallback verification compile command: `120` seconds
- configured verification commands without `timeout_sec`: `300` seconds

## Verification Approvals

`ai-orch verify` blocks commands that match `policy.require_approval` unless the
user approves the exact configured command string:

```bash
python -m ai_orchestrator verify --repo . --approve-command "git push origin main"
```

Approvals are not stored in `.ai-orch/config.yaml`, do not override deny rules,
and apply only to verification commands.

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
