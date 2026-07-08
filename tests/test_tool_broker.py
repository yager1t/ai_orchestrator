import pytest

from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.tools import (
    ToolBroker,
    ToolCall,
    ToolResult,
    ToolSpec,
    make_tool_idempotency_key,
)


def test_tool_broker_runs_read_tool_and_records_action(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = ToolCall(
        spec=ToolSpec("fs.read", "read"),
        idempotency_key=make_tool_idempotency_key(
            "fs.read",
            {"path": "README.md"},
            task_id=task.task_id,
        ),
        arguments={"path": "README.md"},
        task_id=task.task_id,
    )

    result = broker.run(call, lambda _call: {"content": "hello"})
    actions = store.list_action_records(task.task_id)

    assert result.status == "succeeded"
    assert result.output == {"content": "hello"}
    assert len(actions) == 1
    assert actions[0].status == "succeeded"
    assert actions[0].action_type == "fs.read"
    assert actions[0].policy_action == "allow"
    assert actions[0].payload["risk_tier"] == "read"
    assert actions[0].result["status"] == "succeeded"


def test_tool_broker_denies_policy_blocked_call_without_executor(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    executed = False
    call = ToolCall(
        spec=ToolSpec("fs.read", "read"),
        idempotency_key="tool:fs.read:blocked",
        arguments={"command": "cat ~/.codex/auth.json"},
        task_id=task.task_id,
    )

    def executor(_call: ToolCall) -> dict[str, object]:
        nonlocal executed
        executed = True
        return {"content": "secret"}

    result = broker.run(call, executor)
    actions = store.list_action_records(task.task_id)
    approvals = store.list_approval_requests(task.task_id)

    assert not executed
    assert result.status == "policy_denied"
    assert len(actions) == 1
    assert actions[0].status == "policy_denied"
    assert actions[0].policy_action == "deny"
    assert actions[0].command_string == "cat ~/.codex/auth.json"
    assert approvals == []


def test_tool_broker_requires_approval_for_write_risk_without_executor(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="completed",
        prompt="prompt",
        raw_output="output",
        decision_status="continue",
        decision_reason="test",
    )
    broker = ToolBroker(store, PolicyEngine())
    executed = False
    call = ToolCall(
        spec=ToolSpec("fs.write", "write"),
        idempotency_key="tool:fs.write:approval",
        arguments={"path": "README.md", "content": "updated"},
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
    )

    def executor(_call: ToolCall) -> dict[str, object]:
        nonlocal executed
        executed = True
        return {"bytes": 7}

    result = broker.run(call, executor)
    repeated_result = broker.run(call, executor)
    actions = store.list_action_records(task.task_id)
    approvals = store.list_approval_requests(task.task_id)

    assert not executed
    assert result.status == "needs_approval"
    assert result.output["approval_id"] == approvals[0].approval_id
    assert repeated_result.status == "needs_approval"
    assert repeated_result.output["approval_id"] == approvals[0].approval_id
    assert result.error == "Tool risk tier requires approval: write"
    assert len(actions) == 1
    assert actions[0].status == "needs_approval"
    assert actions[0].policy_action == "allow"
    assert actions[0].policy_reason == "Tool risk tier requires approval: write"
    assert actions[0].payload["risk_tier"] == "write"
    assert actions[0].result["output"]["approval_id"] == approvals[0].approval_id
    assert len(approvals) == 1
    assert approvals[0].iteration_id == iteration.iteration_id
    assert approvals[0].source == "tool_broker"
    assert approvals[0].command_string == "tool write fs.write"
    assert approvals[0].reason == "Tool risk tier requires approval: write"


def test_tool_broker_runs_approved_write_risk_and_records_retry_action(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = ToolCall(
        spec=ToolSpec("fs.write", "write"),
        idempotency_key="tool:fs.write:approved",
        arguments={"path": "README.md", "content": "updated"},
        task_id=task.task_id,
    )

    requested = broker.run(call, lambda _call: {"bytes": 7})
    approval_id = requested.output["approval_id"]

    assert isinstance(approval_id, int)
    approved = broker.run_approved(
        call,
        lambda _call: ToolResult(
            call=call,
            status="succeeded",
            output={"bytes": 7},
        ),
        approval_id=approval_id,
    )
    actions = store.list_action_records(task.task_id)

    assert approved.status == "succeeded"
    assert approved.output["approval_id"] == approval_id
    assert approved.output["tool_output"] == {"bytes": 7}
    assert [action.status for action in actions] == ["needs_approval", "succeeded"]
    assert actions[1].idempotency_key == f"{call.idempotency_key}:approval:{approval_id}"
    assert actions[1].payload["approved_retry"] is True
    assert actions[1].payload["approval_id"] == approval_id
    assert actions[1].result["output"]["tool_output"] == {"bytes": 7}


def test_tool_broker_approved_retry_does_not_override_deny_rules(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    executed = False
    call = ToolCall(
        spec=ToolSpec("fs.write", "write"),
        idempotency_key="tool:fs.write:denied-approved",
        arguments={"command": "cat ~/.codex/auth.json"},
        task_id=task.task_id,
    )

    def executor(_call: ToolCall) -> dict[str, object]:
        nonlocal executed
        executed = True
        return {"bytes": 7}

    result = broker.run_approved(call, executor, approval_id=1)
    actions = store.list_action_records(task.task_id)

    assert not executed
    assert result.status == "policy_denied"
    assert result.output["approval_id"] == 1
    assert actions[0].status == "policy_denied"
    assert actions[0].policy_action == "deny"


def test_tool_broker_records_failed_executor_result(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = ToolCall(
        spec=ToolSpec("fs.read", "read"),
        idempotency_key="tool:fs.read:failure",
        arguments={"path": "missing.txt"},
        task_id=task.task_id,
    )

    def executor(_call: ToolCall) -> dict[str, object]:
        raise RuntimeError("file missing")

    result = broker.run(call, executor)
    actions = store.list_action_records(task.task_id)

    assert result.status == "failed"
    assert result.error == "file missing"
    assert actions[0].status == "failed"
    assert actions[0].result["error"] == "file missing"


def test_tool_broker_records_precomputed_result_without_executor(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = ToolCall(
        spec=ToolSpec("verification.run", "read", action_type="verification_command"),
        idempotency_key="tool:verification.run:precomputed",
        arguments={"command": "python -m pytest", "name": "unit"},
        task_id=task.task_id,
    )
    result = ToolResult(
        call=call,
        status="succeeded",
        output={"verification_id": 1, "status": "passed"},
    )

    recorded = broker.record_result(call, result)
    actions = store.list_action_records(task.task_id)

    assert recorded == result
    assert len(actions) == 1
    assert actions[0].action_type == "verification_command"
    assert actions[0].status == "succeeded"
    assert actions[0].command_string == "python -m pytest"
    assert actions[0].policy_action == "allow"
    assert actions[0].payload["tool_name"] == "verification.run"


def test_tool_broker_requires_task_id(tmp_path) -> None:
    broker = ToolBroker(StateStore(tmp_path / "state.db"), PolicyEngine())
    call = ToolCall(
        spec=ToolSpec("fs.read", "read"),
        idempotency_key="tool:fs.read:no-task",
    )

    with pytest.raises(ValueError, match="ToolCall task_id is required"):
        broker.run(call, lambda _call: {})
