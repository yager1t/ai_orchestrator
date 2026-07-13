from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import cast

from ai_orchestrator.policy.engine import PolicyDecision, PolicyEngine
from ai_orchestrator.storage.db import StateStore, StoredActionRecord
from ai_orchestrator.storage.redaction import redact_secrets
from ai_orchestrator.tools.types import (
    TOOL_RESULT_STATUSES,
    ActionDecision,
    ActionDecisionAction,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)

ToolExecutorOutput = dict[str, object] | ToolResult
ToolExecutor = Callable[[ToolCall], ToolExecutorOutput]


class ToolBroker:
    """Policy and audit boundary for typed tool calls."""

    def __init__(
        self,
        state_store: StateStore,
        policy_engine: PolicyEngine,
    ) -> None:
        self.state_store = state_store
        self.policy_engine = policy_engine

    def run(
        self,
        call: ToolCall,
        executor: ToolExecutor,
    ) -> ToolResult:
        if call.task_id is None:
            raise ValueError("ToolCall task_id is required for broker audit")

        policy_decision, command_string = self._evaluate_policy(call)
        policy_decision = self._effective_policy_decision(call, policy_decision)
        blocked_status = self._blocked_status(call, policy_decision)
        if blocked_status is not None:
            reason = self._blocked_reason(call, policy_decision)
            result = ToolResult(
                call=call,
                status=blocked_status,
                error=reason,
            )
            action = self.state_store.record_action(
                task_id=call.task_id,
                iteration_id=call.iteration_id,
                idempotency_key=call.idempotency_key,
                action_type=call.action_type,
                status=result.status,
                command_string=command_string,
                policy_action=policy_decision.action,
                policy_reason=reason,
                payload=self._action_payload(call, command_string=command_string),
                result=self._action_result_payload(
                    result,
                    policy_decision=policy_decision,
                ),
            )
            self._record_call_event(
                call,
                "command_denied" if blocked_status == "policy_denied" else "command_requested",
                action_id=action.action_id,
                status=blocked_status,
                reason=reason,
                idempotency_suffix="blocked",
            )
            if blocked_status == "needs_approval":
                approval_id = self._approval_id_from_action(action)
                if approval_id is not None:
                    result = ToolResult(
                        call=call,
                        status=blocked_status,
                        output={
                            "action_id": action.action_id,
                            "approval_id": approval_id,
                        },
                        error=reason,
                    )
                    self.state_store.complete_action_record(
                        action.action_id,
                        result.status,
                        result=self._action_result_payload(
                            result,
                            policy_decision=policy_decision,
                            approval_id=approval_id,
                        ),
                    )
                else:
                    approval_id = self._create_approval_request(
                        call=call,
                        command_string=command_string,
                        reason=reason,
                    )
                    if approval_id is not None:
                        result = ToolResult(
                            call=call,
                            status=blocked_status,
                            output={
                                "action_id": action.action_id,
                                "approval_id": approval_id,
                            },
                            error=reason,
                        )
                        self.state_store.complete_action_record(
                            action.action_id,
                            result.status,
                            result=self._action_result_payload(
                                result,
                                policy_decision=policy_decision,
                                approval_id=approval_id,
                            ),
                        )
            return result

        action = self.state_store.record_action(
            task_id=call.task_id,
            iteration_id=call.iteration_id,
            idempotency_key=call.idempotency_key,
            action_type=call.action_type,
            status="started",
            command_string=command_string,
            policy_action=policy_decision.action,
            policy_reason=policy_decision.reason,
            payload=self._action_payload(call, command_string=command_string),
        )
        replayed_result = self._completed_result_from_action(call, action)
        if replayed_result is not None:
            self._record_call_event(
                call,
                "command_replayed",
                action_id=action.action_id,
                status=replayed_result.status,
                reason="Skipped executor for completed action record",
                idempotency_suffix="replayed",
            )
            return replayed_result
        self._record_call_event(
            call,
            "command_approved",
            action_id=action.action_id,
            status="approved",
            reason=policy_decision.reason,
            idempotency_suffix="approved",
        )
        self._record_call_event(
            call,
            "command_started",
            action_id=action.action_id,
            status="started",
            reason=policy_decision.reason,
            idempotency_suffix="started",
        )
        try:
            result = self._result_from_executor_output(call, executor(call))
        except Exception as exc:
            result = ToolResult(call=call, status="failed", error=str(exc))

        self.state_store.complete_action_record(
            action.action_id,
            result.status,
            result=self._action_result_payload(
                result,
                policy_decision=policy_decision,
            ),
        )
        self._record_sandbox_decision_event(call, action.action_id, result)
        self._record_call_event(
            call,
            "command_finished",
            action_id=action.action_id,
            status=result.status,
            reason=result.error,
            idempotency_suffix="finished",
        )
        return result

    def run_approved(
        self,
        call: ToolCall,
        executor: ToolExecutor,
        *,
        approval_id: int,
    ) -> ToolResult:
        if call.task_id is None:
            raise ValueError("ToolCall task_id is required for broker audit")
        if approval_id < 1:
            raise ValueError("Approval id must be positive")

        policy_decision, command_string = self._evaluate_policy(call)
        policy_decision = self._effective_policy_decision(call, policy_decision)
        retry_idempotency_key = f"{call.idempotency_key}:approval:{approval_id}"
        retry_payload = {
            **call.action_payload(),
            "approval_id": approval_id,
            "approved_retry": True,
        }
        if policy_decision.action == "deny":
            result = self._with_approval_metadata(
                ToolResult(
                    call=call,
                    status="policy_denied",
                    error=policy_decision.reason,
                ),
                action_id=None,
                approval_id=approval_id,
            )
            action = self.state_store.record_action(
                task_id=call.task_id,
                iteration_id=call.iteration_id,
                idempotency_key=retry_idempotency_key,
                action_type=call.action_type,
                status=result.status,
                command_string=command_string,
                policy_action=policy_decision.action,
                policy_reason=policy_decision.reason,
                payload=self._action_payload(
                    call,
                    command_string=command_string,
                    extra=retry_payload,
                ),
                result=self._action_result_payload(
                    result,
                    policy_decision=policy_decision,
                    approval_id=approval_id,
                ),
            )
            self._record_call_event(
                call,
                "command_denied",
                action_id=action.action_id,
                status=result.status,
                reason=policy_decision.reason,
                idempotency_suffix=f"approval:{approval_id}:denied",
            )
            result = self._with_approval_metadata(
                result,
                action_id=action.action_id,
                approval_id=approval_id,
            )
            self.state_store.complete_action_record(
                action.action_id,
                result.status,
                result=self._action_result_payload(
                    result,
                    policy_decision=policy_decision,
                    approval_id=approval_id,
                ),
            )
            return result

        action = self.state_store.record_action(
            task_id=call.task_id,
            iteration_id=call.iteration_id,
            idempotency_key=retry_idempotency_key,
            action_type=call.action_type,
            status="started",
            command_string=command_string,
            policy_action=policy_decision.action,
            policy_reason=self._approved_reason(policy_decision, approval_id),
            payload=self._action_payload(
                call,
                command_string=command_string,
                extra=retry_payload,
            ),
        )
        replayed_result = self._completed_result_from_action(call, action)
        if replayed_result is not None:
            self._record_call_event(
                call,
                "command_replayed",
                action_id=action.action_id,
                status=replayed_result.status,
                reason="Skipped executor for completed approved action record",
                idempotency_suffix=f"approval:{approval_id}:replayed",
            )
            return replayed_result
        self._record_call_event(
            call,
            "command_approved",
            action_id=action.action_id,
            status="approved",
            reason=self._approved_reason(policy_decision, approval_id),
            idempotency_suffix=f"approval:{approval_id}:approved",
        )
        self._record_call_event(
            call,
            "command_started",
            action_id=action.action_id,
            status="started",
            reason=self._approved_reason(policy_decision, approval_id),
            idempotency_suffix=f"approval:{approval_id}:started",
        )
        try:
            result = self._result_from_executor_output(call, executor(call))
        except Exception as exc:
            result = ToolResult(call=call, status="failed", error=str(exc))
        result = self._with_approval_metadata(
            result,
            action_id=action.action_id,
            approval_id=approval_id,
        )
        self.state_store.complete_action_record(
            action.action_id,
            result.status,
            result=self._action_result_payload(
                result,
                policy_decision=policy_decision,
                approval_id=approval_id,
            ),
        )
        self._record_sandbox_decision_event(call, action.action_id, result)
        self._record_call_event(
            call,
            "command_finished",
            action_id=action.action_id,
            status=result.status,
            reason=result.error,
            idempotency_suffix=f"approval:{approval_id}:finished",
        )
        return result

    def record_result(
        self,
        call: ToolCall,
        result: ToolResult,
    ) -> ToolResult:
        if call.task_id is None:
            raise ValueError("ToolCall task_id is required for broker audit")

        policy_decision, command_string = self._evaluate_policy(call)
        policy_decision = self._effective_policy_decision(call, policy_decision)
        recorded_result = self._result_allowed_for_audit(call, result, policy_decision)
        action = self.state_store.record_action(
            task_id=call.task_id,
            iteration_id=call.iteration_id,
            idempotency_key=call.idempotency_key,
            action_type=call.action_type,
            status=recorded_result.status,
            command_string=command_string,
            policy_action=policy_decision.action,
            policy_reason=(
                policy_decision.reason
                if policy_decision.action in {"ask", "deny"}
                else None
            ),
            payload=self._action_payload(call, command_string=command_string),
            result=self._action_result_payload(
                recorded_result,
                policy_decision=policy_decision,
            ),
        )
        if recorded_result.status == "policy_denied":
            self._record_sandbox_decision_event(call, action.action_id, recorded_result)
            self._record_call_event(
                call,
                "command_denied",
                action_id=action.action_id,
                status=recorded_result.status,
                reason=policy_decision.reason,
                idempotency_suffix="audit:denied",
            )
        elif recorded_result.status == "needs_approval":
            self._record_call_event(
                call,
                "command_requested",
                action_id=action.action_id,
                status=recorded_result.status,
                reason=recorded_result.error or policy_decision.reason,
                idempotency_suffix="audit:approval",
            )
        else:
            self._record_sandbox_decision_event(call, action.action_id, recorded_result)
            self._record_call_event(
                call,
                "command_finished",
                action_id=action.action_id,
                status=recorded_result.status,
                reason=recorded_result.error,
                idempotency_suffix="audit:finished",
            )
        return recorded_result

    def _record_sandbox_decision_event(
        self,
        call: ToolCall,
        action_id: int,
        result: ToolResult,
    ) -> None:
        if call.task_id is None:
            return
        sandbox_decision = self._sandbox_decision_payload(result.output)
        if sandbox_decision is None or sandbox_decision.get("action") != "deny":
            return

        payload: dict[str, object] = {
            "action_id": action_id,
            "tool_name": call.spec.name,
            "risk_tier": call.spec.risk_tier,
            "status": result.status,
            "decision": sandbox_decision,
        }
        sandbox_profile = self._sandbox_profile_payload(result.output)
        if sandbox_profile is not None:
            payload["sandbox_profile"] = sandbox_profile
        self.state_store.append_task_event(
            call.task_id,
            "sandbox.decision",
            payload,
            actor="tool_broker",
            summary=f"Sandbox denied {call.spec.name}",
            idempotency_key=f"sandbox-decision:{action_id}",
        )

    def _sandbox_decision_payload(
        self,
        output: dict[str, object],
    ) -> dict[str, object] | None:
        decision = output.get("sandbox_decision")
        if isinstance(decision, dict) and all(isinstance(key, str) for key in decision):
            return cast(dict[str, object], decision)
        nested = output.get("tool_output")
        if isinstance(nested, dict):
            nested_decision = nested.get("sandbox_decision")
            if isinstance(nested_decision, dict) and all(
                isinstance(key, str) for key in nested_decision
            ):
                return cast(dict[str, object], nested_decision)
        return None

    def _sandbox_profile_payload(
        self,
        output: dict[str, object],
    ) -> dict[str, object] | None:
        profile = output.get("sandbox_profile")
        if isinstance(profile, dict) and all(isinstance(key, str) for key in profile):
            return cast(dict[str, object], profile)
        nested = output.get("tool_output")
        if isinstance(nested, dict):
            nested_profile = nested.get("sandbox_profile")
            if isinstance(nested_profile, dict) and all(
                isinstance(key, str) for key in nested_profile
            ):
                return cast(dict[str, object], nested_profile)
        return None

    def _evaluate_policy(self, call: ToolCall) -> tuple[PolicyDecision, str]:
        argv = call.arguments.get("argv")
        if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
            return (
                self.policy_engine.evaluate_argv(argv),
                subprocess.list2cmdline(argv),
            )

        command = call.arguments.get("command")
        if isinstance(command, str):
            return self.policy_engine.evaluate_command(command), command

        subject = f"tool {call.spec.risk_tier} {call.spec.name}"
        return self.policy_engine.evaluate_command(subject), subject

    def _blocked_status(
        self,
        call: ToolCall,
        policy_decision: PolicyDecision,
    ) -> ToolResultStatus | None:
        if policy_decision.action == "deny":
            return "policy_denied"
        if policy_decision.action == "ask":
            return "needs_approval"
        if call.spec.risk_tier != "read":
            return "needs_approval"
        return None

    def _effective_policy_decision(
        self,
        call: ToolCall,
        policy_decision: PolicyDecision,
    ) -> PolicyDecision:
        if policy_decision.action == "deny":
            return policy_decision
        action_type = call.classified_action_type
        if action_type in {"dangerous", "secret_sensitive"}:
            return PolicyDecision(
                "deny",
                f"Denied by action classification: {action_type}",
            )
        return policy_decision

    def _blocked_reason(
        self,
        call: ToolCall,
        policy_decision: PolicyDecision,
    ) -> str:
        if policy_decision.action in {"ask", "deny"}:
            return policy_decision.reason
        return f"Tool risk tier requires approval: {call.spec.risk_tier}"

    def _create_approval_request(
        self,
        call: ToolCall,
        command_string: str,
        reason: str,
    ) -> int | None:
        if call.task_id is None:
            return None

        approval = self.state_store.add_approval_request(
            task_id=call.task_id,
            iteration_id=call.iteration_id,
            source="tool_broker",
            command_string=command_string,
            reason=reason,
        )
        return approval.approval_id

    def _approval_id_from_action(self, action: StoredActionRecord) -> int | None:
        output = action.result.get("output")
        if not isinstance(output, dict):
            return None
        approval_id = output.get("approval_id")
        if isinstance(approval_id, int):
            return approval_id
        return None

    def _approved_reason(
        self,
        policy_decision: PolicyDecision,
        approval_id: int,
    ) -> str:
        return f"{policy_decision.reason}; approved by approval_request {approval_id}"

    def _result_from_executor_output(
        self,
        call: ToolCall,
        output: ToolExecutorOutput,
    ) -> ToolResult:
        if isinstance(output, ToolResult):
            return ToolResult(
                call=call,
                status=output.status,
                output=output.output,
                error=output.error,
            )
        return ToolResult(call=call, status="succeeded", output=output)

    def _with_approval_metadata(
        self,
        result: ToolResult,
        *,
        action_id: int | None,
        approval_id: int,
    ) -> ToolResult:
        metadata: dict[str, object] = {"approval_id": approval_id}
        if action_id is not None:
            metadata["action_id"] = action_id
        return ToolResult(
            call=result.call,
            status=result.status,
            output={
                **metadata,
                "tool_output": result.output,
            },
            error=result.error,
        )

    def _result_allowed_for_audit(
        self,
        call: ToolCall,
        result: ToolResult,
        policy_decision: PolicyDecision,
    ) -> ToolResult:
        if policy_decision.action == "deny":
            return ToolResult(
                call=call,
                status="policy_denied",
                error=policy_decision.reason,
            )
        if call.spec.risk_tier != "read" and result.status == "succeeded":
            return ToolResult(
                call=call,
                status="needs_approval",
                error=policy_decision.reason,
            )
        return result

    def _completed_result_from_action(
        self,
        call: ToolCall,
        action: StoredActionRecord,
    ) -> ToolResult | None:
        if action.status == "started":
            return None
        status = action.result.get("status")
        if not isinstance(status, str):
            status = action.status
        if status not in TOOL_RESULT_STATUSES:
            return None

        output = action.result.get("output")
        if isinstance(output, dict) and all(isinstance(key, str) for key in output):
            result_output = cast(dict[str, object], output)
        else:
            result_output = action.result

        error = action.result.get("error")
        return ToolResult(
            call=call,
            status=cast(ToolResultStatus, status),
            output=result_output,
            error=error if isinstance(error, str) else None,
        )

    def _action_payload(
        self,
        call: ToolCall,
        *,
        command_string: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = call.action_payload()
        if extra is not None:
            payload.update(extra)
        payload["action_request"] = call.action_request(
            command_string=command_string,
        ).to_payload()
        return payload

    def _action_result_payload(
        self,
        result: ToolResult,
        *,
        policy_decision: PolicyDecision,
        approval_id: int | None = None,
    ) -> dict[str, object]:
        payload = result.action_result()
        payload["action_decision"] = ActionDecision(
            action=self._typed_policy_action(policy_decision),
            reason=policy_decision.reason or f"Policy decision: {policy_decision.action}",
            approval_id=approval_id,
            policy_name="PolicyEngine",
        ).to_payload()
        action_result = result.typed_action_result().to_payload()
        output_preview = self._action_output_preview(result.output)
        if output_preview:
            action_result["output_preview"] = output_preview
        payload["action_result"] = action_result
        return payload

    def _action_output_preview(self, output: dict[str, object]) -> dict[str, object]:
        preview: dict[str, object] = {}
        stdout = self._first_string_value(output, "stdout")
        stderr = self._first_string_value(output, "stderr")
        exit_code = self._first_int_value(output, "exit_code")
        if stdout is not None:
            preview["stdout"] = self._preview_text(stdout)
        if stderr is not None:
            preview["stderr"] = self._preview_text(stderr)
        if exit_code is not None:
            preview["exit_code"] = exit_code
        return preview

    def _first_string_value(
        self,
        output: dict[str, object],
        key: str,
    ) -> str | None:
        value = output.get(key)
        if isinstance(value, str):
            return value
        nested = output.get("tool_output")
        if isinstance(nested, dict):
            nested_value = nested.get(key)
            if isinstance(nested_value, str):
                return nested_value
        return None

    def _first_int_value(
        self,
        output: dict[str, object],
        key: str,
    ) -> int | None:
        value = output.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        nested = output.get("tool_output")
        if isinstance(nested, dict):
            nested_value = nested.get(key)
            if isinstance(nested_value, int) and not isinstance(nested_value, bool):
                return nested_value
        return None

    def _preview_text(self, value: str, limit: int = 400) -> str:
        redacted = redact_secrets(value) or ""
        if len(redacted) <= limit:
            return redacted
        return f"{redacted[:limit]}..."

    def _typed_policy_action(
        self,
        policy_decision: PolicyDecision,
    ) -> ActionDecisionAction:
        if policy_decision.action not in {"allow", "ask", "deny"}:
            raise ValueError(f"Unsupported policy action: {policy_decision.action}")
        return cast(ActionDecisionAction, policy_decision.action)

    def _record_call_event(
        self,
        call: ToolCall,
        event_type: str,
        *,
        action_id: int,
        status: str,
        reason: str | None,
        idempotency_suffix: str,
    ) -> None:
        if call.task_id is None:
            return
        self.state_store.append_task_event(
            call.task_id,
            event_type,
            {
                "action_id": action_id,
                "action_type": call.action_type,
                "tool": call.spec.name,
                "risk_tier": call.spec.risk_tier,
                "status": status,
                "reason": reason,
            },
            iteration_id=call.iteration_id,
            correlation_id=call.idempotency_key,
            idempotency_key=f"{call.idempotency_key}:{idempotency_suffix}",
            actor="policy",
            summary=f"{event_type}: {call.spec.name} ({status})",
        )
