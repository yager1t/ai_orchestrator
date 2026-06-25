# Backlog

## P0 — стартовый MVP

### TASK-001: AgentAdapter + MockAgentAdapter

Роль: Adapter Agent
Файлы:

```text
ai_orchestrator/agents/base.py
ai_orchestrator/agents/mock.py
tests/test_mock_agent.py
```

DoD:

- есть единый интерфейс агента;
- mock adapter возвращает предсказуемый результат;
- тесты проходят.

---

### TASK-002: VerificationRunner

Роль: Verification Agent
Файлы:

```text
ai_orchestrator/verification/runner.py
tests/test_verification.py
```

DoD:

- умеет запускать shell-команду;
- сохраняет exit code/stdout/stderr;
- поддерживает timeout;
- тесты success/failure проходят.

---

### TASK-003: Supervisor FSM

Роль: Supervisor Agent
Файлы:

```text
ai_orchestrator/core/fsm.py
ai_orchestrator/core/supervisor.py
tests/test_supervisor.py
```

DoD:

- состояния описаны enum;
- есть минимальный цикл run-once;
- есть status done/blocked;
- тесты проходят.

---

### TASK-004: CLI

Роль: CLI/TUI Agent
Файлы:

```text
ai_orchestrator/cli/app.py
ai_orchestrator/__main__.py
```

DoD:

- `python -m ai_orchestrator --help` работает;
- `init`, `start`, `verify` доступны.

---

### TASK-005: PolicyEngine

Роль: Security Agent
Файлы:

```text
ai_orchestrator/policy/engine.py
tests/test_policy.py
```

DoD:

- deny для `rm -rf /`;
- ask для `git push`;
- allow для безопасных read-only команд.

---

## P1

- SQLite storage.
- Markdown report.
- GenericCLIAdapter.
- CodexExecAdapter.

## P2

- Claude adapter.
- Kimi/Gemini specialized adapters beyond current config-driven CLI aliases.
- TUI.
- MCP/ACP research spikes.
