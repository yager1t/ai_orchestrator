from pathlib import Path

REQUIRED = [
    "AGENTS.md",
    "docs/AI_DEV_RULES.md",
    "docs/AGENT_TASK_DISTRIBUTION.md",
    "ai_orchestrator/__main__.py",
    "tests/test_mock_agent.py",
]

missing = [path for path in REQUIRED if not Path(path).exists()]
if missing:
    raise SystemExit(f"Missing required files: {missing}")

print("Project skeleton looks OK")
