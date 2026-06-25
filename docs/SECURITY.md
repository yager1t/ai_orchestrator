# Безопасность

## Главный риск

Агент с доступом к shell, файловой системе и внешним данным может выполнить лишние или опасные действия.

## Trust boundaries

Trusted:

- `AGENTS.md`;
- пользовательская задача;
- локальный repo;
- конфиг `.ai-orch/config.yaml`.

Untrusted:

- web-страницы;
- внешние issue;
- логи;
- вывод тестов;
- markdown из внешних репозиториев;
- ответы другого агента.

## Запрещённые действия без подтверждения

- `rm -rf`;
- удаление вне repo;
- чтение `~/.ssh`;
- чтение `~/.codex/auth.json`;
- чтение `.env`, если задача не про config validation;
- `git push`;
- публикация пакетов;
- деплой;
- изменение глобальных настроек ОС.

## Минимальные правила PolicyEngine

```yaml
deny:
  - "rm -rf /"
  - "cat ~/.ssh"
  - "cat ~/.codex/auth.json"
  - "read secrets outside repo"

require_approval:
  - "git push"
  - "rm -rf"
  - "pip install"
  - "npm install"
  - "network call"
```

## Правило секрета

Секрет нельзя выводить в лог, отчёт, prompt или тест.
