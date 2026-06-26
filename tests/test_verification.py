from pathlib import Path

from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessResult
from ai_orchestrator.verification.runner import VerificationCommand, VerificationRunner


class RecordingProcessRunner:
    def __init__(self) -> None:
        self.argv: list[str] | None = None
        self.cwd: Path | None = None
        self.timeout_sec: int | None = None

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
    ) -> ProcessResult:
        self.argv = argv
        self.cwd = cwd
        self.timeout_sec = timeout_sec
        return ProcessResult(status="success", exit_code=0, stdout="ok", stderr="")


def test_verification_success() -> None:
    runner = VerificationRunner()
    result = runner.run(VerificationCommand("ok", "python -c \"print('ok')\""))

    assert result.status == "passed"
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_verification_failure() -> None:
    runner = VerificationRunner()
    result = runner.run(VerificationCommand("fail", "python -c \"import sys; sys.exit(3)\""))

    assert result.status == "failed"
    assert result.exit_code == 3


def test_verification_uses_process_runner_with_parsed_argv(tmp_path: Path) -> None:
    process_runner = RecordingProcessRunner()
    runner = VerificationRunner(process_runner=process_runner)
    result = runner.run(
        VerificationCommand("ok", "python -c \"print('ok')\"", timeout_sec=12),
        cwd=tmp_path,
    )

    assert result.status == "passed"
    assert process_runner.argv == ["python", "-c", "print('ok')"]
    assert process_runner.cwd == tmp_path
    assert process_runner.timeout_sec == 12


def test_verification_uses_structured_argv_without_splitting(tmp_path: Path) -> None:
    process_runner = RecordingProcessRunner()
    runner = VerificationRunner(process_runner=process_runner)
    result = runner.run(
        VerificationCommand(
            "ok",
            "",
            timeout_sec=12,
            argv=["python", "-c", "print('ok')"],
        ),
        cwd=tmp_path,
    )

    assert result.status == "passed"
    assert process_runner.argv == ["python", "-c", "print('ok')"]
    assert process_runner.cwd == tmp_path
    assert process_runner.timeout_sec == 12


def test_verification_does_not_execute_shell_operators(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    runner = VerificationRunner()
    result = runner.run(
        VerificationCommand(
            "no-shell",
            f"python -c \"import sys; sys.exit(0)\" && python -c \"from pathlib import Path; Path(r'{marker}').write_text('ran')\"",
        )
    )

    assert result.status == "passed"
    assert marker.exists() is False


def test_verification_reports_invalid_command() -> None:
    runner = VerificationRunner()
    result = runner.run(VerificationCommand("invalid", 'python -c "unterminated'))

    assert result.status == "failed"
    assert result.exit_code is None
    assert result.error is not None
    assert "Invalid command" in result.error


def test_verification_policy_denies_command_without_running(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    runner = VerificationRunner(policy_engine=PolicyEngine())
    result = runner.run(
        VerificationCommand(
            "danger",
            f"cat ~/.codex/auth.json && python -c \"from pathlib import Path; Path(r'{marker}').write_text('ran')\"",
        )
    )

    assert result.status == "policy_denied"
    assert result.exit_code is None
    assert marker.exists() is False


def test_verification_policy_requires_approval_without_running(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    runner = VerificationRunner(policy_engine=PolicyEngine())
    result = runner.run(
        VerificationCommand(
            "approval",
            f"git push origin main && python -c \"from pathlib import Path; Path(r'{marker}').write_text('ran')\"",
        )
    )

    assert result.status == "needs_approval"
    assert result.exit_code is None
    assert marker.exists() is False


def test_verification_runs_exactly_approved_command() -> None:
    command = "python -c \"print('approval-token ok')\""
    runner = VerificationRunner(
        policy_engine=PolicyEngine(ask_patterns=["approval-token"]),
        approved_commands={command},
    )

    result = runner.run(VerificationCommand("approved", command))

    assert result.status == "passed"
    assert result.exit_code == 0
    assert "approval-token ok" in result.stdout


def test_verification_approval_requires_exact_command_match(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    approved_command = "python -c \"print('approval-token ok')\""
    changed_command = (
        f"python -c \"from pathlib import Path; "
        f"Path(r'{marker}').write_text('ran approval-token')\""
    )
    runner = VerificationRunner(
        policy_engine=PolicyEngine(ask_patterns=["approval-token"]),
        approved_commands={approved_command},
    )

    result = runner.run(VerificationCommand("changed", changed_command))

    assert result.status == "needs_approval"
    assert result.exit_code is None
    assert marker.exists() is False


def test_verification_approval_does_not_override_deny(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    command = (
        f"cat ~/.codex/auth.json && python -c "
        f"\"from pathlib import Path; Path(r'{marker}').write_text('ran')\""
    )
    runner = VerificationRunner(
        policy_engine=PolicyEngine(),
        approved_commands={command},
    )

    result = runner.run(VerificationCommand("denied", command))

    assert result.status == "policy_denied"
    assert result.exit_code is None
    assert marker.exists() is False


def test_verification_structured_argv_policy_uses_executed_command() -> None:
    runner = VerificationRunner(
        policy_engine=PolicyEngine(ask_patterns=["approval-token"]),
    )

    result = runner.run(
        VerificationCommand(
            "argv",
            "",
            argv=["python", "-c", "print('approval-token ok')"],
        )
    )

    assert result.status == "needs_approval"
