# TASK-XXX: Title

## Agent Role

Supervisor / Architect / Core / Adapter / Verification / Security / Storage /
CLI / Docs / Review

## Intent

Briefly describe the intended outcome and why it matters.

## Assumptions

- ...

## Scope

In:

- ...

Out:

- ...

## Files

```text
...
```

## Acceptance Criteria

- [ ] ...
- [ ] Error and negative paths are handled where applicable.
- [ ] Documentation is updated if behavior changes.

## Negative Scenarios

List the cases that must fail closed or remain blocked.

- ...

## Verification Map

| Rule / behavior | Evidence source | Check type | Status |
| --- | --- | --- | --- |
| ... | docs / code / config | unit / integration / manual | existing / proposed / none |

## Required Checks

```bash
python -m ruff check ai_orchestrator tests
python -m mypy
python -m pytest
python -m compileall ai_orchestrator
python -m ai_orchestrator verify --repo .
git diff --check
```

## Risks

- ...

## Review Notes

- Intended vs implemented:
- Remaining gaps:
- Next manual step:
