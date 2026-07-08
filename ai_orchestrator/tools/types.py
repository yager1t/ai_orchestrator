from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

ToolRiskTier = Literal["read", "write", "network", "destructive"]
ToolResultStatus = Literal[
    "succeeded",
    "failed",
    "skipped",
    "policy_denied",
    "needs_approval",
]

TOOL_RISK_TIERS: tuple[str, ...] = ("read", "write", "network", "destructive")
TOOL_RESULT_STATUSES: tuple[str, ...] = (
    "succeeded",
    "failed",
    "skipped",
    "policy_denied",
    "needs_approval",
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk_tier: ToolRiskTier
    description: str = ""
    action_type: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.name, "Tool name")
        _validate_risk_tier(self.risk_tier)
        if self.action_type is not None:
            _validate_non_empty(self.action_type, "Tool action type")

    @property
    def resolved_action_type(self) -> str:
        return self.action_type or self.name


@dataclass(frozen=True)
class ToolCall:
    spec: ToolSpec
    idempotency_key: str
    arguments: dict[str, object] = field(default_factory=dict)
    task_id: str | None = None
    iteration_id: int | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.idempotency_key, "Tool idempotency key")
        _validate_json_object(self.arguments, "Tool arguments")

    @property
    def action_type(self) -> str:
        return self.spec.resolved_action_type

    def action_payload(self) -> dict[str, object]:
        return {
            "tool_name": self.spec.name,
            "risk_tier": self.spec.risk_tier,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    status: ToolResultStatus
    output: dict[str, object] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        _validate_result_status(self.status)
        _validate_json_object(self.output, "Tool result output")
        if self.error is not None:
            _validate_non_empty(self.error, "Tool result error")

    def action_result(self) -> dict[str, object]:
        result: dict[str, object] = {
            "tool_name": self.call.spec.name,
            "risk_tier": self.call.spec.risk_tier,
            "status": self.status,
            "output": self.output,
        }
        if self.error is not None:
            result["error"] = self.error
        return result


def make_tool_idempotency_key(
    tool_name: str,
    arguments: dict[str, object] | None = None,
    *,
    task_id: str | None = None,
    iteration_id: int | None = None,
) -> str:
    _validate_non_empty(tool_name, "Tool name")
    payload: dict[str, object] = {
        "tool_name": tool_name.strip(),
        "task_id": task_id,
        "iteration_id": iteration_id,
        "arguments": arguments or {},
    }
    _validate_json_object(payload, "Tool idempotency payload")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"tool:{tool_name.strip()}:{digest}"


def _validate_non_empty(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} cannot be empty")


def _validate_risk_tier(risk_tier: str) -> None:
    if risk_tier not in TOOL_RISK_TIERS:
        raise ValueError(f"Unsupported tool risk tier: {risk_tier}")


def _validate_result_status(status: str) -> None:
    if status not in TOOL_RESULT_STATUSES:
        raise ValueError(f"Unsupported tool result status: {status}")


def _validate_json_object(payload: dict[str, object], label: str) -> None:
    try:
        json.dumps(payload, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON-serializable") from exc
