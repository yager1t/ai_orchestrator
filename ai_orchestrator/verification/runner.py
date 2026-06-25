from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_orchestrator.policy.engine import PolicyEngine


@dataclass(frozen=True)
class VerificationCommand:
    name: str
    run: str
    timeout_sec: int = 300


@dataclass(frozen=True)
class VerificationResult:
    name: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None = None


class VerificationRunner:
    def __init__(self, policy_engine: PolicyEngine | None = None) -> None:
        self.policy_engine = policy_engine

    def run(self, command: VerificationCommand, cwd: Path | None = None) -> VerificationResult:
        if self.policy_engine is not None:
            decision = self.policy_engine.evaluate_command(command.run)
            if decision.action == "deny":
                return VerificationResult(
                    name=command.name,
                    status="policy_denied",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    error=decision.reason,
                )
            if decision.action == "ask":
                return VerificationResult(
                    name=command.name,
                    status="needs_approval",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    error=decision.reason,
                )

        try:
            completed = subprocess.run(
                command.run,
                cwd=str(cwd) if cwd else None,
                shell=True,
                capture_output=True,
                text=True,
                timeout=command.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return VerificationResult(
                name=command.name,
                status="timeout",
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                error=f"Command timed out after {command.timeout_sec}s",
            )

        status = "passed" if completed.returncode == 0 else "failed"
        return VerificationResult(
            name=command.name,
            status=status,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run_many(
        self,
        commands: list[VerificationCommand],
        cwd: Path | None = None,
    ) -> list[VerificationResult]:
        return [self.run(command, cwd=cwd) for command in commands]
