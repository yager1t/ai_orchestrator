"""Local operator client for the stable CLI control surface."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ai_orchestrator.control.mcp_acp import McpAcpRequest, cli_args_for_operation
from ai_orchestrator.process.runner import ProcessResult, ProcessRunner


class OperatorRunner(Protocol):
    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
    ) -> ProcessResult: ...


@dataclass(frozen=True)
class LocalOperatorResult:
    operation: str
    argv: list[str]
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    payload: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success" and self.exit_code == 0 and self.error is None


@dataclass(frozen=True)
class LocalOperatorClient:
    repo: Path
    runner: OperatorRunner | None = None
    python_executable: str = sys.executable
    timeout_sec: int = 300

    _TEXT_OUTPUT_OPERATIONS = frozenset({"export_trace"})
    _EXPECTED_CONTROL_COMMANDS = {
        "start_task": "start",
        "get_status": "status",
        "list_approvals": "approvals list",
        "approve_action": "approvals approve",
        "reject_action": "approvals reject",
        "retry_approval": "approvals retry",
    }

    def __post_init__(self) -> None:
        object.__setattr__(self, "repo", self.repo.resolve())

    def run(self, request: McpAcpRequest) -> LocalOperatorResult:
        if request.repo.resolve() != self.repo:
            raise ValueError("request repo must match the client repo")

        normalized_request = McpAcpRequest(
            operation=request.operation,
            repo=self.repo,
            task=request.task,
            task_id=request.task_id,
            approval_id=request.approval_id,
            resolution=request.resolution,
            redact=request.redact,
        )
        cli_args = cli_args_for_operation(normalized_request)
        argv = [self.python_executable, "-m", "ai_orchestrator", *cli_args]
        runner = self.runner or ProcessRunner()
        result = runner.run(argv, cwd=self.repo, timeout_sec=self.timeout_sec)

        payload = None
        command_error = _process_error(result)
        error = command_error
        if result.status != "success" or result.exit_code != 0:
            error = command_error
        if request.operation not in self._TEXT_OUTPUT_OPERATIONS:
            if result.stdout.strip():
                try:
                    loaded = json.loads(result.stdout)
                except json.JSONDecodeError as exc:
                    payload_error = f"Invalid JSON output: {exc.msg}"
                    error = (
                        f"{command_error}; {payload_error}"
                        if command_error
                        else payload_error
                    )
                else:
                    if isinstance(loaded, dict):
                        payload = loaded
                        control_error = _control_payload_error(
                            loaded,
                            expected_command=self._EXPECTED_CONTROL_COMMANDS.get(
                                request.operation
                            ),
                        )
                        if control_error and command_error:
                            error = f"{command_error}; {control_error}"
                        elif control_error:
                            error = control_error
                    else:
                        payload_error = "Invalid JSON output: expected object"
                        error = (
                            f"{command_error}; {payload_error}"
                            if command_error
                            else payload_error
                        )
            elif result.status == "success" and result.exit_code == 0:
                error = "Missing JSON output"

        return LocalOperatorResult(
            operation=request.operation,
            argv=argv,
            status=result.status,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            payload=payload,
            error=error,
        )

    def start_task(self, task: str) -> LocalOperatorResult:
        return self.run(McpAcpRequest(operation="start_task", repo=self.repo, task=task))

    def get_status(self, task_id: str) -> LocalOperatorResult:
        return self.run(
            McpAcpRequest(operation="get_status", repo=self.repo, task_id=task_id)
        )

    def list_approvals(self) -> LocalOperatorResult:
        return self.run(McpAcpRequest(operation="list_approvals", repo=self.repo))

    def approve_action(
        self, approval_id: int, *, resolution: str
    ) -> LocalOperatorResult:
        return self.run(
            McpAcpRequest(
                operation="approve_action",
                repo=self.repo,
                approval_id=approval_id,
                resolution=resolution,
            )
        )

    def reject_action(
        self, approval_id: int, *, resolution: str
    ) -> LocalOperatorResult:
        return self.run(
            McpAcpRequest(
                operation="reject_action",
                repo=self.repo,
                approval_id=approval_id,
                resolution=resolution,
            )
        )

    def retry_approval(self, approval_id: int) -> LocalOperatorResult:
        return self.run(
            McpAcpRequest(
                operation="retry_approval",
                repo=self.repo,
                approval_id=approval_id,
            )
        )

    def export_trace(self, task_id: str, *, redact: bool = True) -> LocalOperatorResult:
        return self.run(
            McpAcpRequest(
                operation="export_trace",
                repo=self.repo,
                task_id=task_id,
                redact=redact,
            )
        )


def _process_error(result: ProcessResult) -> str | None:
    if result.status == "success" and result.exit_code == 0:
        return None
    return (
        result.error
        or result.stderr.strip()
        or f"Command failed with exit code {result.exit_code}"
    )


def _control_payload_error(
    payload: dict[str, Any],
    *,
    expected_command: str | None,
) -> str | None:
    schema_version = payload.get("schema_version")
    if schema_version != "1.0":
        return f"Invalid JSON output: expected schema_version '1.0', got {schema_version!r}"

    command = payload.get("command")
    if expected_command is not None and command != expected_command:
        return (
            "Invalid JSON output: expected command "
            f"{expected_command!r}, got {command!r}"
        )

    ok = payload.get("ok")
    if not isinstance(ok, bool):
        return f"Invalid JSON output: expected boolean ok, got {ok!r}"

    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        return "Invalid JSON output: expected non-empty generated_at"

    if ok is True and payload.get("error") is not None:
        return "Invalid JSON output: expected null error for successful operation"

    if ok is False:
        envelope_error = payload.get("error")
        if isinstance(envelope_error, dict):
            code = envelope_error.get("code")
            message = envelope_error.get("message")
            if code and message:
                return f"Control operation failed: {code}: {message}"
            if code:
                return f"Control operation failed: {code}"
        return "Control operation failed"

    return None
