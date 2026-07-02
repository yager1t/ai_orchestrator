from pathlib import Path

from ai_orchestrator.agents.base import SessionRef, TaskContext
from ai_orchestrator.agents.generic import GenericCLIAdapter


def test_generic_cli_adapter_runs_prompt(tmp_path: Path) -> None:
    agent = GenericCLIAdapter(
        command="python",
        args=["-c", "import sys; print(sys.argv[1])", "{prompt}"],
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))
    result = agent.run_step(session, "hello generic")

    assert agent.check_available() is True
    assert result.status == "success"
    assert "hello generic" in result.raw_output


def test_generic_cli_adapter_logs_metadata_without_prompt_or_output(caplog, tmp_path: Path) -> None:
    secret = "secret-generic-token"
    agent = GenericCLIAdapter(
        command="python",
        args=["-c", "import sys; print(sys.argv[1])", "{prompt}"],
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    with caplog.at_level("DEBUG", logger="ai_orchestrator.agents.generic"):
        result = agent.run_step(session, secret)

    assert result.status == "success"
    assert secret in result.raw_output
    assert secret not in caplog.text
    assert "generic run finished" in caplog.text


def test_generic_cli_adapter_reports_failure(tmp_path: Path) -> None:
    agent = GenericCLIAdapter(
        command="python",
        args=["-c", "import sys; print('bad'); sys.exit(5)"],
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))
    result = agent.run_step(session, "hello")

    assert result.status == "failed"
    assert "bad" in result.raw_output


def test_generic_cli_adapter_passes_env(tmp_path: Path) -> None:
    agent = GenericCLIAdapter(
        command="python",
        args=["-c", "import os; print(os.environ['AI_ORCH_GENERIC_ENV'])"],
        env={"AI_ORCH_GENERIC_ENV": "configured"},
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "hello")

    assert result.status == "success"
    assert "configured" in result.raw_output


def test_generic_cli_adapter_rejects_unknown_session(tmp_path: Path) -> None:
    agent = GenericCLIAdapter(command="python", args=["-c", "print('ok')"])
    session = SessionRef(session_id="missing", agent_name="generic")

    result = agent.run_step(session, "hello")

    assert result.status == "failed"
    assert result.error == "Unknown generic CLI session"


def test_generic_cli_adapter_stop_session(tmp_path: Path) -> None:
    agent = GenericCLIAdapter(command="python", args=["-c", "print('ok')"])
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    agent.stop_session(session)
    result = agent.run_step(session, "hello")

    assert result.status == "failed"
    assert result.error == "Unknown generic CLI session"
