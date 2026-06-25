from pathlib import Path

from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.verification.runner import VerificationCommand, VerificationRunner


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
