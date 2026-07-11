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
ActionType = Literal[
    "read",
    "write",
    "shell",
    "git",
    "network",
    "verification",
    "dangerous",
    "secret_sensitive",
]
ActionDecisionAction = Literal["allow", "ask", "deny"]

TOOL_RISK_TIERS: tuple[str, ...] = ("read", "write", "network", "destructive")
TOOL_RESULT_STATUSES: tuple[str, ...] = (
    "succeeded",
    "failed",
    "skipped",
    "policy_denied",
    "needs_approval",
)
ACTION_TYPES: tuple[str, ...] = (
    "read",
    "write",
    "shell",
    "git",
    "network",
    "verification",
    "dangerous",
    "secret_sensitive",
)
ACTION_DECISION_ACTIONS: tuple[str, ...] = ("allow", "ask", "deny")


@dataclass(frozen=True)
class ActionRisk:
    action_type: ActionType
    risk_tier: ToolRiskTier
    requires_approval: bool = False
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_action_type(self.action_type)
        _validate_risk_tier(self.risk_tier)
        for reason in self.reasons:
            _validate_non_empty(reason, "Action risk reason")

    def to_payload(self) -> dict[str, object]:
        return {
            "action_type": self.action_type,
            "risk_tier": self.risk_tier,
            "requires_approval": self.requires_approval,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ActionProvenance:
    source: str
    idempotency_key: str
    task_id: str | None = None
    iteration_id: int | None = None
    actor: str = "tool_broker"
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.source, "Action source")
        _validate_non_empty(self.idempotency_key, "Action idempotency key")
        _validate_non_empty(self.actor, "Action actor")
        if self.correlation_id is not None:
            _validate_non_empty(self.correlation_id, "Action correlation id")

    def to_payload(self) -> dict[str, object]:
        return {
            "source": self.source,
            "actor": self.actor,
            "task_id": self.task_id,
            "iteration_id": self.iteration_id,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class ActionDecision:
    action: ActionDecisionAction
    reason: str
    approval_id: int | None = None
    policy_name: str | None = None

    def __post_init__(self) -> None:
        _validate_action_decision(self.action)
        _validate_non_empty(self.reason, "Action decision reason")
        if self.approval_id is not None and self.approval_id < 1:
            raise ValueError("Action decision approval id must be positive")
        if self.policy_name is not None:
            _validate_non_empty(self.policy_name, "Action decision policy name")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "action": self.action,
            "reason": self.reason,
        }
        if self.approval_id is not None:
            payload["approval_id"] = self.approval_id
        if self.policy_name is not None:
            payload["policy_name"] = self.policy_name
        return payload


@dataclass(frozen=True)
class ActionRequest:
    name: str
    idempotency_key: str
    risk: ActionRisk
    provenance: ActionProvenance
    arguments: dict[str, object] = field(default_factory=dict)
    command_string: str | None = None
    record_type: str | None = None
    schema_version: str = "action-envelope/v1"

    def __post_init__(self) -> None:
        _validate_non_empty(self.name, "Action request name")
        _validate_non_empty(self.idempotency_key, "Action request idempotency key")
        _validate_json_object(self.arguments, "Action request arguments")
        if self.command_string is not None:
            _validate_non_empty(self.command_string, "Action request command")
        if self.record_type is not None:
            _validate_non_empty(self.record_type, "Action request record type")
        _validate_non_empty(self.schema_version, "Action request schema version")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "record_type": self.record_type or self.name,
            "idempotency_key": self.idempotency_key,
            "risk": self.risk.to_payload(),
            "provenance": self.provenance.to_payload(),
            "arguments": self.arguments,
        }
        if self.command_string is not None:
            payload["command_string"] = self.command_string
        return payload


