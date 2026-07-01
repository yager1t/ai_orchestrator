# Release Readiness Review

Date: 2026-07-01

Scope:

- Final reviewer-ready handoff for the current MVP hardening pass.
- Covers docs cleanup, release-check support, optional Codebase Memory context,
  adapter coverage, policy hardening, verification flow, state storage, and
  read-only TUI baseline.

Repository state at review start:

- Branch: `main`
- Latest implementation commit: `b997125 test(agents): cover kimi default cli alias args`
- Local diff before this packet: clean

## Documentation Inventory

| Document | Status | Notes |
| --- | --- | --- |
| `README.md` | current | Describes MVP status, commands, supported agents, memory workflow, and verification baseline. |
| `CHANGELOG.md` | current | Unreleased section records the hardening pass. |
| `docs/ARCHITECTURE.md` | current | Includes TUI expansion gate and optional memory provider boundary. |
| `docs/SECURITY.md` | current | Covers policy scope, command execution, and secret handling. |
| `docs/BACKLOG.md` | current | P0/P1/P2 empty; P3 deferred items link to gates. |
| `docs/DECISIONS.md` | current | Includes ADR-0002 for deferring PyYAML. |
| `docs/MCP_ACP_RESEARCH.md` | current | Defines runtime proposal gate before MCP/ACP execution support. |
| `docs/CODEBASE_MEMORY_RESEARCH.md` | current | Defines memory planning criteria and manual playbooks. |

## Intended vs Implemented

| Boundary | Intended rule | Implementation evidence | Test evidence | Status |
| --- | --- | --- | --- | --- |
| Supervisor completion | Executor agents do not self-certify done. | Supervisor FSM and decision loop own final status. | `tests/test_supervisor.py`, `tests/test_decision.py` | matches |
| Verification commands | Verification is independent and policy-checked. | `VerificationRunner`, structured argv, approval flow. | `tests/test_verification.py`, CLI tests | matches |
| Command execution | No `shell=True`; subprocesses go through `ProcessRunner`. | `RunOptions`, adapter and verification callers. | `tests/test_process_runner.py`, adapter tests | matches |
| Policy approvals | Dangerous commands require deny/ask handling before execution. | `PolicyEngine`, built-in hardening and custom patterns. | `tests/test_policy.py`, adapter contract tests | matches |
| Agent adapters | Providers stay behind `AgentAdapter`. | Generic, Codex, Claude, Kimi, Gemini adapters. | `tests/test_adapter_contract.py`, provider tests | matches |
| State and resume | SQLite persists task, iteration, and verification history. | State store with WAL, migrations, redaction. | `tests/test_storage.py` | matches |
| Release readiness | Packaging docs and version entrypoints are checked. | `ai-orch release-check --repo .`. | `tests/test_release_checks.py` | matches |

## Verification Results

| Command | Result | Notes |
| --- | --- | --- |
| `python -m ruff check ai_orchestrator tests` | passed | Required project check. |
| `python -m mypy` | passed | 36 source files checked. |
| `python -m pytest` | passed | 212 tests passed. |
| `python -m compileall ai_orchestrator` | passed | Package compiled. |
| `python -m ai_orchestrator verify --repo .` | passed | Compile and tests passed through product command. |
| `python -m ai_orchestrator release-check --repo .` | passed | Release docs and entrypoints present. |
| `git diff --check` | passed | Only expected CRLF working-copy warning on edited markdown/docs files. |

## Code Memory Context

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Codebase Memory indexed | yes | Fast local index used for adapter discovery during the final adapter test step. |
| Architecture summary used | no | Not needed for this docs-only packet. |
| Change impact checked | manual | Bounded file diffs and targeted tests were used for each step. |
| High-risk affected symbols | n/a | Final packet changes are documentation-only. |
| ADR links or gaps | current | PyYAML remains deferred by ADR-0002. |

## Launch Blockers

- None known for the current MVP hardening baseline.

## Deferred Work

- Replace the minimal YAML parser with PyYAML only if broader YAML compatibility is needed.
- Add deeper provider-specific adapter contract tests when provider behavior diverges from the shared contract.
- Expand TUI beyond read-only views only when an interactive workflow is justified.
- Continue MCP/ACP research before runtime execution support.
- Evaluate deeper supervisor memory planning only after `start --use-memory` proves useful in real tasks.

## Sign-off Notes

- Supervisor decision: current MVP hardening pass is ready for review or pause.
- Reviewer: Codex
- Remaining manual checks: tag/release decision, if a tagged release is desired.
