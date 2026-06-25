# Агентское распределение задач

Этот файл описывает, как распределять работу между агентскими ролями при разработке `ai-orch`.

---

## 1. Supervisor Agent

### Отвечает за

- главный цикл задачи;
- статусы;
- Definition of Done;
- лимиты итераций;
- решение `continue / done / blocked`.

### Файлы

```text
ai_orchestrator/core/supervisor.py
ai_orchestrator/core/fsm.py
ai_orchestrator/core/decision.py
tests/test_supervisor.py
tests/test_decision.py
```

### Типовые задачи

- добавить новое состояние FSM;
- реализовать no-change detection;
- добавить лимит повторов;
- сформировать follow-up prompt.

---

## 2. Architect Agent

### Отвечает за

- границы модулей;
- интерфейсы;
- технические решения;
- ADR.

### Файлы

```text
docs/ARCHITECTURE.md
docs/DECISIONS.md
ai_orchestrator/agents/base.py
ai_orchestrator/config/schema.py
```

### Типовые задачи

- утвердить интерфейс AgentAdapter;
- описать State Store;
- выбрать формат отчёта;
- описать контракты между модулями.

---

## 3. Core Agent

### Отвечает за

- planner;
- context builder;
- decision engine;
- follow-up generator.

### Файлы

```text
ai_orchestrator/core/planner.py
ai_orchestrator/core/context.py
ai_orchestrator/core/decision.py
ai_orchestrator/core/followup.py
```

---

## 4. Adapter Agent

### Отвечает за

- подключение CLI-агентов;
- subprocess/PTY;
- обработку stdout/stderr;
- timeout;
- session metadata.

### Файлы

```text
ai_orchestrator/agents/base.py
ai_orchestrator/agents/mock.py
ai_orchestrator/agents/generic.py
ai_orchestrator/agents/codex.py
ai_orchestrator/agents/claude.py
ai_orchestrator/process/runner.py
```

### Приоритет адаптеров

1. MockAgentAdapter.
2. GenericCLIAdapter.
3. CodexExecAdapter.
4. ClaudeHeadlessAdapter.
5. Kimi/Gemini stubs.
6. MCP/ACP later.

---

## 5. Verification Agent

### Отвечает за

- запуск проверок;
- timeout;
- сбор stdout/stderr;
- parse результатов;
- отчёт по проверкам.

### Файлы

```text
ai_orchestrator/verification/runner.py
ai_orchestrator/verification/checks.py
tests/test_verification.py
```

---

## 6. Security Agent

### Отвечает за

- PolicyEngine;
- allow/deny/ask;
- dangerous command detection;
- запрет секретов;
- sandbox assumptions.

### Файлы

```text
ai_orchestrator/policy/engine.py
ai_orchestrator/policy/rules.py
docs/SECURITY.md
tests/test_policy.py
```

---

## 7. Storage Agent

### Отвечает за

- SQLite schema;
- сохранение Task/Session/Iteration/VerificationRun;
- resume после перезапуска.

### Файлы

```text
ai_orchestrator/storage/db.py
ai_orchestrator/storage/models.py
ai_orchestrator/storage/migrations.py
tests/test_storage.py
```

---

## 8. CLI/TUI Agent

### Отвечает за

- CLI-команды;
- вывод статуса;
- TUI позднее.

### Файлы

```text
ai_orchestrator/cli/app.py
ai_orchestrator/tui/app.py
tests/test_cli.py
```

---

## 9. Docs Agent

### Отвечает за

- README;
- backlog;
- changelog;
- инструкции запуска;
- отчёты.

### Файлы

```text
README.md
CHANGELOG.md
docs/*.md
tasks/*.md
prompts/*.md
```

---

## 10. Review Agent

### Отвечает за финальную проверку

- нет ли лишнего scope;
- проходят ли тесты;
- нет ли секретов;
- нет ли нарушения архитектуры;
- понятен ли следующий шаг.

### Команды

```bash
git status --short
git diff --stat
git diff --check
python -m pytest
python -m compileall ai_orchestrator
```
