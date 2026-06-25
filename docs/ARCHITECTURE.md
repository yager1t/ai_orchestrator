# Архитектура MVP

## Компоненты

```text
CLI -> Supervisor FSM -> Agent Router -> AgentAdapter -> Process Runner
                  |             |
                  |             -> Verification Runner
                  |             -> Policy Engine
                  |             -> State Store
                  |
                  -> Markdown Report
```

## Главные контракты

### AgentAdapter

Любой агент должен реализовать единый контракт:

```python
check_available() -> bool
start_session(context) -> SessionRef
run_step(session, prompt) -> AgentResult
continue_session(session, prompt) -> AgentResult
stop_session(session) -> None
get_status(session) -> AgentStatus
```

### VerificationRunner

Запускает проверки независимо от агента.

### PolicyEngine

Решает, можно ли выполнить действие:

```text
allow | ask | deny
```

## Приоритет интеграции агентов

1. Headless CLI.
2. JSON/JSONL output.
3. Resume.
4. Subprocess.
5. PTY.
6. MCP/ACP.
7. GUI fallback.

## Почему не GUI-first

GUI/window automation хрупкая: зависит от фокуса, layout, DOM, accessibility tree и состояния окна. Поэтому она не должна быть core-path MVP.
