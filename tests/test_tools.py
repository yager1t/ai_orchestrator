from pathlib import Path

import pytest

from ai_orchestrator.memory import CodebaseMemoryResult
from ai_orchestrator.process.runner import ProcessResult, RunOptions
from ai_orchestrator.tools import (
    ACTION_TYPES,
    TOOL_RISK_TIERS,
    ActionDecision,
    ActionRisk,
    ToolCall,
    ToolExecutorRegistry,
    ToolResult,
    ToolSpec,
    classify_tool_action,
    file_tool_executor,
    make_fs_write_call,
    make_memory_tool_call,
    make_process_tool_call,
    make_tool_call,
    make_tool_idempotency_key,
    make_verification_tool_call,
    memory_tool_executor,
    process_tool_executor,
)


def test_tool_spec_accepts_known_risk_tiers() -> None:
    specs = [ToolSpec(f"{tier}_tool", tier) for tier in TOOL_RISK_TIERS]

    assert [spec.risk_tier for spec in specs] == list(TOOL_RISK_TIERS)


def test_tool_call_exposes_action_record_payload() -> None:
    spec = ToolSpec(
        name="verification.run",
        risk_tier="read",
        action_type="verification_command",
    )
    call = ToolCall(
        spec=spec,
        idempotency_key="tool:verification.run:demo",
        arguments={"command": "python -m pytest"},
        task_id="task-1",
        iteration_id=2,
    )

    assert call.action_type == "verification_command"
    assert call.action_payload() == {
        "tool_name": "verification.run",
        "risk_tier": "read",
        "arguments": {"command": "python -m pytest"},
    }


def test_tool_call_builds_typed_action_request_payload() -> None:
    call = ToolCall(
        spec=ToolSpec("verification.run", "read", action_type="verification_command"),
        idempotency_key="tool:verification.run:demo",
        arguments={"command": "python -m pytest"},
        task_id="task-1",
        iteration_id=2,
    )

    request = call.action_request(command_string="python -m pytest").to_payload()

    assert request["schema_version"] == "action-envelope/v1"
    assert request["name"] == "verification.run"
    assert request["record_type"] == "verification_command"
    assert request["command_string"] == "python -m pytest"
    assert request["arguments"] == {"command": "python -m pytest"}
    assert request["risk"] == {
        "action_type": "verification",
        "risk_tier": "read",
        "requires_approval": False,
        "reasons": [],
    }
    assert request["provenance"] == {
        "source": "verification.run",
        "actor": "tool_broker",
        "task_id": "task-1",
        "iteration_id": 2,
        "idempotency_key": "tool:verification.run:demo",
        "correlation_id": "tool:verification.run:demo",
    }


def test_tool_action_classification_covers_v0_5_action_types() -> None:
    assert "secret_sensitive" in ACTION_TYPES
    assert classify_tool_action(ToolCall(ToolSpec("fs.read", "read"), "read-1")) == "read"
    assert classify_tool_action(ToolCall(ToolSpec("fs.write", "write"), "write-1")) == "write"
    assert (
        classify_tool_action(
            ToolCall(
                ToolSpec("process.run", "read"),
                "shell-1",
                arguments={"argv": ["python", "-m", "pytest"]},
            )
        )
        == "shell"
    )
    assert (
        classify_tool_action(
            ToolCall(
                ToolSpec("process.run", "write"),
                "git-1",
                arguments={"argv": ["git", "status", "--short"]},
            )
        )
        == "git"
    )
    assert (
        classify_tool_action(
            ToolCall(
                ToolSpec("memory.index_repository", "network"),
                "network-1",
            )
        )
        == "network"
    )
    assert (
        classify_tool_action(
            ToolCall(
                ToolSpec("process.run", "read"),
                "secret-1",
                arguments={"command": "cat ~/.codex/auth.json"},
            )
        )
        == "secret_sensitive"
    )
    assert (
        classify_tool_action(ToolCall(ToolSpec("fs.delete", "destructive"), "danger-1"))
        == "dangerous"
    )


def test_tool_result_exposes_action_result_payload() -> None:
    call = ToolCall(
        spec=ToolSpec("fs.read", "read"),
        idempotency_key="tool:fs.read:demo",
        arguments={"path": "README.md"},
    )
    result = ToolResult(
        call=call,
        status="succeeded",
        output={"bytes": 42},
    )

    assert result.action_result() == {
        "tool_name": "fs.read",
        "risk_tier": "read",
        "status": "succeeded",
        "output": {"bytes": 42},
    }
    assert result.typed_action_result().to_payload() == {
        "status": "succeeded",
        "summary": "fs.read succeeded",
        "output": {"bytes": 42},
    }


