# Changelog

## Unreleased

- Added a minimal decision engine for supervisor `done` / `continue` / `blocked` outcomes.
- Added supervisor retry flow that sends a follow-up prompt after failed verification.
- Added SQLite state storage for tasks, iterations, and verification runs.
- Added `ai-orch status <task_id>` for reading stored task history.
- Added `ai-orch resume <task_id>` for rerunning a stored task from SQLite context.
- Added config-driven verification commands for `start`, `resume`, and `verify`.
- Added policy checks before executing configured verification commands.
- Added config-driven policy deny and require-approval patterns.
- Added markdown task reports from stored SQLite task history.
- Added failed verification output excerpts to markdown reports.
- Added a minimal generic CLI adapter backed by a central process runner.
- Added config-driven agent selection for mock and generic CLI agents.
- Added policy checks before executing configured generic CLI agent commands.
- Added a minimal Codex exec adapter with policy checks before subprocess execution.
- Added Codex exec JSON and JSONL output normalization.
- Added Codex exec resume support for adapter continuations.
- Added a minimal Claude headless adapter with policy checks and JSON output normalization.
- Added starter config examples and CLI integration coverage for Codex and Claude agents.
- Added fallback agent routing from project config.
- Added `ai-orch agents --check` availability diagnostics.
- Added stored blocked iterations for unavailable agents so status and reports show the blocker.
- Changed supervisor flow to skip verification when an agent step is already blocked or failed.
- Added configurable no-change detection in the supervisor loop.
- Included repository status snapshots in supervisor no-change detection.
- Ignored local runtime/cache artifacts in supervisor repository snapshots.
- Skipped supervisor no-change blocking when repository snapshots are unavailable.
- Added config-driven Kimi and Gemini CLI agent aliases.
- Added CLI integration coverage for Kimi and Gemini agent aliases.
- Added policy coverage for Kimi and Gemini agent aliases.
- Added availability diagnostics coverage for Kimi and Gemini agent aliases.
- Documented supported MVP agent config types.
- Preserved explicit empty args for Kimi and Gemini CLI aliases.
- Added CLI start coverage for Kimi and Gemini default alias argv rendering.
- Preserved built-in hard-deny policy rules when custom deny rules are configured.
- Preserved explicit empty args for Codex and Claude headless adapters.

## 0.1.0 — bootstrap

- Добавлен стартовый комплект проекта.
- Добавлены правила Codex в `AGENTS.md`.
- Добавлено агентское распределение задач.
- Добавлен минимальный Python-каркас.
