import subprocess
import time

import pytest

from ai_orchestrator.process.runner import ProcessRunner, RunOptions


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


def test_process_runner_check_available_expands_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("AI_ORCH_TOOL_DIR", "C:\\Tools")
    monkeypatch.setattr(
        "ai_orchestrator.process.runner.shutil.which",
        lambda command: command if command == "C:\\Tools\\demo.exe" else None,
    )

    assert ProcessRunner().check_available("%AI_ORCH_TOOL_DIR%\\demo.exe") is True


def test_process_runner_uses_resolved_executable(monkeypatch) -> None:
    captured_argv = []

    class FakePopen:
        def __init__(self, argv, *args, **kwargs) -> None:
            captured_argv.append(argv)
            self.returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    monkeypatch.setattr(
        "ai_orchestrator.process.runner.shutil.which",
        lambda command: "C:\\Tools\\demo.cmd" if command == "demo" else None,
    )
    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    result = ProcessRunner().run(["demo", "--version"])

    assert result.status == "success"
    assert captured_argv == [["C:\\Tools\\demo.cmd", "--version"]]


def test_process_runner_expands_executable_env_vars(monkeypatch) -> None:
    captured_argv = []

    class FakePopen:
        def __init__(self, argv, *args, **kwargs) -> None:
            captured_argv.append(argv)
            self.returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    monkeypatch.setenv("AI_ORCH_TOOL_DIR", "C:\\Tools")
    monkeypatch.setattr(
        "ai_orchestrator.process.runner.shutil.which",
        lambda command: command if command == "C:\\Tools\\demo.exe" else None,
    )
    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    result = ProcessRunner().run(["%AI_ORCH_TOOL_DIR%\\demo.exe", "--version"])

    assert result.status == "success"
    assert captured_argv == [["C:\\Tools\\demo.exe", "--version"]]


def test_process_runner_passes_run_options_env(monkeypatch) -> None:
    captured_env = {}

    class FakePopen:
        def __init__(self, argv, *args, **kwargs) -> None:
            captured_env.update(kwargs.get("env") or {})
            self.returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    monkeypatch.setattr("ai_orchestrator.process.runner.shutil.which", lambda command: command)
    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    monkeypatch.setenv("AI_ORCH_RUNNER_BASE", "configured")

    result = ProcessRunner().run(
        ["demo"],
        options=RunOptions(env={"AI_ORCH_RUNNER_ENV": "%AI_ORCH_RUNNER_BASE%"}),
    )

    assert result.status == "success"
    assert captured_env["AI_ORCH_RUNNER_ENV"] == "configured"


def test_process_runner_reads_subprocess_output_as_utf8(monkeypatch) -> None:
    captured_kwargs = {}

    class FakePopen:
        def __init__(self, argv, *args, **kwargs) -> None:
            captured_kwargs.update(kwargs)
            self.returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    monkeypatch.setattr("ai_orchestrator.process.runner.shutil.which", lambda command: command)
    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    result = ProcessRunner().run(["demo"])

    assert result.status == "success"
    assert captured_kwargs["encoding"] == "utf-8"
    assert captured_kwargs["errors"] == "replace"


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

    monkeypatch.setattr("ai_orchestrator.process.runner.shutil.which", lambda command: command)
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

    monkeypatch.setattr("ai_orchestrator.process.runner.shutil.which", lambda command: command)
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


def test_process_runner_accepts_run_options(monkeypatch) -> None:
    processes = []

    class FakePopen:
        def __init__(self, *args, **kwargs) -> None:
            self.terminated = False
            self.killed = False
            processes.append(self)

        def communicate(self, timeout=None):
            if not self.terminated:
                raise subprocess.TimeoutExpired(cmd=["slow"], timeout=timeout)
            return "cancel stdout", "cancel stderr"

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setattr("ai_orchestrator.process.runner.shutil.which", lambda command: command)
    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    result = ProcessRunner().run(
        ["slow"],
        options=RunOptions(
            timeout_sec=30,
            terminate_grace_sec=1,
            should_cancel=lambda: True,
        ),
    )

    assert result.status == "cancelled"
    assert result.stdout == "cancel stdout"
    assert result.stderr == "cancel stderr"
    assert processes[0].terminated is True
    assert processes[0].killed is False


def test_process_runner_emits_progress_while_waiting(monkeypatch) -> None:
    progress: list[str] = []

    class FakePopen:
        def __init__(self, *args, **kwargs) -> None:
            self.returncode = 0
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls < 3:
                time.sleep(0.11)
                raise subprocess.TimeoutExpired(cmd=["slow"], timeout=timeout)
            return "done", ""

    monkeypatch.setattr("ai_orchestrator.process.runner.shutil.which", lambda command: command)
    monkeypatch.setattr("ai_orchestrator.process.runner.subprocess.Popen", FakePopen)

    result = ProcessRunner().run(
        ["slow"],
        options=RunOptions(
            timeout_sec=30,
            on_progress=progress.append,
            progress_label="agent demo",
            progress_interval_sec=0.1,
        ),
    )

    assert result.status == "success"
    assert any(message.startswith("agent demo running for ") for message in progress)


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

    monkeypatch.setattr("ai_orchestrator.process.runner.shutil.which", lambda command: command)
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
