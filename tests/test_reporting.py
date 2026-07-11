from pathlib import Path

from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.reporting.markdown import render_task_report
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.tools import ToolBroker, make_process_tool_call
from ai_orchestrator.verification.runner import VerificationResult


def test_render_task_report_includes_iterations_and_checks(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
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
        agent_summary="updated report fixture",
        files_changed=["README.md"],
        tool_actions=["write README.md"],
        exit_reason="success",
        uncertainty="low",
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
        {"source": "test"},
    )
    store.record_action(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="test-report-action",
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
        idempotency_key="test-report-brokered",
    )
    broker.run(
        broker_call,
        lambda _call: {"stdout": "broker ok", "stderr": "", "exit_code": 0},
    )
    leased_action = store.record_action(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="test-report-lease",
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
        reason="Verification failed: lint",
        follow_up_prompt="Fix lint",
        failed_checks=[
            {
                "name": "lint",
                "status": "failed",
                "exit_code": 1,
                "output_excerpt": "lint failed",
            }
        ],
    )
    lesson = store.record_memory_lesson(
        source_task_id=task.task_id,
        source_iteration_id=iteration.iteration_id,
        lesson="Remember to rerun lint after formatting",
        outcome_status="blocked",
        failure_reason="Verification failed: lint",
        failed_checks=[{"name": "lint", "status": "failed"}],
        follow_up_prompt="Fix lint",
    )
    store.add_reflection_record(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        reflection_type="failed_verification",
        failure_reason="Verification failed: lint",
        failed_checks=[{"name": "lint", "status": "failed"}],
        follow_up_prompt="Fix lint",
    )
    store.record_memory_influence(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        lesson_id=lesson.lesson_id,
        reason="selected for planning",
    )
    graph = store.create_plan_graph("Report graph")
    node = store.add_plan_graph_node(
        graph.graph_id,
        "report-node",
        "Report node",
        status="done",
        task_text="Render a PlanGraph-aware report",
        acceptance_criteria=["PlanGraph section is present"],
        verification_requirement="python -m pytest tests/test_reporting.py",
        task_id=task.task_id,
    )
    store.update_task_status(task.task_id, "done")

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert f"# ai-orch report: {task.task_id}" in report
    assert f"- Run id: `{store.run_id_for_task(task.task_id)}`" in report
    assert "- Status: `done`" in report
    assert "- Iterations: `1`" in report
    assert "- Verification runs: `1` (`passed`: 1)" in report
    assert "- Task events: `4`" in report
    assert "- Action records: `3` (`started`: 1, `succeeded`: 2)" in report
    assert "- Replan decisions: `1`" in report
    assert "- Memory lessons: `1`" in report
    assert "- Reflection records: `1`" in report
    assert "- Memory influences: `1`" in report
    assert "- Timeline entries:" in report
    assert "- Verification verdict: `verified`" in report
    assert "final supervisor decision is backed by passing checks: `unit`" in report
    assert "- Final decision: `done`" in report
    assert "- Final reason: Verification passed: unit" in report
    assert "## PlanGraph" in report
    assert f"- Graph: `{graph.graph_id}` status=`active` title=Report graph" in report
    assert "- Graph progress: `done`: 1" in report
    assert (
        f"- Node: `{node.node_id}` key=`report-node` status=`done` attempts=`0`"
        in report
    )
    assert "- Node task: Render a PlanGraph-aware report" in report
    assert "- Acceptance criteria: PlanGraph section is present" in report
    assert (
        "- Verification requirement: python -m pytest tests/test_reporting.py"
        in report
    )
    assert "### Iteration 1" in report
    assert "## Timeline" in report
    assert "task.created" in report
    assert "iteration.recorded" in report
    assert "verification.recorded" in report
    assert "reflection.failed_verification" in report
    assert "memory.influence" in report
    assert "action.recorded" in report
    assert '"source": "test"' in report
    assert "## Actions" in report
    assert "- `1`: `verification_command` status=`succeeded`" in report
    assert "key=`test-report-action`" in report
    assert "- Command: `python -m pytest`" in report
    assert "- `2`: `process.read` status=`succeeded`" in report
    assert "- Requested action: `process.read`" in report
    assert "- Risk: category=`shell` tier=`read` approval_required=`False`" in report
    assert "- Decision: `allow` reason=No blocking policy matched" in report
    assert "- Outcome: `succeeded` summary=process.read succeeded" in report
    assert '- Output preview: `{"exit_code": 0, "stderr": "", "stdout": "broker ok"}`' in report
    assert "- Provenance: source=`process.read` actor=`tool_broker`" in report
    assert "- `3`: `tool_call` status=`started`" in report
    assert "- Lease owner: `worker-1`" in report
    assert "- Lease expires: `2026-01-01T00:00:30+00:00`" in report
    assert "- Heartbeat: `2026-01-01T00:00:00+00:00`" in report
    assert "## Replan Decisions" in report
    assert "- `1`: status=`continue` source=`verification`" in report
    assert "- Reason: Verification failed: lint" in report
    assert "- Failed checks: lint: failed" in report
    assert "- Follow-up prompt: Fix lint" in report
    assert "## Memory Lessons" in report
    assert "Remember to rerun lint after formatting" in report
    assert "## Reflections" in report
    assert "`failed_verification`" in report
    assert "## Memory Influence" in report
    assert "selected for planning" in report
    assert "- Agent summary: updated report fixture" in report
    assert "- Files changed: `1`" in report
    assert "- Tool actions: `1`" in report
    assert "- Exit reason: success" in report
    assert "- Uncertainty: low" in report
    assert "- `README.md`" in report
    assert "- write README.md" in report
    assert "- `unit`: `passed` exit=`0`" in report


