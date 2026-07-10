# v0.3 GOAL Plan: First-Run Product UX

## Goal

Make the next release feel like:

```text
installed -> chose a scenario -> got a verified result
```

The focus is not more orchestration depth. The focus is reducing user friction
for people who want a local AI developer assistant that completes coding tasks
through supervisor-controlled verification.

## Scope

- Keep the current supervisor, adapter, verification, policy, storage, and
  reporting architecture intact.
- Add beginner-facing commands as safer wrappers over the existing `start`
  flow.
- Keep advanced YAML configuration available, but avoid making it the first
  user touchpoint.
- Do not add Web UI, dashboards, new provider API adapters, or broad
  integrations in this release.
- Do not publish packages, push branches, or create remote tags without
  explicit operator approval.

## P0 Work

### 1. Onboarding Wizard

Add a beginner-facing command, `ai-orch onboard`, that:

- checks whether local config exists;
- checks state/report directories;
- scans for known worker CLIs;
- identifies mock demo mode vs real worker mode;
- recommends a setup command;
- offers clear scenario commands for first use.

The command must support text and `--json` output.

Exit criteria:

- Missing config points to `ai-orch setup`.
- Missing Codex or other worker CLIs points to native install/login.
- Mock mode is explicitly labeled as demo/smoke mode.
- JSON output is stable enough for tests.

### 2. Product Commands

Add friendly commands over the existing supervisor loop:

- `ai-orch fix`
- `ai-orch task`
- `ai-orch analyze`
- `ai-orch review`
- `ai-orch docs`

These commands should:

- accept a user prompt through `--task` or a positional prompt;
- use beginner role templates;
- call the same supervisor path as `ai-orch start`;
- print the same report/next-command summary.

Exit criteria:

- Each command creates a stored task through the supervisor.
- Each command keeps verification as the authority for completion.
- Tests cover command routing and prompt shaping.

### 3. Error UX

Improve first-run errors with actionable next commands for:

- missing config;
- unavailable selected worker;
- mock mode;
- missing verification commands.

Exit criteria:

- User-facing failures include a concrete command to run next.
- Existing JSON behavior remains machine-readable.

## P1 Work

### 4. Beginner Roles

Introduce prompt templates for:

- Developer
- Bug fixer
- Code reviewer
- Documentation writer
- Security auditor
- QA engineer

Exit criteria:

- Templates are code-local, typed, and testable.
- No new agent type is added.

### 5. Report Summary

Improve the end-of-run CLI summary:

- task id;
- result;
- files changed if available;
- verification result;
- report command;
- timeline command;
- report path when written by the command.

Exit criteria:

- `start`, `demo`, and product commands share the same summary shape.
- Tests assert the summary contains useful next steps.

### 6. Install UX Documentation

Clarify:

- packaged install target through `pipx`;
- future WinGet/Homebrew channels;
- Linux `curl | bash` as a planned distribution route, not a silently shipped
  security shortcut;
- local install fallback.

Exit criteria:

- README, INSTALL, USER_GUIDE, and release docs agree.
- Release checks require wizard and product-command documentation.

## Release Gates

Prepare the release as `0.3.0` with:

- version bump;
- changelog entry;
- release-check additions for v0.3 docs;
- tests for new CLI behavior.

Required checks:

```bash
ruff check .
mypy ai_orchestrator
python -m pytest
python -m compileall ai_orchestrator
python -m ai_orchestrator verify --repo .
python -m ai_orchestrator release-check --repo .
git diff --check
```

If any check fails, switch to REPAIR mode and apply the smallest targeted fix.
