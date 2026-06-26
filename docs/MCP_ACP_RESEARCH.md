# MCP / ACP research notes

MCP and ACP are out of MVP scope, but they are likely future integration paths for richer agent interoperability.

## MVP boundary

- Current MVP integrates agents through headless CLI adapters.
- Agent execution must still go through `AgentAdapter`.
- Verification must stay supervisor-owned and independent from agent self-reporting.
- Dangerous commands still go through `PolicyEngine`.

## Candidate integration shape

Future MCP/ACP support should be introduced as adapter implementations, not as a replacement for supervisor control:

```text
Supervisor -> AgentAdapter -> MCP/ACP client -> external agent/server
```

## First safe spike

1. Add a read-only capability discovery command for an MCP/ACP endpoint.
2. Store endpoint config outside hard-coded code paths.
3. Return availability/status through `ai-orch agents --check`.
4. Do not execute tools until policy and approval behavior is specified.

## Open questions

- How should sessions/resume map to each protocol?
- What output envelope should normalize tool calls, final answers, and errors?
- Which operations require approval before execution?
- How should credentials be provided without storing secrets in repo config?
