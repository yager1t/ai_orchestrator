from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner


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
    def __init__(
        self,
        policy_engine: PolicyEngine | None = None,
        process_runner: ProcessRunner | None = None,
        approved_commands: set[str] | None = None,
    ) -> None:
        self.policy_engine = policy_engine
        self.process_runner = process_runner or ProcessRunner()
        self.approved_commands = frozenset(approved_commands or set())

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
                if command.run not in self.approved_commands:
                    return VerificationResult(
                        name=command.name,
                        status="needs_approval",
                        exit_code=None,
                        stdout="",
                        stderr="",
                        error=decision.reason,
                    )

        try:
            argv = shlex.split(command.run)
        except ValueError as exc:
            return VerificationResult(
                name=command.name,
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error=f"Invalid command: {exc}",
            )

        completed = self.process_runner.run(argv, cwd=cwd, timeout_sec=command.timeout_sec)

        status = "passed" if completed.status == "success" else completed.status
        return VerificationResult(
            name=command.name,
            status=status,
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error=completed.error,
        )

    def run_many(
        self,
        commands: list[VerificationCommand],
        cwd: Path | None = None,
    ) -> list[VerificationResult]:
        return [self.run(command, cwd=cwd) for command in commands]
