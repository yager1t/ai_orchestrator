# Release checklist

Use this checklist before tagging or publishing an `ai-orch` release.

## Version

- Keep `pyproject.toml` `[project].version` and `ai_orchestrator.__version__` in sync.
- Run `python -m ai_orchestrator --version` and confirm the printed version.
- Keep release notes in `CHANGELOG.md`.
- Run `python -m ai_orchestrator release-check --repo .` before tagging.

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
