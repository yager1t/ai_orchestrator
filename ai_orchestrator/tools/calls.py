from __future__ import annotations

from typing import Any

from ai_orchestrator.tools.types import (
    ToolCall,
    ToolRiskTier,
    ToolSpec,
    make_tool_idempotency_key,
)


def make_fs_read_call(
    path: str,
    *,
    task_id: str | None = None,
    iteration_id: int | None = None,
    idempotency_key: str | None = None,
) -> ToolCall:
    arguments = _without_none({"path": path})
    return _make_tool_call(
        tool_name="fs.read",
        risk_tier="read",
        arguments=arguments,
        task_id=task_id,
        iteration_id=iteration_id,
        idempotency_key=idempotency_key,
    )


def make_fs_write_call(
    path: str,
    content: str,
    *,
    create_parents: bool = False,
    task_id: str | None = None,
    iteration_id: int | None = None,
    idempotency_key: str | None = None,
) -> ToolCall:
    arguments = _without_none(
        {
            "path": path,
            "content": content,
            "create_parents": create_parents,
        }
    )
    return _make_tool_call(
        tool_name="fs.write",
        risk_tier="write",
        arguments=arguments,
        task_id=task_id,
        iteration_id=iteration_id,
        idempotency_key=idempotency_key,
    )


def make_process_tool_call(
    tool_name: str,
    risk_tier: ToolRiskTier,
    *,
    argv: list[str] | None = None,
    command: str | None = None,
    timeout_sec: int | None = None,
    task_id: str | None = None,
    iteration_id: int | None = None,
    idempotency_key: str | None = None,
) -> ToolCall:
    if (argv is None) == (command is None):
        raise ValueError("Process tool call requires exactly one of argv or command")
    arguments = _without_none(
        {
            "argv": argv,
            "command": command,
            "timeout_sec": timeout_sec,
        }
    )
    return _make_tool_call(
        tool_name=tool_name,
        risk_tier=risk_tier,
        arguments=arguments,
        task_id=task_id,
        iteration_id=iteration_id,
        idempotency_key=idempotency_key,
    )


def make_memory_tool_call(
    tool: str,
    *,
    risk_tier: ToolRiskTier = "read",
    args: dict[str, Any] | None = None,
    task_id: str | None = None,
    iteration_id: int | None = None,
    idempotency_key: str | None = None,
) -> ToolCall:
    if not tool.strip():
        raise ValueError("Memory tool cannot be empty")
    return _make_tool_call(
        tool_name=f"memory.{tool.strip()}",
        risk_tier=risk_tier,
        arguments=args or {},
        task_id=task_id,
        iteration_id=iteration_id,
        idempotency_key=idempotency_key,
    )


def make_verification_tool_call(
    *,
    name: str,
    arguments: dict[str, object],
    task_id: str,
    iteration_id: int,
    idempotency_key: str | None = None,
) -> ToolCall:
    return _make_tool_call(
        tool_name="verification.run",
        risk_tier="read",
        action_type="verification_command",
        arguments={"name": name, **arguments},
        task_id=task_id,
        iteration_id=iteration_id,
        idempotency_key=idempotency_key,
    )


def make_tool_call(
    *,
    tool_name: str,
    risk_tier: ToolRiskTier,
    arguments: dict[str, object],
    task_id: str | None,
    iteration_id: int | None,
    idempotency_key: str | None,
    action_type: str | None = None,
) -> ToolCall:
    key = idempotency_key or make_tool_idempotency_key(
        tool_name,
        arguments,
        task_id=task_id,
        iteration_id=iteration_id,
    )
    return ToolCall(
        spec=ToolSpec(tool_name, risk_tier, action_type=action_type),
        idempotency_key=key,
        arguments=arguments,
        task_id=task_id,
        iteration_id=iteration_id,
    )


def _make_tool_call(
    *,
    tool_name: str,
    risk_tier: ToolRiskTier,
    arguments: dict[str, object],
    task_id: str | None,
    iteration_id: int | None,
    idempotency_key: str | None,
    action_type: str | None = None,
) -> ToolCall:
    return make_tool_call(
        tool_name=tool_name,
        risk_tier=risk_tier,
        arguments=arguments,
        task_id=task_id,
        iteration_id=iteration_id,
        idempotency_key=idempotency_key,
        action_type=action_type,
    )


def _without_none(values: dict[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}
