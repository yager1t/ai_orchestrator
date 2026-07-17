# Release Log

This file records published release outcomes after tagging. Keep planned release
steps in `docs/RELEASE.md` and user-visible changes in `CHANGELOG.md`.

## v1.0.0 - Stable Local Operator Client

Date: 2026-07-17

Release commit: `d04ec66`
Tag: `v1.0.0`
GitHub Release: https://github.com/yager1t/ai_orchestrator/releases/tag/v1.0.0
PyPI distribution: `ai-engineering-supervisor 1.0.0`

### Completed Scope

- Stable standard-library `LocalOperatorClient` for local operator workflows.
- `ai-orch start --json` control envelope with task identity and supervisor
  result metadata.
- Client coverage for start, status, approvals, retry, and trace export over
  the existing CLI control surface.
- Strict client failures for process errors, invalid JSON, malformed envelopes,
  incompatible schema versions, and `ok: false` payloads.
- Repository path pinning at client creation time.
- CI packaged install smoke coverage for the console script.
- v1.0 release-check gate for client docs, tests, workflow content, and
  no-server MCP/ACP boundary docs.

### Not Done In v1.0

- No MCP/ACP server, listener, daemon, or protocol runtime was implemented.
- No web dashboard, cloud multi-user deployment, auto-merge, or auto-push
  behavior was added.
- No direct state-store mutation or direct task-completion API was added to the
  local operator client.
- Queue inspection remains on the documented CLI JSON surface; dedicated queue
  client wrappers were deferred until the queue JSON envelope needs a stable
  Python API.

### Verification

- `python -m pytest`: 688 passed
- `python -m compileall ai_orchestrator`: passed
- `ruff check .`: passed
- `mypy ai_orchestrator`: passed
- `python -m ai_orchestrator verify --repo .`: passed
- `python -m ai_orchestrator release-check --repo .`: passed
- `git diff --check`: passed, with Windows LF/CRLF warnings only
- Local packaged install smoke: passed
- GitHub Actions `Publish to PyPI`: success