@dataclass(frozen=True)
class ActionResult:
    status: ToolResultStatus
    summary: str
    output: dict[str, object] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        _validate_result_status(self.status)
        _validate_non_empty(self.summary, "Action result summary")
        _validate_json_object(self.output, "Action result output")
        if self.error is not None:
            _validate_non_empty(self.error, "Action result error")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "summary": self.summary,
            "output": self.output,
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload


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

    @property
    def classified_action_type(self) -> ActionType:
        return classify_tool_action(self)

    def action_payload(self) -> dict[str, object]:
        return {
            "tool_name": self.spec.name,
            "risk_tier": self.spec.risk_tier,
            "arguments": self.arguments,
        }

    def action_request(self, *, command_string: str | None = None) -> ActionRequest:
        classified = self.classified_action_type
        reasons: list[str] = []
        if self.spec.risk_tier != "read":
            reasons.append(f"Tool risk tier: {self.spec.risk_tier}")
        if classified in {"dangerous", "secret_sensitive"}:
            reasons.append(f"Classified action type: {classified}")

        return ActionRequest(
            name=self.spec.name,
            record_type=self.action_type,
            idempotency_key=self.idempotency_key,
            risk=ActionRisk(
                action_type=classified,
                risk_tier=self.spec.risk_tier,
                requires_approval=self.spec.risk_tier != "read",
                reasons=tuple(reasons),
            ),
            provenance=ActionProvenance(
                source=self.spec.name,
                task_id=self.task_id,
                iteration_id=self.iteration_id,
                idempotency_key=self.idempotency_key,
                correlation_id=self.idempotency_key,
            ),
            arguments=self.arguments,
            command_string=command_string,
        )


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

    def typed_action_result(self) -> ActionResult:
        summary = f"{self.call.spec.name} {self.status}"
        return ActionResult(
            status=self.status,
            summary=summary,
            output=self.output,
            error=self.error,
        )


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


def classify_tool_action(call: ToolCall) -> ActionType:
    command_text = _command_text(call)
    if _looks_secret_sensitive(call, command_text):
        return "secret_sensitive"
    if call.spec.risk_tier == "destructive":
        return "dangerous"
    if call.spec.action_type == "verification_command" or call.spec.name.startswith(
        "verification."
    ):
        return "verification"
    if command_text is not None:
        if _first_command_token(call, command_text) == "git":
            return "git"
        return "shell"
    if call.spec.risk_tier == "network":
        return "network"
    if call.spec.risk_tier == "write":
        return "write"
    return "read"


def _validate_non_empty(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} cannot be empty")


def _validate_risk_tier(risk_tier: str) -> None:
    if risk_tier not in TOOL_RISK_TIERS:
        raise ValueError(f"Unsupported tool risk tier: {risk_tier}")


def _validate_result_status(status: str) -> None:
    if status not in TOOL_RESULT_STATUSES:
        raise ValueError(f"Unsupported tool result status: {status}")


def _validate_action_type(action_type: str) -> None:
    if action_type not in ACTION_TYPES:
        raise ValueError(f"Unsupported action type: {action_type}")


def _validate_action_decision(action: str) -> None:
    if action not in ACTION_DECISION_ACTIONS:
        raise ValueError(f"Unsupported action decision: {action}")


def _validate_json_object(payload: dict[str, object], label: str) -> None:
    try:
        json.dumps(payload, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON-serializable") from exc


def _command_text(call: ToolCall) -> str | None:
    command = call.arguments.get("command")
    if isinstance(command, str) and command.strip():
        return command.strip()

    argv = call.arguments.get("argv")
    if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
        return " ".join(argv).strip() or None
    return None


def _first_command_token(call: ToolCall, command_text: str) -> str | None:
    argv = call.arguments.get("argv")
    if isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv):
        first = argv[0].strip().lower()
        return first or None
    return command_text.split(maxsplit=1)[0].strip().lower() or None


def _looks_secret_sensitive(call: ToolCall, command_text: str | None) -> bool:
    haystack = " ".join(
        item
        for item in (
            call.spec.name,
            command_text or "",
            str(call.arguments.get("path", "")),
        )
        if item
    ).lower()
    return any(
        marker in haystack
        for marker in (
            ".env",
            "auth.json",
            "id_rsa",
            "private_key",
            "api_key",
            "secret",
            "token=",
            "_token",
            "password",
        )
    )
