from pathlib import Path

from ai_orchestrator.agents.mock import MockAgentAdapter
from ai_orchestrator.agents.base import TaskContext


def test_mock_agent_returns_success() -> None:
    agent = MockAgentAdapter()
    context = TaskContext(task="test task", repo_path=Path("."))
    session = agent.start_session(context)
    result = agent.run_step(session, "hello")

    assert agent.check_available() is True
    assert result.status == "success"
    assert result.session_id == session.session_id
    assert "hello" in result.raw_output


def test_mock_agent_supports_scripted_result() -> None:
    agent = MockAgentAdapter(
        scripted_status="blocked",
        scripted_output="blocked output",
        scripted_error="blocked reason",
        scripted_files_changed=["demo.py"],
    )
    session = agent.start_session(TaskContext(task="test task", repo_path=Path(".")))

    result = agent.run_step(session, "hello")

    assert result.status == "blocked"
    assert result.raw_output == "blocked output"
    assert result.error == "blocked reason"
    assert result.files_changed == ["demo.py"]
