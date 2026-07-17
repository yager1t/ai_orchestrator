# AI Task Finisher / ai-orch

`ai-orch` helps you run local AI coding agents such as Codex CLI, Claude Code,
Gemini CLI, Kimi CLI, or a generic wrapper without letting the agent declare its
own work finished. It supervises the run, executes independent verification, and
leaves an auditable report.

Use it when you want a local control plane for coding tasks:

- give a task to a CLI worker;
- verify the result with real commands;
- continue, finish, or block based on supervisor checks;
- keep reports, timelines, approvals, and traces on disk.

The core rule is simple: executor agents do not decide that work is done.
Completion is accepted only after supervisor-controlled verification passes.

```text
plan -> execute -> verify -> decide -> continue | done | blocked
```

## Project Status

The robust local control plane is implemented in the current `main` branch.
The latest published release is `v1.0.0 - Stable Local Operator Client`.

Current working surface:

- CLI commands: `init`, `setup`, `doctor`, `start`, `status`, `cancel`,
  `resume`, `recover`, `report`, `timeline`, `export`, `verify`, `release-check`, `ci`, `agents`,
  `metrics`, `eval`, `approvals`, `autopilot`, `memory`, and `tui`.
- Supervisor loop with verification-gated completion.
- SQLite task, iteration, verification, event, action, approval, PlanGraph,
  replan, memory, autopilot queue, dead-letter, loop-ledger, and
  schema-version storage.
- Policy checks for agent, verification, brokered tool, and memory commands.
- Cooperative cancellation and subprocess termination.
- Safe metadata logs with stable `event=...` fields.
- Markdown reports and JSON traces generated from stored task history.
- Read-only TUI status, task list, approval, current iteration, logs, memory
  lessons, and memory influence views.
- Structured adapter output fields stored with each iteration:
  `summary`, `files_changed`, `tool_actions`, `exit_reason`, and `uncertainty`.
- Optional Codebase Memory CLI helpers plus durable memory lessons ranked into
  supervisor planning context as non-authoritative hints.
- Typed tool broker with read/write/network/destructive risk tiers, durable
  action records, approval requests, and deny-rule precedence.
- Local golden, chaos, and security red-team evaluation suites.
- Review hygiene with CODEOWNERS, local ruff pre-commit hooks, and release checks.
- Stable `LocalOperatorClient` for local tools that need to start tasks, inspect
  status, handle approvals, retry approved actions, and export traces without
  parsing human-oriented stdout.

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
- `python -m pytest`: 688 passed
- `python -m compileall ai_orchestrator`: passed
- `python -m ai_orchestrator verify --repo .`: passed
- `python -m ai_orchestrator release-check --repo .`: passed
- `git diff --check`: passed

## First Run

Choose one path.

### Try It Safely

Run the bundled docs-only demo. It uses the built-in `mock` worker, so it does
not need Codex, Claude, Gemini, Kimi, or any provider credentials.

```bash
python -m pip install -e ".[dev]"
ai-orch demo
```

The command runs `examples/docs_only_quickstart`, verifies that its README has a
top-level heading, writes a task report, and prints the next real-worker path.

### Use It On Your Project

For a real AI worker, install and log in to that worker CLI first. The most
direct Codex path is:

```bash
ai-orch setup --profile codex-safe --agent codex
ai-orch doctor agents
ai-orch onboard
ai-orch fix --task "Review this repository and suggest the safest next fix" --repo .
```

`setup` writes `.ai-orch/config.yaml`, `doctor agents` explains worker
availability and auth expectations, `onboard` gives a first-run readiness
wizard, and `fix` runs the same verification-gated supervisor loop with a
beginner-friendly role template.

When the selected agent is `mock`, the CLI states that it is demo/smoke-test
mode rather than real AI work.

## Install Paths

For packaged releases, the universal end-user path is `pipx`:

```bash
pipx install ai-engineering-supervisor
ai-orch --help
```

