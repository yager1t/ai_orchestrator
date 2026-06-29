from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import pytest

from ai_orchestrator.agents.base import AgentAdapter, AgentResult, SessionRef, TaskContext
from ai_orchestrator.agents.claude import ClaudeHeadlessAdapter
from ai_orchestrator.agents.codex import CodexExecAdapter
from ai_orchestrator.agents.gemini import GeminiCLIAdapter
from ai_orchestrator.agents.generic import GenericCLIAdapter
from ai_orchestrator.agents.kimi import KimiCLIAdapter
from ai_orchestrator.agents.mock import MockAgentAdapter
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessResult, RunOptions


class RunnerBackedAdapter(Protocol):
    name: str
    command: str
    timeout_sec: int
    args: list[str]
    runner: "ContractRunner"

    def check_available(self) -> bool:
        ...

    def start_session(self, context: TaskContext) -> SessionRef:
        ...

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        ...

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        ...

    def stop_session(self, session: SessionRef) -> None:
        ...


@dataclass(frozen=True)
class AdapterCase:
    adapter_type: type[RunnerBackedAdapter]
    name: str
    command: str
    args: list[str]
    success_stdout: str
    expected_output: str
    unknown_error: str
    session_prefix: str | None = None
    expected_continue_prefix: list[str] | None = None


class ContractRunner:
    def __init__(self, stdout: str, available: bool = True) -> None:
        self.stdout = stdout
        self.available = available
        self.runs: list[tuple[list[str], Path | None, int, Callable[[], bool] | None]] = []

    def check_available(self, command: str) -> bool:
        return self.available

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        terminate_grace_sec: int = 5,
        should_cancel: Callable[[], bool] | None = None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        effective_timeout = timeout_sec
        effective_cancel = should_cancel
        if options is not None:
            effective_timeout = options.timeout_sec
            effective_cancel = options.should_cancel
        self.runs.append((argv, cwd, effective_timeout, effective_cancel))
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout=self.stdout,
            stderr="stderr fallback",
        )


ADAPTER_CASES = [
    AdapterCase(
        adapter_type=GenericCLIAdapter,
        name="generic",
        command="generic-agent",
        args=["--repo", "{repo}", "--prompt", "{prompt}"],
        success_stdout="generic ok",
        expected_output="generic ok",
        unknown_error="Unknown generic CLI session",
        session_prefix="generic",
    ),
    AdapterCase(
        adapter_type=GeminiCLIAdapter,
        name="gemini",
        command="gemini",
        args=["-p", "{prompt}"],
        success_stdout="gemini ok",
        expected_output="gemini ok",
        unknown_error="Unknown generic CLI session",
        session_prefix="generic",
    ),
    AdapterCase(
        adapter_type=KimiCLIAdapter,
        name="kimi",
        command="kimi",
        args=["--prompt", "{prompt}"],
        success_stdout="kimi ok",
        expected_output="kimi ok",
        unknown_error="Unknown generic CLI session",
        session_prefix="generic",
    ),
    AdapterCase(
        adapter_type=CodexExecAdapter,
        name="codex",
        command="codex",
        args=["exec", "--json", "{prompt}"],
        success_stdout='{"type":"result","message":"codex ok"}',
        expected_output="codex ok",
        unknown_error="Unknown Codex exec session",
        session_prefix="codex",
        expected_continue_prefix=["codex", "exec", "--json", "resume"],
    ),
    AdapterCase(
        adapter_type=ClaudeHeadlessAdapter,
        name="claude",
        command="claude",
        args=["-p", "{prompt}", "--output-format", "json"],
        success_stdout='{"result":"claude ok"}',
        expected_output="claude ok",
        unknown_error="Unknown Claude headless session",
        session_prefix="claude",
        expected_continue_prefix=["claude", "-c", "-p"],
    ),
]


def build_runner_backed_adapter(case: AdapterCase, runner: ContractRunner) -> RunnerBackedAdapter:
    return case.adapter_type(
        command=case.command,
        args=list(case.args),
        timeout_sec=17,
        name=case.name,
        runner=runner,
        policy_engine=PolicyEngine(),
    )


