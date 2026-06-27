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


def test_process_runner_logs_metadata_without_output(caplog) -> None:
    secret_output = "secret-output-token"

    with caplog.at_level("DEBUG", logger="ai_orchestrator.process.runner"):
        result = ProcessRunner().run(["python", "-c", f"print('{secret_output}')"])

    assert result.status == "success"
    assert secret_output in result.stdout
    assert secret_output not in caplog.text
    assert "process exited" in caplog.text
