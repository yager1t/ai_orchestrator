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

Code intelligence MCP servers such as `codebase-memory-mcp` should first be
treated as optional context providers, not executor agents. They can enrich
planning and review with read-only architecture or impact data while supervisor
verification remains authoritative.

## First safe spike

1. Add a read-only capability discovery command for an MCP/ACP endpoint.
2. Store endpoint config outside hard-coded code paths.
3. Return availability/status through `ai-orch doctor agents`.
4. Do not execute tools until policy and approval behavior is specified.

## Runtime proposal gate

Do not propose runtime MCP/ACP execution support until a research spike can
answer the protocol boundaries in implementation-ready terms.

Minimum evidence before moving beyond discovery:

- a session/resume mapping for at least one protocol;
- a normalized result envelope for tool output, final messages, and failures;
- a policy matrix for read-only, write, network, filesystem, and shell-like
  operations;
- a credential loading model that does not store secrets in repository config;
- adapter contract tests showing how availability, timeout, cancellation, and
  error states map back to `AgentAdapter`.

The first runtime proposal should still keep MCP/ACP behind `AgentAdapter`.
Supervisor decisions, verification, and dangerous-command approval must remain
owned by `ai-orch`, not delegated to the external protocol endpoint.

## Open questions

- How should sessions/resume map to each protocol?
- What output envelope should normalize tool calls, final answers, and errors?
- Which operations require approval before execution?
- How should credentials be provided without storing secrets in repo config?
