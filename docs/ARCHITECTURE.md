# MVP Architecture

`ai-orch` is a local supervisor for CLI-based AI agents. The supervisor, not the
executor agent, decides when a task is complete.

## Control Flow

```text
CLI
  -> Supervisor
    -> AgentAdapter
      -> ProcessRunner
    -> VerificationRunner
      -> ProcessRunner
    -> PolicyEngine
    -> StateStore
    -> MarkdownReport
```

The task loop is:

```text
plan -> execute -> verify -> decide -> continue | done | blocked
```

## Main Components

### CLI

The CLI exposes task lifecycle commands:

- `init`
- `start`
- `resume`
- `cancel`
- `status`
- `report`
- `verify`
- `agents`
- `tui`

### Supervisor

The supervisor owns task progress and final decisions. It stores each iteration,
runs verification, sends follow-up prompts when verification fails, and stops only
after the decision engine returns `done` or `blocked`.

### AgentAdapter

All executor integrations implement the same adapter contract:

```python
check_available() -> bool
start_session(context) -> SessionRef
run_step(session, prompt) -> AgentResult
continue_session(session, prompt) -> AgentResult
stop_session(session) -> None
get_status(session) -> AgentStatus
```

Current adapters:

- mock
- generic CLI
- Codex exec
- Claude headless
- Kimi CLI alias
- Gemini CLI alias

### ProcessRunner

`ProcessRunner` is the only subprocess execution path for adapters and
verification. Callers pass argv and `RunOptions`; commands are not executed
through `shell=True`.

### VerificationRunner

Verification is config-driven and runs independently from the agent. Commands can
use structured `argv` config or legacy command strings. Policy checks run before
execution, and exact-command approvals are required for configured approval
patterns.

### PolicyEngine

`PolicyEngine` is a defense-in-depth guard for command execution. It classifies
commands as:

```text
allow | ask | deny
```

Built-in rules use token-aware matching to reduce substring false positives.
Custom patterns remain backward compatible.

### StateStore

The SQLite store persists tasks, iterations, verification runs, and schema
version. Runtime pragmas enable WAL, busy timeout, and foreign keys.

### Reporting And TUI

Markdown reports summarize stored task history. The current TUI surface is
read-only and mirrors stored state:

- task status
- task list
- pending approvals
- current iteration
- iteration logs

### Optional Memory Providers

External code memory tools can provide planning and review context, but they do
not replace supervisor decisions or verification. The preferred future shape is
an optional provider invoked through `ProcessRunner`, with `PolicyEngine`
approval for indexing or persistent writes. `docs/CODEBASE_MEMORY_RESEARCH.md`
records the first candidate integration.

The initial CLI surface is read-mostly:

- `memory status`
- `memory search`
- `memory architecture`
- `memory impact`
- `memory preflight --area supervisor|adapter|release`
- `memory index --approve`

## Integration Priority

1. Headless CLI.
2. Structured output when available.
3. Resume/session support.
4. Subprocess execution through `ProcessRunner`.
5. PTY only if a CLI cannot run headlessly.
6. MCP/ACP after research spikes.
7. GUI fallback outside the MVP core path.

## Why Not GUI-First

Window automation is fragile because it depends on focus, layout, accessibility
metadata, and desktop state. The MVP core path stays on deterministic CLI and
subprocess interfaces.
