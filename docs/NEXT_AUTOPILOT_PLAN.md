# Next Autopilot Plan

Use this plan for the first real-agent autopilot smoke run after the MVP branch
is pushed and reviewed.

## Real Agent Smoke

- [x] Create `docs/AUTOPILOT_REAL_AGENT_LOG.md` with one paragraph saying Kimi Code CLI ran through `ai-orch autopilot run --execute --worktree`, using `--output-format text -p`, and verification passed with compile and tests.
- [ ] Add a short `docs/AUTOPILOT_REAL_AGENT_LOG.md` note that records the real agent name, the command used, and the verification result for the smoke run.
- [ ] Retry the real-agent smoke by adding `docs/AUTOPILOT_REAL_AGENT_LOG.md` with the agent name, command, budget limit, and verification result.
- [ ] Retry the guarded real-agent smoke by adding `docs/AUTOPILOT_REAL_AGENT_LOG.md` with Claude as the agent, `--max-budget-usd 2`, and the passed compile/tests result.
- [ ] Create `docs/AUTOPILOT_REAL_AGENT_LOG.md` with one paragraph saying Claude ran through `ai-orch autopilot run --execute --worktree`, budget limit was `$2`, and verification passed with compile and tests.
