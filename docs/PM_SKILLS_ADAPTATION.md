# PM Skills Adaptation Notes

This note records what is useful to adapt from
[`phuryn/pm-skills`](https://github.com/phuryn/pm-skills) for `ai-orch`.

## Useful Patterns

### Shipping packet

The `pm-ai-shipping` flow is the strongest fit. Its useful idea is a single
review-ready packet that compiles:

- documentation inventory;
- agent operating context;
- test coverage;
- security findings;
- performance or runtime findings;
- launch blockers;
- recommended next actions.

For `ai-orch`, this maps well to a future report mode that combines existing
verification results, policy decisions, runtime logs, and review notes.

### Intended vs implemented

The `intended-vs-implemented` skill is directly relevant to supervisor and
security work. The useful discipline is to compare documented intent against
implementation evidence, one boundary at a time.

For `ai-orch`, the high-value boundaries are:

- dangerous command policy and approval behavior;
- agent adapter contracts;
- verification command execution;
- state persistence and resume behavior;
- cancellation and runtime limits;
- redaction of logs and stored output.

Each finding should cite both sides: the intended rule in docs/config and the
implementation or test evidence in code.

### Test derivation from intent

The `derive-tests` flow separates current coverage from proposed coverage and
unverified gaps. That is useful for keeping the project honest after agent-made
changes.

For `ai-orch`, adapt this as a lightweight coverage map:

- existing tests that pin documented safety rules;
- proposed tests for uncovered rules;
- gaps ranked by risk;
- deterministic checks that must run in CI;
- guarded/manual checks that should not block default CI.

### Pre-mortem and red-team planning

The `pre-mortem` and `red-team-prd` workflows are useful before larger changes
to supervisor, security, state, or adapters. They should stay process-level,
not runtime dependencies.

Recommended use:

- list load-bearing assumptions before a bounded step;
- write the failure mode as "fails if ...";
- identify the cheapest test or check that can falsify the assumption;
- classify launch blockers separately from follow-up work.

### Test scenario template

The `test-scenarios` template is useful for feature specs and bugfix tasks. It
adds explicit starting conditions, actor/role, steps, expected outcomes, and
negative cases.

For `ai-orch`, this can improve `tasks/TASK_TEMPLATE.md` and review notes by
making error-path coverage mandatory for logic that touches agents, policy,
verification, storage, or subprocess execution.

## Implemented Project Changes

### Low-risk docs-only

- Extended `tasks/TASK_TEMPLATE.md` with:
  - intent;
  - assumptions;
  - acceptance criteria;
  - negative scenarios;
  - existing vs proposed verification.
- Added an intended-vs-implemented checklist to
  `docs/SHIPPING_PACKET_TEMPLATE.md`.
- Added a release/shipping packet template under `docs/`.
- Refreshed mojibake-affected docs while preserving their content.

## Remaining Ideas

### Medium-risk process changes

- Add an `ai-orch verify --coverage-map` style report later, derived from docs
  and current tests.
- Add a supervisor report section that separates:
  - completed checks;
  - proposed checks;
  - unverified gaps;
  - blockers.

### Higher-risk runtime changes

- Do not add PM-style workflows as runtime behavior yet.
- Do not let executor agents self-certify completion.
- Do not add new production dependencies for these practices.

## Recommended First Bounded Step

Completed: `tasks/TASK_TEMPLATE.md` now includes acceptance criteria,
assumptions, negative scenarios, and verification mapping.
