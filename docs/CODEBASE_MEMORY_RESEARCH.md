# Codebase Memory MCP Research

This note records what `ai-orch` can safely adapt from
[`DeusData/codebase-memory-mcp`](https://github.com/DeusData/codebase-memory-mcp).

## Summary

`codebase-memory-mcp` is a local code intelligence backend. It indexes a
repository into a persistent SQLite-backed knowledge graph and exposes MCP/CLI
tools for architecture summaries, graph search, call tracing, change impact
analysis, ADR management, and code search.

For `ai-orch`, the right fit is optional external memory, not an embedded
indexer. The project should use the existing binary or CLI as a bounded tool
behind `ProcessRunner` and `PolicyEngine`.

## Useful Capabilities

- `get_architecture`: compact repo overview for supervisor planning.
- `search_graph`: structured symbol, class, route, or file discovery.
- `trace_path`: call-chain context for risky code changes.
- `detect_changes`: blast-radius and risk mapping for local diffs.
- `search_code`: graph-aware text search inside indexed files.
- `manage_adr`: machine-queryable architecture decision memory.
- Shared graph artifact: optional team bootstrap for large repositories.

## Integration Shape

Future support should be introduced as an optional memory provider:

```text
Supervisor
  -> MemoryProvider
    -> ProcessRunner
      -> codebase-memory-mcp cli ...
```

This keeps supervisor ownership intact:

- executor agents do not self-certify completion;
- memory output is context, not authority;
- verification remains independent;
- subprocess execution stays centralized.

## Policy Model

Default read-only operations:

- `list_projects`
- `index_status`
- `get_architecture`
- `search_graph`
- `trace_path`
- `search_code`
- `detect_changes`

Require explicit approval:

- `index_repository`, because it scans the repository and writes a local cache;
- `manage_adr`, because it persists architecture decisions;
- shared graph artifact export/import, because it can create repository files.

Deny or require a separate user request:

- install/update/uninstall commands;
- agent configuration mutation;
- `delete_project`;
- commands that write outside the configured cache or repository boundary.

## Candidate Config

```yaml
memory:
  provider: codebase-memory-mcp
  command:
    - codebase-memory-mcp
    - cli
  project: ai_orchestrator_starter
  timeout_sec: 120
```

## Supervisor Usage

Future supervisor planning can enrich context with:

1. `get_architecture` for module overview.
2. `search_graph` for relevant symbols.
3. `trace_path` for affected call chains.
4. `detect_changes` during review to estimate blast radius.

The enriched context should be summarized and stored as iteration metadata, not
treated as verified truth.

Current recommended manual flow before a risky task:

```bash
python -m ai_orchestrator memory status --repo .
python -m ai_orchestrator memory index --repo . --approve
python -m ai_orchestrator memory architecture --repo .
python -m ai_orchestrator memory search --repo . --pattern ".*Policy.*" --label Class
python -m ai_orchestrator memory impact --repo .
```

The next automation step should be opt-in, such as `start --use-memory`, and
must stay read-only unless the user separately approves indexing.

## Shipping Packet Usage

Shipping packets can include:

- indexed / not indexed status;
- architecture summary;
- changed symbols and blast radius;
- high-risk affected boundaries;
- ADR links or gaps.

## Do Not Do Yet

- Do not vendor the C indexing engine into `ai-orch`.
- Do not add a production dependency on the external binary.
- Do not run installer scripts automatically.
- Do not commit `.codebase-memory/graph.db.zst` by default.
- Do not replace planned MCP/ACP research with an ad hoc runtime integration.

## First Implementation Step

Add a small optional wrapper that invokes `codebase-memory-mcp cli` through
`ProcessRunner`. It should expose read-only commands first and leave indexing
behind policy approval.

Implemented baseline:

- `CodebaseMemoryClient` builds structured argv and never uses `shell=True`.
- Read-only tools can run directly through `ProcessRunner`.
- Indexing, ADR writes, trace ingestion, project deletion, and unknown tools
  require exact command approval.
- `PolicyEngine` still evaluates the final argv before execution.

CLI surface:

```bash
python -m ai_orchestrator memory status --repo .
python -m ai_orchestrator memory search --repo . --pattern ".*Supervisor.*" --label Class
python -m ai_orchestrator memory architecture --repo .
python -m ai_orchestrator memory impact --repo .
python -m ai_orchestrator memory index --repo . --approve
```

`memory index` does not run unless the caller passes `--approve` or an exact
`--approve-command` string.
