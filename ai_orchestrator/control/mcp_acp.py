"""MCP/ACP operation boundary mapped to the local CLI control surface.

This module intentionally does not run commands or start a server. Future
protocol adapters can use it to keep operation semantics aligned with the
existing supervisor-owned CLI contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


McpAcpOperation = Literal[
    "start_task",
    "get_status",
    "list_approvals",
    "approve_action",
    "reject_action",
    "retry_approval",
    "export_trace",
]


@dataclass(frozen=True)
class McpAcpRequest:
    operation: McpAcpOperation
    repo: Path
    task: str | None = None
    task_id: str | None = None
    approval_id: int | None = None
    resolution: str | None = None
    redact: bool = True


def cli_args_for_operation(request: McpAcpRequest) -> list[str]:
    """Return ai-orch CLI args for one future MCP/ACP operation.

    The returned argv must still be executed through the normal CLI process.
    That preserves supervisor completion authority, approval handling, policy
    checks, and trace/export behavior.
    """

    repo_args = ["--repo", str(request.repo)]

    if request.operation == "start_task":
        task = _required_text(request.task, "task")
        return ["start", "--task", task, *repo_args]
    if request.operation == "get_status":
        return ["status", _required_text(request.task_id, "task_id"), *repo_args, "--json"]
    if request.operation == "list_approvals":
        return ["approvals", "list", *repo_args, "--json"]
    if request.operation == "approve_action":
        return [
            "approvals",
            "approve",
            _required_approval_id(request.approval_id),
            *repo_args,
            "--resolution",
            _required_text(request.resolution, "resolution"),
            "--json",
        ]
    if request.operation == "reject_action":
        return [
            "approvals",
            "reject",
            _required_approval_id(request.approval_id),
            *repo_args,
            "--resolution",
            _required_text(request.resolution, "resolution"),
            "--json",
        ]
    if request.operation == "retry_approval":
        return [
            "approvals",
            "retry",
            _required_approval_id(request.approval_id),
            *repo_args,
            "--json",
        ]
    if request.operation == "export_trace":
        args = ["export", _required_text(request.task_id, "task_id"), *repo_args]
        if request.redact:
            args.append("--redact")
        return args
    raise ValueError(f"Unsupported MCP/ACP operation: {request.operation}")


def _required_text(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required for this operation")
    return value


def _required_approval_id(value: int | None) -> str:
    if value is None:
        raise ValueError("approval_id is required for this operation")
    if value <= 0:
        raise ValueError("approval_id must be positive")
    return str(value)
