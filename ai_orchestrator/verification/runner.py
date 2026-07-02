from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner, RunOptions


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationCommand:
    name: str
    run: str
    timeout_sec: int = 300
    argv: list[str] | None = None


@dataclass(frozen=True)
class VerificationResult:
    name: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None = None
    command_string: str | None = None


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
        logger.debug(
            "starting verification name=%s has_argv=%s timeout_sec=%s",
            command.name,
            command.argv is not None,
            command.timeout_sec,
        )
        policy_command = command.run
        argv = command.argv
        if argv is not None:
            policy_command = subprocess.list2cmdline(argv)

        if self.policy_engine is not None:
            decision = self.policy_engine.evaluate_command(policy_command)
            if decision.action == "deny":
                logger.warning(
                    "verification policy denied name=%s reason=%s",
                    command.name,
                    decision.reason,
                )
                return VerificationResult(
                    name=command.name,
                    status="policy_denied",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    error=decision.reason,
                )
            if decision.action == "ask":
                if policy_command not in self.approved_commands:
                    logger.warning(
                        "verification needs approval name=%s reason=%s",
                        command.name,
                        decision.reason,
                    )
                    return VerificationResult(
                        name=command.name,
                        status="needs_approval",
                        exit_code=None,
                        stdout="",
                        stderr="",
                        error=decision.reason,
                        command_string=policy_command,
                    )

        if argv is None:
            try:
                argv = shlex.split(command.run)
            except ValueError as exc:
                logger.warning("verification invalid command name=%s", command.name)
                return VerificationResult(
                    name=command.name,
                    status="failed",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    error=f"Invalid command: {exc}",
                )

        completed = self.process_runner.run(
            argv,
            cwd=cwd,
            options=RunOptions(timeout_sec=command.timeout_sec),
        )

        status = "passed" if completed.status == "success" else completed.status
        logger.debug(
            "verification finished name=%s status=%s exit_code=%s",
            command.name,
            status,
            completed.exit_code,
        )
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
