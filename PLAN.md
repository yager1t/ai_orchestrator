# Goal Mode Plan: Finish Robust Autopilot

This file contains the remaining work after the completed Stage 1, Stage 2,
and most of Stage 3 slices from `docs/ROBUST_AUTOPILOT_PLAN.md`.

Goal: finish the whole robust autopilot plan without stopping after each item.
After every iteration, update this file, run checks, then continue with the next
unchecked task until all items are complete and the Definition of Done is met.

## Operating Rules For Goal Mode

- Work in bounded iterations, but do not stop after each checklist item.
- After each completed iteration:
  - mark completed tasks in this file;
  - add a short note under `Progress Log`;
  - run the required checks;
  - continue to the next unchecked task.
- Stop only when all checkboxes are complete and the Definition of Done below is
  satisfied.
- Preserve existing behavior and tests unless a task explicitly requires a
  behavior change.
- Keep deny rules stronger than approvals.
- Do not add production dependencies unless a task clearly justifies it.
- Do not push, publish, deploy, or run destructive commands.

## Required Checks

Run these after each implementation iteration:

```bash
python -m pytest
python -m compileall ai_orchestrator
ruff check .
mypy ai_orchestrator
git diff --check
```

If an iteration changes only documentation, `git diff --check` is the minimum,
but run the full suite before marking the whole plan complete.

## Definition Of Done

- [x] Every task in this `PLAN.md` is checked.
- [x] `docs/ROBUST_AUTOPILOT_PLAN.md` matches the implemented state.
- [x] `CHANGELOG.md` records user-visible behavior changes.
- [x] Tests cover new storage, policy, retry, memory, evaluation, and loop
      behavior.
- [x] `python -m pytest` passes.
- [x] `python -m compileall ai_orchestrator` passes.
- [x] `ruff check .` passes.
- [x] `mypy ai_orchestrator` passes.
- [x] `git diff --check` has no whitespace errors.
- [x] No secrets, tokens, private logs, local absolute user paths, or internal
      research notes are added to public docs.

## Stage 3 Remaining: Typed Tool Broker Polish

- [x] Replace remaining ad hoc production `ToolCall` construction with factory
      helpers where it improves clarity.
- [x] Keep low-level tests free to build `ToolCall` objects manually when they
      are testing the contract itself.
- [x] Add or update regression tests for factory usage in supervisor/CLI code.
- [x] Ensure brokered `fs.*`, `process.*`, and `memory.*` tool calls are visible
      in action records and task timelines.
- [x] Update `docs/ROBUST_AUTOPILOT_PLAN.md` and `CHANGELOG.md`.

## Stage 4: Memory And Self-Repair

- [x] Add durable storage for episodic memory summaries or lessons learned from
      task outcomes.
- [x] Add reflection records for blocked runs and failed verification.
- [x] Persist structured fields such as source task, iteration, failure reason,
      failed checks, follow-up prompt, and timestamps.
- [x] Add stale-memory rules so old or repeatedly unhelpful lessons can be
      ignored without deleting history.
- [x] Add a memory influence log showing which memory entries were injected into
      planning context and why.
- [x] Expose memory/reflection data in Markdown reports and JSON trace exports.
- [x] Feed relevant lessons into supervisor planning context as
      non-authoritative hints.
- [x] Ensure verifier results remain the only authority for completion.
- [x] Add CLI/TUI inspection commands for memory lessons and influence logs.
- [x] Add tests for blocked-run reflection, failed-verification reflection,
      stale-memory filtering, and memory influence reporting.
- [x] Update `docs/ROBUST_AUTOPILOT_PLAN.md` and `CHANGELOG.md`.

## Stage 5: Observability And Evaluation

- [x] Add a correlation/run id through tasks, task events, action records,
      approval requests, verification runs, and replan decisions.
- [x] Include correlation ids in Markdown reports and JSON trace exports.
- [x] Extend replayable traces so they are sufficient to reconstruct a run
      timeline with events, actions, approvals, verifications, replans, memory
      influence, and final status.
- [x] Add a local golden task suite definition.
- [x] Add a command to run golden tasks and summarize pass rate, recovery rate,
      blocked count, and unsafe action count.
- [x] Add chaos tests for crash mid-action, stale action lease, flaky verifier,
      unavailable agent, and interrupted approved retry.
- [x] Add security red-team scenarios for denied paths, denied commands,
      approval bypass attempts, and out-of-repo file writes.
- [x] Ensure unsafe action count is tracked and expected to stay zero.
- [x] Update `docs/ROBUST_AUTOPILOT_PLAN.md` and `CHANGELOG.md`.

## Stage 6: Guarded Unattended Mode

- [x] Add `ai-orch autopilot loop --max-items N --stop-on-risk` or equivalent
      guarded loop command.
- [x] Keep the loop dry-run-by-default unless existing command style clearly
      requires a separate `--execute` flag.
- [x] Add runtime, attempts, and action-count budget ledgers.
- [x] Stop the loop on approval, risk, blocker, failed checks, unavailable
      agent, exhausted budget, or explicit cancellation.
- [x] Add a dead-letter queue for poisoned tasks that repeatedly fail or block.
- [x] Keep operator summaries after every processed item.
- [x] Ensure no auto-push, auto-merge, deploy, or destructive cleanup is added.
- [x] Add tests for loop completion, stop-on-risk, budget exhaustion,
      dead-letter behavior, and report generation.
- [x] Update `docs/ROBUST_AUTOPILOT_PLAN.md` and `CHANGELOG.md`.

## Final Review

