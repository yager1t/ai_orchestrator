from pathlib import Path

from ai_orchestrator.agents.base import SessionRef, TaskContext
from ai_orchestrator.agents.codex import CodexExecAdapter
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessResult


class FakeRunner:
    def __init__(
        self,
        stdout: str = '{"type":"result","message":"ok"}',
        stdout_sequence: list[str] | None = None,
    ) -> None:
        self.runs: list[tuple[list[str], Path | None, int]] = []
        self.stdout = stdout
        self.stdout_sequence = stdout_sequence or []

    def check_available(self, command: str) -> bool:
        return command == "codex"

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
    ) -> ProcessResult:
        self.runs.append((argv, cwd, timeout_sec))
        stdout = self.stdout_sequence.pop(0) if self.stdout_sequence else self.stdout
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout=stdout,
            stderr="",
        )


def test_codex_exec_adapter_runs_default_command(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = CodexExecAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "finish task")

    assert agent.check_available() is True
    assert result.status == "success"
    assert result.raw_output == "ok"
    assert runner.runs == [
        (
            ["codex", "exec", "--json", "--sandbox", "workspace-write", "finish task"],
            tmp_path,
            1800,
        )
    ]


def test_codex_exec_adapter_logs_metadata_without_prompt_or_output(caplog, tmp_path: Path) -> None:
    secret = "secret-codex-token"
    runner = FakeRunner(stdout=f'{{"type":"result","message":"{secret}"}}')
    agent = CodexExecAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    with caplog.at_level("DEBUG", logger="ai_orchestrator.agents.codex"):
        result = agent.run_step(session, secret)

    assert result.status == "success"
    assert secret in result.raw_output
    assert secret not in caplog.text
    assert "codex run finished" in caplog.text


def test_codex_exec_adapter_normalizes_jsonl_output(tmp_path: Path) -> None:
    runner = FakeRunner(
        stdout='\n'.join(
            [
                '{"type":"progress","message":"working"}',
                '{"type":"result","message":{"content":[{"text":"finished"}]}}',
            ]
        )
    )
    agent = CodexExecAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "finish task")

    assert result.status == "success"
    assert result.raw_output == "working\nfinished"


def test_codex_exec_adapter_keeps_plain_output(tmp_path: Path) -> None:
    runner = FakeRunner(stdout="plain codex output")
    agent = CodexExecAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "finish task")

    assert result.status == "success"
    assert result.raw_output == "plain codex output"


def test_codex_exec_adapter_continues_with_last_by_default(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = CodexExecAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    agent.run_step(session, "first")
    result = agent.continue_session(session, "follow up")

    assert result.status == "success"
    assert runner.runs[1] == (
        [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "resume",
            "--last",
            "follow up",
        ],
        tmp_path,
        1800,
    )


def test_codex_exec_adapter_continues_with_session_id_from_json(tmp_path: Path) -> None:
    runner = FakeRunner(
        stdout_sequence=[
            '{"type":"session","session_id":"11111111-1111-1111-1111-111111111111"}',
            '{"type":"result","message":"continued"}',
        ]
    )
    agent = CodexExecAdapter(runner=runner)
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    agent.run_step(session, "first")
    result = agent.continue_session(session, "follow up")

    assert result.status == "success"
    assert result.raw_output == "continued"
    assert runner.runs[1] == (
        [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "resume",
            "11111111-1111-1111-1111-111111111111",
            "follow up",
        ],
        tmp_path,
        1800,
    )


def test_codex_exec_adapter_blocks_resume_policy_ask(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = CodexExecAdapter(runner=runner, policy_engine=PolicyEngine())
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    agent.run_step(session, "first")
    result = agent.continue_session(session, "git push origin main")

    assert result.status == "needs_approval"
    assert result.error == "Requires approval: git push"
    assert len(runner.runs) == 1


def test_codex_exec_adapter_renders_repo_placeholder(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = CodexExecAdapter(
        args=["exec", "--cd", "{repo}", "{prompt}"],
        timeout_sec=42,
        runner=runner,
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "hello")

    assert result.status == "success"
    assert runner.runs[0] == (
        ["codex", "exec", "--cd", str(tmp_path), "hello"],
        tmp_path,
        42,
    )


def test_codex_exec_adapter_blocks_policy_denied_command(tmp_path: Path) -> None:
    runner = FakeRunner()
    agent = CodexExecAdapter(
        args=["exec", "cat ~/.codex/auth.json", "{prompt}"],
        runner=runner,
        policy_engine=PolicyEngine(),
    )
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "hello")

    assert result.status == "blocked"
    assert result.error == "Denied by pattern: ~/.codex/auth.json"
    assert runner.runs == []


def test_codex_exec_adapter_rejects_unknown_session() -> None:
    agent = CodexExecAdapter()
    session = SessionRef(session_id="missing", agent_name="codex")

    result = agent.run_step(session, "hello")

    assert result.status == "failed"
    assert result.error == "Unknown Codex exec session"
