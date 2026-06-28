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

## Secret storage

Do not store API keys, tokens, passwords, or private key material in `.ai-orch/config.yaml`,
task prompts, stored reports, or test fixtures.

Agent credentials should come from the agent CLI's native auth flow or process environment,
for example `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or vendor-specific environment variables.
The MVP config only describes commands, argv, policy, verification, and timeout behavior.

Stored agent and verification outputs redact common secret-like token formats before they are
persisted or rendered into markdown reports. This redaction is a safety net, not a replacement
for keeping secrets out of prompts and command output.

## Policy scope

PolicyEngine is defense-in-depth for trusted project configuration and agent-generated commands.
It is not a sandbox and must not be treated as the primary isolation boundary.

Use each agent's native sandbox or permission model for real isolation, for example Codex
workspace sandbox settings. PolicyEngine should reduce obvious accidents and block known-dangerous
command shapes, while the agent sandbox limits filesystem and process impact.

## Verification approvals

Verification commands that match `require_approval` return `needs_approval` by default.
For the MVP, approval is explicit and one-shot through the CLI:

```bash
python -m ai_orchestrator verify --repo . --approve-command "exact command string"
```

Rules:

- Approval uses exact command string matching only.
- Approval can only unblock `ask` decisions; `deny` decisions still win.
- Approvals are not read from `.ai-orch/config.yaml` and should not be stored in repo config.
- Approval applies to verification commands only, not agent execution commands.
- No `--approve-all` or pattern approval mode is supported.