def test_action_dataclasses_validate_and_serialize() -> None:
    risk = ActionRisk(
        action_type="write",
        risk_tier="write",
        requires_approval=True,
        reasons=("Tool risk tier: write",),
    )
    decision = ActionDecision(
        action="ask",
        reason="Tool risk tier requires approval: write",
        approval_id=7,
        policy_name="PolicyEngine",
    )

    assert risk.to_payload() == {
        "action_type": "write",
        "risk_tier": "write",
        "requires_approval": True,
        "reasons": ["Tool risk tier: write"],
    }
    assert decision.to_payload() == {
        "action": "ask",
        "reason": "Tool risk tier requires approval: write",
        "approval_id": 7,
        "policy_name": "PolicyEngine",
    }


def test_make_tool_idempotency_key_is_stable_for_ordered_payloads() -> None:
    first = make_tool_idempotency_key(
        "fs.write",
        {"path": "a.txt", "content": "hello"},
        task_id="task-1",
        iteration_id=1,
    )
    second = make_tool_idempotency_key(
        "fs.write",
        {"content": "hello", "path": "a.txt"},
        task_id="task-1",
        iteration_id=1,
    )

    assert first == second
    assert first.startswith("tool:fs.write:")


def test_tool_call_factories_build_stable_typed_calls() -> None:
    fs_call = make_fs_write_call(
        "README.md",
        "hello",
        create_parents=True,
        task_id="task-1",
        iteration_id=2,
    )
    same_fs_call = make_fs_write_call(
        "README.md",
        "hello",
        create_parents=True,
        task_id="task-1",
        iteration_id=2,
    )
    process_call = make_process_tool_call(
        "process.write",
        "write",
        argv=["python", "-m", "pytest"],
        timeout_sec=12,
        task_id="task-1",
    )
    memory_call = make_memory_tool_call(
        "index_repository",
        risk_tier="network",
        args={"repo_path": "."},
        task_id="task-1",
    )
    verification_call = make_verification_tool_call(
        name="unit",
        arguments={"command": "python -m pytest", "verification_id": 1},
        task_id="task-1",
        iteration_id=2,
        idempotency_key="verification-key",
    )

    assert fs_call.spec.name == "fs.write"
    assert fs_call.spec.risk_tier == "write"
    assert fs_call.arguments == {
        "path": "README.md",
        "content": "hello",
        "create_parents": True,
    }
    assert fs_call.idempotency_key == same_fs_call.idempotency_key
    assert process_call.arguments == {
        "argv": ["python", "-m", "pytest"],
        "timeout_sec": 12,
    }
    assert memory_call.spec.name == "memory.index_repository"
    assert memory_call.spec.risk_tier == "network"
    assert memory_call.arguments == {"repo_path": "."}
    assert verification_call.action_type == "verification_command"
    assert verification_call.idempotency_key == "verification-key"
    assert verification_call.arguments == {
        "name": "unit",
        "command": "python -m pytest",
        "verification_id": 1,
    }


def test_generic_tool_call_factory_preserves_action_type_for_restored_calls() -> None:
    call = make_tool_call(
        tool_name="fs.write",
        risk_tier="write",
        action_type="custom_action",
        arguments={"path": "result.txt", "content": "ok"},
        task_id="task-1",
        iteration_id=3,
        idempotency_key="tool:fs.write:restored",
    )

    assert call.spec.name == "fs.write"
    assert call.action_type == "custom_action"
    assert call.arguments == {"path": "result.txt", "content": "ok"}
    assert call.task_id == "task-1"
    assert call.iteration_id == 3
    assert call.idempotency_key == "tool:fs.write:restored"


def test_tool_executor_registry_routes_exact_and_prefix_matches() -> None:
    exact_call = ToolCall(ToolSpec("fs.write", "write"), "tool:fs.write:1")
    prefix_call = ToolCall(ToolSpec("process.write", "write"), "tool:process.write:1")
    registry = ToolExecutorRegistry()
    registry.register("fs.write", lambda call: {"tool": call.spec.name})
    registry.register_prefix("process.", lambda call: {"prefix": call.spec.name})

    exact = registry.run(exact_call)
    prefix = registry.run(prefix_call)
    missing = registry.run(ToolCall(ToolSpec("unknown.write", "write"), "tool:unknown:1"))

    assert exact == {"tool": "fs.write"}
    assert prefix == {"prefix": "process.write"}
    assert isinstance(missing, ToolResult)
    assert missing.status == "failed"
    assert missing.error == "No executor registered for tool: unknown.write"