For a checked-out repository or release ZIP, use the local install path:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
ai-orch --help
ai-orch setup
ai-orch doctor
ai-orch demo
ai-orch onboard
ai-orch review --repo .
python -m pytest
```

`start` and `resume` print run progress, including the selected agent,
verification phase, result, and follow-up commands. When the selected agent is
`mock`, the CLI states that it is smoke-test mode rather than real AI work.

For a non-editable local install, run `python -m pip install .`. See
[`docs/INSTALL.md`](docs/INSTALL.md) for the install smoke path and release
verification commands. See [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) for the
operator workflow after installation.

On Windows, use the one-command local installer:

```cmd
INSTALL_WINDOWS.cmd
```

After it finishes, run:

```cmd
ai-orch.cmd
```

If the installer says Python is missing, run:

```cmd
INSTALL_WINDOWS.cmd /install-python
```

The normal installer also asks whether it should install Python when Python is
missing; `/install-python` just skips that question.

See [`docs/WINDOWS_INSTALL.md`](docs/WINDOWS_INSTALL.md) for PowerShell options,
developer install mode, and troubleshooting.

On Ubuntu/Linux, use:

```bash
bash INSTALL_LINUX.sh
```

After it finishes, run:

```bash
./ai-orch
```

See [`docs/LINUX_INSTALL.md`](docs/LINUX_INSTALL.md) for Python/bootstrap
options and troubleshooting.

On macOS, use the dedicated guide:

```bash
python3 -m pip install .
ai-orch demo
```

See [`docs/MAC_INSTALL.md`](docs/MAC_INSTALL.md) for `pipx`, local install,
launcher, and Homebrew-channel guidance.

## Configuration

## Human-Friendly Task Commands

`start` remains the explicit low-level command, but most first runs can use a
scenario command:

```bash
ai-orch fix --task "Fix the failing payment test"
ai-orch task --task "Add OAuth login"
ai-orch analyze
ai-orch review
ai-orch docs --task "Document local setup"
```

These commands use beginner role templates such as Bug fixer, Developer, Code
reviewer, Documentation writer, Security auditor, and QA engineer. They do not
bypass supervisor verification; they only shape the task prompt and then call
the normal run loop.

Use `ai-orch onboard` any time you need the guided readiness view again.

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
  max_lessons: 5
```

## Manual Code Memory Workflow

The external Codebase Memory provider is optional and manual: use it to inspect
architecture, search symbols, and map impact before risky work. Separately,
`ai-orch` stores durable memory lessons from blocked or failed-verification
runs. The supervisor ranks active lessons against the current task text and
injects up to `memory.max_lessons` as read-only, non-authoritative planning
hints. Verification remains the source of truth.

Suggested flow before a risky change:

```bash
python -m ai_orchestrator memory status --repo .
python -m ai_orchestrator memory index --repo . --approve
python -m ai_orchestrator memory architecture --repo .
python -m ai_orchestrator memory search --repo . --pattern ".*Supervisor.*" --label Class
python -m ai_orchestrator memory impact --repo .
python -m ai_orchestrator memory lessons --repo .
python -m ai_orchestrator memory influence --repo . --task-id <task-id>
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

Use `ai-orch doctor agents --repo .` to inspect the connector matrix for the
current machine. It reports whether each known worker is configured, enabled,
available on `PATH`, how credentials are expected to be supplied, and whether a
native API adapter exists.

Connector support:

| Connector | CLI/headless support | Native API adapter | Credential model |
| --- | --- | --- | --- |
| Codex | yes, via `codex exec` | not implemented | Codex CLI login or CLI-managed credentials |
| Claude | yes, via `claude -p` | not implemented | Claude CLI login or CLI-managed credentials |
| Gemini | yes, via `gemini -p` | not implemented | Gemini CLI login or CLI-managed credentials |
| Kimi | yes, via `kimi` | not implemented | Kimi CLI login or CLI-managed credentials |
| Generic | yes, configurable command wrapper | wrapper-owned | external env/secret store outside `.ai-orch/config.yaml` |
| Mock | yes, smoke-test only | not applicable | no credentials |

Native provider API adapters are intentionally not part of the current
production surface. If a provider API is required today, wrap it with the
`generic_cli` adapter and inject credentials from the shell, OS/user secret
store, service manager, or CI secrets.

Timeouts are configured per agent and verification command with `timeout_sec`.
Use `orchestrator.max_runtime_sec` as an outer cooperative budget for the
supervisor loop.

Default runtime values:

- generic, Kimi, and Gemini CLI aliases: `300` seconds
- Codex exec and Claude headless adapters: `1800` seconds
- fallback verification compile command: `120` seconds
- configured verification commands without `timeout_sec`: `300` seconds

## Autopilot

`ai-orch autopilot` is a guarded helper for Markdown plans, persisted queues,
durable PlanGraphs, worktree inspection, and bounded unattended loops.

```bash
python -m ai_orchestrator autopilot next --repo . --plan docs/POST_MVP_ROADMAP.md
python -m ai_orchestrator autopilot run --repo . --plan docs/POST_MVP_ROADMAP.md
python -m ai_orchestrator autopilot run --repo . --execute --worktree ../ai-orch-autopilot
python -m ai_orchestrator autopilot queue sync --repo . --plan docs/BACKLOG.md
python -m ai_orchestrator autopilot queue run-batch --repo . --plan docs/BACKLOG.md --max-items 2
python -m ai_orchestrator autopilot plan add-node 1 --repo . --key tests --title "Run tests" --acceptance-criterion "pytest passes"
python -m ai_orchestrator autopilot plan ready 1 --repo .
python -m ai_orchestrator autopilot plan recover 1 --repo . --json
python -m ai_orchestrator autopilot loop --repo . --plan docs/BACKLOG.md --max-items 2
python -m ai_orchestrator autopilot loop-history --repo . --plan docs/BACKLOG.md
```

Before unattended work, run:

```bash
python -m ai_orchestrator doctor --repo .
python -m ai_orchestrator doctor agents --repo .
python -m ai_orchestrator autopilot queue preflight --repo . --plan docs/BACKLOG.md
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
PlanGraph ready output is deterministic and includes non-ready explanations in
JSON and text output. PlanGraph nodes can store task text, acceptance criteria,
verification requirements, blocked reasons, source/repair links, and linked
task or queue ids; reports and JSON trace exports include the linked graph
snapshot when a task was run from a node. Use `autopilot plan recover` as a
dry run to inspect stale `in_progress` graph nodes, then add
`--apply --reason "..."` to mark them blocked for operator recovery.
`autopilot loop` is also dry-run-by-default and persists a budget ledger with
mode, runtime/action/attempt budgets, selected and processed counts,
dead-letter counts, stop reason, result code, selected item ids, and elapsed
runtime. Use `autopilot loop-history` to inspect those persisted loop runs
after restart.
See [docs/AUTOPILOT_RUNBOOK.md](docs/AUTOPILOT_RUNBOOK.md) for the operator
loop covering dry runs, execution, approvals, retry, reports, and stop
conditions.

