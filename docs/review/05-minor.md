# 05 - Minor Follow-Ups (P3)

## Findings

Minor review suggestions included CI polish, incremental typing, configurable mock behavior,
and a more explicit process runner options object.

## Status

Partially addressed.

## Addressed

- Added pip dependency caching to CI.
- Added Ruff linting to dev dependencies and CI.
- Added configurable scripted results to `MockAgentAdapter`.
- Added `RunOptions` for `ProcessRunner`.
- Added migration dispatcher tests that simulate version-to-version transitions.

## Deferred

- Python 3.13 CI matrix.
- Full type checker integration.
- Root `REVIEW.md` cleanup.

Root `REVIEW.md` remains intentionally untracked until explicitly requested.
