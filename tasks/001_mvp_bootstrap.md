# TASK-001: MVP bootstrap

## Роль

Adapter Agent + Supervisor Agent.

## Цель

Довести стартовый каркас до состояния, когда:

```bash
python -m ai_orchestrator --help
python -m pytest
```

работают стабильно.

## Bounded steps

### Step 1

Проверить и доработать `AgentAdapter` и `MockAgentAdapter`.

Файлы:

```text
ai_orchestrator/agents/base.py
ai_orchestrator/agents/mock.py
tests/test_mock_agent.py
```

DoD:

- mock adapter возвращает `AgentResult(status="success")`;
- есть session id;
- тесты проходят.

### Step 2

Доработать `VerificationRunner`.

Файлы:

```text
ai_orchestrator/verification/runner.py
tests/test_verification.py
```

DoD:

- success command возвращает passed;
- failed command возвращает failed;
- timeout обрабатывается.

### Step 3

Доработать CLI.

Файлы:

```text
ai_orchestrator/cli/app.py
ai_orchestrator/__main__.py
```

DoD:

- `--help` работает;
- `init`, `start`, `verify` работают.

## Запреты

- Не реализовывать CodexAdapter в этой задаче.
- Не добавлять внешние зависимости.
- Не менять архитектуру.