- [x] Review the final diff for unrelated changes.
- [x] Confirm public docs do not include private review notes or local logs.
- [x] Confirm all generated commands and examples are safe by default.
- [x] Confirm `docs/ROBUST_AUTOPILOT_PLAN.md` no longer has stale handoff text
      for completed work.
- [x] Produce a final summary with changed files, checks, risks, and suggested
      commit message.

## Next Iteration: Evaluation, Budgets, Memory Relevance

- [x] Make `ai-orch eval golden` execute golden tasks through the supervisor
      instead of only summarizing scenario definitions.
- [x] Split evaluation commands into `eval golden`, `eval chaos`, `eval
      redteam`, and `eval all` while preserving JSON/text output.
- [x] Persist autopilot loop budget ledgers in SQLite so runtime, attempts,
      actions, selected/processed counts, dead-letter counts, and stop reason
      survive restart.
- [x] Improve supervisor memory lesson selection beyond a hard-coded
      `limit=3` by ranking active lessons against the task text and making the
      limit configurable without new production dependencies.
- [x] Add regression tests for executable evaluations, split eval CLI commands,
      durable loop ledgers, and ranked memory influence.
- [x] Update `CHANGELOG.md`, `docs/ROBUST_AUTOPILOT_PLAN.md`, and this progress
      log.
- [x] Run all required checks again.

## Progress Log

- 2026-07-08: Started the next Goal Mode iteration for four improvements:
  executable evaluation suites, durable loop budget ledgers, split evaluation
  CLI commands, and ranked/configurable memory lesson selection.
- 2026-07-08: Completed bounded iteration for executable evaluations and
  durable loop ledger persistence: `eval golden/chaos/redteam/all` now run
  scenarios through the supervisor, loop runs are stored in SQLite, and
  `autopilot loop-history` exposes the persisted budget ledger.
- 2026-07-08: Completed bounded iteration for memory relevance: supervisor
  memory context now uses ranked active lessons against task text, honors the
  configurable `memory.max_lessons` limit, and logs ranked influence reasons.
- 2026-07-08: Completed full required verification for the next iteration:
  `python -m pytest`, `python -m compileall ai_orchestrator`, `ruff check .`,
  `mypy ai_orchestrator`, and `git diff --check` all passed.
- 2026-07-08: Completed final review and Definition of Done after repeating the
  full mandatory checks, removing stale robust-plan handoff text, and replacing
  the local absolute path in the reusable Goal Mode prompt with a placeholder.
- 2026-07-08: Completed Stage 6 guarded unattended mode by adding
  dry-run-by-default `ai-orch autopilot loop`, preflight risk stopping,
  runtime/attempt/action budget ledgers, durable dead-letter records for
  blocked queue items, operator summaries, and regression coverage for loop
  completion, risk stops, budget exhaustion, dead-letter behavior, and report
  generation.
- 2026-07-08: Completed Stage 5 observability and evaluation by adding stable
  run ids to reports, timelines, and JSON traces, extending trace exports with
  memory/replan/action/approval/verification correlation, adding unsafe action
  accounting, and introducing a local golden/chaos/security evaluation suite
  with `ai-orch eval golden`.
- 2026-07-08: Completed Stage 4 memory and self-repair by adding durable
  memory lessons, blocked/failed-verification reflection records, stale-memory
  filtering, memory influence logs, non-authoritative supervisor context
  injection, report/export visibility, and CLI/TUI inspection commands.
- 2026-07-08: Completed Stage 3 polish by adding a generic typed tool-call
  factory for restored action records, switching CLI broker retry restoration to
  the factory path, and keeping brokered fs/process/memory calls visible through
  durable action records and timelines.
- 2026-07-08: Created this Goal Mode plan from the remaining stages of
  `docs/ROBUST_AUTOPILOT_PLAN.md`.

## Prompt For A New Goal Mode Window

Copy this prompt into a new Codex window in Goal mode:

```text
Работай в репозитории:
<absolute-path-to-repo>

Цель: выполнить весь PLAN.md до конца.

Открой и прочитай:
- AGENTS.md
- PLAN.md
- docs/ROBUST_AUTOPILOT_PLAN.md
- CHANGELOG.md

Нужно выполнить все незакрытые пункты из PLAN.md. Не останавливайся после
каждого пункта и не спрашивай подтверждение между пунктами, если нет реального
блокера или опасного действия. Работай маленькими bounded iterations.

После каждой итерации:
1. Обновляй PLAN.md: отмечай выполненные пункты, добавляй короткую запись в
   Progress Log.
2. Обновляй docs/ROBUST_AUTOPILOT_PLAN.md и CHANGELOG.md, если изменилось
   поведение или статус плана.
3. Запускай проверки:
   - python -m pytest
   - python -m compileall ai_orchestrator
   - ruff check .
   - mypy ai_orchestrator
   - git diff --check
4. Если проверки прошли, переходи к следующему незакрытому пункту PLAN.md.
5. Если проверки упали, исправляй минимальным diff и повторяй проверки.

Остановись только когда:
- все пункты PLAN.md выполнены;
- Definition of Done в PLAN.md соблюдён;
- все обязательные проверки проходят;
- финальный ответ содержит что сделано, проверки, изменённые файлы,
  риски/ограничения и следующий шаг, если он остался.

Важные правила:
- deny rules всегда сильнее approvals;
- не добавляй production-зависимости без явного обоснования;
- не делай git push, deploy, publish или destructive-команды;
- не трогай секреты, ключи, токены, ~/.ssh, ~/.codex/auth.json;
- не откатывай чужие изменения в грязном worktree;
- используй codebase-memory-mcp для code discovery, если он доступен.
```