def test_render_task_report_returns_none_for_missing_task(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    assert render_task_report(store, "missing-task") is None


def test_render_task_report_includes_selected_queue_worktree_path(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo queue worktree", repo_path=tmp_path)
    worktree = tmp_path / "worktrees" / "task-1"
    store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Run queue item in a rotated worktree",
        status="in_progress",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert f"- Queue worktree: `{worktree}`" in report


def test_render_task_report_includes_failed_verification_excerpt(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo failure", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo failure",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Verification failed after 1 iteration(s): unit: failed exit=1",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="ignored stdout",
            stderr="assertion failed on line 10",
        ),
    )

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert "- `unit`: `failed` exit=`1`" in report
    assert "- Verification verdict: `not_verified`" in report
    assert "final verification is not fully passing (`unit`: `failed`)" in report
    assert "assertion failed on line 10" in report
    assert "```text" in report


def test_render_task_report_includes_approval_history(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo approval report", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo approval report",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Approval required",
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push origin main",
        reason="Policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="Approved by operator",
    )
    store.record_approval_retry(
        approval.approval_id,
        status="failed",
        exit_code=1,
        error="retry failed",
    )

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert "- Approval requests: `1` (`approved`: 1)" in report
    assert "## Approvals" in report
    assert f"- `{approval.approval_id}`: `approved`" in report
    assert "source=`verification` iteration=`1`" in report
    assert "- Command: `git push origin main`" in report
    assert "- Reason: Policy requires approval" in report
    assert "- Resolution: Approved by operator" in report
    assert "- Retry count: `1`" in report
    assert "- Last retry: `failed` exit=`1`" in report
    assert "- Last retry error: retry failed" in report


def test_render_task_report_redacts_secret_like_verification_output(tmp_path: Path) -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo secret", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo secret",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Verification failed after 1 iteration(s): unit: failed exit=1",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="",
            stderr=f"leaked {secret}",
        ),
    )

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert secret not in report
    assert "***REDACTED***" in report


def test_render_task_report_includes_unavailable_agent_blocker(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo unavailable", repo_path=tmp_path)
    store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="generic",
        agent_status="unavailable",
        prompt="demo unavailable",
        raw_output="",
        decision_status="blocked",
        decision_reason="Agent is not available",
    )
    store.update_task_status(task.task_id, "blocked")

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert "- Status: `blocked`" in report
    assert "- Iterations: `1`" in report
    assert "- Verification runs: `0`" in report
    assert "- Verification verdict: `not_verified`" in report
    assert "- Verification note: no final verification run was recorded" in report
    assert "- Final decision: `blocked`" in report
    assert "- Agent: `generic`" in report
    assert "- Agent status: `unavailable`" in report
    assert "- Reason: Agent is not available" in report
    assert "- No verification runs recorded." in report
