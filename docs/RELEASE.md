# Release checklist

Use this checklist before tagging or publishing an `ai-orch` release.

## Version

- Keep `pyproject.toml` `[project].version` and `ai_orchestrator.__version__` in sync.
- Run `python -m ai_orchestrator --version` and confirm the printed version.
- Keep release notes in `CHANGELOG.md`.
- Run `python -m ai_orchestrator release-check --repo .` before tagging.

## Install

- Confirm `pyproject.toml` exposes `ai-orch` in `[project.scripts]`.
- Run `python -m pip install -e ".[dev]"` during development and confirm
  `ai-orch --version`.
- For a packaged local smoke test, create a clean virtual environment and run
  `python -m pip install .`, then `ai-orch --help`.
- Confirm `ai-orch demo` runs the bundled docs-only first-value path.
- Confirm `ai-orch onboard --json` reports config, worker, verification, and
  scenario readiness.
- Confirm at least one product command, such as `ai-orch review --repo .`,
  routes through the supervisor and writes a report.
- Confirm `README.md`, `docs/INSTALL.md`, `docs/USER_GUIDE.md`, and
  `docs/MAC_INSTALL.md` describe the same `pipx`, demo, and real-worker setup
  flow.
- Follow `docs/INSTALL.md` for the install smoke path.
- PyPI publishing uses `.github/workflows/publish-pypi.yml` and requires the
  repository Actions secret `PYPI_API_TOKEN`.

## Verification

Run the project checks from the repository root:

```bash
python -m pytest
python -m compileall ai_orchestrator
python -m ai_orchestrator verify --repo .
python -m ai_orchestrator release-check --repo .
git diff --check
```

For larger or risky releases, compile a reviewer-ready handoff using
`docs/SHIPPING_PACKET_TEMPLATE.md`.

## Git

- Confirm `git status --short` has only intended changes before commit.
- Commit locally with a scoped message.
- Do not run `git push` unless explicitly approved by the user.
- Create tags only after the release commit is reviewed.
