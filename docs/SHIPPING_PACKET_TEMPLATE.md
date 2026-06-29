# Shipping Packet Template

Use this template when preparing a reviewer-ready handoff for an `ai-orch`
release, risky change, or completed hardening pass.

The packet compiles evidence. It should not claim that a task is complete unless
the supervisor decision and verification results support that claim.

## Shipping Packet: Scope

Scope:

- ...

Repository state:

- Branch:
- Commit:
- Local diff:

## Documentation Inventory

| Document | Status | Notes |
| --- | --- | --- |
| `README.md` | present / stale / missing / n/a | ... |
| `CHANGELOG.md` | present / stale / missing / n/a | ... |
| `docs/ARCHITECTURE.md` | present / stale / missing / n/a | ... |
| `docs/SECURITY.md` | present / stale / missing / n/a | ... |
| `docs/BACKLOG.md` | present / stale / missing / n/a | ... |
| `docs/DECISIONS.md` | present / stale / missing / n/a | ... |
| `tasks/*.md` | present / stale / missing / n/a | ... |
| `prompts/*.md` | present / stale / missing / n/a | ... |

## Agent Context

| Artifact | Status | Notes |
| --- | --- | --- |
| `AGENTS.md` | current / stale / missing | ... |
| Role prompts | current / stale / missing | ... |
| Task template | current / stale / missing | ... |

## Intended vs Implemented

| Boundary | Intended rule | Implementation evidence | Test evidence | Status |
| --- | --- | --- | --- | --- |
| Policy approvals | ... | ... | ... | matches / gap / unknown |
| Verification commands | ... | ... | ... | matches / gap / unknown |
| Agent adapters | ... | ... | ... | matches / gap / unknown |
| State and resume | ... | ... | ... | matches / gap / unknown |
| Runtime limits and cancellation | ... | ... | ... | matches / gap / unknown |
| Redaction | ... | ... | ... | matches / gap / unknown |

## Verification Results

| Command | Result | Notes |
| --- | --- | --- |
| `python -m ruff check ai_orchestrator tests` | passed / failed / not run | ... |
| `python -m mypy` | passed / failed / not run | ... |
| `python -m pytest` | passed / failed / not run | ... |
| `python -m compileall ai_orchestrator` | passed / failed / not run | ... |
| `python -m ai_orchestrator verify --repo .` | passed / failed / not run | ... |
| `git diff --check` | passed / failed / not run | ... |

## Coverage Map

| Rule / behavior | Existing coverage | Proposed coverage | Gap / risk |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

## Code Memory Context

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Codebase Memory indexed | yes / no / n/a | ... |
| Architecture summary used | yes / no / n/a | ... |
| Change impact checked | yes / no / n/a | ... |
| High-risk affected symbols | yes / no / n/a | ... |
| ADR links or gaps | yes / no / n/a | ... |

## Security Summary

| Finding | Severity | Evidence | Fix / next step | Status |
| --- | --- | --- | --- | --- |
| ... | critical / high / medium / low | ... | ... | open / fixed / accepted |

## Runtime / Performance Summary

| Area | Finding | Evidence | Fix / next step | Status |
| --- | --- | --- | --- | --- |
| Process runner | ... | ... | ... | open / fixed / accepted |
| Storage | ... | ... | ... | open / fixed / accepted |
| TUI / CLI | ... | ... | ... | open / fixed / accepted |

## Launch Blockers

- ...

## Recommended Next Actions

- ...

## Sign-off Notes

- Supervisor decision:
- Reviewer:
- Remaining manual checks:
