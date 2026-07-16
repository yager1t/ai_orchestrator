# v0.8 JSON Contract Inventory

Date: 2026-07-16
Status: initial contract inventory
Related plan: `docs/V0_8_GOAL_PLAN.md`

## Contract Tiers

v0.8 separates JSON outputs into three tiers so local automation can depend on a
small stable surface without freezing every internal storage shape.

- **Stable.** Documented and covered by contract tests. Existing fields remain
  compatible for v0.8, and additions must be backward compatible.
- **Stable candidate.** Intended for promotion during v0.8 after tests and docs
  define the supported fields.
- **Experimental or internal.** Useful for humans, debugging, or implementation
  plumbing. These payloads may change without compatibility guarantees.

New stable JSON outputs should use a common envelope:

```json
{
  "schema_version": "string",
  "command": "string",
  "generated_at": "ISO-8601 timestamp",
  "ok": true,
  "error": null
}
```

Existing v0.7/v0.8 surfaces may keep their historical top-level shape while the
first contract tests freeze the current baseline. Free-form nested fields such
as action payloads, tool results, raw storage metadata, and provider-specific
adapter details are extensible unless a test explicitly promotes them.

Local absolute paths are allowed in local-only operator payloads. Stable
contracts should prefer repo-relative paths where practical and must never
include secrets, API keys, private key material, or unredacted secret-like
command fragments.

Path/redaction policy: operator JSON may include local paths needed for audit
and recovery, while trace exports should use `--redact` when sharing artifacts
outside the local machine or review context.

## Stable Now

These surfaces are the first v0.8 baseline contracts:

- `ai-orch export <task_id> --repo <repo> [--output PATH] [--redact]`
- `ai-orch status <task_id> --repo <repo> --json`
- `ai-orch timeline <task_id> --repo <repo> --json`
- `ai-orch recover --repo <repo> --json`
- `ai-orch approvals list|show|approve|reject|retry --repo <repo> --json`
- `ai-orch autopilot queue status --repo <repo> --json`

`export` is the canonical trace artifact. Its stable baseline includes
`metadata`, `task`, `timeline`, `task_events`, `action_records`,
`action_journal`, `replan_decisions`, `plan_graph`, `memory_lessons`,
`reflection_records`, `memory_influence`, `iterations`, `verification_runs`,
and `approvals`.

`timeline --json` is the replay read model for one task. Its stable baseline is
the top-level `task` object plus ordered `timeline` entries.

`recover --json` is the recovery preflight/apply read model. Its stable baseline
includes `apply`, `dry_run`, `reason`, recovery candidate sections with
`count` and `items`, and applied recovery counters.

`status --json`, `approvals * --json`, and `autopilot queue status --json` use
the v0.8 control envelope with `schema_version`, `command`, `generated_at`,
`ok`, and `error`.

## Stable Candidates

These commands are candidates for promotion after focused tests define their
supported fields:

- `ai-orch autopilot queue show <plan_item_id> --repo <repo> [--plan PLAN] --json`
- `ai-orch autopilot queue list --repo <repo> (--plan PLAN|--all-plans) --json`
- `ai-orch autopilot queue readiness --repo <repo> (--plan PLAN|--all-plans) --json`
- `ai-orch autopilot queue preflight --repo <repo> --plan PLAN --json`
- `ai-orch autopilot queue reconcile|recover-in-progress|requeue|skip ... --json`
- `ai-orch autopilot plan list|show|ready --repo <repo> --json`
- `ai-orch worktree status|inspect|cleanup --repo <repo> --base-dir DIR --json`

For queue and PlanGraph payloads, stable fields should be limited to operator
workflow data: ids, status, task links, selected worktree path, blocked reason,
readiness, next action, report path, and trace path. Deeper graph mutation
payloads remain experimental until explicitly promoted.

## Experimental Or Internal

- `ai-orch setup --json`, `doctor --json`, and `onboard --json` are onboarding
  helpers, not the primary v0.8 automation contract.
- `ai-orch eval golden|chaos|redteam|all --json`.
- `ai-orch autopilot loop-history --json`.
- `ai-orch autopilot queue refresh-created-refs --json`.
- `ai-orch autopilot queue link-plan-graph <plan_item_id> ... --json`.
- `ai-orch autopilot plan create|update|add-node|update-node|add-dependency ... --json`.
- `ai-orch autopilot plan recover --json`.
- JSON artifacts written by `--summary-json PATH` batch commands.
- Human-oriented output from `verify`, `release-check`, `ci`, `agents`,
  `metrics`, `report`, `tui *`, `memory *`, and product aliases.

## Known Gaps

- Most current JSON outputs do not share a common envelope yet.
- Several payloads still expose raw dataclass/storage fields; these must be
  treated as extensible until contract tests narrow the public fields.

## First Bounded Slice

The first v0.8 implementation slice protects the existing `export`,
`timeline --json`, and `recover --json` shapes with tests before changing
runtime behavior. Later slices can introduce common envelopes or additional
`--json` flags with migration notes and compatibility tests.
