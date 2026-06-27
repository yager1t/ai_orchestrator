import subprocess

import pytest

from ai_orchestrator.process.runner import ProcessRunner


def test_process_runner_success() -> None:
    result = ProcessRunner().run(["python", "-c", "print('ok')"])

    assert result.status == "success"
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_process_runner_failure() -> None:
    result = ProcessRunner().run(["python", "-c", "import sys; sys.exit(4)"])

    assert result.status == "failed"
    assert result.exit_code == 4


def test_process_runner_missing_command() -> None:
    result = ProcessRunner().run(["definitely-missing-ai-orch-command"])

    assert result.status == "failed"
    assert result.exit_code is None
    assert result.error == "Command not found: definitely-missing-ai-orch-command"


def test_process_runner_terminates_process_on_timeout(monkeypatch) -> None:
    processes = []

    class FakePopen:
        def __init__(self, *args, **kwargs) -> None:
            self.communicate_calls = 0
            self.terminated = False
            self.killed = False
            self.returncode = None
            processes.append(self)

        def communicate(self, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(cmd=["slow"], timeout=timeout)
            return "partial stdout", "partial stderr"

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    result = ProcessRunner().run(["slow"], timeout_sec=1, terminate_grace_sec=1)

    assert result.status == "timeout"
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"
    assert processes[0].terminated is True
    assert processes[0].killed is False


def test_process_runner_terminates_process_on_cancel(monkeypatch) -> None:
    processes = []
    cancel_checks = 0

    class FakePopen:
        def __init__(self, *args, **kwargs) -> None:
            self.communicate_calls = 0
            self.terminated = False
            self.killed = False
            self.returncode = None
            processes.append(self)

        def communicate(self, timeout=None):
            self.communicate_calls += 1
            if not self.terminated:
                raise subprocess.TimeoutExpired(cmd=["slow"], timeout=timeout)
            return "partial stdout", "partial stderr"

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    def should_cancel() -> bool:
        nonlocal cancel_checks
        cancel_checks += 1
        return cancel_checks >= 2

    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    result = ProcessRunner().run(
        ["slow"],
        timeout_sec=30,
        terminate_grace_sec=1,
        should_cancel=should_cancel,
    )

    assert result.status == "cancelled"
    assert result.error == "Command cancelled"
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"
    assert processes[0].terminated is True
    assert processes[0].killed is False


def test_process_runner_terminates_process_on_keyboard_interrupt(monkeypatch) -> None:
    processes = []

    class FakePopen:
        def __init__(self, *args, **kwargs) -> None:
            self.communicate_calls = 0
            self.terminated = False
            self.killed = False
            processes.append(self)

        def communicate(self, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise KeyboardInterrupt
            return "", ""

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    with pytest.raises(KeyboardInterrupt):
        ProcessRunner().run(["interrupt"], timeout_sec=30, terminate_grace_sec=1)

    assert processes[0].terminated is True
    assert processes[0].killed is False


def test_process_runner_logs_metadata_without_output(caplog) -> None:
    secret_output = "secret-output-token"

    with caplog.at_level("DEBUG", logger="ai_orchestrator.process.runner"):
        result = ProcessRunner().run(["python", "-c", f"print('{secret_output}')"])

    assert result.status == "success"
    assert secret_output in result.stdout
    assert secret_output not in caplog.text
    assert "event=process.exited" in caplog.text
