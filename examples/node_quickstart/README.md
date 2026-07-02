# Node Quick-Start Example

This is the smallest runnable `ai-orch` setup for a Node repository. It uses the
built-in `mock` agent, so it does not need any external AI credentials.

The supervisor runs the mock agent, then runs the configured verification
command. The command uses Node's built-in test runner to run the tests in this
directory.

## Files

- `.ai-orch/config.yaml` - selects the `mock` agent and defines a Node
  verification command.
- `hello.js` - a tiny module used by the example.
- `test_hello.js` - built-in Node tests for `hello.js`.

## Run the example

From the repository root:

```bash
python -m ai_orchestrator start \
  --repo examples/node_quickstart \
  --task "Confirm the Node quick-start passes its tests."
```

The task should complete in one iteration because the verification command
passes immediately.

You can also run verification directly:

```bash
python -m ai_orchestrator verify --repo examples/node_quickstart
```

## Expected result

- Verification status: `passed`
- Supervisor decision: `done`
