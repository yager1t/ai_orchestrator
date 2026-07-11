from __future__ import annotations

import subprocess
from collections.abc import Callable

from ai_orchestrator.policy.engine import PolicyDecision, PolicyEngine
from ai_orchestrator.storage.db import StateStore, StoredActionRecord
from ai_orchestrator.tools.types import ToolCall, ToolResult, ToolResultStatus

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
                payload=call.action_payload(),
                result=result.action_result(),
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
                        result=result.action_result(),
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
                            result=result.action_result(),
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
            payload=call.action_payload(),
        )
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
            result=result.action_result(),
        )
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
                payload=retry_payload,
                result=result.action_result(),
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
                result=result.action_result(),
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
            payload=retry_payload,
        )
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
            result=result.action_result(),
        )
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
            payload=call.action_payload(),
            result=recorded_result.action_result(),
        )
        if recorded_result.status == "policy_denied":
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
            self._record_call_event(
                call,
                "command_finished",
                action_id=action.action_id,
                status=recorded_result.status,
                reason=recorded_result.error,
                idempotency_suffix="audit:finished",
            )
        return recorded_result

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
