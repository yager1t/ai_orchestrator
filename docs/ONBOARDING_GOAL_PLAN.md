# Product-Ready Onboarding GOAL Plan

## Goal

Turn `ai-orch` from a strong developer utility into a product-ready local CLI
with a clear first-run path for users who already have Codex/ChatGPT or another
supported worker CLI.

The next release should prioritize packaging, onboarding, and first value over
new orchestration depth.

## Scope

- Keep the existing supervisor architecture intact.
- Keep `ai-orch` CLI-first and local-first.
- Do not add production dependencies unless a release-critical blocker appears.
- Do not collect, store, or print provider secrets.
- Do not publish packages, push commits, or create remote tags without explicit
  operator approval.

## Implementation Queue

### 1. First-screen product docs

- Rewrite the top of `README.md` around user value, not internal architecture.
- Split onboarding into two routes:
  - "Try it safely" through a mock/demo example.
  - "Use it on my project" through setup, doctor, and a real worker CLI.
- Move quickstart examples into the main onboarding path.
- Make `mock` mode visibly different from real AI worker mode.

Exit criteria:

- A new user can identify the product value and the first command path within
  the first README screen.
- README, install docs, and user guide agree on the same first-run model.

### 2. Packaging and platform docs

- Add `pipx` as the universal end-user install route for future package
  distribution.
- Keep local repository install paths for contributors and release ZIP users.
- Add a dedicated macOS install guide.
- Document Homebrew as a planned platform channel unless an actual tap exists.
- Keep Windows and Linux installer guidance visible.

Exit criteria:

- Docs clearly distinguish package install, repository install, and platform
  installer paths.
- macOS no longer looks unsupported or accidental.

### 3. Codex-first onboarding

- Make `setup` and `doctor` explain the difference between:
  - installed,
  - selected worker configured,
  - real worker CLI available,
  - external worker login/auth required,
  - verification configured,
  - mock demo mode.
- Keep authentication delegated to worker CLIs such as Codex CLI.
- Make Codex the most obvious real-worker path without removing Claude, Gemini,
  Kimi, Generic, or Mock support.

Exit criteria:

- `ai-orch setup --agent codex` and `ai-orch doctor agents` give an operator a
  clear next step when Codex CLI is missing or not ready.

### 4. First-value command

- Add a command such as `ai-orch demo` or `ai-orch quickstart`.
- The command should run a safe built-in demo path by default.
- It should end with a human-readable summary: selected mode, worker, task id,
  verification result, report location, and next command.
- It must not require external AI credentials for the mock path.

Exit criteria:

- A clean checkout can produce a verified first result without a real worker
  CLI.
- A real-worker operator gets a clear route from demo to first real task.

### 5. Setup presets

- Add simple setup presets over the existing config model:
  - `codex-safe`
  - `python-project`
  - `node-project`
  - `docs-project`
  - `readonly-review`
- Preserve manual `.ai-orch/config.yaml` editing for advanced use.

Exit criteria:

- Presets reduce early YAML exposure without changing supervisor internals.
- Tests cover generated preset config basics.

### 6. Release hardening

- Extend release checks to catch missing onboarding docs and install routes.
- Update `CHANGELOG.md`.
- Bump the package version for the onboarding release.

Exit criteria:

- `release-check` fails when required onboarding docs disappear.
- Version metadata and changelog are in sync for the new release.

## Required Verification

Run before considering the GOAL complete:

```bash
ruff check .
mypy ai_orchestrator
python -m pytest
python -m compileall ai_orchestrator
python -m ai_orchestrator verify --repo .
python -m ai_orchestrator release-check --repo .
git diff --check
```

If any check fails, switch to REPAIR mode and make the smallest targeted fix.

## Git Boundary

The implementation can prepare a local release commit and tag plan, but remote
pushes, package publication, and remote tags require explicit operator approval.
