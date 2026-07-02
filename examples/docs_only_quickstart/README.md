# Docs-Only Quick Start Example

This is the smallest runnable `ai-orch` setup for a repository that contains
only Markdown documentation. It uses the built-in `mock` agent, so it does not
need any external AI credentials.

The supervisor runs the mock agent, then runs the configured verification
command. The command only checks that `README.md` contains a top-level heading.

## Files

- `.ai-orch/config.yaml` - selects the `mock` agent and defines a docs-style
  verification command.
- `README.md` - the only documentation file in the repository.

## Run the example

From the repository root:

```bash
python -m ai_orchestrator start \
  --repo examples/docs_only_quickstart \
  --task "Confirm the README has a top-level heading."
```

The task should complete in one iteration because the verification command
passes immediately.

You can also run verification directly:

```bash
python -m ai_orchestrator verify --repo examples/docs_only_quickstart
```

## Expected result

- Verification status: `passed`
- Supervisor decision: `done`