Use the real-agent smoke fixture before unattended runs to confirm that a
non-mock adapter can execute through subprocesses and pass independent
verification:

```bash
python scripts/run_real_agent_smoke.py
```

## Evaluation

Local evaluation suites execute through the supervisor against isolated
temporary repositories:

```bash
python -m ai_orchestrator eval golden --repo .
python -m ai_orchestrator eval chaos --repo .
python -m ai_orchestrator eval redteam --repo .
python -m ai_orchestrator eval all --repo . --json
```

Evaluation summaries include executed count, pass rate, recovery count, blocked
count, chaos/security counts, and unsafe action count. Unsafe action count is
expected to remain zero.

## Verification Approvals

`ai-orch verify` blocks commands that match `policy.require_approval` unless the
user approves the exact configured command string:

```bash
python -m ai_orchestrator verify --repo . --approve-command "git push origin main"
```

Approvals are not stored in `.ai-orch/config.yaml`, do not override deny rules,
and apply only to the exact verification, brokered tool, or memory command that
created or matched the approval request.

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

`ai-orch setup` intentionally does not ask for API keys and does not create a
`.env` file. Use each worker CLI's native login flow first when one exists
(`codex login`, `claude login`, or the equivalent command for that tool). If a
generic wrapper needs a raw provider key, inject it outside the project config
through the process environment, an OS/user secret store, a service manager, or
CI secrets. Keep `.env` files out of git and load them from your shell or
wrapper only when you deliberately choose that local workflow.

`ai-orch` stores command names, arguments, timeouts, verification rules, and
policy rules. It should not store or retrieve raw provider credentials. Stored
agent and verification outputs redact common secret-like token formats before
reports are rendered.

## State Migrations

The SQLite state store tracks schema version with `PRAGMA user_version`.
Future schema updates should add explicit version-to-version migration functions
in `ai_orchestrator/storage/migrations.py`.

## Documentation Map

- `docs/ARCHITECTURE.md`: current component overview.
- `docs/USER_GUIDE.md`: practical operator guide for installation, tasks,
  approvals, memory, autopilot, evaluations, and recovery.
- `docs/LINUX_INSTALL.md`: one-command Ubuntu/Linux installer and troubleshooting.
- `docs/WINDOWS_INSTALL.md`: one-command Windows installer and troubleshooting.
- `docs/MVP_IMPLEMENTATION_PLAN.md`: implemented phases and deferred work.
- `docs/POST_MVP_ROADMAP.md`: post-MVP product and engineering roadmap.
- `docs/BACKLOG.md`: current backlog.
- `docs/V1_0_GOAL_PLAN.md`: released v1.0 stable local operator client plan.
- `docs/RELEASE_LOG.md`: published release outcomes and verification records.
- `docs/SECURITY.md`: security model and secret handling.
- `docs/CODEBASE_MEMORY_RESEARCH.md`: optional Codebase Memory integration notes.
- `docs/PUBLICATION_POLICY.md`: public/private documentation boundary.
- `docs/RELEASE.md`: release checklist.
- `CHANGELOG.md`: project change log.

## Development Rules

- Work in small bounded steps.
- Prefer standard-library code until a dependency is justified.
- Run tests after code changes.
- Do not push, publish, deploy, or run destructive commands without explicit user approval.
- Keep project-facing docs and changelog entries in English.
