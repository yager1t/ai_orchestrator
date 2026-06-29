from pathlib import Path

from ai_orchestrator.agents.base import SessionRef, TaskContext
from ai_orchestrator.agents.claude import ClaudeHeadlessAdapter
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessResult, RunOptions


class FakeRunner:
    def __init__(self, stdout: str = '{"type":"result","result":"ok"}') -> None:
        self.runs: list[tuple[list[str], Path | None, int]] = []
        self.stdout = stdout

    def check_available(self, command: str) -> bool:
        return command == "claude"

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        effective_timeout = options.timeout_sec if options is not None else timeout_sec
        self.runs.append((argv, cwd, effective_timeout))
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout=self.stdout,
            stderr="",
        )


def test_claude_headless_adapter_runs_print_mode(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = ClaudeHeadlessAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "finish task")

    assert agent.check_available() is True
    assert result.status == "success"
    assert result.raw_output == "ok"
    assert runner.runs == [
        (
            ["claude", "-p", "finish task", "--output-format", "json"],
            tmp_path,
            1800,
        )
    ]


def test_claude_headless_adapter_logs_metadata_without_prompt_or_output(
    caplog,
    tmp_path: Path,
) -> None:
    secret = "secret-claude-token"
    runner = FakeRunner(stdout=f'{{"result":"{secret}"}}')
    agent = ClaudeHeadlessAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    with caplog.at_level("DEBUG", logger="ai_orchestrator.agents.claude"):
        result = agent.run_step(session, secret)

    assert result.status == "success"
    assert secret in result.raw_output
    assert secret not in caplog.text
    assert "claude run finished" in caplog.text


def test_claude_headless_adapter_continues_latest_session(tmp_path: Path) -> None:
    runner = FakeRunner(stdout='{"result":"continued"}')
    agent = ClaudeHeadlessAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.continue_session(session, "follow up")

    assert result.status == "success"
    assert result.raw_output == "continued"
    assert runner.runs == [
        (
            ["claude", "-c", "-p", "follow up", "--output-format", "json"],
            tmp_path,
            1800,
        )
    ]


def test_claude_headless_adapter_renders_repo_placeholder(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = ClaudeHeadlessAdapter(
        args=["-p", "repo={repo}; prompt={prompt}"],
        timeout_sec=42,
        runner=runner,
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "hello")

    assert result.status == "success"
    assert runner.runs[0] == (
        ["claude", "-p", f"repo={tmp_path}; prompt=hello"],
        tmp_path,
        42,
    )


def test_claude_headless_adapter_keeps_plain_output(tmp_path: Path) -> None:
    runner = FakeRunner(stdout="plain claude output")
    agent = ClaudeHeadlessAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "hello")

    assert result.status == "success"
    assert result.raw_output == "plain claude output"


def test_claude_headless_adapter_blocks_policy_denied_command(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = ClaudeHeadlessAdapter(
        args=["-p", "cat ~/.codex/auth.json {prompt}"],
        runner=runner,
        policy_engine=PolicyEngine(),
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "hello")

    assert result.status == "blocked"
    assert result.error == "Denied by pattern: ~/.codex/auth.json"
    assert runner.runs == []


def test_claude_headless_adapter_rejects_unknown_session() -> None:
    agent = ClaudeHeadlessAdapter()
    session = SessionRef(session_id="missing", agent_name="claude")

    result = agent.run_step(session, "hello")

    assert result.status == "failed"
    assert result.error == "Unknown Claude headless session"