@pytest.mark.parametrize("case", ADAPTER_CASES, ids=[case.name for case in ADAPTER_CASES])
def test_runner_backed_adapters_follow_session_contract(
    tmp_path: Path,
    case: AdapterCase,
) -> None:
    runner = ContractRunner(stdout=case.success_stdout)
    adapter = build_runner_backed_adapter(case, runner)
    cancelled = False

    def should_cancel() -> bool:
        return cancelled

    context = TaskContext(task="demo", repo_path=tmp_path, cancellation_requested=should_cancel)

    session = adapter.start_session(context)
    result = adapter.run_step(session, "finish task")

    assert adapter.check_available() is True
    assert session.agent_name == case.name
    assert session.session_id.startswith(f"{case.session_prefix}-")
    assert result.status == "success"
    assert result.raw_output == case.expected_output
    assert result.session_id == session.session_id
    assert result.error is None
    assert runner.runs[0][1:] == (tmp_path, 17, should_cancel)

    expected_run_argv = [
        case.command,
        *[
            item.replace("{repo}", str(tmp_path)).replace("{prompt}", "finish task")
            for item in case.args
        ],
    ]
    assert runner.runs[0][0] == expected_run_argv

    continued = adapter.continue_session(session, "follow up")

    assert continued.status == "success"
    assert continued.session_id == session.session_id
    assert runner.runs[1][1:] == (tmp_path, 17, should_cancel)
    if case.expected_continue_prefix is None:
        assert runner.runs[1][0] == [
            case.command,
            *[
                item.replace("{repo}", str(tmp_path)).replace("{prompt}", "follow up")
                for item in case.args
            ],
        ]
    else:
        assert runner.runs[1][0][: len(case.expected_continue_prefix)] == case.expected_continue_prefix
        assert "follow up" in runner.runs[1][0]

    adapter.stop_session(session)
    stopped = adapter.run_step(session, "after stop")

    assert stopped.status == "failed"
    assert stopped.error == case.unknown_error


@pytest.mark.parametrize("case", ADAPTER_CASES, ids=[case.name for case in ADAPTER_CASES])
def test_runner_backed_adapters_report_unavailable_binary(case: AdapterCase) -> None:
    runner = ContractRunner(stdout=case.success_stdout, available=False)
    adapter = build_runner_backed_adapter(case, runner)

    assert adapter.check_available() is False


@pytest.mark.parametrize("case", ADAPTER_CASES, ids=[case.name for case in ADAPTER_CASES])
def test_runner_backed_adapters_reject_unknown_sessions(case: AdapterCase) -> None:
    runner = ContractRunner(stdout=case.success_stdout)
    adapter = build_runner_backed_adapter(case, runner)

    result = adapter.run_step(SessionRef(session_id="missing", agent_name=case.name), "hello")

    assert result.status == "failed"
    assert result.raw_output == ""
    assert result.error == case.unknown_error
    assert runner.runs == []


@pytest.mark.parametrize("case", ADAPTER_CASES, ids=[case.name for case in ADAPTER_CASES])
def test_runner_backed_adapters_enforce_policy_before_process(
    tmp_path: Path,
    case: AdapterCase,
) -> None:
    runner = ContractRunner(stdout=case.success_stdout)
    adapter = case.adapter_type(
        command=case.command,
        args=["{prompt}"],
        timeout_sec=17,
        name=case.name,
        runner=runner,
        policy_engine=PolicyEngine(
            deny_patterns=["deny-token"],
            ask_patterns=["ask-token"],
        ),
    )
    session = adapter.start_session(TaskContext(task="demo", repo_path=tmp_path))

    denied = adapter.run_step(session, "deny-token")
    needs_approval = adapter.run_step(session, "ask-token")

    assert denied.status == "blocked"
    assert denied.error == "Denied by pattern: deny-token"
    assert needs_approval.status == "needs_approval"
    assert needs_approval.error == "Requires approval: ask-token"
    assert runner.runs == []


def test_mock_adapter_follows_minimal_contract(tmp_path: Path) -> None:
    adapter: AgentAdapter = MockAgentAdapter(
        scripted_status="success",
        scripted_output="mock ok",
        scripted_files_changed=["changed.py"],
    )
    context = TaskContext(task="demo", repo_path=tmp_path)

    session = adapter.start_session(context)
    result = adapter.run_step(session, "finish task")
    continued = adapter.continue_session(session, "follow up")
    adapter.stop_session(session)

    assert adapter.check_available() is True
    assert session.agent_name == "mock"
    assert session.session_id.startswith("mock-")
    assert result.status == "success"
    assert result.raw_output == "mock ok"
    assert result.session_id == session.session_id
    assert result.files_changed == ["changed.py"]
    assert continued.session_id == session.session_id
