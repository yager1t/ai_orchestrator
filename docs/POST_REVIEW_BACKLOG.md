# Post-Review Backlog

This file tracks follow-up items that remain after the initial external review cleanup.

## P1

- Decide whether to replace the minimal config parser with PyYAML.
  - Current position: defer until config needs broader YAML compatibility.
  - Expected decision file: `docs/DECISIONS.md`.

- Add a lightweight migration path for SQLite schema changes.
  - Current state: `PRAGMA user_version` marks schema version and rejects future schemas.
  - Next step: add `ai_orchestrator/storage/migrations.py` when schema changes beyond version 1.

## P2

- Add structured logging for supervisor, verification, agent execution, and storage.
- Add graceful shutdown handling for long-running agent subprocesses.
- Revisit global runtime budgets as a complement to per-command `timeout_sec`.
