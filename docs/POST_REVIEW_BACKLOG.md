# Post-Review Backlog

This file tracks follow-up items that remain after the initial external review cleanup.

## P1

- Decide whether to replace the minimal config parser with PyYAML.
  - Current position: defer until config needs broader YAML compatibility.
  - Expected decision file: `docs/DECISIONS.md`.

- Expand the lightweight migration path for SQLite schema changes.
  - Current state: `ai_orchestrator/storage/migrations.py` owns schema version checks.
  - Next step: add explicit version-to-version migration functions when schema changes beyond version 1.

## P2

- Continue refining structured logging fields and operator-facing log configuration.
- Add graceful shutdown handling for long-running agent subprocesses.
- Revisit global runtime budgets as a complement to per-command `timeout_sec`.
