# AI Task Finisher / ai-orch

## Project status

The MVP control plane is implemented and pushed to `origin/main`.

Current working surface:

- CLI commands: `init`, `start`, `resume`, `status`, `report`, `verify`, `agents`, `agents --check`.
- Supervisor completes tasks only after verification passes.
- SQLite state store records tasks, iterations, and verification runs.
- Policy checks protect verification and agent commands.
- Supported agents: mock, generic CLI, Codex exec, Claude headless, and Kimi/Gemini CLI aliases.
- Markdown reports are generated from stored task history.

Latest verified baseline:

- `python -m pytest`: 100 passed
- `python -m compileall ai_orchestrator`: passed
- `python -m ai_orchestrator verify --repo .`: passed
- `git diff --check`: passed

## Language policy

Project descriptions, README updates, and changelog/log entries may be written in English. User-facing assistant replies should stay in Russian unless the user asks otherwise.
MVP-проект оркестратора локальных ИИ-агентов.

Цель: управлять установленными CLI-агентами — Codex CLI, Claude Code, Gemini CLI, Kimi Code CLI и generic CLI — через единый supervisor-loop:

```text
PLAN -> DISPATCH -> RUN AGENT -> COLLECT -> VERIFY -> DECIDE -> CONTINUE/DONE/BLOCKED
```

Главное правило проекта: **задача не считается завершённой по словам агента**. Завершение возможно только после проверок, соответствия Definition of Done и финального отчёта.

---

## Быстрый старт для чистого проекта

```bash
git init
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m ai_orchestrator --help
python -m ai_orchestrator init
python -m ai_orchestrator start --task "Проверить MVP-каркас" --repo .
python -m pytest
```

---

## Agent config

Agent routing is configured in `.ai-orch/config.yaml`.

Supported MVP agent types:

- `mock`
- `generic_cli`
- `codex_exec`
- `claude_headless`
- `kimi` / `kimi_cli` as config-driven CLI aliases
- `gemini` / `gemini_cli` as config-driven CLI aliases

Kimi and Gemini aliases use the same subprocess, policy, timeout, and availability-check path as `generic_cli`. Keep their `command` and `args` explicit in config when real CLI flags differ from the defaults.

## Verification approvals

`ai-orch verify` blocks commands that match `policy.require_approval` unless the user approves the exact configured command string:

```bash
python -m ai_orchestrator verify --repo . --approve-command "git push origin main"
```

Approvals are not stored in `.ai-orch/config.yaml`, do not override deny rules, and apply only to verification commands.

---

## Старт работы через Codex

В корне проекта уже есть `AGENTS.md`. Codex должен автоматически читать этот файл перед началом работы.

Рекомендуемый запуск:

```bash
codex
```

или для неинтерактивного режима:

```bash
codex exec --sandbox workspace-write "Выполни задачу из tasks/001_mvp_bootstrap.md. Следуй AGENTS.md."
```

---

## Что входит в стартовый комплект

```text
AGENTS.md                         # главные инструкции Codex для проекта
AGENTS_GLOBAL_TEMPLATE.md          # шаблон глобальных правил ~/.codex/AGENTS.md
docs/AI_DEV_RULES.md               # правила разработки с ИИ
docs/AGENT_TASK_DISTRIBUTION.md    # распределение агентских ролей
docs/CODEX_WORKFLOW.md             # как работать в Codex по шагам
docs/MVP_IMPLEMENTATION_PLAN.md    # этапы разработки MVP
docs/BACKLOG.md                    # стартовый backlog
docs/ARCHITECTURE.md               # архитектура MVP
docs/SECURITY.md                   # безопасность
prompts/                           # промпты для ролей агентов
tasks/                             # шаблоны задач
.ai-orch/config.yaml               # пример будущего конфига оркестратора
ai_orchestrator/                   # минимальный Python-каркас
tests/                             # стартовые тесты
```

---

## Первый рекомендуемый порядок разработки

1. Прочитать `AGENTS.md`.
2. Прочитать `docs/AGENT_TASK_DISTRIBUTION.md`.
3. Начать с `tasks/001_mvp_bootstrap.md`.
4. Реализовывать только один bounded step за итерацию.
5. После каждого изменения запускать проверки.
6. Фиксировать результат в `docs/DECISIONS.md` и `CHANGELOG.md`.

---

## Основной принцип

MVP должен быть не “макросом поверх окон”, а **control plane над CLI-агентами**.

Приоритет интеграции:

1. Headless / non-interactive CLI.
2. JSON / JSONL / stream output.
3. Resume / continue session.
4. Subprocess / PTY.
5. MCP / ACP.
6. GUI/window automation только как fallback.
