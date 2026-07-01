# Real Agent Smoke Fixture

This fixture exercises a real `generic_cli` adapter through a local Python
helper. It does not use the mock agent and does not require external AI
credentials.

The helper writes `SMOKE_RESULT.md`; verification passes only when
`tools/verify_smoke.py` confirms the expected markers.

Run directly:

```bash
python -m ai_orchestrator start --repo examples/real_agent_smoke --task "Run the real-agent smoke fixture."
```

Prefer the operator script for repeatable runs because it copies the fixture to
a temporary directory before execution:

```bash
python scripts/run_real_agent_smoke.py
```
