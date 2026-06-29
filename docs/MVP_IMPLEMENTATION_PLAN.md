# MVP Implementation Plan

This document records the MVP implementation phases and their current status.
Detailed historical changes are tracked in `CHANGELOG.md`.

## Status

The local MVP is implemented and hardened for the current development baseline.

Verified baseline:

```bash
python -m pytest
python -m compileall ai_orchestrator
python -m ai_orchestrator verify --repo .
```

## Implemented Phases

### Phase 0. Project Setup

- Repository guidance in `AGENTS.md`.
- Architecture and task distribution docs.
- Python package skeleton.
- Test baseline.

### Phase 1. Core Skeleton

- CLI commands: `init`, `start`, `status`, `resume`, `verify`, `cancel`.
- Task, session, iteration, and verification result models.
- Supervisor FSM and decision loop.
- Mock agent adapter.
- Markdown reports.

### Phase 2. Verification Runner

- Config-driven verification commands.
- Structured `argv` command support.
- Timeout handling.
- stdout/stderr capture.
- Exact-command approval flow.
- Policy checks before execution.

### Phase 3. Supervisor Loop

- Plan/execute/verify/continue/done/blocked cycle.
- Follow-up prompts after failed verification.
- No-change retry detection.
- Runtime budget and cancellation polling.
- Safe metadata logging.

### Phase 4. Storage

- SQLite task, iteration, and verification storage.
- Resume support.
- Schema version marker and migration dispatcher.
- WAL, busy timeout, and foreign-key pragmas.
- Redaction for secret-like stored output.

### Phase 5. CLI Agent Adapters

- Generic CLI adapter through `ProcessRunner`.
- Codex exec adapter.
- Claude headless adapter.
- Gemini and Kimi CLI adapter wrappers.
- Availability diagnostics.

### Phase 6. Policy Engine

- Built-in deny and require-approval rules.
- Token-aware command matching.
- Wrapper and newline command handling.
- Custom pattern compatibility.
- Security documentation.

### Phase 7. Read-Only TUI

- `tui status`
- `tui tasks`
- `tui approvals`
- `tui current`
- `tui logs`

### Phase 8. CI And Quality Gates

- GitHub Actions CI.
- Python 3.12/3.13 matrix.
- Ruff linting.
- Mypy type checking.
- Pytest, compileall, ai-orch verification, and whitespace checks.

## Deferred

- Replace the minimal YAML parser with PyYAML only if broader YAML compatibility is needed.
- Add deeper provider-specific adapter contract tests.
- Expand TUI into interactive workflows when required.
- Continue MCP/ACP research before runtime support.
- Add release packaging checks before tagged releases.
