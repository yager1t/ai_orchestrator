# План реализации MVP

## Этап 0. Подготовка

- [ ] Прочитать `AGENTS.md`.
- [ ] Прочитать `docs/AGENT_TASK_DISTRIBUTION.md`.
- [ ] Запустить стартовые тесты.
- [ ] Убедиться, что проект открывается в Codex.

---

## Этап 1. Каркас

- [ ] CLI-команды: `init`, `start`, `status`, `verify`.
- [ ] Базовые модели Task/Session/Iteration.
- [ ] FSM states.
- [ ] MockAgentAdapter.
- [ ] Markdown report.

DoD:

```bash
python -m ai_orchestrator --help
python -m pytest
```

---

## Этап 2. Verification Runner

- [ ] Shell command runner.
- [ ] Timeout.
- [ ] stdout/stderr capture.
- [ ] Result model.
- [ ] Tests for success/failure/timeout.

---

## Этап 3. Supervisor loop

- [ ] Plan stub.
- [ ] Run agent.
- [ ] Collect result.
- [ ] Run verification.
- [ ] Decide done/continue/blocked.
- [ ] Save report.

---

## Этап 4. Storage

- [ ] SQLite schema.
- [ ] Persist tasks.
- [ ] Persist iterations.
- [ ] Persist verification runs.
- [ ] Resume task.

---

## Этап 5. Generic CLI Adapter

- [ ] Запуск произвольной команды.
- [ ] Prompt через argv template.
- [ ] Timeout.
- [ ] stdout/stderr.
- [ ] Session metadata.

---

## Этап 6. Codex Adapter

- [ ] `codex` availability check.
- [ ] `codex exec`.
- [ ] JSONL mode.
- [ ] `codex exec resume`.
- [ ] Safe sandbox defaults.

---

## Этап 7. Policy Engine

- [ ] deny rules;
- [ ] require approval rules;
- [ ] command classification;
- [ ] tests.

---

## Этап 8. TUI позднее

- [ ] Textual app.
- [ ] Task list.
- [ ] Current iteration.
- [ ] Logs.
- [ ] Approvals.
