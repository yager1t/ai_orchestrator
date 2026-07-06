# Код-ревью (раунд 3) — закрытие замечаний

Дата обновления: 2026-07-07.

Базовая линия после исправлений:

- `python -m pytest` — **469 passed**
- `python -m compileall ai_orchestrator` — ok
- `ruff check .` — passed
- `mypy ai_orchestrator` — passed
- `git diff --check` — passed

## Что закрыто с прошлого ревью ✅

- Policy: подстрока → токенный разбор с обёртками (env, sudo, nice)
- SQLite: WAL + busy_timeout + foreign_keys
- Logging: структурное `event=...` во всех модулях
- Subprocess: terminate/kill, cancel-флаг, runtime-бюджет
- CI: workflow (pytest, compile, verify, lint)
- Миграции БД: `PRAGMA user_version`, `migrate_schema()`
- Autopilot: план-очередь, worktree-ротация, recovery, preflight
- Approvals: CLI + TUI + retry + stale + история
- Redaction: `redact_secrets()` в `raw_output`, stdout, stderr, error
- Codebase Memory: клиент с approval-gate для write-tools
- Release checks: pyproject metadata, version sync, entrypoints, docs
- Export: JSON trace с `--redact`

## Закрыто в этой серии правок ✅

### 1. Неоднозначный `_already_started`

Статус: закрыто.

`autopilot/queue.py` теперь определяет уже начатый autopilot item по точной
persisted-строке `- Source: <path>:<line>`, а не по substring match в source или
task text. Добавлен регрессионный тест на частичное совпадение line number и
одинаковый task text.

### 2. `_agent_config_value` и отсутствующий `agent_config`

Статус: закрыто.

`queue preflight` и autopilot profile output теперь строятся через единый
`_agent_profile_data()`. Если выбранный агент отсутствует в `config.agents`,
profile явно получает `configured=false`, поля `(missing)`,
`preflight_result=risk_or_unavailable` и `next_action=fix_agent`.

### 3. `plan_items` без индекса по `(status, plan_item_id)`

Статус: закрыто.

Добавлен индекс `idx_plan_items_status_id` для fresh schema и миграция
`7 -> 8` для существующих state stores. Добавлены storage tests для fresh DB,
upgrade from v4 и upgrade from v7.

### 4. `max_runtime_sec` — нет единой валидации на вход

Статус: закрыто.

`--max-runtime-sec` проверяется общим guard после `argparse`, поэтому любой
subcommand с этим аргументом получает одинаковый reject для `0` и отрицательных
значений. Повторяющийся parser argument вынесен в helper.

### 5. `verify` и `policy_denied` в exit code

Статус: закрыто.

CLI `verify` теперь считает `policy_denied` допустимым для CI-style gate:
команда печатает статус, но возвращает `0`. `needs_approval` по-прежнему
возвращает non-zero exit code.

### 6. `list_tasks` сортировка без `DESC` на `task_id`

Статус: уже было закрыто в текущем коде.

`StateStore.list_tasks()` сортирует по
`updated_at DESC, created_at DESC, task_id DESC`.

### 7. `migrate_between_versions` без миграций

Статус: закрыто.

Добавлен тест контракта: если `current_version == target_version`,
`migrate_between_versions(..., migrations={})` является no-op и не требует
наличия migration map.

### 8. `CODEOWNERS` отсутствует

Статус: закрыто.

Добавлен `.github/CODEOWNERS`.

### 9. `.pre-commit-config.yaml` не настроен

Статус: закрыто.

Добавлен локальный pre-commit config с `ruff check` и `ruff format` hooks.

### 10. `release-docs` требует `SHIPPING_PACKET_TEMPLATE.md`

Статус: уже было закрыто в текущем дереве.

`docs/SHIPPING_PACKET_TEMPLATE.md` присутствует.

### 11. `_state_store_for_repo` создаёт новый store каждый раз

Статус: закрыто малым изменением.

CLI теперь переиспользует `StateStore` instances по resolved DB path.
Добавлен regression test на reuse для одного repo.

## Отложено отдельно 🟡

### `cli/app.py` и крупный `build_parser()`

Полное разбиение `build_parser()` на `_build_main_parser()`,
`_build_autopilot_parser()`, `_build_approvals_parser()` оставлено отдельной
refactor-задачей. В этой серии сделан безопасный первый шаг: повторяющийся
`--max-runtime-sec` parser option вынесен в helper.

Причина отложения: полный parser split — большой косметический diff с высоким
риском случайно изменить CLI surface. Его лучше делать отдельной итерацией с
snapshot-тестами help output.

## Итог

Критические и существенные пункты round3 закрыты. Оставшийся parser split — не
поведенческий blocker, а отдельная maintainability-задача.
