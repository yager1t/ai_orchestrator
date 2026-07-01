from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from ai_orchestrator.cli.app import main
from ai_orchestrator.storage.db import StateStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "examples" / "real_agent_smoke"


def test_real_agent_smoke_fixture_runs_through_generic_adapter(tmp_path: Path) -> None:
    smoke_repo = tmp_path / "smoke"
    shutil.copytree(FIXTURE, smoke_repo)

    exit_code = main(
        [
            "start",
            "--repo",
            str(smoke_repo),
            "--task",
            "Run the real-agent smoke fixture.",
        ]
    )

    result_file = smoke_repo / "SMOKE_RESULT.md"
    tasks = StateStore(smoke_repo / ".ai-orch" / "state" / "ai-orch.db").list_tasks()
    iterations = StateStore(
        smoke_repo / ".ai-orch" / "state" / "ai-orch.db"
    ).list_iterations(tasks[0].task_id)

    assert exit_code == 0
    assert result_file.exists()
    assert "status: done" in result_file.read_text(encoding="utf-8")
    assert tasks[0].status == "done"
    assert iterations[0].agent_name == "generic"


def test_real_agent_smoke_operator_script_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_real_agent_smoke.py"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert "Real-agent smoke run passed." in result.stdout
    assert "Verification passed: smoke-result" in result.stdout