def test_process_tool_executor_runs_command_or_argv(tmp_path) -> None:
    captured: list[tuple[list[str], RunOptions | None]] = []

    class FakeProcessRunner:
        def run(
            self,
            argv: list[str],
            cwd=None,
            timeout_sec: int = 300,
            terminate_grace_sec: int = 5,
            should_cancel=None,
            options: RunOptions | None = None,
        ) -> ProcessResult:
            captured.append((argv, options))
            return ProcessResult(
                status="success",
                exit_code=0,
                stdout="ok",
                stderr="",
            )

    call = ToolCall(
        ToolSpec("process.write", "write"),
        "tool:process.write:1",
        arguments={"command": "python -c \"print('ok')\"", "timeout_sec": 12},
    )

    result = process_tool_executor(
        tmp_path,
        process_runner=FakeProcessRunner(),  # type: ignore[arg-type]
    )(call)

    assert result.status == "succeeded"
    assert result.output["argv"] == ["python", "-c", "print('ok')"]
    assert result.output["exit_code"] == 0
    assert result.output["stdout"] == "ok"
    assert captured[0][1] == RunOptions(timeout_sec=12)


def test_file_tool_executor_reads_and_writes_repo_files(tmp_path) -> None:
    write_call = ToolCall(
        ToolSpec("fs.write", "write"),
        "tool:fs.write:1",
        arguments={
            "path": "nested/example.txt",
            "content": "hello",
            "create_parents": True,
        },
    )
    read_call = ToolCall(
        ToolSpec("fs.read", "read"),
        "tool:fs.read:1",
        arguments={"path": "nested/example.txt"},
    )
    executor = file_tool_executor(tmp_path)

    written = executor(write_call)
    read = executor(read_call)

    assert written.status == "succeeded"
    assert written.output == {"path": "nested/example.txt", "bytes": 5}
    assert read.status == "succeeded"
    assert read.output == {
        "path": "nested/example.txt",
        "content": "hello",
        "bytes": 5,
    }


def test_file_tool_executor_rejects_paths_outside_repo(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    call = ToolCall(
        ToolSpec("fs.write", "write"),
        "tool:fs.write:outside",
        arguments={"path": str(outside), "content": "nope"},
    )

    result = file_tool_executor(tmp_path)(call)

    assert result.status == "failed"
    assert result.error == "File tool path must be inside the repository"
    assert not outside.exists()


def test_memory_tool_executor_runs_memory_namespaced_tool(tmp_path) -> None:
    captured: list[tuple[str, dict[str, object] | None, Path | None]] = []

    class FakeMemoryClient:
        def run_tool(
            self,
            tool: str,
            args: dict[str, object] | None = None,
            cwd: Path | None = None,
        ) -> CodebaseMemoryResult:
            captured.append((tool, args, cwd))
            return CodebaseMemoryResult(
                tool=tool,
                status="passed",
                exit_code=0,
                stdout='{"ok":true}',
                stderr="",
            )

    call = ToolCall(
        ToolSpec("memory.search_graph", "read"),
        "tool:memory.search_graph:1",
        arguments={"query": "approval", "limit": 5},
    )

    result = memory_tool_executor(FakeMemoryClient(), cwd=tmp_path)(call)

    assert result.status == "succeeded"
    assert result.output["tool"] == "search_graph"
    assert result.output["memory_status"] == "passed"
    assert result.output["stdout"] == '{"ok":true}'
    assert captured == [("search_graph", {"query": "approval", "limit": 5}, tmp_path)]


def test_tool_types_reject_invalid_contract_values() -> None:
    with pytest.raises(ValueError, match="Tool name cannot be empty"):
        ToolSpec(" ", "read")
    with pytest.raises(ValueError, match="Unsupported tool risk tier"):
        ToolSpec("demo", "admin")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Tool idempotency key cannot be empty"):
        ToolCall(ToolSpec("demo", "read"), " ")
    with pytest.raises(ValueError, match="Unsupported tool result status"):
        ToolResult(
            ToolCall(ToolSpec("demo", "read"), "tool:demo:1"),
            "done",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="Tool arguments must be JSON-serializable"):
        ToolCall(
            ToolSpec("demo", "read"),
            "tool:demo:2",
            arguments={"bad": {1, 2, 3}},
        )
    with pytest.raises(ValueError, match="Process tool call requires exactly one"):
        make_process_tool_call("process.write", "write")
    with pytest.raises(ValueError, match="Memory tool cannot be empty"):
        make_memory_tool_call(" ")
