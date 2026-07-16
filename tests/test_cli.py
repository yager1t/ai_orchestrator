import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_orchestrator import __version__
from ai_orchestrator.autopilot import load_plan_tasks
from ai_orchestrator.cli.app import _state_store_for_repo, main
from ai_orchestrator.core.supervisor import Supervisor, SupervisorResult
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessResult, ProcessRunner, RunOptions
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.tools import (
    ToolBroker,
    make_fs_write_call,
    make_memory_tool_call,
    make_process_tool_call,
)
from ai_orchestrator.verification.release import ReleaseCheckResult, run_release_checks
from ai_orchestrator.verification.runner import VerificationResult, VerificationRunner


def test_version_command(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    output = capsys.readouterr().out
    assert exc.value.code == 0
    assert output == f"ai-orch {__version__}\n"


def test_log_level_configures_logging(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_basic_config(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("ai_orchestrator.cli.app.logging.basicConfig", fake_basic_config)

    exit_code = main(["--log-level", "debug", "agents", "--repo", str(tmp_path)])

    assert exit_code == 0
    assert calls
    assert calls[0]["level"] == 10


def test_state_store_for_repo_reuses_store_for_same_repo(tmp_path: Path) -> None:
    first = _state_store_for_repo(tmp_path)
    second = _state_store_for_repo(tmp_path)

    assert second is first


def task_id_from_run_output(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("task-") and ":" in line:
            return line.split(":", 1)[0]
    raise AssertionError(f"Could not find task id in output:\n{output}")


def test_autopilot_next_prints_next_plan_item(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    exit_code = main(["autopilot", "next", "--repo", str(tmp_path), "--plan", str(plan)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Task: Add approval CLI" in output
    assert "Source:" in output


def test_autopilot_run_defaults_to_dry_run(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    exit_code = main(["autopilot", "run", "--repo", str(tmp_path), "--plan", str(plan)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Agent profile:" in output
    assert "name: mock" in output
    assert "mode: mock" in output
    assert "available: yes" in output
    assert "Dry run: add --execute" in output


def test_autopilot_run_blocks_unavailable_real_agent_before_execution(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="missing-ai-orch-agent-binary",
    )

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Agent profile:" in output
    assert "name: generic" in output
    assert "type: generic_cli" in output
    assert "mode: real" in output
    assert "command: missing-ai-orch-agent-binary" in output
    assert "available: no" in output
    assert "Execution blocked: selected agent is unavailable: generic" in output


def test_autopilot_run_blocks_mock_agent_without_explicit_allow(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: mock agent selected" in output


def test_autopilot_run_uses_opt_in_worktree_for_execution(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    worktree = tmp_path / "autopilot-worktree"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")
    worktree.mkdir()
    captured_repos: list[Path] = []

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        assert repo == tmp_path
        assert candidate == worktree.resolve()
        return None

    def fake_dirty(repo: Path) -> bool:
        assert repo == worktree.resolve()
        return False

    def fake_run_once(self, task: str, repo: Path, planning_context=None) -> SupervisorResult:
        captured_repos.append(repo)
        return SupervisorResult(status="done", summary="Verification passed: custom", task_id="task-1")

    monkeypatch.setattr("ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate)
    monkeypatch.setattr("ai_orchestrator.cli.app._repo_has_uncommitted_changes", fake_dirty)
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Execution repo: {worktree.resolve()}" in output
    assert "task-1: Verification passed: custom" in output
    assert captured_repos == [worktree.resolve()]


def test_autopilot_run_blocks_invalid_worktree_before_execution(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    worktree = tmp_path / "not-worktree"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        return f"worktree path does not exist: {candidate}"

    def fake_run_once(self, task: str, repo: Path, planning_context=None) -> SupervisorResult:
        raise AssertionError("supervisor should not start with an invalid worktree")

    monkeypatch.setattr("ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate)
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: worktree path does not exist:" in output


def test_autopilot_plan_create_add_node_and_show_json(capsys, tmp_path: Path) -> None:
    exit_code = main(
        [
            "autopilot",
            "plan",
            "create",
            "--repo",
            str(tmp_path),
            "--title",
            "Robust autopilot",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    graph_id = payload["graph"]["graph_id"]

    assert exit_code == 0
    assert payload["graph"]["title"] == "Robust autopilot"
    assert payload["graph"]["status"] == "active"

    exit_code = main(
        [
            "autopilot",
            "plan",
            "add-node",
            str(graph_id),
            "--repo",
            str(tmp_path),
            "--key",
            "discover",
            "--title",
            "Discover current state",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    first_node_id = payload["node"]["node_id"]

    assert exit_code == 0
    assert payload["node"]["node_key"] == "discover"

    exit_code = main(
        [
            "autopilot",
            "plan",
            "add-node",
            str(graph_id),
            "--repo",
            str(tmp_path),
            "--key",
            "implement",
            "--title",
            "Implement next slice",
            "--task-text",
            "Implement the next bounded slice",
            "--acceptance-criterion",
            "targeted tests pass",
            "--verification-requirement",
            "python -m pytest",
            "--source-node-id",
            str(first_node_id),
            "--node-type",
            "repair",
            "--depends-on",
            str(first_node_id),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(payload["nodes"]) == 2
    assert payload["dependencies"] == [
        {
            "graph_id": graph_id,
            "node_id": payload["node"]["node_id"],
            "depends_on_node_id": first_node_id,
            "created_at": payload["dependencies"][0]["created_at"],
        }
    ]

    exit_code = main(
        [
            "autopilot",
            "plan",
            "show",
            str(graph_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["graph"]["graph_id"] == graph_id
    assert [node["node_key"] for node in payload["nodes"]] == ["discover", "implement"]
    implement_node = payload["nodes"][1]
    assert implement_node["task_text"] == "Implement the next bounded slice"
    assert implement_node["acceptance_criteria"] == ["targeted tests pass"]
    assert implement_node["verification_requirement"] == "python -m pytest"
    assert implement_node["source_node_id"] == first_node_id
    assert implement_node["node_type"] == "repair"
    assert len(payload["dependencies"]) == 1


def test_autopilot_plan_ready_lists_executable_nodes_json(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    graph = store.create_plan_graph("Ready graph")
    first = store.add_plan_graph_node(graph.graph_id, "first", "First step")
    second = store.add_plan_graph_node(
        graph.graph_id,
        "second",
        "Second step",
        depends_on_node_ids=[first.node_id],
    )

    exit_code = main(
        [
            "autopilot",
            "plan",
            "ready",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["graph"]["graph_id"] == graph.graph_id
    assert payload["ready_count"] == 1
    assert [node["node_id"] for node in payload["nodes"]] == [first.node_id]
    assert [
        (item["node"]["node_id"], item["ready"], item["reason"])
        for item in payload["readiness"]
    ] == [
        (first.node_id, True, "ready"),
        (second.node_id, False, "blocked_dependencies"),
    ]
    assert payload["readiness"][1]["blocking_dependencies"][0]["node_id"] == first.node_id

    store.update_plan_graph_node_status(first.node_id, "done")
    exit_code = main(
        [
            "autopilot",
            "plan",
            "ready",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--limit",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Ready PlanGraph nodes: 1" in output
    assert f"node={second.node_id} key=second" in output
    assert "Not ready PlanGraph nodes:" in output
    assert f"node={first.node_id} key=first reason=node_status_done" in output


def test_autopilot_plan_run_next_dry_run_keeps_node_pending(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    graph = store.create_plan_graph("Run graph")
    node = store.add_plan_graph_node(graph.graph_id, "root", "Root step")

    exit_code = main(
        [
            "autopilot",
            "plan",
            "run-next",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
        ]
    )
    output = capsys.readouterr().out
    loaded_node = store.get_plan_graph_node(node.node_id)

    assert exit_code == 0
    assert f"PlanGraph node: {node.node_id}" in output
    assert "Dry run: add --execute" in output
    assert loaded_node is not None
    assert loaded_node.status == "pending"
    assert loaded_node.attempts == 0


def test_autopilot_plan_run_next_executes_and_creates_replan_follow_up(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    graph = store.create_plan_graph("Run graph")
    node = store.add_plan_graph_node(graph.graph_id, "root", "Root step")

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id="plan-node-task",
        )
        iteration = self.state_store.add_iteration(
            task_id=stored.task_id,
            iteration_index=1,
            agent_name="mock",
            agent_status="success",
            prompt=task,
            raw_output="failed",
            decision_status="continue",
            decision_reason="Verification failed: unit",
        )
        self.state_store.record_replan_decision(
            task_id=stored.task_id,
            iteration_id=iteration.iteration_id,
            source="verification",
            status="continue",
            reason="Verification failed: unit",
            follow_up_prompt="Fix graph node failure",
            failed_checks=[{"name": "unit", "status": "failed"}],
        )
        return SupervisorResult(
            status="blocked",
            summary="Verification failed",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "plan",
            "run-next",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    output = capsys.readouterr().out

    loaded_node = store.get_plan_graph_node(node.node_id)
    decisions = store.list_replan_decisions("plan-node-task")
    nodes = store.list_plan_graph_nodes(graph.graph_id)
    follow_up = nodes[1]
    dependencies = store.list_plan_graph_dependencies(
        graph.graph_id,
        node_id=follow_up.node_id,
    )

    assert exit_code == 1
    assert "PlanGraph node" in output
    assert "status=blocked" in output
    assert "Report:" in output
    assert loaded_node is not None
    assert loaded_node.status == "blocked"
    assert loaded_node.attempts == 1
    assert len(decisions) == 1
    assert decisions[0].plan_graph_id == graph.graph_id
    assert decisions[0].plan_graph_node_id == node.node_id
    assert [plan_node.node_key for plan_node in nodes] == [
        "root",
        f"replan-{decisions[0].replan_id}",
    ]
    assert follow_up.status == "pending"
    assert dependencies[0].depends_on_node_id == node.node_id


def test_autopilot_plan_run_batch_dry_run_keeps_nodes_pending(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    graph = store.create_plan_graph("Batch graph")
    first = store.add_plan_graph_node(graph.graph_id, "first", "First step")
    second = store.add_plan_graph_node(graph.graph_id, "second", "Second step")

    exit_code = main(
        [
            "autopilot",
            "plan",
            "run-batch",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    loaded_first = store.get_plan_graph_node(first.node_id)
    loaded_second = store.get_plan_graph_node(second.node_id)

    assert exit_code == 0
    assert f"PlanGraph node: {first.node_id}" in output
    assert f"PlanGraph node: {second.node_id}" in output
    assert "Dry run: would process 2 PlanGraph node(s)." in output
    assert loaded_first is not None
    assert loaded_second is not None
    assert loaded_first.status == "pending"
    assert loaded_first.attempts == 0
    assert loaded_second.status == "pending"
    assert loaded_second.attempts == 0


def test_autopilot_plan_recover_blocks_stale_in_progress_nodes(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    graph = store.create_plan_graph("Recover graph")
    node = store.add_plan_graph_node(graph.graph_id, "stale", "Stale node")
    store.update_plan_graph_node_status(node.node_id, "in_progress")

    exit_code = main(
        [
            "autopilot",
            "plan",
            "recover",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    dry_run_node = store.get_plan_graph_node(node.node_id)

    assert exit_code == 0
    assert payload["mode"] == "dry_run"
    assert payload["stale_count"] == 1
    assert payload["nodes"][0]["node_id"] == node.node_id
    assert dry_run_node is not None
    assert dry_run_node.status == "in_progress"

    exit_code = main(
        [
            "autopilot",
            "plan",
            "recover",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--apply",
            "--reason",
            "worker interrupted",
        ]
    )
    output = capsys.readouterr().out
    recovered_node = store.get_plan_graph_node(node.node_id)

    assert exit_code == 0
    assert "PlanGraph recover" in output
    assert "blocked_nodes: 1" in output
    assert recovered_node is not None
    assert recovered_node.status == "blocked"
    assert recovered_node.blocked_reason == "worker interrupted"


def test_autopilot_plan_run_batch_stops_on_blocked_node(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    graph = store.create_plan_graph("Batch graph")
    first = store.add_plan_graph_node(graph.graph_id, "first", "First step")
    second = store.add_plan_graph_node(graph.graph_id, "second", "Second step")
    third = store.add_plan_graph_node(graph.graph_id, "third", "Third step")
    call_count = 0

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        nonlocal call_count
        call_count += 1
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id=f"plan-node-batch-{call_count}",
        )
        return SupervisorResult(
            status="done" if call_count == 1 else "blocked",
            summary=f"Result {call_count}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "plan",
            "run-batch",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "3",
        ]
    )
    output = capsys.readouterr().out

    loaded_first = store.get_plan_graph_node(first.node_id)
    loaded_second = store.get_plan_graph_node(second.node_id)
    loaded_third = store.get_plan_graph_node(third.node_id)

    assert exit_code == 1
    assert "PlanGraph batch stopped after 2 node(s): status=blocked" in output
    assert call_count == 2
    assert loaded_first is not None
    assert loaded_second is not None
    assert loaded_third is not None
    assert loaded_first.status == "done"
    assert loaded_first.attempts == 1
    assert loaded_second.status == "blocked"
    assert loaded_second.attempts == 1
    assert loaded_third.status == "pending"
    assert loaded_third.attempts == 0


def test_autopilot_plan_updates_graph_and_node_status(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    graph = store.create_plan_graph("Robust autopilot")
    node = store.add_plan_graph_node(
        graph.graph_id,
        node_key="implement",
        title="Implement next slice",
    )

    exit_code = main(
        [
            "autopilot",
            "plan",
            "update",
            str(graph.graph_id),
            "--repo",
            str(tmp_path),
            "--status",
            "blocked",
        ]
    )
    output = capsys.readouterr().out
    loaded_graph = store.get_plan_graph(graph.graph_id)

    assert exit_code == 0
    assert "Updated PlanGraph" in output
    assert loaded_graph is not None
    assert loaded_graph.status == "blocked"

    exit_code = main(
        [
            "autopilot",
            "plan",
            "update-node",
            str(node.node_id),
            "--repo",
            str(tmp_path),
            "--status",
            "in_progress",
            "--increment-attempts",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded_node = store.get_plan_graph_node(node.node_id)

    assert exit_code == 0
    assert payload["node"]["status"] == "in_progress"
    assert payload["node"]["attempts"] == 1
    assert loaded_node is not None
    assert loaded_node.status == "in_progress"
    assert loaded_node.attempts == 1


def test_autopilot_plan_reports_missing_graph(capsys, tmp_path: Path) -> None:
    exit_code = main(
        [
            "autopilot",
            "plan",
            "show",
            "404",
            "--repo",
            str(tmp_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "PlanGraph not found: 404" in output


def test_autopilot_queue_link_plan_graph_dry_run_and_apply_json(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo queue item",
    )
    graph = store.create_plan_graph("Demo graph")
    root = store.add_plan_graph_node(graph.graph_id, "root", "Root step")

    exit_code = main(
        [
            "autopilot",
            "queue",
            "link-plan-graph",
            str(item.plan_item_id),
            "--repo",
            str(tmp_path),
            "--graph-id",
            str(graph.graph_id),
            "--root-node-id",
            str(root.node_id),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["mode"] == "dry_run"
    assert payload["applied"] is False
    assert payload["link"]["graph_id"] == graph.graph_id
    assert loaded is not None
    assert loaded.plan_graph_id is None
    assert loaded.plan_graph_root_node_id is None

    exit_code = main(
        [
            "autopilot",
            "queue",
            "link-plan-graph",
            str(item.plan_item_id),
            "--repo",
            str(tmp_path),
            "--graph-id",
            str(graph.graph_id),
            "--root-node-id",
            str(root.node_id),
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["mode"] == "apply"
    assert payload["applied"] is True
    assert payload["plan_item"]["plan_graph_id"] == graph.graph_id
    assert payload["plan_item"]["plan_graph_root_node_id"] == root.node_id
    assert loaded is not None
    assert loaded.plan_graph_id == graph.graph_id
    assert loaded.plan_graph_root_node_id == root.node_id

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            str(item.plan_item_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["plan_graph_id"] == graph.graph_id
    assert payload["plan_graph_root_node_id"] == root.node_id


def test_autopilot_queue_link_plan_graph_rejects_wrong_root_node(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo queue item",
    )
    graph = store.create_plan_graph("First graph")
    other_graph = store.create_plan_graph("Other graph")
    other_root = store.add_plan_graph_node(other_graph.graph_id, "root", "Root")

    exit_code = main(
        [
            "autopilot",
            "queue",
            "link-plan-graph",
            str(item.plan_item_id),
            "--repo",
            str(tmp_path),
            "--graph-id",
            str(graph.graph_id),
            "--root-node-id",
            str(other_root.node_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 1
    assert f"PlanGraph root node not found in graph {graph.graph_id}" in output
    assert loaded is not None
    assert loaded.plan_graph_id is None


def test_status_prints_stored_task(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.update_task_status(task.task_id, "done")

    exit_code = main(["status", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Task: {task.task_id}" in output
    assert "Status: done" in output
    assert "Iterations: 1" in output
    assert "check=unit status=passed exit=0" in output


def test_status_json_prints_stored_task(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.update_task_status(task.task_id, "done")

    exit_code = main(["status", task.task_id, "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["schema_version"] == "1.0"
    assert payload["command"] == "status"
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["task"]["task_id"] == task.task_id
    assert payload["task"]["status"] == "done"
    assert payload["iteration_count"] == 1
    assert payload["iterations"][0]["iteration_id"] == iteration.iteration_id
    assert payload["iterations"][0]["verification_runs"][0]["name"] == "unit"
    assert payload["iterations"][0]["verification_runs"][0]["status"] == "passed"


def test_status_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["status", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_status_json_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["status", "missing-task", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["command"] == "status"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "task_not_found"
    assert payload["error"]["task_id"] == "missing-task"


def test_metrics_prints_local_summary(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="generic",
        agent_status="failed",
        prompt="demo task",
        raw_output="failed",
        decision_status="blocked",
        decision_reason="agent failed",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="failed",
        ),
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push",
        reason="approval required",
    )
    store.resolve_approval_request(approval.approval_id, status="approved")

    exit_code = main(["metrics", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Metrics" in output
    assert "tasks: 1" in output
    assert "iterations: 1" in output
    assert "verification: total=1 passed=0 not_passed=1 pass_rate=0.0%" in output
    assert "approvals: total=1 pending=0 approved=1 rejected=0 stale=0" in output
    assert "adapter_failures: 1" in output


def test_cancel_marks_task_cancelled(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("cancel me", repo_path=tmp_path)

    exit_code = main(["cancel", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    loaded = store.get_task(task.task_id)

    assert exit_code == 0
    assert f"Cancelled: {task.task_id}" in output
    assert loaded is not None
    assert loaded.status == "cancelled"


def test_cancel_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["cancel", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_approvals_list_prints_pending_requests(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )

    exit_code = main(["approvals", "list", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"{approval.approval_id}: status=pending" in output
    assert "source=verification" in output
    assert "command=git push origin main" in output


def test_approvals_list_json_prints_pending_requests(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )

    exit_code = main(["approvals", "list", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["command"] == "approvals list"
    assert payload["ok"] is True
    assert payload["status_filter"] == "pending"
    assert payload["count"] == 1
    assert payload["approvals"][0]["approval_id"] == approval.approval_id
    assert payload["approvals"][0]["status"] == "pending"
    assert payload["approvals"][0]["command_string"] == "git push origin main"


def test_approvals_list_prints_empty_state(capsys, tmp_path: Path) -> None:
    exit_code = main(["approvals", "list", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No approval requests found." in output


def test_approvals_list_json_prints_empty_list(capsys, tmp_path: Path) -> None:
    exit_code = main(["approvals", "list", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["count"] == 0
    assert payload["approvals"] == []


def test_approvals_show_prints_details(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="memory",
        command_string="codebase-memory-mcp cli index_repository",
        reason="memory indexing requires approval",
    )

    exit_code = main(
        ["approvals", "show", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Approval: {approval.approval_id}" in output
    assert "Status: pending" in output
    assert "Source: memory" in output
    assert "Reason: memory indexing requires approval" in output


def test_approvals_show_json_prints_details(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="memory",
        command_string="codebase-memory-mcp cli index_repository",
        reason="memory indexing requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "show",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["command"] == "approvals show"
    assert payload["approval"]["approval_id"] == approval.approval_id
    assert payload["approval"]["source"] == "memory"
    assert payload["approval"]["reason"] == "memory indexing requires approval"


def test_approvals_approve_resolves_request(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "approve",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--resolution",
            "looks safe",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_approval_request(approval.approval_id)

    assert exit_code == 0
    assert f"{approval.approval_id}: status=approved" in output
    assert loaded is not None
    assert loaded.status == "approved"
    assert loaded.resolution == "looks safe"


def test_approvals_approve_json_resolves_request(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "approve",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--resolution",
            "looks safe",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["command"] == "approvals approve"
    assert payload["approval"]["approval_id"] == approval.approval_id
    assert payload["approval"]["status"] == "approved"
    assert payload["approval"]["resolution"] == "looks safe"


def test_approvals_reject_resolves_request(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="pip install demo",
        reason="package install requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "reject",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--resolution",
            "not needed",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_approval_request(approval.approval_id)

    assert exit_code == 0
    assert f"{approval.approval_id}: status=rejected" in output
    assert loaded is not None
    assert loaded.status == "rejected"
    assert loaded.resolution == "not needed"


def test_approvals_reject_json_resolves_request(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="pip install demo",
        reason="package install requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "reject",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--resolution",
            "not needed",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["command"] == "approvals reject"
    assert payload["approval"]["approval_id"] == approval.approval_id
    assert payload["approval"]["status"] == "rejected"
    assert payload["approval"]["resolution"] == "not needed"


def test_approvals_retry_runs_approved_request(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[list[str], Path | None]] = []

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured.append((argv, cwd))
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout="retry ok",
            stderr="",
        )

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(
        tmp_path,
        command_name="approval",
        command_run="retry-token command",
        require_approval_patterns=["retry-token"],
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="retry-token command",
        reason="policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="looks safe",
    )

    exit_code = main(
        ["approvals", "retry", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "retry: passed exit=0" in output
    assert "retry history: count=1 last_status=passed last_exit=0" in output
    assert "retry ok" in output
    assert captured == [(["retry-token", "command"], tmp_path)]
    actions = store.list_action_records(task.task_id)
    loaded = store.get_approval_request(approval.approval_id)
    assert loaded is not None
    assert loaded.retry_count == 1
    assert loaded.last_retry_status == "passed"
    assert loaded.last_retry_exit_code == 0
    assert len(actions) == 1
    assert actions[0].action_type == "process.approval_retry"
    assert actions[0].status == "succeeded"
    assert actions[0].payload["approved_retry"] is True
    assert actions[0].payload["action_request"]["risk"]["action_type"] == "shell"
    assert actions[0].result["action_decision"]["approval_id"] == approval.approval_id
    assert actions[0].result["action_result"]["output_preview"] == {
        "stdout": "retry ok",
        "stderr": "",
        "exit_code": 0,
    }


def test_approvals_retry_json_runs_approved_request(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[list[str], Path | None]] = []

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured.append((argv, cwd))
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout="retry ok",
            stderr="",
        )

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(
        tmp_path,
        command_name="approval",
        command_run="retry-token command",
        require_approval_patterns=["retry-token"],
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="retry-token command",
        reason="policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="looks safe",
    )

    exit_code = main(
        [
            "approvals",
            "retry",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["command"] == "approvals retry"
    assert payload["ok"] is True
    assert payload["approval_id"] == approval.approval_id
    assert payload["task_id"] == task.task_id
    assert payload["retry_status"] == "passed"
    assert payload["exit_code"] == 0
    assert payload["retry_count"] == 1
    assert payload["stdout"] == "retry ok"
    assert captured == [(["retry-token", "command"], tmp_path)]


def test_approvals_retry_runs_approved_tool_broker_request(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[list[str], Path | None]] = []

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        terminate_grace_sec: int = 5,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured.append((argv, cwd))
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout="tool retry ok",
            stderr="",
        )

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = make_process_tool_call(
        "process.write",
        "write",
        argv=["python", "-c", "print('ok')"],
        task_id=task.task_id,
        idempotency_key="tool:process.write:approval",
    )
    requested = broker.run(call, lambda _call: {"unused": True})
    approval_id = requested.output["approval_id"]
    assert isinstance(approval_id, int)
    store.resolve_approval_request(
        approval_id,
        "approved",
        resolution="looks safe",
    )

    exit_code = main(["approvals", "retry", str(approval_id), "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    actions = store.list_action_records(task.task_id)
    loaded = store.get_approval_request(approval_id)

    assert exit_code == 0
    assert "retry: passed exit=0" in output
    assert "tool retry ok" in output
    assert captured == [(["python", "-c", "print('ok')"], tmp_path)]
    assert loaded is not None
    assert loaded.retry_count == 1
    assert loaded.last_retry_status == "passed"
    assert loaded.last_retry_exit_code == 0
    assert [action.status for action in actions] == ["needs_approval", "succeeded"]
    assert actions[1].payload["approved_retry"] is True
    assert actions[1].result["output"]["approval_id"] == approval_id


def test_approvals_retry_runs_approved_fs_write_request(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = make_fs_write_call(
        "generated/result.txt",
        "approved content",
        create_parents=True,
        task_id=task.task_id,
        idempotency_key="tool:fs.write:approval",
    )
    requested = broker.run(call, lambda _call: {"unused": True})
    approval_id = requested.output["approval_id"]
    assert isinstance(approval_id, int)
    store.resolve_approval_request(approval_id, "approved", resolution="looks safe")

    exit_code = main(["approvals", "retry", str(approval_id), "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    written = tmp_path / "generated" / "result.txt"
    actions = store.list_action_records(task.task_id)
    loaded = store.get_approval_request(approval_id)

    assert exit_code == 0
    assert "retry: passed exit=None" in output
    assert written.read_text(encoding="utf-8") == "approved content"
    assert loaded is not None
    assert loaded.retry_count == 1
    assert loaded.last_retry_status == "passed"
    assert loaded.last_retry_exit_code is None
    assert [action.status for action in actions] == ["needs_approval", "succeeded"]
    assert actions[1].result["output"]["tool_output"] == {
        "path": "generated/result.txt",
        "bytes": 16,
    }


def test_approvals_retry_applies_configured_sandbox_writable_paths(
    capsys,
    tmp_path: Path,
) -> None:
    write_config(tmp_path)
    config_path = tmp_path / ".ai-orch" / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """
sandbox:
  writable_paths:
    - "docs"
""",
        encoding="utf-8",
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = make_fs_write_call(
        "src/example.py",
        "print('blocked')",
        create_parents=True,
        task_id=task.task_id,
        idempotency_key="tool:fs.write:sandbox",
    )
    requested = broker.run(call, lambda _call: {"unused": True})
    approval_id = requested.output["approval_id"]
    assert isinstance(approval_id, int)
    store.resolve_approval_request(approval_id, "approved", resolution="looks safe")

    exit_code = main(["approvals", "retry", str(approval_id), "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    loaded = store.get_approval_request(approval_id)
    actions = store.list_action_records(task.task_id)
    events = store.list_task_events(task.task_id)
    sandbox_events = [
        event for event in events if event.event_type == "sandbox.decision"
    ]

    assert exit_code == 1
    assert "retry: policy_denied exit=None" in output
    assert "outside writable sandbox scope" in output
    assert not (tmp_path / "src" / "example.py").exists()
    assert loaded is not None
    assert loaded.retry_count == 1
    assert loaded.last_retry_status == "policy_denied"
    assert len(sandbox_events) == 1
    assert sandbox_events[0].payload["action_id"] == actions[1].action_id
    assert sandbox_events[0].payload["tool_name"] == "fs.write"
    assert sandbox_events[0].payload["status"] == "policy_denied"
    assert sandbox_events[0].payload["decision"] == {
        "action": "deny",
        "reason": f"Path is outside writable sandbox scope: {tmp_path / 'docs'}",
        "path": str(tmp_path / "src" / "example.py"),
    }


def test_approvals_retry_runs_approved_memory_tool_request(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[list[str], Path | None]] = []

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        terminate_grace_sec: int = 5,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured.append((argv, cwd))
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout='{"indexed":true}',
            stderr="",
        )

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    broker = ToolBroker(store, PolicyEngine())
    call = make_memory_tool_call(
        "index_repository",
        risk_tier="network",
        args={"repo_path": str(tmp_path.resolve())},
        task_id=task.task_id,
        idempotency_key="tool:memory.index_repository:approval",
    )
    requested = broker.run(call, lambda _call: {"unused": True})
    approval_id = requested.output["approval_id"]
    assert isinstance(approval_id, int)
    store.resolve_approval_request(approval_id, "approved", resolution="looks safe")

    exit_code = main(["approvals", "retry", str(approval_id), "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    loaded = store.get_approval_request(approval_id)

    assert exit_code == 0
    assert "retry: passed exit=0" in output
    assert '{"indexed":true}' in output
    assert captured == [
        (
            [
                "codebase-memory-mcp",
                "cli",
                "index_repository",
                json.dumps({"repo_path": str(tmp_path.resolve())}, sort_keys=True),
            ],
            tmp_path,
        )
    ]
    assert loaded is not None
    assert loaded.retry_count == 1
    assert loaded.last_retry_status == "passed"
    assert loaded.last_retry_exit_code == 0


def test_approvals_retry_requires_approved_request(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="retry-token command",
        reason="policy requires approval",
    )

    exit_code = main(
        ["approvals", "retry", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert f"Approval request is not approved: {approval.approval_id} status=pending" in output


def test_approvals_retry_json_requires_approved_request(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="retry-token command",
        reason="policy requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "retry",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "approval_not_approved"
    assert payload["error"]["approval_id"] == approval.approval_id
    assert payload["error"]["status"] == "pending"
    assert store.get_approval_request(approval.approval_id).retry_count == 0  # type: ignore[union-attr]


def test_approvals_stale_marks_old_pending_requests(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    old_approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="old command",
        reason="old approval",
    )
    fresh_approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="fresh command",
        reason="fresh approval",
    )
    old_created_at = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE approval_requests SET created_at = ? WHERE approval_id = ?",
            (old_created_at, old_approval.approval_id),
        )

    exit_code = main(
        [
            "approvals",
            "stale",
            "--repo",
            str(tmp_path),
            "--older-than-hours",
            "24",
            "--resolution",
            "too old",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"{old_approval.approval_id}: status=stale" in output
    assert "old command" in output
    assert "fresh command" not in output
    assert store.list_approval_requests(status="pending") == [fresh_approval]
    stale = store.list_approval_requests(status="stale")
    assert len(stale) == 1
    assert stale[0].resolution == "too old"


def test_approvals_retry_does_not_override_deny_rules(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        calls.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="ran", stderr="")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(
        tmp_path,
        command_name="danger",
        command_run="dangerous command",
        deny_patterns=["dangerous"],
        require_approval_patterns=["dangerous"],
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="dangerous command",
        reason="policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="operator approved",
    )

    exit_code = main(
        ["approvals", "retry", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "retry: policy_denied exit=None" in output
    assert "Denied by pattern: dangerous" in output
    assert calls == []


def test_approvals_retry_json_does_not_override_deny_rules(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        calls.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="ran", stderr="")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(
        tmp_path,
        command_name="danger",
        command_run="dangerous command",
        deny_patterns=["dangerous"],
        require_approval_patterns=["dangerous"],
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="dangerous command",
        reason="policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="operator approved",
    )

    exit_code = main(
        [
            "approvals",
            "retry",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["retry_status"] == "policy_denied"
    assert payload["error"]["code"] == "policy_denied"
    assert "Denied by pattern: dangerous" in payload["error"]["message"]
    assert calls == []


def test_approvals_returns_error_for_missing_request(capsys, tmp_path: Path) -> None:
    exit_code = main(["approvals", "show", "404", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Approval request not found: 404" in output


def test_approvals_show_json_returns_error_for_missing_request(
    capsys,
    tmp_path: Path,
) -> None:
    exit_code = main(["approvals", "show", "404", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["command"] == "approvals show"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "approval_not_found"
    assert payload["error"]["approval_id"] == 404


def test_tui_status_prints_read_only_task_view(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )

    exit_code = main(["tui", "status", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Task {task.task_id}" in output
    assert "Status: created" in output
    assert "Iterations" in output
    assert "check: unit passed exit=0" in output


def test_tui_status_prints_task_approval_history(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo approval task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo approval task",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Approval required",
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="deploy production",
        reason="Policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "rejected",
        resolution="Not safe enough",
    )

    exit_code = main(["tui", "status", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Approvals" in output
    assert f"approval={approval.approval_id} status=rejected" in output
    assert f"task={task.task_id} iteration={iteration.iteration_id}" in output
    assert "command: deploy production" in output
    assert "reason: Policy requires approval" in output
    assert "resolution: Not safe enough" in output


def test_tui_status_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "status", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_tui_tasks_prints_read_only_task_list(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    first = store.create_task("first task", repo_path=tmp_path, task_id="task-1")
    second = store.create_task("second task", repo_path=tmp_path, task_id="task-2")
    store.update_task_status(first.task_id, "done")
    store.update_task_status(second.task_id, "blocked")

    exit_code = main(["tui", "tasks", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Tasks" in output
    assert "task-2 [blocked] second task" in output
    assert "task-1 [done] first task" in output
    assert output.index("task-2") < output.index("task-1")


def test_tui_tasks_prints_empty_state(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "tasks", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No tasks recorded." in output


def test_tui_approvals_prints_pending_verification_approvals(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("needs approval", repo_path=tmp_path, task_id="task-approval")
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="needs approval",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Approval required",
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="deploy production",
        reason="Requires approval: deploy",
    )

    exit_code = main(["tui", "approvals", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Approvals" in output
    assert f"approval={approval.approval_id} status=pending" in output
    assert f"task=task-approval iteration={iteration.iteration_id}" in output
    assert "command: deploy production" in output
    assert "reason: Requires approval: deploy" in output


def test_tui_approvals_prints_empty_state(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "approvals", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No approval requests recorded." in output


def test_tui_current_prints_latest_iteration(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("current task", repo_path=tmp_path, task_id="task-current")
    first = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="current task",
        raw_output="done",
        decision_status="continue",
        decision_reason="Needs another pass",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=first.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="failed",
        ),
    )
    second = store.add_iteration(
        task_id=task.task_id,
        iteration_index=2,
        agent_name="mock",
        agent_status="success",
        prompt="current task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=second.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )

    exit_code = main(["tui", "current", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Current iteration for task-current" in output
    assert "Iteration: 2" in output
    assert "Decision: done" in output
    assert "unit: passed exit=0" in output


def test_tui_current_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "current", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_tui_current_prints_empty_iteration_state(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("empty current", repo_path=tmp_path, task_id="task-empty")

    exit_code = main(["tui", "current", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Current iteration for task-empty" in output
    assert "No iterations recorded." in output


def test_tui_logs_prints_iteration_prompt_and_output(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("log task", repo_path=tmp_path, task_id="task-logs")
    store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="please finish",
        raw_output="done output",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )

    exit_code = main(["tui", "logs", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Logs for task-logs" in output
    assert "prompt: please finish" in output
    assert "output: done output" in output


def test_tui_logs_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "logs", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_tui_memory_views_print_lessons_and_influence(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    seed = store.create_task("seed", repo_path=tmp_path)
    task = store.create_task("run", repo_path=tmp_path)
    lesson = store.record_memory_lesson(
        source_task_id=seed.task_id,
        lesson="Use verifier result as authority",
        outcome_status="blocked",
    )
    store.record_memory_influence(
        task_id=task.task_id,
        lesson_id=lesson.lesson_id,
        reason="selected for planning",
    )

    lessons_exit = main(["tui", "memory-lessons", "--repo", str(tmp_path)])
    lessons_output = capsys.readouterr().out
    influence_exit = main(
        [
            "tui",
            "memory-influence",
            "--repo",
            str(tmp_path),
            "--task-id",
            task.task_id,
        ]
    )
    influence_output = capsys.readouterr().out

    assert lessons_exit == 0
    assert "Memory lessons" in lessons_output
    assert "Use verifier result as authority" in lessons_output
    assert influence_exit == 0
    assert "Memory influence" in influence_output
    assert f"task={task.task_id}" in influence_output


def test_report_writes_markdown_file(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo report", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo report",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.update_task_status(task.task_id, "done")

    exit_code = main(["report", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"

    assert exit_code == 0
    assert f"Report: {report_path}" in output
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert f"# ai-orch report: {task.task_id}" in report
    assert "- `unit`: `passed` exit=`0`" in report


def test_report_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["report", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_recover_dry_run_reports_interrupted_state(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("interrupted task", repo_path=tmp_path, status="running")
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="recover-action-1",
        action_type="tool_call",
    )
    store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )

    exit_code = main(["recover", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Recovery" in output
    assert "running_tasks: 1" in output
    assert "expired_action_leases: 1" in output
    assert "stale_started_actions: 0" in output
    assert "dry_run: use --apply --reason" in output
    assert store.get_task(task.task_id).status == "running"  # type: ignore[union-attr]
    assert store.get_action_record(action.action_id).status == "started"  # type: ignore[union-attr]


def test_recover_apply_requires_reason(capsys, tmp_path: Path) -> None:
    exit_code = main(["recover", "--repo", str(tmp_path), "--apply"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--reason is required when --apply is set" in output


def test_recover_apply_blocks_running_tasks_and_fails_expired_actions(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("interrupted task", repo_path=tmp_path, status="running")
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="recover-action-apply",
        action_type="tool_call",
    )
    store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )

    exit_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--apply",
            "--reason",
            "operator recovered interrupted run",
        ]
    )
    output = capsys.readouterr().out
    recovered_task = store.get_task(task.task_id)
    recovered_action = store.get_action_record(action.action_id)
    events = store.list_task_events(task.task_id)

    assert exit_code == 0
    assert "blocked_tasks: 1" in output
    assert "failed_actions: 1" in output
    assert recovered_task is not None
    assert recovered_task.status == "blocked"
    assert recovered_action is not None
    assert recovered_action.status == "failed"
    assert recovered_action.lease_owner is None
    assert recovered_action.lease_expires_at is None
    assert recovered_action.result["recovered"] is True
    assert events[-1].event_type == "task.recovered"
    assert events[-1].payload["reason"] == "operator recovered interrupted run"


def test_recover_json_reports_counts(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("json interrupted task", repo_path=tmp_path, status="running")
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="recover-action-json",
        action_type="tool_call",
    )
    store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )

    exit_code = main(["recover", "--repo", str(tmp_path), "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert set(payload) == {
        "apply",
        "dry_run",
        "reason",
        "running_tasks",
        "expired_action_leases",
        "stale_started_actions",
        "worktree_recovery_candidates",
        "recovered",
    }
    assert payload["apply"] is False
    assert payload["dry_run"] is True
    assert payload["reason"] is None
    for section in (
        "running_tasks",
        "expired_action_leases",
        "stale_started_actions",
        "worktree_recovery_candidates",
    ):
        assert set(payload[section]) == {"count", "items"}
    assert payload["running_tasks"]["count"] == 1
    assert payload["running_tasks"]["items"][0]["task_id"] == task.task_id
    assert payload["expired_action_leases"]["count"] == 1
    assert payload["expired_action_leases"]["items"][0]["action_id"] == action.action_id
    assert payload["stale_started_actions"]["count"] == 0
    assert payload["worktree_recovery_candidates"]["count"] == 0
    assert payload["recovered"] == {
        "blocked_tasks": 0,
        "failed_actions": 0,
        "marked_worktree_recoveries": 0,
    }


def test_recover_apply_json_reports_recovery_counts(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("json apply interrupted task", repo_path=tmp_path, status="running")
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="recover-action-json-apply",
        action_type="tool_call",
    )
    store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )

    exit_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--apply",
            "--reason",
            "operator recovered json apply",
            "--json",
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    recovered_task = store.get_task(task.task_id)
    recovered_action = store.get_action_record(action.action_id)

    assert exit_code == 0
    assert payload["apply"] is True
    assert payload["dry_run"] is False
    assert payload["reason"] == "operator recovered json apply"
    assert payload["recovered"] == {
        "blocked_tasks": 1,
        "failed_actions": 1,
        "marked_worktree_recoveries": 0,
    }
    assert recovered_task is not None
    assert recovered_task.status == "blocked"
    assert recovered_action is not None
    assert recovered_action.status == "failed"
    assert recovered_action.result["reason"] == "operator recovered json apply"


def test_recover_reports_stale_worktree_execution(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("stale worktree task", repo_path=tmp_path, status="running")
    worktree = tmp_path / "worktree"
    profile = {
        "task_id": task.task_id,
        "worktree_path": str(worktree),
        "branch": "codex/stale",
        "base_ref": "main",
        "dirty": True,
        "cleanup_eligible": False,
    }
    store.append_task_event(
        task.task_id,
        "worktree.execution_profile",
        {"profile": profile, "sandbox": {"root": str(worktree)}},
        actor="supervisor",
    )
    old_timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (old_timestamp, task.task_id),
        )

    exit_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--worktree-stale-minutes",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "worktree_recovery_candidates: 1" in output
    assert (
        f"[worktree_recovery] {task.task_id}: inspect_resume_or_block "
        f"operator=inspect queue_item=- node=- "
        f"next=inspect_task_timeline "
        f"worktree={worktree} updated={old_timestamp}"
    ) in output
    assert store.get_task(task.task_id).status == "running"  # type: ignore[union-attr]


def test_recover_apply_marks_stale_worktree_execution(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("stale clean worktree", repo_path=tmp_path, status="running")
    worktree = tmp_path / "worktree"
    profile = {
        "task_id": task.task_id,
        "worktree_path": str(worktree),
        "branch": "codex/merged",
        "base_ref": "main",
        "dirty": False,
        "cleanup_eligible": True,
    }
    store.append_task_event(
        task.task_id,
        "worktree.execution_profile",
        {"profile": profile, "sandbox": {"root": str(worktree)}},
        actor="supervisor",
    )
    old_timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (old_timestamp, task.task_id),
        )

    exit_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--worktree-stale-minutes",
            "1",
            "--apply",
            "--reason",
            "operator reviewed stale worktree",
        ]
    )
    output = capsys.readouterr().out
    events = store.list_task_events(task.task_id)
    worktree_events = [
        event for event in events if event.event_type == "worktree.recovery_recommendation"
    ]
    recovered_task = store.get_task(task.task_id)

    assert exit_code == 0
    assert "marked_worktree_recoveries: 1" in output
    assert recovered_task is not None
    assert recovered_task.status == "blocked"
    assert len(worktree_events) == 1
    assert worktree_events[0].payload["recommendation"] == "cleanup"
    assert worktree_events[0].payload["operator_recommendation"] == "cleanup_candidate"
    assert (
        worktree_events[0].payload["action_plan"]["commands"][-1]["name"]
        == "cleanup_candidates_dry_run"
    )
    assert worktree_events[0].payload["worktree_path"] == str(worktree)
    assert worktree_events[0].payload["previous_status"] == "running"
    assert worktree_events[0].payload["reason"] == "operator reviewed stale worktree"


def test_recover_json_reports_stale_worktree_execution(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("stale unlinked worktree", repo_path=tmp_path, status="running")
    worktree = tmp_path / "worktree"
    profile = {
        "task_id": task.task_id,
        "worktree_path": str(worktree),
        "branch": None,
        "base_ref": "main",
        "dirty": None,
        "cleanup_eligible": False,
    }
    store.append_task_event(
        task.task_id,
        "worktree.execution_profile",
        {"profile": profile, "sandbox": {"root": str(worktree)}},
        actor="supervisor",
    )
    old_timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (old_timestamp, task.task_id),
        )

    exit_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--worktree-stale-minutes",
            "1",
            "--json",
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["worktree_recovery_candidates"]["count"] == 1
    item = payload["worktree_recovery_candidates"]["items"][0]
    assert item["task_id"] == task.task_id
    assert item["recommendation"] == "inspect_requeue_or_block"
    assert item["operator_recommendation"] == "block"
    assert item["worktree_path"] == str(worktree)
    assert item["queue_item"] is None
    assert item["plan_graph_node"] is None
    assert item["action_plan"]["operator_recommendation"] == "block"
    assert item["action_plan"]["commands"][0]["name"] == "inspect_task_timeline"
    assert item["action_plan"]["commands"][-1]["name"] == "block_task_manual_review"
    assert item["action_plan"]["commands"][-1]["requires_explicit_apply"] is True
    assert item["action_plan"]["commands"][-1]["available"] is False


def test_recover_links_stale_worktree_execution_to_queue_and_plan_graph(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("linked stale worktree", repo_path=tmp_path, status="running")
    worktree = tmp_path / "worktree"
    profile = {
        "task_id": task.task_id,
        "worktree_path": str(worktree),
        "branch": "codex/linked",
        "base_ref": "main",
        "dirty": False,
        "cleanup_eligible": False,
    }
    store.append_task_event(
        task.task_id,
        "worktree.execution_profile",
        {"profile": profile, "sandbox": {"root": str(worktree)}},
        actor="supervisor",
    )
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=7,
        section="v0.7",
        text="Run linked worktree task",
        status="in_progress",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    graph = store.create_plan_graph(task_id=task.task_id, title="Linked graph")
    node = store.add_plan_graph_node(
        graph_id=graph.graph_id,
        node_key="root",
        title="Root",
        task_text="Run linked worktree task",
        status="in_progress",
        task_id=task.task_id,
        plan_item_id=item.plan_item_id,
    )
    store.link_plan_item_to_plan_graph(
        item.plan_item_id,
        graph.graph_id,
        plan_graph_root_node_id=node.node_id,
    )
    old_timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (old_timestamp, task.task_id),
        )

    text_exit = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--worktree-stale-minutes",
            "1",
        ]
    )
    text_output = capsys.readouterr().out
    json_exit = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--worktree-stale-minutes",
            "1",
            "--json",
        ]
    )
    json_output = capsys.readouterr().out
    payload = json.loads(json_output)
    linked = payload["worktree_recovery_candidates"]["items"][0]

    assert text_exit == 0
    assert json_exit == 0
    assert (
        f"[worktree_recovery] {task.task_id}: inspect_branch operator=resume "
        f"queue_item={item.plan_item_id} node={node.node_id} "
        f"next=inspect_task_timeline"
    ) in text_output
    assert linked["operator_recommendation"] == "resume"
    assert linked["queue_item"]["plan_item_id"] == item.plan_item_id
    assert linked["queue_item"]["status"] == "in_progress"
    assert linked["queue_item"]["selected_worktree_path"] == str(worktree)
    assert linked["plan_graph_node"]["node_id"] == node.node_id
    assert linked["plan_graph_node"]["status"] == "in_progress"
    assert linked["action_plan"]["commands"][0]["name"] == "inspect_task_timeline"
    assert linked["action_plan"]["commands"][1]["name"] == "inspect_worktree"
    assert linked["action_plan"]["commands"][2]["name"] == "resume_task"
    assert linked["action_plan"]["commands"][2]["argv"] == [
        "python",
        "-m",
        "ai_orchestrator.cli.app",
        "resume",
        task.task_id,
        "--repo",
        str(tmp_path),
    ]


def test_recover_apply_recommendation_requeue_dry_run(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("blocked linked worktree", repo_path=tmp_path, status="running")
    worktree = tmp_path / "worktree"
    store.append_task_event(
        task.task_id,
        "worktree.execution_profile",
        {
            "profile": {
                "task_id": task.task_id,
                "worktree_path": str(worktree),
                "branch": "codex/requeue",
                "base_ref": "main",
                "dirty": False,
                "cleanup_eligible": False,
            }
        },
        actor="supervisor",
    )
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=9,
        section="v0.7",
        text="Requeue linked worktree task",
        status="blocked",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    old_timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (old_timestamp, task.task_id),
        )

    exit_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--worktree-stale-minutes",
            "1",
            "--apply-recommendation",
            "requeue",
            "--task-id",
            task.task_id,
        ]
    )
    output = capsys.readouterr().out
    loaded_task = store.get_task(task.task_id)
    loaded_item = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "Recovery recommendation dry run" in output
    assert "recommendation: requeue" in output
    assert f"plan_item_id: {item.plan_item_id}" in output
    assert loaded_task is not None
    assert loaded_task.status == "running"
    assert loaded_item is not None
    assert loaded_item.status == "blocked"
    assert loaded_item.task_id == task.task_id


def test_recover_apply_recommendation_requeue_apply_json(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("apply requeue worktree", repo_path=tmp_path, status="running")
    worktree = tmp_path / "worktree"
    store.append_task_event(
        task.task_id,
        "worktree.execution_profile",
        {
            "profile": {
                "task_id": task.task_id,
                "worktree_path": str(worktree),
                "branch": "codex/requeue",
                "base_ref": "main",
                "dirty": False,
                "cleanup_eligible": False,
            }
        },
        actor="supervisor",
    )
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=10,
        section="v0.7",
        text="Apply requeue linked worktree task",
        status="blocked",
        task_id=task.task_id,
        selected_worktree_path=worktree,
        blocked_reason="stale worktree execution",
    )
    old_timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (old_timestamp, task.task_id),
        )

    exit_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--worktree-stale-minutes",
            "1",
            "--apply-recommendation",
            "requeue",
            "--task-id",
            task.task_id,
            "--apply",
            "--reason",
            "operator accepted requeue recommendation",
            "--json",
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    loaded_task = store.get_task(task.task_id)
    loaded_item = store.get_plan_item(item.plan_item_id)
    events = store.list_task_events(task.task_id)
    applied_events = [
        event for event in events if event.event_type == "worktree.recovery_applied"
    ]

    assert exit_code == 0
    assert payload["apply"] is True
    assert payload["recommendation"] == "requeue"
    assert payload["plan_item_id"] == item.plan_item_id
    assert payload["queue_item"]["status"] == "created"
    assert loaded_task is not None
    assert loaded_task.status == "blocked"
    assert loaded_item is not None
    assert loaded_item.status == "created"
    assert loaded_item.task_id is None
    assert loaded_item.selected_worktree_path is None
    assert loaded_item.blocked_reason is None
    assert len(applied_events) == 1
    assert applied_events[0].payload["recommendation"] == "requeue"
    assert applied_events[0].payload["reason"] == "operator accepted requeue recommendation"


def test_recover_reports_and_applies_stale_started_actions_without_lease(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("stale action task", repo_path=tmp_path)
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="recover-stale-action",
        action_type="process.approval_retry",
    )
    old_timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE action_records SET updated_at = ? WHERE action_id = ?",
            (old_timestamp, action.action_id),
        )

    dry_run_code = main(["recover", "--repo", str(tmp_path)])
    dry_run_output = capsys.readouterr().out

    assert dry_run_code == 0
    assert "expired_action_leases: 0" in dry_run_output
    assert "stale_started_actions: 1" in dry_run_output
    assert f"[stale_action] {action.action_id}: process.approval_retry" in dry_run_output
    assert store.get_action_record(action.action_id).status == "started"  # type: ignore[union-attr]

    apply_code = main(
        [
            "recover",
            "--repo",
            str(tmp_path),
            "--apply",
            "--reason",
            "operator recovered stale action",
        ]
    )
    apply_output = capsys.readouterr().out
    recovered_action = store.get_action_record(action.action_id)

    assert apply_code == 0
    assert "failed_actions: 1" in apply_output
    assert recovered_action is not None
    assert recovered_action.status == "failed"
    assert recovered_action.result["recovered"] is True
    assert recovered_action.result["reason"] == "operator recovered stale action"


def test_timeline_prints_replay_read_model(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("timeline task", repo_path=tmp_path)
    store.append_task_event(task.task_id, "task.recovered", {"reason": "test"})

    exit_code = main(["timeline", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Timeline: {task.task_id}" in output
    assert "entries: 2" in output
    assert "task.created status=created" in output
    assert "task.recovered" in output


def test_timeline_json_prints_replay_read_model(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("timeline json task", repo_path=tmp_path)
    store.append_task_event(task.task_id, "task.recovered", {"reason": "test"})

    exit_code = main(["timeline", task.task_id, "--repo", str(tmp_path), "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert set(payload) == {"task", "timeline"}
    assert payload["task"]["task_id"] == task.task_id
    assert payload["task"]["status"] == "created"
    assert payload["timeline"][0]["timeline_index"] == 1
    assert payload["timeline"][0]["source"] == "task"
    assert [entry["event_type"] for entry in payload["timeline"]] == [
        "task.created",
        "task.recovered",
    ]
    assert payload["timeline"][1]["payload"] == {
        "sequence": 1,
        "payload": {"reason": "test"},
        "run_id": store.run_id_for_task(task.task_id),
    }


def test_timeline_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["timeline", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_timeline_json_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["timeline", "missing-task", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["command"] == "timeline"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "task_not_found"
    assert payload["error"]["task_id"] == "missing-task"


def test_export_writes_json_trace_file(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo export", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo export",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.append_task_event(
        task.task_id,
        "task.created",
        {"source": "export-test"},
    )
    store.record_action(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="export-action-1",
        action_type="verification_command",
        status="succeeded",
        command_string="python -m pytest",
        payload={"name": "unit"},
        result={"exit_code": 0},
    )
    broker = ToolBroker(store, PolicyEngine())
    broker_call = make_process_tool_call(
        "process.read",
        "read",
        argv=["python", "-m", "pytest"],
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="export-action-brokered",
    )
    broker.run(
        broker_call,
        lambda _call: {"stdout": "broker ok", "stderr": "", "exit_code": 0},
    )
    leased_action = store.record_action(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="export-action-lease",
        action_type="tool_call",
    )
    store.acquire_action_lease(
        leased_action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )
    store.record_replan_decision(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        status="continue",
        reason="Verification failed: unit",
        follow_up_prompt="Fix unit",
        failed_checks=[
            {
                "name": "unit",
                "status": "failed",
                "exit_code": 1,
                "output_excerpt": "assertion failed",
            }
        ],
    )
    lesson = store.record_memory_lesson(
        source_task_id=task.task_id,
        source_iteration_id=iteration.iteration_id,
        lesson="Retry unit after fixing assertion",
        outcome_status="blocked",
        failure_reason="Verification failed: unit",
        failed_checks=[{"name": "unit", "status": "failed"}],
        follow_up_prompt="Fix unit",
    )
    store.add_reflection_record(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        reflection_type="failed_verification",
        failure_reason="Verification failed: unit",
        failed_checks=[{"name": "unit", "status": "failed"}],
        follow_up_prompt="Fix unit",
    )
    store.record_memory_influence(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        lesson_id=lesson.lesson_id,
        reason="selected for planning",
    )
    graph = store.create_plan_graph("Export graph")
    graph_node = store.add_plan_graph_node(
        graph.graph_id,
        "export-node",
        "Export node",
        status="done",
        task_text="Export a PlanGraph-aware trace",
        acceptance_criteria=["trace includes graph snapshot"],
        verification_requirement="python -m pytest tests/test_cli.py",
        task_id=task.task_id,
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push",
        reason="approval required",
    )
    store.resolve_approval_request(approval.approval_id, status="approved")
    store.update_task_status(task.task_id, "done")

    exit_code = main(["export", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    trace_path = tmp_path / ".ai-orch" / "traces" / f"{task.task_id}.json"

    assert exit_code == 0
    assert f"Trace: {trace_path}" in output
    assert trace_path.exists()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert set(trace) == {
        "metadata",
        "task",
        "timeline",
        "task_events",
        "action_records",
        "action_journal",
        "replan_decisions",
        "plan_graph",
        "memory_lessons",
        "reflection_records",
        "memory_influence",
        "iterations",
        "verification_runs",
        "approvals",
    }
    assert trace["metadata"]["schema_version"] == "1.2"
    assert trace["metadata"]["task_id"] == task.task_id
    assert trace["metadata"]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["metadata"]["unsafe_action_count"] == 0
    assert trace["metadata"]["redaction_mode"] == "none"
    assert "exported_at" in trace["metadata"]
    exported_at = datetime.fromisoformat(trace["metadata"]["exported_at"])
    assert exported_at.tzinfo is not None
    assert trace["task"]["task_id"] == task.task_id
    assert trace["task"]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["task"]["status"] == "done"
    assert len(trace["timeline"]) >= 1
    assert all(entry["run_id"] == store.run_id_for_task(task.task_id) for entry in trace["timeline"])
    assert any(entry["event_type"] == "task.created" for entry in trace["timeline"])
    assert any(entry["event_type"] == "replan.decision" for entry in trace["timeline"])
    assert any(entry["event_type"] == "reflection.failed_verification" for entry in trace["timeline"])
    assert any(entry["event_type"] == "memory.influence" for entry in trace["timeline"])
    assert len(trace["task_events"]) == 4
    assert trace["task_events"][0]["sequence"] == 1
    assert trace["task_events"][0]["event_type"] == "task.created"
    assert trace["task_events"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["task_events"][0]["payload"] == {"source": "export-test"}
    assert [event["event_type"] for event in trace["task_events"][1:]] == [
        "command_approved",
        "command_started",
        "command_finished",
    ]
    assert len(trace["action_records"]) == 3
    assert trace["action_records"][0]["idempotency_key"] == "export-action-1"
    assert trace["action_records"][0]["action_type"] == "verification_command"
    assert trace["action_records"][0]["status"] == "succeeded"
    assert trace["action_records"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["action_records"][0]["result"] == {"exit_code": 0}
    assert trace["action_records"][1]["idempotency_key"] == "export-action-brokered"
    assert trace["action_records"][1]["payload"]["action_request"]["risk"] == {
        "action_type": "shell",
        "risk_tier": "read",
        "requires_approval": False,
        "reasons": [],
    }
    assert trace["action_records"][2]["idempotency_key"] == "export-action-lease"
    assert trace["action_records"][2]["lease_owner"] == "worker-1"
    assert trace["action_records"][2]["lease_expires_at"] == "2026-01-01T00:00:30+00:00"
    assert trace["action_records"][2]["heartbeat_at"] == "2026-01-01T00:00:00+00:00"
    assert len(trace["action_journal"]) == 3
    assert trace["action_journal"][0]["requested_action"] is None
    assert trace["action_journal"][1]["requested_action"] == "process.read"
    assert trace["action_journal"][1]["category"] == "shell"
    assert trace["action_journal"][1]["risk_tier"] == "read"
    assert trace["action_journal"][1]["policy_action"] == "allow"
    assert trace["action_journal"][1]["decision"]["action"] == "allow"
    assert trace["action_journal"][1]["output_preview"] == {
        "stdout": "broker ok",
        "stderr": "",
        "exit_code": 0,
    }
    assert trace["action_journal"][1]["provenance"]["task_id"] == task.task_id
    assert trace["action_journal"][2]["lease"]["owner"] == "worker-1"
    assert len(trace["replan_decisions"]) == 1
    assert trace["replan_decisions"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["replan_decisions"][0]["status"] == "continue"
    assert trace["replan_decisions"][0]["failed_checks"][0]["name"] == "unit"
    assert trace["plan_graph"]["graph"]["graph_id"] == graph.graph_id
    assert trace["plan_graph"]["context_node"]["node_id"] == graph_node.node_id
    assert trace["plan_graph"]["context_node"]["task_text"] == (
        "Export a PlanGraph-aware trace"
    )
    assert trace["plan_graph"]["context_node"]["acceptance_criteria"] == [
        "trace includes graph snapshot"
    ]
    assert trace["plan_graph"]["readiness"][0]["reason"] == "node_status_done"
    assert trace["memory_lessons"][0]["lesson"] == "Retry unit after fixing assertion"
    assert trace["memory_lessons"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["reflection_records"][0]["reflection_type"] == "failed_verification"
    assert trace["reflection_records"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["memory_influence"][0]["lesson_id"] == lesson.lesson_id
    assert trace["memory_influence"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert len(trace["iterations"]) == 1
    assert trace["iterations"][0]["prompt"] == "demo export"
    assert trace["iterations"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["iterations"][0]["decision_status"] == "done"
    assert len(trace["verification_runs"]) == 1
    assert trace["verification_runs"][0]["name"] == "unit"
    assert trace["verification_runs"][0]["status"] == "passed"
    assert trace["verification_runs"][0]["run_id"] == store.run_id_for_task(task.task_id)
    assert trace["verification_runs"][0]["stdout"] == "ok"
    assert len(trace["approvals"]) == 1
    assert trace["approvals"][0]["status"] == "approved"
    assert trace["approvals"][0]["run_id"] == store.run_id_for_task(task.task_id)


def test_export_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["export", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_export_writes_to_custom_output_path(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("custom export", repo_path=tmp_path)
    store.update_task_status(task.task_id, "blocked")

    custom_path = tmp_path / "trace.json"
    exit_code = main(
        ["export", task.task_id, "--repo", str(tmp_path), "--output", str(custom_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Trace: {custom_path}" in output
    assert custom_path.exists()

    trace = json.loads(custom_path.read_text(encoding="utf-8"))
    assert trace["task"]["task_id"] == task.task_id
    assert trace["task"]["status"] == "blocked"


def test_export_redact_flag_omits_bulky_fields(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("redacted export", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo redact",
        raw_output="bulky raw output",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="bulky stdout",
            stderr="bulky stderr",
        ),
    )
    store.update_task_status(task.task_id, "done")

    exit_code = main(["export", task.task_id, "--repo", str(tmp_path), "--redact"])
    output = capsys.readouterr().out
    trace_path = tmp_path / ".ai-orch" / "traces" / f"{task.task_id}.json"

    assert exit_code == 0
    assert f"Trace: {trace_path}" in output
    assert trace_path.exists()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["metadata"]["redaction_mode"] == "redacted"
    assert trace["iterations"][0]["prompt"] == "demo redact"
    assert "raw_output" not in trace["iterations"][0]
    assert trace["verification_runs"][0]["name"] == "unit"
    assert trace["verification_runs"][0]["status"] == "passed"
    assert "stdout" not in trace["verification_runs"][0]
    assert "stderr" not in trace["verification_runs"][0]

    loaded_iteration = store.list_iteration_details(task.task_id)[0]
    assert loaded_iteration.raw_output == "bulky raw output"
    loaded_run = store.list_verification_details(task.task_id)[0]
    assert loaded_run.stdout == "bulky stdout"
    assert loaded_run.stderr == "bulky stderr"


def test_export_without_redact_keeps_bulky_fields(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("full export", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo full",
        raw_output="raw agent output",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="verification stdout",
            stderr="verification stderr",
        ),
    )

    exit_code = main(["export", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    trace_path = tmp_path / ".ai-orch" / "traces" / f"{task.task_id}.json"

    assert exit_code == 0
    assert f"Trace: {trace_path}" in output
    assert trace_path.exists()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["iterations"][0]["raw_output"] == "raw agent output"
    assert trace["verification_runs"][0]["stdout"] == "verification stdout"
    assert trace["verification_runs"][0]["stderr"] == "verification stderr"


def test_agents_lists_project_config(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        fallback_agents=["mock"],
        include_generic_agent=True,
    )

    exit_code = main(["agents", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "default: generic" in output
    assert "fallbacks: mock" in output
    assert "generic: enabled type=generic_cli" in output


def test_setup_writes_beginner_config_without_secrets(
    capsys,
    tmp_path: Path,
) -> None:
    exit_code = main(["setup", "--repo", str(tmp_path), "--agent", "mock"])
    output = capsys.readouterr().out
    config_path = tmp_path / ".ai-orch" / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert "Wrote:" in output
    assert 'default_agent: "mock"' in config_text
    assert 'command: "codex"' in config_text
    assert "OPENAI_API_KEY" not in config_text
    assert (tmp_path / ".ai-orch" / "state").is_dir()
    assert (tmp_path / ".ai-orch" / "reports").is_dir()


def test_setup_auto_selects_detected_agent(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_which(command: str) -> str | None:
        if command == "claude":
            return "/usr/bin/claude"
        return None

    monkeypatch.setattr("ai_orchestrator.cli.app.shutil.which", fake_which)

    exit_code = main(["setup", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    config_text = (tmp_path / ".ai-orch" / "config.yaml").read_text(encoding="utf-8")

    assert exit_code == 0
    assert payload["default_agent"] == "claude"
    assert payload["detected_agents"]["claude"] == "/usr/bin/claude"
    assert 'default_agent: "claude"' in config_text
    assert 'command: "claude"' in config_text


def test_setup_codex_safe_profile_prefers_codex_when_detected(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_which(command: str) -> str | None:
        if command == "codex":
            return "/usr/bin/codex"
        return None

    monkeypatch.setattr("ai_orchestrator.cli.app.shutil.which", fake_which)

    exit_code = main(
        ["setup", "--repo", str(tmp_path), "--profile", "codex-safe", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    config_text = (tmp_path / ".ai-orch" / "config.yaml").read_text(encoding="utf-8")

    assert exit_code == 0
    assert payload["profile"] == "codex-safe"
    assert payload["default_agent"] == "codex"
    assert payload["readiness"]["mode"] == "real worker"
    assert payload["readiness"]["real_worker_ready"] == "yes"
    assert 'setup_profile: "codex-safe"' in config_text
    assert 'default_agent: "codex"' in config_text


def test_setup_docs_profile_writes_docs_verification(
    capsys,
    tmp_path: Path,
) -> None:
    exit_code = main(
        [
            "setup",
            "--repo",
            str(tmp_path),
            "--agent",
            "mock",
            "--profile",
            "docs-project",
        ]
    )
    output = capsys.readouterr().out
    config_text = (tmp_path / ".ai-orch" / "config.yaml").read_text(encoding="utf-8")

    assert exit_code == 0
    assert "profile: docs-project" in output
    assert 'setup_profile: "docs-project"' in config_text
    assert 'name: "readme-has-heading"' in config_text
    assert "OPENAI_API_KEY" not in config_text


def test_setup_refuses_to_overwrite_existing_config(
    capsys,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    config_path.write_text("existing: true\n", encoding="utf-8")

    exit_code = main(["setup", "--repo", str(tmp_path), "--agent", "mock"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Config already exists" in output
    assert config_path.read_text(encoding="utf-8") == "existing: true\n"


def test_doctor_reports_ready_setup(
    capsys,
    tmp_path: Path,
) -> None:
    assert main(["setup", "--repo", str(tmp_path), "--agent", "mock"]) == 0
    capsys.readouterr()

    exit_code = main(["doctor", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["config_exists"] is True
    assert payload["default_agent"] == "mock"
    assert payload["default_agent_available"] == "yes"
    assert payload["readiness"]["mode"] == "mock demo"
    assert payload["readiness"]["mock_demo_mode"] == "yes"
    assert payload["issues"] == []


def test_doctor_reports_missing_config(
    capsys,
    tmp_path: Path,
) -> None:
    exit_code = main(["doctor", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "missing_config" in output
    assert "Suggested fix: run ai-orch setup --repo ." in output


def test_doctor_agents_reports_connector_matrix(
    capsys,
    tmp_path: Path,
) -> None:
    assert main(["setup", "--repo", str(tmp_path), "--agent", "mock"]) == 0
    capsys.readouterr()

    exit_code = main(["doctor", "agents", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    connectors = {item["name"]: item for item in payload["connectors"]}

    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["api_adapters"]["status"] == "not_implemented"
    assert connectors["mock"]["availability"] == "yes"
    assert connectors["mock"]["api_status"] == "not_applicable"
    assert connectors["codex"]["api_status"].startswith("not_implemented")
    assert connectors["codex"]["auth_model"] == (
        "native CLI login or CLI-managed provider credentials"
    )
    assert connectors["codex"]["next_step"]
    assert payload["readiness"]["selected_worker"] == "mock"


def test_demo_runs_docs_only_first_value_path(capsys, tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
orchestrator:
  default_agent: "mock"
  max_iterations: 2

agents:
  mock:
    enabled: true
    type: "mock"

verification:
  strict: true
  commands:
    - name: "readme-has-heading"
      argv:
        - "python"
        - "-c"
        - "import re, sys; txt = open('README.md', encoding='utf-8').read(); sys.exit(0 if re.search(r'^# ', txt, re.MULTILINE) else 1)"
      timeout_sec: 30
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["demo", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== ai-orch demo ===" in output
    assert "Demo summary:" in output
    assert "- result: done" in output
    assert "Run summary:" in output
    assert "verification: passed" in output
    assert "Next real-worker path:" in output
    assert list((tmp_path / ".ai-orch" / "reports").glob("task-*.md"))


def test_onboard_reports_missing_config_with_next_steps(
    capsys,
    tmp_path: Path,
) -> None:
    exit_code = main(["onboard", "--repo", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["config_exists"] is False
    assert payload["ready"] is False
    assert payload["recommended_steps"][0].startswith("Run: ai-orch setup")
    assert any(item["name"] == "Fix a bug" for item in payload["scenarios"])


def test_onboard_reports_ready_mock_demo_mode(
    capsys,
    tmp_path: Path,
) -> None:
    assert main(["setup", "--repo", str(tmp_path), "--agent", "mock"]) == 0
    capsys.readouterr()

    exit_code = main(["onboard", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== ai-orch onboard ===" in output
    assert "Recommended path:" in output
    assert "ai-orch demo" in output
    assert "Scenarios:" in output
    assert "ai-orch fix" in output


def test_product_fix_command_uses_role_template_and_writes_report(
    capsys,
    tmp_path: Path,
) -> None:
    write_config(tmp_path)

    exit_code = main(
        [
            "fix",
            "--repo",
            str(tmp_path),
            "--task",
            "Fix the payment bug",
        ]
    )
    output = capsys.readouterr().out
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    tasks = store.list_tasks()

    assert exit_code == 0
    assert "action: fix" in output
    assert "Run summary:" in output
    assert "report:" in output
    assert tasks
    assert "Role: Bug fixer." in tasks[0].task
    assert "Fix the payment bug" in tasks[0].task
    assert list((tmp_path / ".ai-orch" / "reports").glob("task-*.md"))


def test_product_command_requires_setup_for_real_project(
    capsys,
    tmp_path: Path,
) -> None:
    exit_code = main(["review", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Config not found" in output
    assert "Next command: ai-orch setup --repo ." in output
    assert "ai-orch demo" in output


def test_doctor_agents_reports_unavailable_default_agent(
    capsys,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
orchestrator:
  default_agent: "codex"

agents:
  codex:
    enabled: true
    type: "codex_exec"
    command: "missing-codex-test-binary"
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["doctor", "agents", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "codex" in output
    assert "available=no" in output
    assert "default_agent_unavailable" in output


def test_agents_lists_adapter_profile(capsys, tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
orchestrator:
  default_agent: "generic"

adapter_profiles:
  python-profile:
    type: "generic_cli"
    command: "python"

agents:
  generic:
    enabled: true
    profile: "python-profile"
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["agents", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "generic: enabled type=generic_cli profile=python-profile" in output


def test_agents_check_reports_availability(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
    )

    exit_code = main(["agents", "--repo", str(tmp_path), "--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "mock: enabled type=mock available=yes" in output
    assert "generic: enabled type=generic_cli available=yes" in output


def test_agents_check_reports_missing_binary(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="missing-ai-orch-agent-binary",
    )

    exit_code = main(["agents", "--repo", str(tmp_path), "--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "generic: enabled type=generic_cli available=no" in output


@pytest.mark.parametrize(
    ("agent_name", "agent_type", "expected_command"),
    [
        ("kimi", "kimi", "kimi"),
        ("kimi", "kimi_cli", "kimi"),
        ("gemini", "gemini", "gemini"),
        ("gemini", "gemini_cli", "gemini"),
    ],
)
def test_agents_check_uses_cli_alias_default_command(
    capsys,
    monkeypatch,
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
    expected_command: str,
) -> None:
    checked_commands: list[str] = []

    def fake_check_available(self: ProcessRunner, command: str) -> bool:
        checked_commands.append(command)
        return command == expected_command

    monkeypatch.setattr(ProcessRunner, "check_available", fake_check_available)
    write_config(
        tmp_path,
        default_agent=agent_name,
        cli_alias_agents={agent_name: agent_type},
        cli_alias_commands={agent_name: None},
    )

    exit_code = main(["agents", "--repo", str(tmp_path), "--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"{agent_name}: enabled type={agent_type} available=yes" in output
    assert checked_commands == [expected_command]


def test_resume_runs_existing_task_and_appends_iteration(capsys, tmp_path: Path) -> None:
    write_config(tmp_path)
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    store.update_task_status(task.task_id, "blocked")

    exit_code = main(["resume", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    loaded = store.get_task(task.task_id)
    iterations = store.list_iterations(task.task_id)

    assert exit_code == 0
    assert "=== ai-orch run ===" in output
    assert "action: resume" in output
    assert f"task_id: {task.task_id}" in output
    assert "status: running" in output
    assert "progress: iteration 1: agent mock started" in output
    assert f"{task.task_id}: Iteration 1: Verification passed: custom" in output
    assert f"ai-orch status {task.task_id} --repo {tmp_path}" in output
    assert loaded is not None
    assert loaded.status == "done"
    assert len(iterations) == 1
    assert iterations[0].decision_status == "done"


def test_resume_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["resume", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_verify_uses_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path)

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "custom: passed exit=0" in output


def test_verify_strict_mode_fails_without_commands(capsys, tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
verification:
  strict: true
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "No verification commands configured." in output


def test_release_check_reports_packaging_status(capsys) -> None:
    exit_code = main(["release-check", "--repo", "."])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "pyproject: passed" in output
    assert "version: passed" in output
    assert "entrypoints: passed" in output
    assert "release-docs: passed" in output
    assert all(item.status == "passed" for item in run_release_checks(Path(".")))


def test_ci_runs_verification_and_release_checks(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    write_config(tmp_path)
    monkeypatch.setattr(
        "ai_orchestrator.cli.app.run_release_checks",
        lambda repo: [
            ReleaseCheckResult(name="pyproject", status="passed", detail="ok"),
            ReleaseCheckResult(name="version", status="passed", detail="ok"),
        ],
    )

    exit_code = main(["ci", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "verification:" in output
    assert "custom: passed exit=0" in output
    assert "release:" in output
    assert "pyproject: passed" in output
    assert "version: passed" in output


def test_ci_fails_when_verification_fails(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, command_run="python -c 'import sys; sys.exit(1)'")

    exit_code = main(["ci", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "custom: failed exit=1" in output
    assert "release:" in output


def test_ci_fails_when_release_check_fails(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    write_config(tmp_path)
    monkeypatch.setattr(
        "ai_orchestrator.cli.app.run_release_checks",
        lambda repo: [
            ReleaseCheckResult(
                name="release-docs",
                status="failed",
                detail="Missing docs: CHANGELOG.md",
            ),
        ],
    )

    exit_code = main(["ci", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "custom: passed exit=0" in output
    assert "release-docs: failed" in output


def test_ci_approves_exact_verification_command(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    command = "python -c \"print('approval-token ok')\""
    write_config(
        tmp_path,
        command_name="approval",
        command_run=command,
        require_approval_patterns=["approval-token"],
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app.run_release_checks",
        lambda repo: [
            ReleaseCheckResult(name="pyproject", status="passed", detail="ok"),
        ],
    )

    exit_code = main(
        [
            "ci",
            "--repo",
            str(tmp_path),
            "--approve-command",
            command,
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "approval: passed exit=0" in output
    assert "release:" in output


def test_start_uses_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path)

    exit_code = main(["start", "--task", "demo", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    task_id = task_id_from_run_output(output)
    assert "=== ai-orch run ===" in output
    assert "action: start" in output
    assert "status: running" in output
    assert "note: mock agent is smoke-test mode" in output
    assert "progress: iteration 1: agent mock started" in output
    assert f"ai-orch status {task_id} --repo {tmp_path}" in output
    assert "Verification passed: custom" in output


def test_start_strict_mode_blocks_without_verification_commands(
    capsys,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
verification:
  strict: true
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["start", "--task", "demo", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = task_id_from_run_output(output)
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.get_task(task_id)

    assert exit_code == 1
    assert "No verification commands configured" in output
    assert task is not None
    assert task.status == "blocked"


def test_start_with_use_memory_enriches_initial_prompt(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    memory_argv: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        if argv[:2] == ["codebase-memory-mcp", "cli"]:
            memory_argv.append(argv)
            return ProcessResult(
                status="success",
                exit_code=0,
                stdout=f"memory output for {argv[2]}",
                stderr="",
            )
        return ProcessResult(status="success", exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(
        [
            "start",
            "--task",
            "demo",
            "--repo",
            str(tmp_path),
            "--use-memory",
            "--memory-area",
            "release",
        ]
    )
    output = capsys.readouterr().out
    task_id = task_id_from_run_output(output)
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.get_task(task_id)
    iterations = store.list_iteration_details(task_id)

    assert exit_code == 0
    assert task is not None
    assert task.task == "demo"
    assert "Planning context (read-only, non-authoritative)" in iterations[0].prompt
    assert "memory preflight area=release" in iterations[0].prompt
    assert "memory output for get_architecture" in iterations[0].prompt
    assert "memory output for detect_changes" in iterations[0].prompt
    assert [item[2] for item in memory_argv] == ["get_architecture", "detect_changes"]


def test_start_uses_generic_agent_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, default_agent="generic", include_generic_agent=True)

    exit_code = main(["start", "--task", "hello generic", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = task_id_from_run_output(output)
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "generic"


def test_start_uses_codex_agent_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, default_agent="codex", include_codex_agent=True)

    exit_code = main(["start", "--task", "hello codex", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = task_id_from_run_output(output)
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "codex"


def test_start_uses_claude_agent_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, default_agent="claude", include_claude_agent=True)

    exit_code = main(["start", "--task", "hello claude", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = task_id_from_run_output(output)
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "claude"


@pytest.mark.parametrize(
    ("agent_name", "agent_type"),
    [
        ("kimi", "kimi_cli"),
        ("gemini", "gemini_cli"),
    ],
)
def test_start_uses_cli_alias_agent_from_project_config(
    capsys,
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
) -> None:
    write_config(
        tmp_path,
        default_agent=agent_name,
        cli_alias_agents={agent_name: agent_type},
    )

    exit_code = main(["start", "--task", f"hello {agent_name}", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = task_id_from_run_output(output)
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == agent_name


@pytest.mark.parametrize(
    ("agent_name", "agent_type", "expected_argv"),
    [
        ("kimi", "kimi_cli", ["kimi", "hello kimi"]),
        ("gemini", "gemini_cli", ["gemini", "-p", "hello gemini"]),
    ],
)
def test_start_uses_cli_alias_default_argv(
    capsys,
    monkeypatch,
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
    expected_argv: list[str],
) -> None:
    captured_argv: list[list[str]] = []

    def fake_check_available(self: ProcessRunner, command: str) -> bool:
        return command == expected_argv[0]

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout=f"{agent_name} ok",
            stderr="",
        )

    def fake_run_many(self: VerificationRunner, commands, cwd=None):
        return [
            VerificationResult(
                name="custom",
                status="passed",
                exit_code=0,
                stdout="",
                stderr="",
            )
        ]

    monkeypatch.setattr(ProcessRunner, "check_available", fake_check_available)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    monkeypatch.setattr(VerificationRunner, "run_many", fake_run_many)
    write_config(
        tmp_path,
        default_agent=agent_name,
        cli_alias_agents={agent_name: agent_type},
        cli_alias_commands={agent_name: None},
        cli_alias_args={agent_name: None},
    )

    exit_code = main(["start", "--task", f"hello {agent_name}", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert captured_argv == [expected_argv]


def test_start_uses_fallback_agent_when_default_unavailable(
    capsys,
    tmp_path: Path,
) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        fallback_agents=["mock"],
        include_generic_agent=True,
        generic_command="missing-ai-orch-agent-binary",
    )

    exit_code = main(["start", "--task", "hello fallback", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = task_id_from_run_output(output)
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "mock"


def test_start_uses_opt_in_worktree_isolation(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_config(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    captured_repos: list[Path] = []

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        assert repo == tmp_path
        assert candidate == worktree.resolve()
        return None

    def fake_run_once(
        self, task: str, repo: Path, planning_context=None
    ) -> SupervisorResult:
        captured_repos.append(repo)
        return SupervisorResult(
            status="done", summary="Verification passed: custom", task_id="task-1"
        )

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate
    )
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "start",
            "--task",
            "demo",
            "--repo",
            str(tmp_path),
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "task-1: Verification passed: custom" in output
    assert captured_repos == [worktree.resolve()]


def test_start_blocks_invalid_worktree_before_execution(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_config(tmp_path)
    worktree = tmp_path / "not-worktree"

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        return f"worktree path does not exist: {candidate}"

    def fake_run_once(
        self, task: str, repo: Path, planning_context=None
    ) -> SupervisorResult:
        raise AssertionError("supervisor should not start with an invalid worktree")

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate
    )
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "start",
            "--task",
            "demo",
            "--repo",
            str(tmp_path),
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: worktree path does not exist:" in output


def test_start_blocks_generic_agent_command_from_project_policy(
    capsys,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "generic-ran.txt"
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_args=[
            "-c",
            (
                "import pathlib, sys; "
                "pathlib.Path(sys.argv[1]).joinpath('generic-ran.txt').write_text('ran')"
            ),
            "{repo}",
        ],
        deny_patterns=["write_text"],
    )

    exit_code = main(["start", "--task", "dangerous generic", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Denied by pattern: write_text" in output
    assert not marker.exists()


def test_verify_blocks_command_that_requires_approval(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        command_name="push",
        command_run="git push origin main",
    )

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "push: needs_approval exit=None" in output


def test_verify_uses_policy_rules_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        command_name="deploy",
        command_run="deploy production",
        require_approval_patterns=["deploy"],
    )

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "deploy: needs_approval exit=None" in output


def test_verify_policy_denied_does_not_block_ci_exit_code(
    capsys,
    tmp_path: Path,
) -> None:
    write_config(
        tmp_path,
        command_name="blocked",
        command_run="rm -rf build",
        deny_patterns=["rm"],
    )

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "blocked: policy_denied exit=None" in output


def test_verify_approves_exact_command_from_cli(capsys, tmp_path: Path) -> None:
    command = "python -c \"print('approval-token ok')\""
    write_config(
        tmp_path,
        command_name="approval",
        command_run=command,
        require_approval_patterns=["approval-token"],
    )

    exit_code = main(
        [
            "verify",
            "--repo",
            str(tmp_path),
            "--approve-command",
            command,
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "approval: passed exit=0" in output


def test_memory_status_prints_provider_config(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(["memory", "status", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "provider: codebase-memory-mcp" in output
    assert "command: codebase-memory-mcp cli" in output
    assert "project: demo" in output
    assert "available: yes" in output


def test_memory_lessons_lists_active_lessons(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("seed", repo_path=tmp_path)
    store.record_memory_lesson(
        source_task_id=task.task_id,
        lesson="Inspect failed checks first",
        outcome_status="blocked",
    )

    exit_code = main(["memory", "lessons", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Memory lessons" in output
    assert "Inspect failed checks first" in output


def test_memory_influence_lists_task_influence(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    seed = store.create_task("seed", repo_path=tmp_path)
    task = store.create_task("run", repo_path=tmp_path)
    lesson = store.record_memory_lesson(
        source_task_id=seed.task_id,
        lesson="Avoid unsafe retry",
        outcome_status="blocked",
    )
    store.record_memory_influence(
        task_id=task.task_id,
        lesson_id=lesson.lesson_id,
        reason="selected for planning",
    )

    exit_code = main(
        [
            "memory",
            "influence",
            "--repo",
            str(tmp_path),
            "--task-id",
            task.task_id,
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Memory influence" in output
    assert f"task={task.task_id}" in output
    assert "selected for planning" in output


def test_memory_search_runs_read_only_tool(capsys, monkeypatch, tmp_path: Path) -> None:
    captured_argv: list[list[str]] = []

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        terminate_grace_sec: int = 5,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout='{"results":[]}',
            stderr="",
        )

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(
        [
            "memory",
            "search",
            "--repo",
            str(tmp_path),
            "--pattern",
            ".*Supervisor.*",
            "--label",
            "Class",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "search_graph: passed exit=0" in output
    assert captured_argv == [
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"label": "Class", "limit": 20, "name_pattern": ".*Supervisor.*", "project": "demo"}',
        ]
    ]


def test_memory_index_requires_explicit_approval(capsys, monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        calls.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="indexed", stderr="")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True)

    exit_code = main(["memory", "index", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    approvals = StateStore(
        tmp_path / ".ai-orch" / "state" / "ai-orch.db"
    ).list_approval_requests(status="pending")

    assert exit_code == 1
    assert "approval_request:" in output
    assert "index_repository: needs_approval exit=None" in output
    assert "Codebase Memory tool requires approval: index_repository" in output
    assert calls == []
    assert len(approvals) == 1
    assert approvals[0].source == "memory"
    assert approvals[0].command_string.startswith("codebase-memory-mcp cli index_repository")
    assert "repo_path" in approvals[0].command_string
    assert approvals[0].reason == "Codebase Memory tool requires approval: index_repository"


def test_memory_index_runs_with_approve_flag(capsys, monkeypatch, tmp_path: Path) -> None:
    captured_argv: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="indexed", stderr="")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True)

    exit_code = main(["memory", "index", "--repo", str(tmp_path), "--approve"])
    output = capsys.readouterr().out
    approvals = StateStore(
        tmp_path / ".ai-orch" / "state" / "ai-orch.db"
    ).list_approval_requests()

    assert exit_code == 0
    assert "index_repository: passed exit=0" in output
    assert approvals == []
    assert captured_argv == [
        [
            "codebase-memory-mcp",
            "cli",
            "index_repository",
            json.dumps({"repo_path": str(tmp_path.resolve())}, sort_keys=True),
        ]
    ]


def test_memory_preflight_adapter_runs_read_only_steps(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_argv: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="{}", stderr="")

    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(
        [
            "memory",
            "preflight",
            "--repo",
            str(tmp_path),
            "--area",
            "adapter",
            "--limit",
            "7",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "preflight: area=adapter" in output
    assert "available: yes" in output
    assert "preflight summary: area=adapter total=6 passed=6 failed=0" in output
    assert captured_argv == [
        [
            "codebase-memory-mcp",
            "cli",
            "get_architecture",
            '{"aspects": ["all"], "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"limit": 7, "name_pattern": ".*Adapter.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"label": "Class", "limit": 7, "name_pattern": ".*CLI.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"limit": 7, "name_pattern": ".*ProcessRunner.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"label": "Class", "limit": 7, "name_pattern": ".*Policy.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "detect_changes",
            '{"project": "demo"}',
        ],
    ]


def test_autopilot_queue_sync_loads_plan_items_without_duplicates(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Synced" in output
    assert "new: 2" in output
    assert "existing: 0" in output
    assert "+ " in output

    exit_code = main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "new: 0" in output
    assert "existing: 2" in output


def test_autopilot_queue_sync_backlog_loads_open_priority_items(
    capsys,
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P2",
                "",
                "- Add deeper queue history filters if recent status summaries are not enough",
                "  for daily operation.",
                "",
                "## P3 / Deferred",
                "",
                "- Defer web dashboard.",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Synced backlog" in output
    assert "priorities: P0, P1, P2" in output
    assert "new: 1" in output
    assert "existing: 0" in output
    assert "Add deeper queue history filters" in output
    assert "Defer web dashboard" not in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = store.list_plan_items(plan_path=backlog)
    assert len(items) == 1
    assert items[0].section == "P2"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "new: 0" in output
    assert "existing: 1" in output


def test_autopilot_queue_refresh_created_refs_dry_run_and_apply(
    capsys,
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P2",
                "",
                "- Completed task",
                "- Keep created task",
            ]
        ),
        encoding="utf-8",
    )
    main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    capsys.readouterr()
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    completed, created = store.list_plan_items(plan_path=backlog)
    store.update_plan_item_status(completed.plan_item_id, "done")
    backlog.write_text(
        "\n".join(["# Backlog", "", "## P2", "", "- Keep created task"]),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "refresh-created-refs",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out
    dry_run_item = store.get_plan_item(created.plan_item_id)

    assert exit_code == 0
    assert "Refresh created backlog refs" in output
    assert "matched: 1" in output
    assert "dry_run: use --apply to update matching created refs" in output
    assert f"id={created.plan_item_id} P2:6->5: Keep created task" in output
    assert dry_run_item is not None
    assert dry_run_item.line_number == 6

    exit_code = main(
        [
            "autopilot",
            "queue",
            "refresh-created-refs",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
            "--apply",
        ]
    )
    output = capsys.readouterr().out
    updated_item = store.get_plan_item(created.plan_item_id)

    assert exit_code == 0
    assert "updated: 1" in output
    assert updated_item is not None
    assert updated_item.plan_item_id == created.plan_item_id
    assert updated_item.status == "created"
    assert updated_item.line_number == 5

    main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out

    assert "new: 0" in output
    assert len(store.list_plan_items(plan_path=backlog)) == 2


def test_autopilot_queue_refresh_created_refs_json_dry_run_and_apply(
    capsys,
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P2",
                "",
                "- Completed task",
                "- Keep created task",
            ]
        ),
        encoding="utf-8",
    )
    main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    capsys.readouterr()
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    completed, created = store.list_plan_items(plan_path=backlog)
    store.update_plan_item_status(completed.plan_item_id, "done")
    backlog.write_text(
        "\n".join(["# Backlog", "", "## P2", "", "- Keep created task"]),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "refresh-created-refs",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
            "--json",
        ]
    )
    dry_run_payload = json.loads(capsys.readouterr().out)
    dry_run_item = store.get_plan_item(created.plan_item_id)

    assert exit_code == 0
    assert dry_run_payload["backlog_path"] == str(backlog)
    assert dry_run_payload["priorities"] == ["P0", "P1", "P2"]
    assert dry_run_payload["apply"] is False
    assert dry_run_payload["dry_run"] is True
    assert dry_run_payload["matched_count"] == 1
    assert dry_run_payload["updated_count"] == 0
    assert dry_run_payload["items"] == [
        {
            "plan_item_id": created.plan_item_id,
            "text": "Keep created task",
            "old_source_ref": {
                "path": str(backlog),
                "section": "P2",
                "line_number": 6,
            },
            "new_source_ref": {
                "path": str(backlog),
                "section": "P2",
                "line_number": 5,
            },
        }
    ]
    assert dry_run_item is not None
    assert dry_run_item.line_number == 6

    exit_code = main(
        [
            "autopilot",
            "queue",
            "refresh-created-refs",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
            "--apply",
            "--json",
        ]
    )
    apply_payload = json.loads(capsys.readouterr().out)
    updated_item = store.get_plan_item(created.plan_item_id)

    assert exit_code == 0
    assert apply_payload["apply"] is True
    assert apply_payload["dry_run"] is False
    assert apply_payload["matched_count"] == 1
    assert apply_payload["updated_count"] == 1
    assert apply_payload["items"][0]["old_source_ref"]["line_number"] == 6
    assert apply_payload["items"][0]["new_source_ref"]["line_number"] == 5
    assert updated_item is not None
    assert updated_item.status == "created"
    assert updated_item.line_number == 5


def test_autopilot_queue_list_shows_status_without_running_execution(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status" in output
    assert "total: 1" in output
    assert "[created]" in output
    assert "Add approval CLI" in output
    assert "Autopilot selected:" not in output
    assert "Dry run" not in output


def test_autopilot_queue_list_filters_by_status_and_limit(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Created task",
                "- [ ] Done task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "done",
            "--status",
            "blocked",
            "--limit",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "total: 3" in output
    assert "filtered: 2 status=done,blocked" in output
    assert "limit: 1" in output
    assert "showing: 1" in output
    assert "[done]" in output
    assert "Done task" in output
    assert "Blocked task" not in output
    assert "Created task" not in output


def test_autopilot_queue_list_all_plans_filters_across_sources(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    roadmap.write_text("- [ ] Roadmap done task\n", encoding="utf-8")
    backlog.write_text("- [ ] Backlog created task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(roadmap),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(backlog),
        ]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    roadmap_item = store.list_plan_items(plan_path=roadmap)[0]
    store.update_plan_item_status(roadmap_item.plan_item_id, "done")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--status",
            "done",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status for all persisted plans" in output
    assert "total: 2" in output
    assert "filtered: 1 status=done" in output
    assert f"[done] {roadmap}:" in output
    assert "Roadmap done task" in output
    assert "Backlog created task" not in output


def test_autopilot_queue_list_json_includes_filtered_rows_and_metadata(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Created task",
                "- [ ] Blocked task",
                "- [ ] Done task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "blocked",
            "--status",
            "done",
            "--limit",
            "1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    refreshed = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert exit_code == 0
    assert payload["plan"] == str(plan)
    assert payload["all_plans"] is False
    assert payload["total"] == 3
    assert payload["filtered"] == 2
    assert payload["status_filter"] == ["blocked", "done"]
    assert payload["limit"] == 1
    assert payload["showing"] == 1
    assert payload["by_status"] == {"blocked": 1, "created": 1, "done": 1}
    assert payload["items"] == [
        {
            "plan_item_id": items["Blocked task"].plan_item_id,
            "plan_path": str(plan),
            "line_number": items["Blocked task"].line_number,
            "text": "Blocked task",
            "status": "blocked",
            "task_id": None,
            "selected_worktree_path": None,
            "blocked_reason": "needs review",
            "plan_graph_id": None,
            "plan_graph_root_node_id": None,
            "report_path": None,
        }
    ]
    assert payload["problem_summary"] == [
        {
            "status": "blocked",
            "reason": "needs review",
            "count": 1,
            "latest_ids": [items["Blocked task"].plan_item_id],
        }
    ]
    assert refreshed["Blocked task"].status == "blocked"
    assert refreshed["Done task"].status == "done"


def test_autopilot_queue_list_json_all_plans_uses_all_persisted_sources(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    roadmap.write_text("- [ ] Roadmap done task\n", encoding="utf-8")
    backlog.write_text("- [ ] Backlog created task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(roadmap),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(backlog),
        ]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    roadmap_item = store.list_plan_items(plan_path=roadmap)[0]
    store.update_plan_item_status(roadmap_item.plan_item_id, "done")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--status",
            "done",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["plan"] == "all persisted plans"
    assert payload["all_plans"] is True
    assert payload["total"] == 2
    assert payload["filtered"] == 1
    assert payload["status_filter"] == ["done"]
    assert payload["by_status"] == {"created": 1, "done": 1}
    assert payload["items"][0]["plan_path"] == str(roadmap)
    assert payload["items"][0]["status"] == "done"
    assert payload["items"][0]["text"] == "Roadmap done task"
    assert payload["problem_summary"] is None


def test_autopilot_queue_sync_works_when_no_unstarted_task_exists(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Already started task\n", encoding="utf-8")
    tasks = load_plan_tasks(plan)
    store = StateStore(tmp_path / "state.db")
    store.create_task(tasks[0].to_prompt(), repo_path=tmp_path)

    exit_code = main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Synced" in output
    assert "new: 1" in output
    assert "No unstarted plan items found" not in output


def test_autopilot_queue_list_handles_missing_plan(capsys, tmp_path: Path) -> None:
    missing_plan = tmp_path / "MISSING.md"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Plan not found:" in output


def test_autopilot_queue_list_shows_report_path_for_completed_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Completed task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task(
        "Completed task", repo_path=tmp_path, task_id="task-report-list"
    )
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="Completed task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.update_task_status(task.task_id, "done")
    worktree = tmp_path / "worktrees" / "task-1"
    store.update_plan_item_status(
        item.plan_item_id,
        "done",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report", encoding="utf-8")

    exit_code = main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[done]" in output
    assert f"worktree={worktree}" in output
    assert f"report={report_path}" in output


def test_autopilot_queue_list_and_status_show_persisted_item_id(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("# Roadmap\n\n- [ ] Trackable task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]

    main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    list_output = capsys.readouterr().out
    assert f"id={item.plan_item_id}" in list_output
    assert item.line_number != item.plan_item_id
    assert f"id={item.line_number} " not in list_output

    main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    status_output = capsys.readouterr().out
    assert f"id={item.plan_item_id}" in status_output
    assert f"id={item.line_number} " not in status_output


def test_autopilot_queue_run_next_defaults_to_dry_run(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    plan_item_id = store.list_plan_items(plan_path=plan)[0].plan_item_id

    exit_code = main(
        ["autopilot", "queue", "run-next", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Task: Add approval CLI" in output
    assert f"Queue item: {plan_item_id}" in output
    assert "Dry run: add --execute" in output
    item = store.get_plan_item(plan_item_id)
    assert item is not None
    assert item.status == "created"
    assert item.task_id is None


def test_autopilot_queue_run_next_executes_one_item_and_updates_status(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    first_item = store.list_plan_items(plan_path=plan)[0]

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(task, repo_path=repo, task_id="task-1")
        return SupervisorResult(
            status="done",
            summary="Verification passed: custom",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Queue item: {first_item.plan_item_id}" in output
    assert "status=done" in output

    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["First task"].task_id == "task-1"
    assert items["Second task"].status == "created"


def test_autopilot_queue_run_next_writes_report_and_prints_path(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(task, repo_path=repo, task_id="task-report-1")
        iteration = self.state_store.add_iteration(
            task_id=stored.task_id,
            iteration_index=1,
            agent_name="mock",
            agent_status="success",
            prompt=task,
            raw_output="done",
            decision_status="done",
            decision_reason="Verification passed: unit",
        )
        self.state_store.add_verification_run(
            task_id=stored.task_id,
            iteration_id=iteration.iteration_id,
            result=VerificationResult(
                name="unit",
                status="passed",
                exit_code=0,
                stdout="ok",
                stderr="",
            ),
        )
        self.state_store.update_task_status(stored.task_id, "done")
        return SupervisorResult(
            status="done",
            summary="Verification passed: custom",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    report_path = tmp_path / ".ai-orch" / "reports" / "task-report-1.md"
    assert report_path.exists()
    assert f"Report: {report_path}" in output
    report_text = report_path.read_text(encoding="utf-8")
    assert "# ai-orch report: task-report-1" in report_text
    assert "- Status: `done`" in report_text


def test_autopilot_queue_run_next_stops_on_blocked_result(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(task, repo_path=repo, task_id="task-2")
        return SupervisorResult(
            status="blocked",
            summary="Agent failed",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=blocked" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "blocked"
    assert item.task_id == "task-2"


def test_autopilot_queue_run_next_updates_linked_plan_graph_node_lifecycle(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    graph = store.create_plan_graph("First task graph")
    root = store.add_plan_graph_node(graph.graph_id, "root", "Root step")
    store.link_plan_item_to_plan_graph(
        item.plan_item_id,
        graph.graph_id,
        plan_graph_root_node_id=root.node_id,
    )

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(task, repo_path=repo, task_id="task-replan")
        iteration = self.state_store.add_iteration(
            task_id=stored.task_id,
            iteration_index=1,
            agent_name="mock",
            agent_status="success",
            prompt=task,
            raw_output="failed",
            decision_status="continue",
            decision_reason="Verification failed: unit",
        )
        self.state_store.record_replan_decision(
            task_id=stored.task_id,
            iteration_id=iteration.iteration_id,
            source="verification",
            status="continue",
            reason="Verification failed: unit",
            failed_checks=[{"name": "unit", "status": "failed"}],
        )
        return SupervisorResult(
            status="blocked",
            summary="Verification failed",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    capsys.readouterr()
    node = store.get_plan_graph_node(root.node_id)
    decisions = store.list_replan_decisions("task-replan")
    nodes = store.list_plan_graph_nodes(graph.graph_id)

    assert exit_code == 1
    assert node is not None
    assert node.status == "blocked"
    assert node.attempts == 1
    assert len(decisions) == 1
    assert decisions[0].plan_graph_id == graph.graph_id
    assert decisions[0].plan_graph_node_id == root.node_id
    assert [plan_node.node_key for plan_node in nodes] == [
        "root",
        f"replan-{decisions[0].replan_id}",
    ]
    assert nodes[1].status == "pending"
    dependencies = store.list_plan_graph_dependencies(
        graph.graph_id,
        node_id=nodes[1].node_id,
    )
    assert len(dependencies) == 1
    assert dependencies[0].depends_on_node_id == root.node_id


def test_autopilot_queue_run_next_returns_zero_when_no_ready_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Only task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "done")

    exit_code = main(
        ["autopilot", "queue", "run-next", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No queued plan items ready" in output


def test_autopilot_queue_run_next_passes_timeout_and_records_blocked_reason_when_budget_exhausted(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    captured_budgets: list[int | None] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_budgets.append(self.max_runtime_sec)
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="task-budget-1"
        )
        return SupervisorResult(
            status="blocked",
            summary="Runtime budget exhausted",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-runtime-sec",
            "42",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=blocked" in output
    assert captured_budgets == [42]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "blocked"
    assert item.task_id == "task-budget-1"
    assert item.blocked_reason == "Runtime budget exhausted"


def test_autopilot_queue_run_next_uses_config_runtime_budget_by_default(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")
    write_config(tmp_path, max_runtime_sec=17)

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    captured_budgets: list[int | None] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_budgets.append(self.max_runtime_sec)
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="task-default-budget"
        )
        return SupervisorResult(
            status="done",
            summary="Verification passed: custom",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    capsys.readouterr()

    assert exit_code == 0
    assert captured_budgets == [17]


def test_autopilot_queue_run_next_rejects_non_positive_runtime_budget(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-runtime-sec",
            "0",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--max-runtime-sec must be greater than 0" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "created"


def test_autopilot_queue_run_batch_passes_timeout_and_records_blocked_reason_when_budget_exhausted(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    captured_budgets: list[int | None] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_budgets.append(self.max_runtime_sec)
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="batch-budget-1"
        )
        return SupervisorResult(
            status="blocked",
            summary="Runtime budget exhausted",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
            "--max-runtime-sec",
            "99",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=blocked" in output
    assert "Batch stopped after 1 item(s): status=blocked" in output
    assert captured_budgets == [99]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "blocked"
    assert items["First task"].task_id == "batch-budget-1"
    assert items["First task"].blocked_reason == "Runtime budget exhausted"
    assert items["Second task"].status == "created"


def test_autopilot_queue_run_batch_rejects_non_positive_runtime_budget(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-runtime-sec",
            "-1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--max-runtime-sec must be greater than 0" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "created"


def test_autopilot_queue_run_batch_defaults_to_dry_run(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Task: First task" in output
    assert "Task: Second task" in output
    assert "Dry run: add --execute" in output
    assert "Dry run: would process 2 item(s)" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert f"Queue item: {items['First task'].plan_item_id}" in output
    assert f"Queue item: {items['Second task'].plan_item_id}" in output
    assert items["First task"].status == "created"
    assert items["Second task"].status == "created"
    assert "=== Batch summary ===" in output
    assert "Selected: 2 item(s)" in output
    assert "Status counts: created=2" in output
    assert (
        f"First non-done queue item: {items['First task'].plan_item_id} (status=created)"
        in output
    )


def test_autopilot_queue_run_batch_dry_run_selects_item_id(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--item-id",
            str(items["Second task"].plan_item_id),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Queue item: {items['Second task'].plan_item_id}" in output
    assert f"Queue item: {items['First task'].plan_item_id}" not in output
    assert "Task: Second task" in output
    assert "Task: First task" not in output
    assert "Selected: 1 item(s)" in output
    assert items["First task"].status == "created"
    assert items["Second task"].status == "created"


def test_autopilot_queue_run_batch_execute_selects_item_id(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
                "- [ ] Third task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    captured_tasks: list[str] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_tasks.append(task)
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="selected-batch-task"
        )
        return SupervisorResult(
            status="done",
            summary="Verification passed",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--item-id",
            str(items["Second task"].plan_item_id),
            "--max-items",
            "3",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert len(captured_tasks) == 1
    assert "Second task" in captured_tasks[0]
    assert "First task" not in captured_tasks[0]
    assert f"Queue item: {items['Second task'].plan_item_id}" in output
    assert f"Queue item: {items['First task'].plan_item_id}" not in output
    assert "Batch complete: processed 1 item(s)" in output

    refreshed = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert refreshed["First task"].status == "created"
    assert refreshed["Second task"].status == "done"
    assert refreshed["Second task"].task_id == "selected-batch-task"
    assert refreshed["Third task"].status == "created"


def test_autopilot_queue_run_batch_item_id_requires_created_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "blocked")

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--item-id",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert f"Queue item {item.plan_item_id} is not ready (status=blocked)" in output


def test_autopilot_queue_run_batch_item_id_requires_selected_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "PLAN_A.md"
    plan_b = tmp_path / "PLAN_B.md"
    plan_a.write_text("- [ ] Plan A task\n", encoding="utf-8")
    plan_b.write_text("- [ ] Plan B task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_a)])
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_b)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_a = store.list_plan_items(plan_path=plan_a)[0]

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan_b),
            "--item-id",
            str(item_a.plan_item_id),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert f"Queue item {item_a.plan_item_id} does not belong to plan {plan_b}" in output


def test_autopilot_queue_run_batch_summary_ignores_terminal_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Old skipped task",
                "- [ ] Ready task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    skipped_item = items["Old skipped task"]
    ready_item = items["Ready task"]
    store.update_plan_item_status(skipped_item.plan_item_id, "skipped")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Queue item: {ready_item.plan_item_id}" in output
    assert "Status counts: created=1" in output
    assert (
        f"First non-done queue item: {ready_item.plan_item_id} (status=created)"
        in output
    )
    assert (
        f"First non-done queue item: {skipped_item.plan_item_id} (status=skipped)"
        not in output
    )


def test_autopilot_queue_run_batch_executes_up_to_max_items(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
                "- [ ] Third task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    queued_items = store.list_plan_items(plan_path=plan)

    call_count = 0

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        nonlocal call_count
        call_count += 1
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id=f"batch-task-{call_count}"
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {call_count}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Queue item: {queued_items[0].plan_item_id}" in output
    assert f"Queue item: {queued_items[1].plan_item_id}" in output
    assert "Batch complete: processed 2 item(s)" in output
    assert call_count == 2

    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["First task"].task_id == "batch-task-1"
    assert items["Second task"].status == "done"
    assert items["Second task"].task_id == "batch-task-2"
    assert items["Third task"].status == "created"
    assert items["Third task"].task_id is None

    report_dir = tmp_path / ".ai-orch" / "reports"
    assert (report_dir / "batch-task-1.md").exists()
    assert (report_dir / "batch-task-2.md").exists()
    assert "=== Batch summary ===" in output
    assert "Processed: 2 item(s)" in output
    assert "Status counts: done=2" in output
    assert (
        f"First non-done queue item: {items['Third task'].plan_item_id} (status=created)"
        in output
    )
    assert f"Reports:\n  {report_dir / 'batch-task-1.md'}\n  {report_dir / 'batch-task-2.md'}" in output


def test_autopilot_queue_run_batch_stops_on_blocked_result(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
                "- [ ] Third task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    call_count = 0

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        nonlocal call_count
        call_count += 1
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id=f"batch-task-{call_count}"
        )
        status = "done" if call_count == 1 else "blocked"
        return SupervisorResult(
            status=status,
            summary=f"Result {call_count}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "3",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=done" in output
    assert "status=blocked" in output
    assert "Batch stopped after 2 item(s): status=blocked" in output
    assert call_count == 2

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["Second task"].status == "blocked"
    assert items["Third task"].status == "created"

    report_dir = tmp_path / ".ai-orch" / "reports"
    assert (report_dir / "batch-task-1.md").exists()
    assert (report_dir / "batch-task-2.md").exists()
    assert "=== Batch summary ===" in output
    assert "Processed: 2 item(s)" in output
    assert "Status counts: blocked=1, done=1" in output
    assert (
        f"First non-done queue item: {items['Second task'].plan_item_id} (status=blocked)"
        in output
    )
    assert f"Reports:\n  {report_dir / 'batch-task-1.md'}\n  {report_dir / 'batch-task-2.md'}" in output
    assert not (report_dir / "batch-task-3.md").exists()


def test_autopilot_loop_defaults_to_dry_run(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")

    exit_code = main(
        [
            "autopilot",
            "loop",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "1",
        ]
    )
    output = capsys.readouterr().out
    item = store.list_plan_items(plan_path=plan)[0]

    assert exit_code == 0
    assert "=== Autopilot loop ===" in output
    assert "Mode: dry-run" in output
    assert "Dry run: would process 1 item(s). Add --execute to run." in output
    assert "=== Loop budget ledger ===" in output
    assert "loop_run_id: " in output
    assert "actions: max=100 selected=1 processed=0" in output
    assert item.status == "created"
    runs = store.list_autopilot_loop_runs(plan_path=plan)
    assert len(runs) == 1
    assert runs[0].mode == "dry-run"
    assert runs[0].selected_count == 1
    assert runs[0].selected_item_ids == [item.plan_item_id]


def test_autopilot_loop_execute_completes_items(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n- [ ] Second task\n", encoding="utf-8")
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")

    call_count = 0

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        nonlocal call_count
        call_count += 1
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id=f"loop-task-{call_count}",
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {call_count}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "loop",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert exit_code == 0
    assert "Mode: execute" in output
    assert "Batch complete: processed 2 item(s)" in output
    assert "Loop complete" in output
    assert "actions: max=100 selected=2 processed=2" in output
    assert items["First task"].status == "done"
    assert items["Second task"].status == "done"
    assert call_count == 2
    runs = store.list_autopilot_loop_runs(plan_path=plan)
    assert len(runs) == 1
    assert runs[0].mode == "execute"
    assert runs[0].processed_count == 2
    assert runs[0].stop_reason == "complete"


def test_autopilot_loop_history_lists_persisted_ledger(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    main(
        [
            "autopilot",
            "loop",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "1",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "loop-history",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["count"] == 1
    assert payload["runs"][0]["mode"] == "dry-run"
    assert payload["runs"][0]["selected_count"] == 1


def test_autopilot_loop_stop_on_risk_blocks_execution(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n- [ ] Blocked task\n", encoding="utf-8")
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        raise AssertionError("loop should stop before supervisor execution")

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "loop",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--stop-on-risk",
        ]
    )
    output = capsys.readouterr().out
    refreshed = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert exit_code == 1
    assert "Loop stopped on risk: next_action=review_blocked" in output
    assert "actions: max=100 selected=0 processed=0" in output
    assert refreshed["Created task"].status == "created"
    assert refreshed["Blocked task"].status == "blocked"
    runs = store.list_autopilot_loop_runs(plan_path=plan)
    assert len(runs) == 1
    assert runs[0].stop_reason == "risk"
    assert runs[0].result_code == 1


def test_autopilot_loop_rejects_exhausted_action_budget(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        [
            "autopilot",
            "loop",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-actions",
            "0",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Loop stopped: budget exhausted (--max-actions must be at least 1)" in output


def test_autopilot_loop_records_dead_letter_for_blocked_item(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Poisoned task\n", encoding="utf-8")
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id="loop-blocked-task",
        )
        return SupervisorResult(
            status="blocked",
            summary="Verification failed",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "loop",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-attempts",
            "1",
        ]
    )
    output = capsys.readouterr().out
    item = store.list_plan_items(plan_path=plan)[0]
    dead_letters = store.list_dead_letter_items(plan_item_id=item.plan_item_id)

    assert exit_code == 1
    assert "Loop stopped: dead-letter" in output
    assert "dead_letters: 1" in output
    assert item.status == "blocked"
    assert len(dead_letters) == 1
    assert dead_letters[0].task_id == "loop-blocked-task"
    assert dead_letters[0].reason == "loop item stopped with status=blocked"


def test_autopilot_loop_writes_batch_report(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    report_path = tmp_path / "loop-report.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")
    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        [
            "autopilot",
            "loop",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "1",
            "--batch-report",
            str(report_path),
        ]
    )
    output = capsys.readouterr().out
    report = report_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert "=== Batch summary ===" in output
    assert report_path.exists()
    assert "# Autopilot Batch Report" in report
    assert "- Mode: `dry-run`" in report


def test_autopilot_queue_run_batch_updates_linked_plan_graph_node_lifecycle(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    graph = store.create_plan_graph("First task graph")
    root = store.add_plan_graph_node(graph.graph_id, "root", "Root step")
    store.link_plan_item_to_plan_graph(
        item.plan_item_id,
        graph.graph_id,
        plan_graph_root_node_id=root.node_id,
    )

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="batch-done"
        )
        return SupervisorResult(
            status="done",
            summary="Verification passed",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "1",
        ]
    )
    capsys.readouterr()

    node = store.get_plan_graph_node(root.node_id)

    assert exit_code == 0
    assert node is not None
    assert node.status == "done"
    assert node.attempts == 1


def test_autopilot_queue_run_batch_returns_zero_when_no_ready_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [x] Completed task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No queued plan items ready" in output


def test_autopilot_queue_run_batch_rejects_non_positive_max_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "0",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--max-items must be at least 1" in output


def test_autopilot_queue_run_batch_rotate_worktrees_rejects_worktree(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "autopilot",
                "queue",
                "run-batch",
                "--repo",
                str(tmp_path),
                "--plan",
                str(plan),
                "--worktree",
                "../wt",
                "--rotate-worktrees",
                "../pool",
            ]
        )

    assert exc.value.code == 2


def test_autopilot_queue_run_batch_rotate_worktrees_blocks_missing_base_dir(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    missing = tmp_path / "pool"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(missing),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Rotation base directory does not exist" in output
    assert str(missing) in output


def test_autopilot_queue_run_batch_rotate_worktrees_dry_run_selects_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()
    wt2 = pool / "wt2"
    wt2.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Task: First task" in output
    assert "Task: Second task" in output
    assert f"Worktree: {wt1.resolve()}" in output
    assert f"Worktree: {wt2.resolve()}" in output
    assert "Dry run: would process 2 item(s) using rotated worktrees" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert f"Queue item: {items['First task'].plan_item_id}" in output
    assert f"Queue item: {items['Second task'].plan_item_id}" in output
    assert items["First task"].status == "created"
    assert items["Second task"].status == "created"
    assert "=== Batch summary ===" in output
    assert "Selected: 2 item(s)" in output
    assert "Status counts: created=2" in output
    assert "Selected worktrees:" in output
    assert f"  {wt1.resolve()}" in output
    assert f"  {wt2.resolve()}" in output


def test_autopilot_queue_run_batch_rotate_worktrees_blocks_when_too_few_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: not enough clean, available worktrees" in output


def test_autopilot_queue_run_batch_rotate_worktrees_skips_busy_worktree(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    pool = tmp_path / "pool"
    pool.mkdir()
    busy_wt = pool / "busy"
    busy_wt.mkdir()
    free_wt = pool / "free"
    free_wt.mkdir()

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    first_item = store.list_plan_items(plan_path=plan)[0]
    busy_task = store.create_task(
        "busy task",
        repo_path=busy_wt.resolve(),
        task_id="busy-task",
    )
    store.update_plan_item_status(
        first_item.plan_item_id,
        "in_progress",
        task_id=busy_task.task_id,
    )

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--max-items",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Worktree: {free_wt.resolve()}" in output
    assert f"Worktree: {busy_wt.resolve()}" not in output


def test_autopilot_queue_run_batch_rotate_worktrees_executes_in_selected_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()
    wt2 = pool / "wt2"
    wt2.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )
    captured_repos: list[Path] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_repos.append(repo.resolve())
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id=f"rotated-task-{len(captured_repos)}",
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {stored.task_id}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--execute",
            "--allow-mock-agent",
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Batch complete: processed 2 item(s)" in output
    assert f"Worktree: {wt1.resolve()}" in output
    assert f"Worktree: {wt2.resolve()}" in output
    assert captured_repos == [wt1.resolve(), wt2.resolve()]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["First task"].task_id == "rotated-task-1"
    assert items["First task"].selected_worktree_path == str(wt1.resolve())
    assert items["Second task"].status == "done"
    assert items["Second task"].task_id == "rotated-task-2"
    assert items["Second task"].selected_worktree_path == str(wt2.resolve())

    first_report = tmp_path / ".ai-orch" / "reports" / "rotated-task-1.md"
    second_report = tmp_path / ".ai-orch" / "reports" / "rotated-task-2.md"
    assert first_report.exists()
    assert second_report.exists()
    assert f"- Queue worktree: `{wt1.resolve()}`" in first_report.read_text(
        encoding="utf-8"
    )
    assert f"- Queue worktree: `{wt2.resolve()}`" in second_report.read_text(
        encoding="utf-8"
    )
    assert "=== Batch summary ===" in output
    assert "Processed: 2 item(s)" in output
    assert "Status counts: done=2" in output
    assert "Selected worktrees:" in output
    assert f"  {wt1.resolve()}" in output
    assert f"  {wt2.resolve()}" in output
    assert f"Reports:\n  {first_report}\n  {second_report}" in output


def test_autopilot_queue_run_batch_fixed_worktree_persists_and_reports(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Fixed worktree task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    worktree = tmp_path / "fixed-wt"
    worktree.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )
    captured_repos: list[Path] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_repos.append(repo.resolve())
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id="fixed-task-1",
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {stored.task_id}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--worktree",
            str(worktree),
            "--max-items",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Batch complete: processed 1 item(s)" in output
    assert captured_repos == [worktree.resolve()]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = list(store.list_plan_items(plan_path=plan))
    assert len(items) == 1
    item = items[0]
    assert item.status == "done"
    assert item.task_id == "fixed-task-1"
    assert item.selected_worktree_path == str(worktree.resolve())
    events = store.list_task_events("fixed-task-1")
    worktree_events = [
        event for event in events if event.event_type == "worktree.execution_profile"
    ]
    assert len(worktree_events) == 1
    assert worktree_events[0].payload["profile"] == {
        "task_id": "fixed-task-1",
        "worktree_path": str(worktree.resolve()),
        "branch": None,
        "base_ref": None,
        "dirty": None,
        "cleanup_eligible": False,
    }
    assert worktree_events[0].payload["sandbox"] == {
        "root": str(worktree.resolve()),
        "writable_paths": [str(worktree.resolve())],
        "forbidden_path_markers": [
            ".env",
            ".ssh",
            ".codex/auth.json",
            "auth.json",
            "id_rsa",
            "id_ed25519",
        ],
        "worktree": worktree_events[0].payload["profile"],
    }

    report_path = tmp_path / ".ai-orch" / "reports" / "fixed-task-1.md"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert f"- Queue worktree: `{worktree.resolve()}`" in report_text
    assert f"- Worktree execution: `{worktree.resolve()}`" in report_text
    assert "- Worktree profile: cleanup_eligible=`False`" in report_text
    assert "=== Batch summary ===" in output
    assert "Processed: 1 item(s)" in output
    assert "Status counts: done=1" in output
    assert "Selected worktrees:" in output
    assert f"  {worktree.resolve()}" in output
    assert f"Reports:\n  {report_path}" in output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    show_output = capsys.readouterr().out
    assert exit_code == 0
    assert f"selected_worktree: {worktree.resolve()}" in show_output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    list_output = capsys.readouterr().out
    assert exit_code == 0
    assert f"worktree={worktree.resolve()}" in list_output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "done",
        ]
    )
    status_output = capsys.readouterr().out
    assert exit_code == 0
    assert f"worktree={worktree.resolve()}" in status_output


def test_autopilot_queue_run_batch_summary_json_dry_run(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    summary_path = tmp_path / "batch-summary.json"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "2",
            "--summary-json",
            str(summary_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== Batch summary ===" in output
    assert summary_path.exists()

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["mode"] == "dry-run"
    assert summary["selected_count"] == 2
    assert summary["status_counts"] == {"created": 2}
    assert summary["report_paths"] == []
    assert summary["selected_worktree_paths"] == []
    assert summary["selected_item_refs"] == [
        {
            "plan_item_id": items["First task"].plan_item_id,
            "status": "created",
            "plan_path": str(plan),
            "line_number": 1,
            "text": "First task",
            "selected_worktree_path": None,
            "task_id": None,
            "report_path": None,
        },
        {
            "plan_item_id": items["Second task"].plan_item_id,
            "status": "created",
            "plan_path": str(plan),
            "line_number": 2,
            "text": "Second task",
            "selected_worktree_path": None,
            "task_id": None,
            "report_path": None,
        },
    ]
    assert summary["first_non_done_item"] == {
        "plan_item_id": items["First task"].plan_item_id,
        "status": "created",
        "text": "First task",
        "source": f"{plan}:1",
    }
    assert summary["preflight_snapshot"]["plan"] == str(plan)
    assert summary["preflight_snapshot"]["total"] == 2
    assert summary["preflight_snapshot"]["created_readiness"] == {"ready": 2, "stale": 0}
    assert summary["preflight_snapshot"]["agent_profile"]["name"] == "mock"
    assert summary["preflight_snapshot"]["preflight_result"] == "pass"
    assert summary["preflight_snapshot"]["next_action"] == "run_batch"


def test_autopilot_queue_run_batch_batch_report_dry_run(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    report_path = tmp_path / "batch-report.md"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "2",
            "--batch-report",
            str(report_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== Batch summary ===" in output
    assert str(report_path) not in output
    assert report_path.exists()

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    report = report_path.read_text(encoding="utf-8")

    assert "# Autopilot Batch Report" in report
    assert "- Mode: `dry-run`" in report
    assert "- Selected: 2 item(s)" in report
    assert "## First Non-Done Item" in report
    assert f"- Queue item: `{items['First task'].plan_item_id}`" in report
    assert f"- Source: `{plan}:1`" in report
    assert "## Reports\n\nNone." in report
    assert '"text": "First task"' in report
    assert '"text": "Second task"' in report
    assert "## Preflight Snapshot" in report
    assert '"next_action": "run_batch"' in report


def test_autopilot_queue_run_batch_summary_json_execute(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
                "- [ ] Third task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")

    call_count = 0

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        nonlocal call_count
        call_count += 1
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id=f"batch-task-{call_count}"
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {call_count}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    summary_path = tmp_path / "batch-summary.json"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
            "--summary-json",
            str(summary_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== Batch summary ===" in output
    assert summary_path.exists()

    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_dir = tmp_path / ".ai-orch" / "reports"

    assert summary["mode"] == "execute"
    assert summary["processed_count"] == 2
    assert summary["status_counts"] == {"done": 2}
    assert summary["first_non_done_item"] == {
        "plan_item_id": items["Third task"].plan_item_id,
        "status": "created",
        "text": "Third task",
        "source": f"{plan}:3",
    }
    assert summary["report_paths"] == [
        str(report_dir / "batch-task-1.md"),
        str(report_dir / "batch-task-2.md"),
    ]
    assert summary["selected_worktree_paths"] == []
    assert summary["selected_item_refs"] == [
        {
            "plan_item_id": items["First task"].plan_item_id,
            "status": "done",
            "plan_path": str(plan),
            "line_number": 1,
            "text": "First task",
            "selected_worktree_path": None,
            "task_id": "batch-task-1",
            "report_path": str(report_dir / "batch-task-1.md"),
        },
        {
            "plan_item_id": items["Second task"].plan_item_id,
            "status": "done",
            "plan_path": str(plan),
            "line_number": 2,
            "text": "Second task",
            "selected_worktree_path": None,
            "task_id": "batch-task-2",
            "report_path": str(report_dir / "batch-task-2.md"),
        },
    ]
    assert summary["preflight_snapshot"]["plan"] == str(plan)
    assert summary["preflight_snapshot"]["total"] == 3
    assert summary["preflight_snapshot"]["created_readiness"] == {"ready": 3, "stale": 0}
    assert summary["preflight_snapshot"]["agent_profile"]["name"] == "mock"
    assert summary["preflight_snapshot"]["preflight_result"] == "pass"
    assert summary["preflight_snapshot"]["next_action"] == "run_batch"


def test_autopilot_queue_run_batch_summary_json_rotated_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()
    wt2 = pool / "wt2"
    wt2.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    captured_repos: list[Path] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_repos.append(repo.resolve())
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id=f"rotated-task-{len(captured_repos)}",
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {stored.task_id}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    summary_path = tmp_path / "batch-summary.json"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--execute",
            "--allow-mock-agent",
            "--max-items",
            "2",
            "--summary-json",
            str(summary_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== Batch summary ===" in output
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_dir = tmp_path / ".ai-orch" / "reports"
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert summary["mode"] == "execute"
    assert summary["processed_count"] == 2
    assert summary["status_counts"] == {"done": 2}
    assert summary["selected_worktree_paths"] == [
        str(wt1.resolve()),
        str(wt2.resolve()),
    ]
    assert summary["report_paths"] == [
        str(report_dir / "rotated-task-1.md"),
        str(report_dir / "rotated-task-2.md"),
    ]
    assert summary["selected_item_refs"] == [
        {
            "plan_item_id": items["First task"].plan_item_id,
            "status": "done",
            "plan_path": str(plan),
            "line_number": 1,
            "text": "First task",
            "selected_worktree_path": str(wt1.resolve()),
            "task_id": "rotated-task-1",
            "report_path": str(report_dir / "rotated-task-1.md"),
        },
        {
            "plan_item_id": items["Second task"].plan_item_id,
            "status": "done",
            "plan_path": str(plan),
            "line_number": 2,
            "text": "Second task",
            "selected_worktree_path": str(wt2.resolve()),
            "task_id": "rotated-task-2",
            "report_path": str(report_dir / "rotated-task-2.md"),
        },
    ]
    assert summary["preflight_snapshot"]["plan"] == str(plan)
    assert summary["preflight_snapshot"]["total"] == 2
    assert summary["preflight_snapshot"]["created_readiness"] == {"ready": 2, "stale": 0}
    assert summary["preflight_snapshot"]["agent_profile"]["name"] == "mock"
    assert summary["preflight_snapshot"]["preflight_result"] == "pass"
    assert summary["preflight_snapshot"]["next_action"] == "run_batch"


def test_autopilot_queue_run_batch_summary_json_dry_run_rotated_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()
    wt2 = pool / "wt2"
    wt2.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    summary_path = tmp_path / "batch-summary.json"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--max-items",
            "2",
            "--summary-json",
            str(summary_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== Batch summary ===" in output
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert summary["mode"] == "dry-run"
    assert summary["selected_count"] == 2
    assert summary["status_counts"] == {"created": 2}
    assert summary["selected_worktree_paths"] == [
        str(wt1.resolve()),
        str(wt2.resolve()),
    ]
    assert summary["report_paths"] == []
    assert summary["selected_item_refs"] == [
        {
            "plan_item_id": items["First task"].plan_item_id,
            "status": "created",
            "plan_path": str(plan),
            "line_number": 1,
            "text": "First task",
            "selected_worktree_path": str(wt1.resolve()),
            "task_id": None,
            "report_path": None,
        },
        {
            "plan_item_id": items["Second task"].plan_item_id,
            "status": "created",
            "plan_path": str(plan),
            "line_number": 2,
            "text": "Second task",
            "selected_worktree_path": str(wt2.resolve()),
            "task_id": None,
            "report_path": None,
        },
    ]
    assert summary["preflight_snapshot"]["plan"] == str(plan)
    assert summary["preflight_snapshot"]["total"] == 2
    assert summary["preflight_snapshot"]["created_readiness"] == {"ready": 2, "stale": 0}
    assert summary["preflight_snapshot"]["agent_profile"]["name"] == "mock"
    assert summary["preflight_snapshot"]["preflight_result"] == "pass"
    assert summary["preflight_snapshot"]["next_action"] == "run_batch"


def test_autopilot_queue_run_batch_summary_json_preserves_nonzero_exit_code(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="blocked-task-1"
        )
        return SupervisorResult(
            status="blocked",
            summary="Blocked by policy",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    summary_path = tmp_path / "batch-summary.json"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
            "--summary-json",
            str(summary_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "=== Batch summary ===" in output
    assert summary_path.exists()

    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["mode"] == "execute"
    assert summary["processed_count"] == 1
    assert summary["status_counts"] == {"blocked": 1}
    assert summary["first_non_done_item"] == {
        "plan_item_id": items["First task"].plan_item_id,
        "status": "blocked",
        "text": "First task",
        "source": f"{plan}:1",
    }
    assert summary["selected_item_refs"] == [
        {
            "plan_item_id": items["First task"].plan_item_id,
            "status": "blocked",
            "plan_path": str(plan),
            "line_number": 1,
            "text": "First task",
            "selected_worktree_path": None,
            "task_id": "blocked-task-1",
            "report_path": str(
                tmp_path / ".ai-orch" / "reports" / "blocked-task-1.md"
            ),
        },
    ]
    assert summary["preflight_snapshot"]["plan"] == str(plan)
    assert summary["preflight_snapshot"]["total"] == 2
    assert summary["preflight_snapshot"]["created_readiness"] == {"ready": 2, "stale": 0}
    assert summary["preflight_snapshot"]["agent_profile"]["name"] == "mock"
    assert summary["preflight_snapshot"]["preflight_result"] == "pass"
    assert summary["preflight_snapshot"]["next_action"] == "run_batch"


def test_autopilot_queue_run_batch_batch_report_preserves_nonzero_exit_code(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="blocked-task-1"
        )
        return SupervisorResult(
            status="blocked",
            summary="Blocked by policy",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    report_path = tmp_path / "batch-report.md"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
            "--batch-report",
            str(report_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Batch stopped after 1 item(s): status=blocked" in output
    assert str(report_path) not in output
    assert report_path.exists()

    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    report = report_path.read_text(encoding="utf-8")
    task_report_path = tmp_path / ".ai-orch" / "reports" / "blocked-task-1.md"

    assert "- Mode: `execute`" in report
    assert "- Processed: 1 item(s)" in report
    assert "- Status counts: `blocked`=1" in report
    assert f"- Queue item: `{items['First task'].plan_item_id}`" in report
    assert f"- `{task_report_path}`" in report
    assert '"status": "blocked"' in report
    assert '"task_id": "blocked-task-1"' in report
    assert '"next_action": "run_batch"' in report


def test_autopilot_queue_run_batch_preflight_snapshot_reflects_pre_execution_risk(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Ready task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="done-task-1"
        )
        return SupervisorResult(
            status="done",
            summary="Done",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    summary_path = tmp_path / "batch-summary.json"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "1",
            "--summary-json",
            str(summary_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== Batch summary ===" in output
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["mode"] == "execute"
    assert summary["processed_count"] == 1
    assert summary["status_counts"] == {"done": 1}
    assert summary["preflight_snapshot"]["total"] == 2
    assert summary["preflight_snapshot"]["created_readiness"] == {"ready": 1, "stale": 0}
    assert summary["preflight_snapshot"]["blocked_in_progress_risk"] == {
        "blocked": 1,
        "in_progress": 0,
    }
    assert summary["preflight_snapshot"]["preflight_result"] == "risk_or_unavailable"
    assert summary["preflight_snapshot"]["next_action"] == "review_blocked"


def test_autopilot_queue_status_summarizes_counts_and_recent_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Done task",
                "- [ ] Blocked task",
                "- [ ] Skipped task",
                "- [ ] Started task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")
    store.update_plan_item_status(items["Skipped task"].plan_item_id, "skipped")
    worktree = tmp_path / "worktrees" / "started"
    store.update_plan_item_status(
        items["Started task"].plan_item_id,
        "in_progress",
        selected_worktree_path=worktree,
    )

    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status" in output
    assert "total: 4" in output
    assert "by status:" in output
    assert "done=1" in output
    assert "blocked=1" in output
    assert "skipped=1" in output
    assert "in_progress=1" in output
    assert "recent started:" in output
    assert "recent done:" in output
    assert "recent blocked:" in output
    assert "recent skipped:" in output
    assert "Started task" in output
    assert f"worktree={worktree}" in output
    assert "Done task" in output
    assert "Blocked task" in output
    assert "Skipped task" in output
    assert "Autopilot selected:" not in output
    assert "Dry run" not in output


def test_autopilot_queue_status_json_summarizes_counts_and_recent_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Done task",
                "- [ ] Blocked task",
                "- [ ] Started task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")
    store.update_plan_item_status(items["Started task"].plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["schema_version"] == "1.0"
    assert payload["command"] == "autopilot queue status"
    assert payload["ok"] is True
    assert payload["plan"] == str(plan)
    assert payload["total"] == 3
    assert payload["filtered"] == 3
    assert payload["by_status"] == {"blocked": 1, "done": 1, "in_progress": 1}
    assert payload["recent"]["done"][0]["plan_item_id"] == items["Done task"].plan_item_id
    assert payload["recent"]["blocked"][0]["status"] == "blocked"
    assert payload["problem_summary"][0]["status"] == "in_progress"
    assert payload["problem_summary"][0]["count"] == 1
    assert payload["problem_summary"][1]["status"] == "blocked"
    assert payload["problem_summary"][1]["count"] == 1


def test_autopilot_queue_status_filters_recent_items_by_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Created task",
                "- [ ] Done task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "created",
            "--status",
            "blocked",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "total: 3" in output
    assert "filtered: 2 status=created,blocked" in output
    assert "created=1" in output
    assert "done=1" in output
    assert "blocked=1" in output
    assert "recent created:" in output
    assert "recent blocked:" in output
    assert "recent done:" not in output
    assert "Created task" in output
    assert "Blocked task" in output
    assert "Done task" not in output


def test_autopilot_queue_status_limits_recent_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    tasks = [f"- [ ] Task {i}" for i in range(6)]
    plan.write_text("\n".join(["# Roadmap", ""] + tasks), encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    for item in store.list_plan_items(plan_path=plan):
        store.update_plan_item_status(item.plan_item_id, "done")

    capsys.readouterr()
    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "total: 6" in output
    assert "recent done:" in output
    assert "Task 5" in output
    assert "Task 4" in output
    assert "Task 3" in output
    assert "Task 2" in output
    assert "Task 1" in output
    assert "Task 0" not in output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--limit",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Task 5" in output
    assert "Task 4" in output
    assert "Task 3" not in output
    assert "Task 2" not in output
    assert "Task 1" not in output
    assert "Task 0" not in output


def test_autopilot_queue_status_handles_missing_plan(
    capsys,
    tmp_path: Path,
) -> None:
    missing_plan = tmp_path / "MISSING.md"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Plan not found:" in output


def test_autopilot_queue_status_all_plans_ignores_missing_plan_arg(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    missing_plan = tmp_path / "MISSING.md"
    roadmap.write_text("- [ ] Roadmap blocked task\n", encoding="utf-8")
    backlog.write_text("- [ ] Backlog created task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(roadmap),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(backlog),
        ]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    roadmap_item = store.list_plan_items(plan_path=roadmap)[0]
    store.update_plan_item_status(roadmap_item.plan_item_id, "blocked")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
            "--all-plans",
            "--status",
            "blocked",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status for all persisted plans" in output
    assert "Plan not found:" not in output
    assert "total: 2" in output
    assert "filtered: 1 status=blocked" in output
    assert "recent blocked:" in output
    assert f"{roadmap}:" in output
    assert "Roadmap blocked task" in output
    assert "Backlog created task" not in output


def test_autopilot_queue_status_problem_summary_groups_by_reason_and_latest_ids(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Done task",
                "- [ ] In progress task",
                "- [ ] Blocked task A1",
                "- [ ] Blocked task A2",
                "- [ ] Blocked task B",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(
        items["Blocked task A1"].plan_item_id,
        "blocked",
        blocked_reason="needs approval",
    )
    store.update_plan_item_status(
        items["Blocked task A2"].plan_item_id,
        "blocked",
        blocked_reason="needs approval",
    )
    store.update_plan_item_status(
        items["Blocked task B"].plan_item_id,
        "blocked",
        blocked_reason="runtime budget exhausted",
    )
    store.update_plan_item_status(
        items["In progress task"].plan_item_id,
        "in_progress",
    )
    expected_in_progress = items["In progress task"].plan_item_id
    expected_a_ids = [
        items["Blocked task A2"].plan_item_id,
        items["Blocked task A1"].plan_item_id,
    ]
    expected_b_id = items["Blocked task B"].plan_item_id
    capsys.readouterr()

    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" in output
    assert f"in_progress ((no reason)): count=1 latest=[{expected_in_progress}]" in output
    assert (
        f"blocked (needs approval): count=2 latest=[{expected_a_ids[0]}, {expected_a_ids[1]}]"
        in output
    )
    assert (
        f"blocked (runtime budget exhausted): count=1 latest=[{expected_b_id}]"
        in output
    )
    # State must be preserved (read-only summary).
    refreshed = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert refreshed["In progress task"].status == "in_progress"
    assert refreshed["Blocked task A1"].status == "blocked"
    assert refreshed["Blocked task A2"].blocked_reason == "needs approval"


def test_autopilot_queue_list_problem_summary_respects_status_filter(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Created task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="policy denied",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "done",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" not in output
    assert "Blocked task" not in output


def test_autopilot_queue_list_problem_summary_groups_problem_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Blocked task",
                "- [ ] In progress task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    blocked_item = items["Blocked task"]
    in_progress_item = items["In progress task"]
    store.update_plan_item_status(
        blocked_item.plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    store.update_plan_item_status(in_progress_item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" in output
    assert (
        f"blocked (needs review): count=1 latest=[{blocked_item.plan_item_id}]"
        in output
    )
    assert (
        "in_progress ((no reason)): count=1 "
        f"latest=[{in_progress_item.plan_item_id}]"
    ) in output
    refreshed = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert refreshed["Blocked task"].status == "blocked"
    assert refreshed["In progress task"].status == "in_progress"


def test_autopilot_queue_status_problem_summary_limits_latest_ids(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join([f"- [ ] Blocked task {i}" for i in range(4)]),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_ids: list[int] = []
    for item in store.list_plan_items(plan_path=plan):
        store.update_plan_item_status(
            item.plan_item_id,
            "blocked",
            blocked_reason="same reason",
        )
        item_ids.append(item.plan_item_id)
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--limit",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" in output
    latest_two = ", ".join(str(plan_item_id) for plan_item_id in reversed(item_ids[-2:]))
    excluded = str(item_ids[0])
    assert f"blocked (same reason): count=4 latest=[{latest_two}]" in output
    assert excluded not in output.split("Problem summary:")[1].split("\n")[1]


def test_autopilot_queue_readiness_summarizes_counts_and_risk(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Ready task",
                "- [ ] Done task",
                "- [ ] Blocked task",
                "- [ ] Started task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    store.update_plan_item_status(
        items["Started task"].plan_item_id,
        "in_progress",
    )

    exit_code = main(
        ["autopilot", "queue", "readiness", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue readiness for" in output
    assert "total: 4" in output
    assert "by status:" in output
    assert "created=1" in output
    assert "done=1" in output
    assert "blocked=1" in output
    assert "in_progress=1" in output
    assert "created readiness: ready=1 stale=0" in output
    assert "blocked/in_progress risk: blocked=1 in_progress=1" in output
    assert "stale created: 0" in output
    assert "stale in_progress: 1" in output
    assert "Started task" in output
    assert "Problem summary:" in output


def test_autopilot_queue_readiness_reports_stale_created_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")

    exit_code = main(
        ["autopilot", "queue", "readiness", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]

    assert exit_code == 0
    assert "created readiness: ready=0 stale=1" in output
    assert "stale created: 1" in output
    assert "stale created items:" in output
    assert f"id={item.plan_item_id}" in output
    assert "Stale task" in output
    assert item.status == "created"


def test_autopilot_queue_readiness_keeps_open_backlog_bullets_ready(
    capsys,
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P2",
                "",
                "- Keep synced backlog bullets ready during preflight.",
            ]
        ),
        encoding="utf-8",
    )

    main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "created readiness: ready=1 stale=0" in output
    assert "stale created: 0" in output
    assert "stale created items:" not in output

    exit_code = main(
        [
            "autopilot",
            "queue",
            "preflight",
            "--repo",
            str(tmp_path),
            "--plan",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "created readiness: ready=1 stale=0" in output
    assert "stale created: 0" in output
    assert "next_action: run_batch" in output


def test_autopilot_queue_readiness_all_plans_aggregates_across_sources(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    roadmap.write_text("- [ ] Roadmap blocked task\n", encoding="utf-8")
    backlog.write_text("- [ ] Backlog stale task\n", encoding="utf-8")

    main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(roadmap)]
    )
    main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(backlog)]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    roadmap_item = store.list_plan_items(plan_path=roadmap)[0]
    store.update_plan_item_status(roadmap_item.plan_item_id, "blocked")
    backlog.write_text("- [x] Backlog stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--all-plans",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue readiness for all persisted plans" in output
    assert "total: 2" in output
    assert "created readiness: ready=0 stale=1" in output
    assert "blocked/in_progress risk: blocked=1 in_progress=0" in output
    assert str(backlog) in output
    assert "Backlog stale task" in output
    assert f"latest=[{roadmap_item.plan_item_id}]" in output


def test_autopilot_queue_readiness_handles_missing_plan(
    capsys,
    tmp_path: Path,
) -> None:
    missing_plan = tmp_path / "MISSING.md"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Plan not found:" in output


def test_autopilot_queue_readiness_limits_stale_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    tasks = [f"- [ ] Stale task {i}" for i in range(4)]
    plan.write_text("\n".join(tasks), encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("\n".join(["- [x] Stale task 0"] + tasks[1:]), encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--limit",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "stale created: 1" in output
    assert "... and 0 more" not in output
    readiness_lines = output.split("Queue readiness for")[1]
    assert readiness_lines.count("Stale task 0") == 1


def test_autopilot_queue_readiness_preserves_queue_state(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Ready task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    before = {item.plan_item_id: item.status for item in store.list_plan_items()}

    exit_code = main(
        ["autopilot", "queue", "readiness", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    after = {item.plan_item_id: item.status for item in store.list_plan_items()}

    assert exit_code == 0
    assert after == before


def test_autopilot_queue_readiness_fail_on_risk_exits_nonzero_for_stale_created(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--fail-on-risk",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "created readiness: ready=0 stale=1" in output


def test_autopilot_queue_readiness_fail_on_risk_exits_nonzero_for_blocked_or_in_progress(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Ready task",
                "- [ ] Blocked task",
                "- [ ] Started task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    store.update_plan_item_status(
        items["Started task"].plan_item_id,
        "in_progress",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--fail-on-risk",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "blocked/in_progress risk: blocked=1 in_progress=1" in output


def test_autopilot_queue_readiness_fail_on_risk_exits_zero_when_clean(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Ready task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--fail-on-risk",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "created readiness: ready=1 stale=0" in output
    assert "blocked/in_progress risk: blocked=0 in_progress=0" in output


def test_autopilot_queue_readiness_json_outputs_machine_readable_object(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Ready task",
                "- [ ] Done task",
                "- [ ] Blocked task",
                "- [ ] Started task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    store.update_plan_item_status(
        items["Started task"].plan_item_id,
        "in_progress",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    result = json.loads(output)
    assert result["plan"] == str(plan)
    assert result["total"] == 4
    assert result["by_status"] == {
        "blocked": 1,
        "created": 1,
        "done": 1,
        "in_progress": 1,
    }
    assert result["created_readiness"] == {"ready": 1, "stale": 0}
    assert result["blocked_in_progress_risk"] == {"blocked": 1, "in_progress": 1}
    assert result["stale_created"] == {"count": 0, "items": []}
    assert result["stale_in_progress"]["count"] == 1
    assert result["stale_in_progress"]["items"][0]["text"] == "Started task"
    assert result["problem_summary"] == [
        {
            "status": "in_progress",
            "reason": "(no reason)",
            "count": 1,
            "latest_ids": [items["Started task"].plan_item_id],
        },
        {
            "status": "blocked",
            "reason": "needs review",
            "count": 1,
            "latest_ids": [items["Blocked task"].plan_item_id],
        },
    ]


def test_autopilot_queue_readiness_json_all_plans_aggregates(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    roadmap.write_text("- [ ] Roadmap blocked task\n", encoding="utf-8")
    backlog.write_text("- [ ] Backlog stale task\n", encoding="utf-8")

    main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(roadmap)]
    )
    main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(backlog)]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    roadmap_item = store.list_plan_items(plan_path=roadmap)[0]
    store.update_plan_item_status(roadmap_item.plan_item_id, "blocked")
    backlog.write_text("- [x] Backlog stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--json",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    result = json.loads(output)
    assert result["plan"] == "all persisted plans"
    assert result["total"] == 2
    assert result["created_readiness"] == {"ready": 0, "stale": 1}
    assert result["blocked_in_progress_risk"] == {"blocked": 1, "in_progress": 0}
    assert result["stale_created"]["count"] == 1
    assert result["stale_created"]["items"][0]["plan_path"] == str(backlog)
    assert result["problem_summary"] == [
        {
            "status": "blocked",
            "reason": "(no reason)",
            "count": 1,
            "latest_ids": [roadmap_item.plan_item_id],
        },
    ]


def test_autopilot_queue_readiness_json_preserves_fail_on_risk(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
            "--fail-on-risk",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    result = json.loads(output)
    assert result["created_readiness"] == {"ready": 0, "stale": 1}


def test_autopilot_queue_readiness_json_handles_missing_plan(
    capsys,
    tmp_path: Path,
) -> None:
    missing_plan = tmp_path / "MISSING.md"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "readiness",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
            "--json",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    result = json.loads(output)
    assert "error" in result
    assert "Plan not found:" in result["error"]


def test_autopilot_queue_preflight_shows_readiness_and_agent_profile(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Ready task",
                "- [ ] Done task",
                "- [ ] Blocked task",
                "- [ ] Started task",
            ]
        ),
        encoding="utf-8",
    )
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="python",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    store.update_plan_item_status(
        items["Started task"].plan_item_id,
        "in_progress",
    )

    exit_code = main(
        ["autopilot", "queue", "preflight", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue preflight for" in output
    assert "total: 4" in output
    assert "created readiness: ready=1 stale=0" in output
    assert "blocked/in_progress risk: blocked=1 in_progress=1" in output
    assert "Agent profile:" in output
    assert "name: generic" in output
    assert "type: generic_cli" in output
    assert "mode: real" in output
    assert "command: python" in output
    assert "available: yes" in output
    assert "preflight_result: risk_or_unavailable" in output
    assert "next_action: recover_in_progress" in output


def test_autopilot_queue_preflight_counts_all_stale_in_progress_with_limit(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Started task one",
                "- [ ] Started task two",
            ]
        ),
        encoding="utf-8",
    )
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="python",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    for item in store.list_plan_items(plan_path=plan):
        store.update_plan_item_status(item.plan_item_id, "in_progress")
    plan.write_text("# Roadmap\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "preflight",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--limit",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "stale in_progress: 2" in output
    assert "stale in_progress items:" in output
    assert "Started task one" in output
    assert "Started task two" not in output
    assert "... and 1 more" in output


def test_autopilot_queue_preflight_preserves_queue_state(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Ready task\n", encoding="utf-8")
    write_config(tmp_path, default_agent="generic", include_generic_agent=True)

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    before = {item.plan_item_id: item.status for item in store.list_plan_items()}

    exit_code = main(
        ["autopilot", "queue", "preflight", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    after = {item.plan_item_id: item.status for item in store.list_plan_items()}

    assert exit_code == 0
    assert after == before


def test_autopilot_queue_preflight_fail_on_risk_exits_nonzero_for_readiness_risk(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")
    write_config(tmp_path, default_agent="generic", include_generic_agent=True)

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "preflight",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--fail-on-risk",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "created readiness: ready=0 stale=1" in output
    assert "preflight_result: risk_or_unavailable" in output
    assert "next_action: reconcile_stale_created" in output


def test_autopilot_queue_preflight_fail_on_risk_exits_nonzero_for_unavailable_agent(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Ready task\n", encoding="utf-8")
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="nonexistent_command_for_preflight_test",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "preflight",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--fail-on-risk",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "Agent profile:" in output
    assert "available: no" in output
    assert "preflight_result: risk_or_unavailable" in output
    assert "next_action: fix_agent" in output


def test_autopilot_queue_preflight_json_outputs_combined_object(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Ready task\n", encoding="utf-8")
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="python",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "preflight",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    result = json.loads(output)
    assert result["plan"] == str(plan)
    assert result["total"] == 1
    assert result["created_readiness"] == {"ready": 1, "stale": 0}
    assert result["agent_profile"]["name"] == "generic"
    assert result["agent_profile"]["type"] == "generic_cli"
    assert result["agent_profile"]["mode"] == "real"
    assert result["agent_profile"]["command"] == "python"
    assert result["agent_profile"]["available"] is True
    assert result["preflight_result"] == "pass"
    assert result["next_action"] == "run_batch"


def test_autopilot_queue_preflight_marks_missing_agent_config_as_risk(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    class GhostAgent:
        name = "ghost"

        def check_available(self) -> bool:
            return True

    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Ready task\n", encoding="utf-8")
    write_config(tmp_path)

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._select_agent",
        lambda config, policy_engine: GhostAgent(),
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "preflight",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
            "--fail-on-risk",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert result["agent_profile"]["name"] == "ghost"
    assert result["agent_profile"]["configured"] is False
    assert result["agent_profile"]["type"] == "(missing)"
    assert result["preflight_result"] == "risk_or_unavailable"
    assert result["next_action"] == "fix_agent"


def test_autopilot_queue_preflight_next_action_review_blocked(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Ready task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="python",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    capsys.readouterr()

    exit_code = main(
        ["autopilot", "queue", "preflight", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "next_action: review_blocked" in output


def test_autopilot_queue_preflight_handles_missing_plan(
    capsys,
    tmp_path: Path,
) -> None:
    missing_plan = tmp_path / "MISSING.md"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "preflight",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Plan not found:" in output


def test_autopilot_queue_reconcile_dry_run_reports_stale_created_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]

    assert exit_code == 0
    assert "Queue reconcile for" in output
    assert "total: 1" in output
    assert "stale_created: 1" in output
    assert "dry_run: use --apply to mark stale items skipped" in output
    assert "[stale]" in output
    assert "Stale task" in output
    assert item.status == "created"


def test_autopilot_queue_reconcile_all_plans_apply_skips_only_stale_created_items(
    capsys,
    tmp_path: Path,
) -> None:
    stale_plan = tmp_path / "STALE.md"
    current_plan = tmp_path / "CURRENT.md"
    stale_plan.write_text("- [ ] Stale task\n", encoding="utf-8")
    current_plan.write_text("- [ ] Current task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(stale_plan),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(current_plan),
        ]
    )
    stale_plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--apply",
        ]
    )
    output = capsys.readouterr().out
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items()}

    assert exit_code == 0
    assert "Queue reconcile for all persisted plans" in output
    assert "total: 2" in output
    assert "stale_created: 1" in output
    assert "skipped: 1" in output
    assert f"[stale] {stale_plan}:" in output
    assert "Stale task" in output
    assert "Current task" not in output
    assert items["Stale task"].status == "skipped"
    assert items["Current task"].status == "created"


def test_autopilot_queue_reconcile_json_dry_run_reports_scope_and_refs(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("stale task", repo_path=tmp_path)
    worktree = tmp_path / "wt"
    store.update_plan_item_status(
        item.plan_item_id,
        "created",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["plan"] == str(plan)
    assert payload["all_plans"] is False
    assert payload["total"] == 1
    assert payload["apply"] is False
    assert payload["dry_run"] is True
    assert payload["skipped"] == {"count": 0}
    assert payload["stale_created"]["count"] == 1
    stale_item = payload["stale_created"]["items"][0]
    assert stale_item["plan_item_id"] == item.plan_item_id
    assert stale_item["task_id"] == task.task_id
    assert stale_item["selected_worktree_path"] == str(worktree)
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_reconcile_json_all_plans_apply_reports_skipped_count(
    capsys,
    tmp_path: Path,
) -> None:
    stale_plan = tmp_path / "STALE.md"
    current_plan = tmp_path / "CURRENT.md"
    stale_plan.write_text("- [ ] Stale task\n", encoding="utf-8")
    current_plan.write_text("- [ ] Current task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(stale_plan),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(current_plan),
        ]
    )
    stale_plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--apply",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items()}

    assert exit_code == 0
    assert payload["plan"] == "all persisted plans"
    assert payload["all_plans"] is True
    assert payload["total"] == 2
    assert payload["apply"] is True
    assert payload["dry_run"] is False
    assert payload["skipped"] == {"count": 1}
    assert payload["stale_created"]["count"] == 1
    stale_item = payload["stale_created"]["items"][0]
    assert stale_item["plan_path"] == str(stale_plan)
    assert stale_item["status"] == "skipped"
    assert items["Stale task"].status == "skipped"
    assert items["Current task"].status == "created"


def test_autopilot_queue_recover_in_progress_dry_run_reports_stale_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "Queue recover for" in output
    assert "stale_in_progress: 1" in output
    assert "dry_run: use --apply --reason" in output
    assert "[stale_in_progress]" in output
    assert "Orphan task" in output
    assert loaded is not None
    assert loaded.status == "in_progress"
    assert loaded.blocked_reason is None


def test_autopilot_queue_recover_in_progress_apply_blocks_with_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            "--reason",
            "batch run timed out",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "stale_in_progress: 1" in output
    assert "blocked: 1" in output
    assert "batch run timed out" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "batch run timed out"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "blocked",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "reason=batch run timed out" in output


def test_autopilot_queue_recover_in_progress_older_than_hours_dry_run_filters_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Old task\n- [ ] Current task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    for item in items.values():
        store.update_plan_item_status(item.plan_item_id, "in_progress")
    old_updated_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE plan_items SET updated_at = ? WHERE plan_item_id = ?",
            (old_updated_at, items["Old task"].plan_item_id),
        )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--older-than-hours",
            "24",
        ]
    )
    output = capsys.readouterr().out
    loaded = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert exit_code == 0
    assert "stale_in_progress: 1" in output
    assert "Old task" in output
    assert "Current task" not in output
    assert loaded["Old task"].status == "in_progress"
    assert loaded["Current task"].status == "in_progress"


def test_autopilot_queue_recover_in_progress_older_than_hours_apply_blocks_only_old_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Old task\n- [ ] Current task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    for item in items.values():
        store.update_plan_item_status(item.plan_item_id, "in_progress")
    old_updated_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE plan_items SET updated_at = ? WHERE plan_item_id = ?",
            (old_updated_at, items["Old task"].plan_item_id),
        )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--older-than-hours",
            "24",
            "--apply",
            "--reason",
            "interrupted",
        ]
    )
    output = capsys.readouterr().out
    loaded = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert exit_code == 0
    assert "stale_in_progress: 1" in output
    assert "blocked: 1" in output
    assert loaded["Old task"].status == "blocked"
    assert loaded["Old task"].blocked_reason == "interrupted"
    assert loaded["Current task"].status == "in_progress"
    assert loaded["Current task"].blocked_reason is None


def test_autopilot_queue_recover_in_progress_apply_requires_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 1
    assert "--reason is required when --apply is set" in output
    assert loaded is not None
    assert loaded.status == "in_progress"


def test_autopilot_queue_recover_in_progress_older_than_hours_must_be_positive(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--older-than-hours",
            "0",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--older-than-hours must be at least 1" in output


def test_autopilot_queue_recover_in_progress_all_plans_blocks_only_in_progress(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    roadmap.write_text("- [ ] Roadmap stuck task\n", encoding="utf-8")
    backlog.write_text("\n".join(["# Backlog", "", "## P2", "", "- Backlog stuck task"]), encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(roadmap),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items()}
    store.update_plan_item_status(items["Roadmap stuck task"].plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--apply",
            "--reason",
            "interrupted",
        ]
    )
    output = capsys.readouterr().out
    loaded = {item.text: item for item in store.list_plan_items()}

    assert exit_code == 0
    assert "Queue recover for all persisted plans" in output
    assert "stale_in_progress: 1" in output
    assert "blocked: 1" in output
    assert loaded["Roadmap stuck task"].status == "blocked"
    assert loaded["Roadmap stuck task"].blocked_reason == "interrupted"
    assert loaded["Backlog stuck task"].status == "created"


def test_autopilot_queue_reconcile_stale_row_includes_refs(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("stale task", repo_path=tmp_path)
    worktree = tmp_path / "wt"
    store.update_plan_item_status(
        item.plan_item_id,
        "created",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert loaded is not None
    assert loaded.status == "created"
    assert f"task={task.task_id}" in output
    assert f"worktree={worktree}" in output
    assert f"report={report_path}" in output


def test_autopilot_queue_recover_in_progress_stale_row_includes_refs_and_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("orphan task", repo_path=tmp_path)
    worktree = tmp_path / "wt"
    store.update_plan_item_status(
        item.plan_item_id,
        "in_progress",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            "--reason",
            "interrupted",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "interrupted"
    assert f"task={task.task_id}" in output
    assert f"worktree={worktree}" in output
    assert f"report={report_path}" in output
    assert "reason=interrupted" in output


def test_autopilot_queue_recover_in_progress_json_dry_run_reports_scope_and_refs(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Old task\n- [ ] Current task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    old_task = store.create_task("old task", repo_path=tmp_path)
    worktree = tmp_path / "wt"
    store.update_plan_item_status(
        items["Old task"].plan_item_id,
        "in_progress",
        task_id=old_task.task_id,
        selected_worktree_path=worktree,
    )
    store.update_plan_item_status(items["Current task"].plan_item_id, "in_progress")
    old_updated_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE plan_items SET updated_at = ? WHERE plan_item_id = ?",
            (old_updated_at, items["Old task"].plan_item_id),
        )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--older-than-hours",
            "24",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = {item.text: item for item in store.list_plan_items(plan_path=plan)}

    assert exit_code == 0
    assert payload["plan"] == str(plan)
    assert payload["all_plans"] is False
    assert payload["apply"] is False
    assert payload["dry_run"] is True
    assert payload["older_than_hours"] == 24
    assert payload["blocked"] == {"count": 0, "reason": None}
    assert payload["applied_reason"] is None
    assert payload["stale_in_progress"]["count"] == 1
    stale_item = payload["stale_in_progress"]["items"][0]
    assert stale_item["plan_item_id"] == items["Old task"].plan_item_id
    assert stale_item["task_id"] == old_task.task_id
    assert stale_item["selected_worktree_path"] == str(worktree)
    assert loaded["Old task"].status == "in_progress"
    assert loaded["Current task"].status == "in_progress"


def test_autopilot_queue_recover_in_progress_json_apply_reports_blocked_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            "--reason",
            "interrupted",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["apply"] is True
    assert payload["dry_run"] is False
    assert payload["blocked"] == {"count": 1, "reason": "interrupted"}
    assert payload["applied_reason"] == "interrupted"
    assert payload["stale_in_progress"]["count"] == 1
    stale_item = payload["stale_in_progress"]["items"][0]
    assert stale_item["status"] == "blocked"
    assert stale_item["blocked_reason"] == "interrupted"
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "interrupted"


def test_autopilot_queue_reconcile_stale_row_omits_refs_when_unset(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[stale]" in output
    assert "task=" not in output
    assert "worktree=" not in output
    assert "report=" not in output


def test_autopilot_queue_status_shows_report_path_for_completed_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Completed task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task(
        "Completed task", repo_path=tmp_path, task_id="task-report-status"
    )
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="Completed task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.update_task_status(task.task_id, "done")
    store.update_plan_item_status(item.plan_item_id, "done", task_id=task.task_id)
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report", encoding="utf-8")

    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "recent done:" in output
    assert f"report={report_path}" in output


def test_memory_preflight_returns_failure_when_any_step_fails(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = 0

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            return ProcessResult(status="failed", exit_code=2, stdout="", stderr="bad")
        return ProcessResult(status="success", exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True)

    exit_code = main(["memory", "preflight", "--repo", str(tmp_path), "--area", "release"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "detect_changes: failed exit=2" in output
    assert "preflight summary: area=release total=2 passed=1 failed=1" in output
    assert "failures:\n  impact: failed" in output
    assert calls == 2


def test_autopilot_queue_show_prints_item_details_without_changing_state(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Queue item: {item.plan_item_id}" in output
    assert "status: created" in output
    assert f"source: {plan}:1" in output
    assert "task: Created task" in output
    assert "task_id: none" in output
    assert "report_path: none" in output
    assert "selected_worktree: none" in output
    assert "reason: none" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_show_prints_blocked_reason_and_report_path(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Done task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("Done task", repo_path=tmp_path)
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        task_id=task.task_id,
        selected_worktree_path=tmp_path / "worktree",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "status: blocked" in output
    assert f"task_id: {task.task_id}" in output
    assert f"report_path: {report_path}" in output
    assert f"selected_worktree: {tmp_path / 'worktree'}" in output
    assert "reason: needs operator review" in output
    assert loaded is not None
    assert loaded.status == "blocked"


def test_autopilot_queue_show_json_prints_item_details_without_changing_state(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("Blocked task", repo_path=tmp_path)
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")
    worktree = tmp_path / "worktree"
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        task_id=task.task_id,
        selected_worktree_path=worktree,
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
            str(item.plan_item_id),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload == {
        "plan_item_id": item.plan_item_id,
        "status": "blocked",
        "source": f"{plan}:1",
        "plan_path": str(plan),
        "line_number": 1,
        "task": "Blocked task",
        "task_id": task.task_id,
        "report_path": str(report_path),
        "selected_worktree": str(worktree),
        "selected_worktree_path": str(worktree),
        "reason": "needs operator review",
        "blocked_reason": "needs operator review",
        "plan_graph_id": None,
        "plan_graph_root_node_id": None,
    }
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_show_reports_missing_item(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "9999",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item not found: 9999" in output


def test_autopilot_queue_show_json_reports_missing_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "9999",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["command"] == "autopilot queue show"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "queue_item_not_found"
    assert payload["error"]["plan_item_id"] == 9999


def test_autopilot_queue_show_with_plan_validates_matching_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Queue item: {item.plan_item_id}" in output
    assert "status: created" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_show_with_plan_rejects_mismatched_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "ROADMAP.md"
    plan_a.write_text("- [ ] Plan A task\n", encoding="utf-8")
    plan_b = tmp_path / "BACKLOG.md"
    plan_b.write_text("- Plan B task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_a)])
    main(
        ["autopilot", "queue", "sync-backlog", "--repo", str(tmp_path), "--backlog", str(plan_b)]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_a = store.list_plan_items(plan_path=plan_a)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan_b),
            str(item_a.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item_a.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item_a.plan_item_id} does not belong to plan {plan_b}" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_requeue_dry_run_reports_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "blocked_reason: needs operator review" in output
    assert "dry_run: use --apply to move this item back to created" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_requeue_json_dry_run_reports_selected_item_and_scope(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--json",
            str(item.plan_item_id),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["mode"] == "dry_run"
    assert payload["applied"] is False
    assert payload["resulting_status"] == "blocked"
    assert payload["plan_item"]["plan_item_id"] == item.plan_item_id
    assert payload["plan_item"]["status"] == "blocked"
    assert payload["plan_item"]["blocked_reason"] == "needs operator review"
    assert payload["plan_scope"] == {
        "requested_plan": str(plan),
        "item_plan": str(plan),
        "validated": True,
    }
    assert payload["cleared_metadata"] == []
    assert payload["would_clear_metadata"] == [
        "blocked_reason",
        "task_id",
        "selected_worktree_path",
    ]
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_requeue_apply_clears_metadata_and_moves_to_created(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("Blocked task", repo_path=tmp_path, task_id="task-old")
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        task_id=task.task_id,
        selected_worktree_path=tmp_path / "old-worktree",
        blocked_reason="agent timed out",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "status: created" in output
    assert "cleared: blocked_reason, task_id, selected_worktree_path" in output
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None
    assert loaded.task_id is None
    assert loaded.selected_worktree_path is None


def test_autopilot_queue_requeue_json_apply_reports_result_and_cleared_metadata(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("Blocked task", repo_path=tmp_path, task_id="task-old")
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        task_id=task.task_id,
        selected_worktree_path=tmp_path / "old-worktree",
        blocked_reason="agent timed out",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--apply",
            "--json",
            str(item.plan_item_id),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["mode"] == "apply"
    assert payload["applied"] is True
    assert payload["resulting_status"] == "created"
    assert payload["plan_item"]["plan_item_id"] == item.plan_item_id
    assert payload["plan_item"]["status"] == "blocked"
    assert payload["plan_item"]["task_id"] == "task-old"
    assert payload["plan_item"]["selected_worktree_path"] == str(
        tmp_path / "old-worktree"
    )
    assert payload["plan_item"]["blocked_reason"] == "agent timed out"
    assert payload["plan_scope"] == {
        "requested_plan": None,
        "item_plan": str(plan),
        "validated": False,
    }
    assert payload["cleared_metadata"] == [
        "blocked_reason",
        "task_id",
        "selected_worktree_path",
    ]
    assert payload["would_clear_metadata"] == []
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None
    assert loaded.task_id is None
    assert loaded.selected_worktree_path is None


def test_autopilot_queue_requeue_apply_requires_blocked_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item.plan_item_id} is not blocked (status=created)" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_requeue_reports_missing_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--apply",
            "9999",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item not found: 9999" in output


def test_autopilot_queue_requeue_with_plan_dry_run_reports_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "dry_run: use --apply to move this item back to created" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_requeue_with_plan_apply_moves_blocked_item_to_created(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "status: created" in output
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None


def test_autopilot_queue_requeue_with_plan_rejects_mismatched_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "ROADMAP.md"
    plan_a.write_text("- [ ] Plan A task\n", encoding="utf-8")
    plan_b = tmp_path / "BACKLOG.md"
    plan_b.write_text("- Plan B task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_a)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_a = store.list_plan_items(plan_path=plan_a)[0]
    store.update_plan_item_status(
        item_a.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan_b),
            "--apply",
            str(item_a.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item_a.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item_a.plan_item_id} does not belong to plan {plan_b}" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_skip_dry_run_reports_created_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed: out of scope",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: created" in output
    assert "reason: operator reviewed: out of scope" in output
    assert "dry_run: use --apply to mark this item skipped" in output
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None


def test_autopilot_queue_skip_dry_run_json_reports_selected_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--reason",
            "operator reviewed: out of scope",
            "--json",
            str(item.plan_item_id),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["plan_item"]["plan_item_id"] == item.plan_item_id
    assert payload["plan_item"]["status"] == "created"
    assert payload["plan_scope"] == {
        "requested_plan": str(plan),
        "item_plan": str(plan),
        "validated": True,
    }
    assert payload["skip_reason"] == "operator reviewed: out of scope"
    assert payload["mode"] == "dry_run"
    assert payload["applied"] is False
    assert payload["resulting_status"] == "created"
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None


def test_autopilot_queue_skip_apply_skips_created_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"
    assert loaded.blocked_reason == "operator reviewed: out of scope"


def test_autopilot_queue_skip_apply_json_reports_resulting_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs external dependency",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed: defer until next quarter",
            "--apply",
            "--json",
            str(item.plan_item_id),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert payload["plan_item"]["plan_item_id"] == item.plan_item_id
    assert payload["plan_item"]["status"] == "blocked"
    assert payload["plan_item"]["blocked_reason"] == "needs external dependency"
    assert payload["plan_scope"] == {
        "requested_plan": None,
        "item_plan": str(plan),
        "validated": False,
    }
    assert payload["skip_reason"] == "operator reviewed: defer until next quarter"
    assert payload["mode"] == "apply"
    assert payload["applied"] is True
    assert payload["resulting_status"] == "skipped"
    assert loaded is not None
    assert loaded.status == "skipped"
    assert loaded.blocked_reason == "operator reviewed: defer until next quarter"


def test_autopilot_queue_skip_apply_skips_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs external dependency",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed: defer until next quarter",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: blocked" in output
    assert "blocked_reason: needs external dependency" in output
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"
    assert loaded.blocked_reason == "operator reviewed: defer until next quarter"


def test_autopilot_queue_skip_apply_requires_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "autopilot",
                "queue",
                "skip",
                "--repo",
                str(tmp_path),
                "--apply",
                str(item.plan_item_id),
            ]
        )
    output = capsys.readouterr().err
    loaded = store.get_plan_item(item.plan_item_id)

    assert exc.value.code == 2
    assert "--reason" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_skip_apply_rejects_non_skippable_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Done task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "done")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item.plan_item_id} cannot be skipped (status=done)" in output
    assert loaded is not None
    assert loaded.status == "done"


def test_autopilot_queue_skip_reports_missing_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed",
            "--apply",
            "9999",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item not found: 9999" in output


def test_autopilot_queue_skip_with_plan_dry_run_and_apply(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--reason",
            "operator reviewed: out of scope",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: created" in output
    assert "dry_run: use --apply to mark this item skipped" in output
    assert loaded is not None
    assert loaded.status == "created"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"


def test_autopilot_queue_skip_with_plan_apply_skips_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: blocked" in output
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"
    assert loaded.blocked_reason == "operator reviewed: out of scope"


def test_autopilot_queue_skip_with_plan_rejects_mismatched_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "ROADMAP.md"
    plan_a.write_text("- [ ] Plan A task\n", encoding="utf-8")
    plan_b = tmp_path / "BACKLOG.md"
    plan_b.write_text("- Plan B task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_a)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_a = store.list_plan_items(plan_path=plan_a)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan_b),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item_a.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item_a.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item_a.plan_item_id} does not belong to plan {plan_b}" in output
    assert loaded is not None
    assert loaded.status == "created"


def write_config(
    repo: Path,
    command_name: str = "custom",
    command_run: str = "python -c \"print('ok')\"",
    deny_patterns: list[str] | None = None,
    require_approval_patterns: list[str] | None = None,
    default_agent: str = "mock",
    fallback_agents: list[str] | None = None,
    include_generic_agent: bool = False,
    include_codex_agent: bool = False,
    include_claude_agent: bool = False,
    cli_alias_agents: dict[str, str] | None = None,
    cli_alias_commands: dict[str, str | None] | None = None,
    cli_alias_args: dict[str, list[str] | None] | None = None,
    generic_command: str = "python",
    generic_args: list[str] | None = None,
    include_memory: bool = False,
    memory_project: str = "",
    max_runtime_sec: int | None = None,
) -> None:
    config_dir = repo / ".ai-orch"
    config_dir.mkdir(parents=True, exist_ok=True)
    deny_patterns = deny_patterns or []
    require_approval_patterns = require_approval_patterns or []
    policy_section = ""
    if deny_patterns or require_approval_patterns:
        deny_lines = "\n".join(f'    - "{pattern}"' for pattern in deny_patterns)
        approval_lines = "\n".join(
            f'    - "{pattern}"' for pattern in require_approval_patterns
        )
        policy_section = "\npolicy:\n"
        if deny_patterns:
            policy_section += f"  deny:\n{deny_lines}\n"
        if require_approval_patterns:
            policy_section += f"  require_approval:\n{approval_lines}\n"
    agent_blocks = [
        """
  mock:
    enabled: true
    type: "mock"
""".rstrip()
    ]
    if include_generic_agent:
        rendered_args = generic_args or [
            "-c",
            "import sys; print(sys.argv[1])",
            "{prompt}",
        ]
        generic_arg_lines = "\n".join(f'      - "{arg}"' for arg in rendered_args)
        agent_blocks.append(
            """
  generic:
    enabled: true
    type: "generic_cli"
    command: "{generic_command}"
    args:
{generic_arg_lines}
    timeout_sec: 30
""".format(
                generic_command=generic_command,
                generic_arg_lines=generic_arg_lines,
            ).rstrip()
        )
    if include_codex_agent:
        agent_blocks.append(
            """
  codex:
    enabled: true
    type: "codex_exec"
    command: "python"
    args:
      - "-c"
      - "print('codex ok')"
    timeout_sec: 30
""".rstrip()
        )
    if include_claude_agent:
        agent_blocks.append(
            """
  claude:
    enabled: true
    type: "claude_headless"
    command: "python"
    args:
      - "-c"
      - "print('claude ok')"
    timeout_sec: 30
""".rstrip()
        )
    cli_alias_commands = cli_alias_commands or {}
    cli_alias_args = cli_alias_args or {}
    for agent_name, agent_type in (cli_alias_agents or {}).items():
        command = cli_alias_commands.get(agent_name, "python")
        command_line = f'    command: "{command}"\n' if command is not None else ""
        args = cli_alias_args.get(
            agent_name,
            [
                "-c",
                f"print('{agent_name} ok')",
            ],
        )
        args_lines = ""
        if args is not None:
            rendered_args = "\n".join(f'      - "{arg}"' for arg in args)
            args_lines = f"    args:\n{rendered_args}\n"
        agent_blocks.append(
            f"""
  {agent_name}:
    enabled: true
    type: "{agent_type}"
{command_line}{args_lines}    timeout_sec: 30
""".rstrip()
        )
    agents_section = "agents:\n" + "\n".join(agent_blocks)
    fallback_section = ""
    if fallback_agents:
        fallback_lines = "\n".join(f'    - "{agent}"' for agent in fallback_agents)
        fallback_section = f"  fallback_agents:\n{fallback_lines}\n"
    runtime_section = ""
    if max_runtime_sec is not None:
        runtime_section = f"  max_runtime_sec: {max_runtime_sec}\n"
    memory_section = ""
    if include_memory:
        memory_section = f"""

memory:
  provider: "codebase-memory-mcp"
  command:
    - "codebase-memory-mcp"
    - "cli"
  project: "{memory_project}"
  timeout_sec: 45
"""

    (config_dir / "config.yaml").write_text(
        f"""
orchestrator:
  default_agent: "{default_agent}"
{fallback_section}{runtime_section}  max_iterations: 3

{agents_section}

verification:
  commands:
    - name: "{command_name}"
      run: "{command_run}"
      timeout_sec: 30
{policy_section}
{memory_section}
""".lstrip(),
        encoding="utf-8",
    )
