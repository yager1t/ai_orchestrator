# Python Quick-Start Example

This is the smallest runnable `ai-orch` setup for a Python repository. It uses
the built-in `mock` agent, so it does not need any external AI credentials.

The supervisor runs the mock agent, then runs the configured verification
command. The command uses the standard-library `unittest` runner to discover
and run the tests in this directory.

## Files

- `.ai-orch/config.yaml` - selects the `mock` agent and defines a Python
  verification command.
- `hello.py` - a tiny module used by the example.
- `test_hello.py` - standard-library tests for `hello.py`.

## Run the example

From the repository root:

```bash
python -m ai_orchestrator start \
  --repo examples/python_quickstart \
  --task "Confirm the Python quick-start passes its tests."
```

The task should complete in one iteration because the verification command
passes immediately.

You can also run verification directly:

```bash
python -m ai_orchestrator verify --repo examples/python_quickstart
```

## Expected result

- Verification status: `passed`
- Supervisor decision: `done`
