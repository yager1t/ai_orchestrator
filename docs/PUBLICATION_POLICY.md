# Public Documentation Policy

This repository keeps public documentation focused on product usage,
architecture, installation, security, release process, and durable roadmap
decisions.

Do not publish local operator traces, real-agent run logs, internal review notes,
agent-specific workflow instructions, or exploratory research reports. Keep those
files outside the tracked repository, for example under the ignored local
`.private/docs/` directory.

## Public docs

- `ARCHITECTURE.md`
- `AUTOPILOT_RUNBOOK.md`
- `BACKLOG.md`
- `CODEBASE_MEMORY_RESEARCH.md`
- `DECISIONS.md`
- `INSTALL.md`
- `MCP_ACP_RESEARCH.md`
- `MVP_IMPLEMENTATION_PLAN.md`
- `POST_MVP_ROADMAP.md`
- `RELEASE.md`
- `SECURITY.md`
- `SHIPPING_PACKET_TEMPLATE.md`
- `PUBLICATION_POLICY.md`

## Private/local docs

Keep these categories out of public commits:

- real-agent and autopilot execution logs;
- completed one-off autopilot plans;
- post-review working backlogs;
- detailed internal review notes;
- agent/task distribution notes and local AI-development workflow rules;
- exploratory research reports with local assumptions, stale baselines, or
  non-public source notes.
