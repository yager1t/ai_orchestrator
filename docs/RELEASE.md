# Release checklist

Use this checklist before tagging or publishing an `ai-orch` release.

## Version

- Keep `pyproject.toml` `[project].version` and `ai_orchestrator.__version__` in sync.
- Run `python -m ai_orchestrator --version` and confirm the printed version.
- Keep release notes in `CHANGELOG.md`.
- Draft the GitHub Release body from `docs/RELEASE_NOTES_TEMPLATE.md`.
- Run `python -m ai_orchestrator release-check --repo .` before tagging.

## GitHub Release Notes

- Use `docs/RELEASE_NOTES_TEMPLATE.md` for the public GitHub Release body.
- Include a short theme paragraph, highlights, operator impact, docs/contracts,
  safety notes, verification, and a full diff link.
- Keep patch releases concise, but still explain why the release exists.
- Do not publish a release whose notes only restate the changelog bullets.

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
- PyPI publishing uses `.github/workflows/publish-pypi.yml` with PyPI Trusted
  Publisher OIDC authentication for the `ai-engineering-supervisor` project.

## Verification

Run the project checks from the repository root:

```bash
python -m pytest
python -m compileall ai_orchestrator
python -m ai_orchestrator verify --repo .
python -m ai_orchestrator release-check --repo .
git diff --check
```

## v0.8 Control Surface Gate

Before tagging v0.8, confirm the stable control surface is documented and
covered by focused contract tests:

- `ai-orch export <task-id> --repo . [--redact]`
- `ai-orch status <task-id> --repo . --json`
- `ai-orch timeline <task-id> --repo . --json`
- `ai-orch recover --repo . --json`
- `ai-orch approvals list|show|approve|reject|retry --repo . --json`
- `ai-orch autopilot queue show|status|readiness|preflight --repo . --json`

Run the v0.8 quality gate before the release commit:

```bash
python -m pytest
python -m compileall ai_orchestrator
ruff check .
mypy ai_orchestrator
python -m ai_orchestrator release-check --repo .
git diff --check
```

The release is blocked if the stable JSON contracts, redaction behavior, error
shapes, hard release stops, or external operator workflow are missing from docs
or tests.

## v0.9 Operator Compatibility Gate

Before tagging v0.9, confirm the local operator compatibility layer is
documented and covered by focused tests:

- v0.8 control-envelope JSON success and error shapes remain compatible.
- The external local operator integration smoke can inspect machine-readable
  status, approvals, queue state, recovery preflight, and redacted trace export
  without external AI credentials.
- The MCP/ACP adapter boundary maps future protocol operations to existing CLI
  control commands without starting a long-running server.
- `release-check` requires the v0.9 goal plan and operator compatibility docs.

Run the v0.9 quality gate before the release commit:

```bash
python -m pytest
python -m compileall ai_orchestrator
ruff check .
mypy ai_orchestrator
python -m ai_orchestrator release-check --repo .
git diff --check
```

The release is blocked if compatibility tests, local operator smoke coverage,
MCP/ACP boundary docs, or release-check coverage are missing.

For larger or risky releases, compile a reviewer-ready handoff using
`docs/SHIPPING_PACKET_TEMPLATE.md`.

## Git

- Confirm `git status --short` has only intended changes before commit.
- Commit locally with a scoped message.
- Do not run `git push` unless explicitly approved by the user.
- Create tags only after the release commit is reviewed.
