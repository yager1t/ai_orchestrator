from pathlib import Path

from ai_orchestrator.agents.base import AgentResult, SessionRef, TaskContext
from ai_orchestrator.agents.mock import MockAgentAdapter
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessResult, RunOptions
from ai_orchestrator.core.supervisor import Supervisor
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.runner import (
    VerificationCommand,
    VerificationResult,
    VerificationRunner,
)


class UnavailableAgent(MockAgentAdapter):
    def check_available(self) -> bool:
        return False

    def start_session(self, context: TaskContext) -> SessionRef:
        raise AssertionError("Supervisor must not start unavailable agents")


class RetryingAgent(MockAgentAdapter):
    def __init__(self) -> None:
        self.continue_prompts: list[str] = []

    def continue_session(self, session: SessionRef, prompt: str):
        self.continue_prompts.append(prompt)
        return self.run_step(session, prompt)


class BlockedAgent(MockAgentAdapter):
    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        return AgentResult(
            status="blocked",
            raw_output="",
            session_id=session.session_id,
            error="Denied by pattern: dangerous",
        )


class StopRecordingAgent(MockAgentAdapter):
    def __init__(self) -> None:
        self.stopped_sessions: list[str] = []

    def stop_session(self, session: SessionRef) -> None:
        self.stopped_sessions.append(session.session_id)


class PromptRecordingAgent(MockAgentAdapter):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        self.prompts.append(prompt)
        return super().run_step(session, prompt)


class InterruptingAgent(StopRecordingAgent):
    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        raise KeyboardInterrupt


class CancellingDuringRunAgent(StopRecordingAgent):
    def __init__(self, store: StateStore, task_id: str) -> None:
        super().__init__()
        self.store = store
        self.task_id = task_id

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        self.store.update_task_status(self.task_id, "cancelled")
        return AgentResult(
            status="success",
            raw_output="cancelled",
            session_id=session.session_id,
        )


class ReturningCancelledAgent(StopRecordingAgent):
    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        return AgentResult(
            status="cancelled",
            raw_output="cancelled",
            session_id=session.session_id,
        )


class NoChangeAgent(MockAgentAdapter):
    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        return AgentResult(
            status="success",
            raw_output="same output",
            session_id=session.session_id,
        )

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        return self.run_step(session, prompt)


class NoisyNoChangeAgent(MockAgentAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        self.calls += 1
        return AgentResult(
            status="success",
            raw_output=f"log line {self.calls}",
            session_id=session.session_id,
        )

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        return self.run_step(session, prompt)


class SequencedVerifier(VerificationRunner):
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.calls = 0

    def run_many(
        self,
        commands: list[VerificationCommand],
        cwd: Path | None = None,
    ) -> list[VerificationResult]:
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return [
            VerificationResult(
                name="unit",
                status=status,
                exit_code=0 if status == "passed" else 1,
                stdout="ok" if status == "passed" else "",
                stderr="" if status == "passed" else "assertion failed",
            )
        ]


class SnapshotRunner:
    def __init__(self, snapshots: list[str]) -> None:
        self.snapshots = snapshots
        self.calls = 0

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        snapshot = self.snapshots[min(self.calls, len(self.snapshots) - 1)]
        self.calls += 1
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout=snapshot,
            stderr="",
        )


class FailingSnapshotRunner:
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        self.calls = 0

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        error = self.errors[min(self.calls, len(self.errors) - 1)]
        self.calls += 1
        return ProcessResult(
            status="failed",
            exit_code=128,
            stdout="",
            stderr=error,
        )


class SequenceClock:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.calls = 0

    def __call__(self) -> float:
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def test_supervisor_done_only_after_verification_passes() -> None:
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=VerificationRunner(),
        verification_commands=[
            VerificationCommand("ok", "python -c \"print('ok')\""),
        ],
    )
    result = supervisor.run_once(task="demo", repo=Path("."))

    assert result.status == "done"


def test_supervisor_adds_planning_context_to_initial_prompt() -> None:
    agent = PromptRecordingAgent()
    supervisor = Supervisor(
        agent=agent,
        verifier=VerificationRunner(),
        verification_commands=[
            VerificationCommand("ok", "python -c \"print('ok')\""),
        ],
    )

    result = supervisor.run_once(
        task="demo",
        repo=Path("."),
        planning_context="architecture summary",
    )

    assert result.status == "done"
    assert agent.prompts == [
        (
            "demo\n\n"
            "Planning context (read-only, non-authoritative):\n\n"
            "architecture summary"
        )
    ]


def test_supervisor_stops_session_after_done() -> None:
    agent = StopRecordingAgent()
    supervisor = Supervisor(
        agent=agent,
        verifier=VerificationRunner(),
        verification_commands=[
            VerificationCommand("ok", "python -c \"print('ok')\""),
        ],
    )

    result = supervisor.run_once(task="demo", repo=Path("."))

    assert result.status == "done"
    assert len(agent.stopped_sessions) == 1


def test_supervisor_stops_session_on_keyboard_interrupt() -> None:
    agent = InterruptingAgent()
    supervisor = Supervisor(
        agent=agent,
        verifier=VerificationRunner(),
        verification_commands=[],
    )

    try:
        supervisor.run_once(task="demo", repo=Path("."))
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("Expected KeyboardInterrupt")

    assert len(agent.stopped_sessions) == 1


def test_supervisor_does_not_resume_cancelled_task(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path, status="cancelled")
    agent = StopRecordingAgent()
    supervisor = Supervisor(
        agent=agent,
        verifier=VerificationRunner(),
        state_store=store,
    )

    result = supervisor.run_existing(task_id=task.task_id, task="demo", repo=tmp_path)

    assert result.status == "cancelled"
    assert result.task_id == task.task_id
    assert agent.stopped_sessions == []
    assert store.list_iterations(task.task_id) == []


def test_supervisor_skips_verification_when_task_cancelled_during_run(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    agent = CancellingDuringRunAgent(store=store, task_id=task.task_id)
    verifier = SequencedVerifier(["passed"])
    supervisor = Supervisor(
        agent=agent,
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
    )

    result = supervisor.run_existing(task_id=task.task_id, task="demo", repo=tmp_path)

    assert result.status == "cancelled"
    assert verifier.calls == 0
    assert len(agent.stopped_sessions) == 1
    assert store.list_iterations(task.task_id) == []


def test_supervisor_marks_agent_cancelled_result_as_cancelled(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    supervisor = Supervisor(
        agent=ReturningCancelledAgent(),
        verifier=SequencedVerifier(["passed"]),
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
    )

    result = supervisor.run_once(task="demo cancelled result", repo=tmp_path)

    assert result.status == "cancelled"
    assert result.task_id is not None
    task = store.get_task(result.task_id)
    assert task is not None
    assert task.status == "cancelled"
    assert store.list_iterations(result.task_id) == []
    assert any(
        event.event_type == "task_cancelled"
        for event in store.list_task_events(result.task_id)
    )


def test_supervisor_blocks_before_verification_when_runtime_budget_exhausted(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    verifier = SequencedVerifier(["passed"])
    supervisor = Supervisor(
        agent=StopRecordingAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
        max_runtime_sec=10,
        clock=SequenceClock([0, 0, 11]),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.summary == "Runtime budget exhausted"
    assert verifier.calls == 0
    assert result.task_id is not None
    task = store.get_task(result.task_id)
    assert task is not None
    assert task.status == "blocked"


def test_supervisor_records_blocked_run_reflection_and_lesson(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    supervisor = Supervisor(
        agent=BlockedAgent(),
        verifier=SequencedVerifier(["passed"]),
        state_store=store,
        max_iterations=1,
    )

    result = supervisor.run_once("do risky work", repo=tmp_path)

    reflections = store.list_reflection_records(result.task_id)
    lessons = [
        lesson
        for lesson in store.list_memory_lessons(include_stale=True)
        if lesson.source_task_id == result.task_id
    ]
    assert result.status == "blocked"
    assert [reflection.reflection_type for reflection in reflections] == ["blocked_run"]
    assert lessons[0].lesson.startswith("blocked run:")
    assert lessons[0].outcome_status == "blocked"


def test_supervisor_records_failed_verification_reflection_and_lesson(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=SequencedVerifier(["failed"]),
        state_store=store,
        max_iterations=1,
    )

    result = supervisor.run_once("fix tests", repo=tmp_path)

    reflections = store.list_reflection_records(result.task_id)
    lessons = [
        lesson
        for lesson in store.list_memory_lessons(include_stale=True)
        if lesson.source_task_id == result.task_id
    ]
    assert result.status == "blocked"
    assert {reflection.reflection_type for reflection in reflections} == {
        "blocked_run",
        "failed_verification",
    }
    assert any(lesson.lesson.startswith("failed verification:") for lesson in lessons)
    assert all(lesson.failed_checks for lesson in lessons)


def test_supervisor_injects_active_memory_lessons_as_non_authoritative_context(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    seed_task = store.create_task("seed", repo_path=tmp_path)
    lesson = store.record_memory_lesson(
        source_task_id=seed_task.task_id,
        lesson="Check policy denial before retry",
        outcome_status="blocked",
    )
    agent = PromptRecordingAgent()
    supervisor = Supervisor(
        agent=agent,
        verifier=SequencedVerifier(["passed"]),
        state_store=store,
        max_iterations=1,
    )

    result = supervisor.run_once("use lessons", repo=tmp_path)

    influences = store.list_memory_influence(result.task_id)
    assert result.status == "done"
    assert "Planning context (read-only, non-authoritative):" in agent.prompts[0]
    assert "Check policy denial before retry" in agent.prompts[0]
    assert [(item.lesson_id, item.injected) for item in influences] == [
        (lesson.lesson_id, True)
    ]


def test_supervisor_ranks_memory_lessons_by_task_text_and_configured_limit(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    seed_task = store.create_task("seed", repo_path=tmp_path)
    relevant_lessons = [
        store.record_memory_lesson(
            source_task_id=seed_task.task_id,
            lesson=f"Flaky verifier recovery lesson {index}: write marker before retry",
            outcome_status="blocked",
        )
        for index in range(4)
    ]
    for index in range(5):
        store.record_memory_lesson(
            source_task_id=seed_task.task_id,
            lesson=f"Documentation-only release note lesson {index}",
            outcome_status="blocked",
        )
    agent = PromptRecordingAgent()
    supervisor = Supervisor(
        agent=agent,
        verifier=SequencedVerifier(["passed"]),
        state_store=store,
        max_iterations=1,
        memory_lesson_limit=4,
    )

    result = supervisor.run_once("fix flaky verifier recovery retry", repo=tmp_path)

    influences = store.list_memory_influence(result.task_id)
    injected_ids = {item.lesson_id for item in influences}
    assert result.status == "done"
    assert injected_ids == {lesson.lesson_id for lesson in relevant_lessons}
    assert "Flaky verifier recovery lesson" in agent.prompts[0]
    assert "Documentation-only release note lesson" not in agent.prompts[0]
    assert all(
        influence.reason
        == "ranked active lesson selected for supervisor planning context"
        for influence in influences
    )


def test_supervisor_logs_metadata_without_task_or_output(caplog) -> None:
    secret = "secret-task-token"
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=VerificationRunner(),
        verification_commands=[
            VerificationCommand("ok", "python -c \"print('ok')\""),
        ],
    )

    with caplog.at_level("DEBUG", logger="ai_orchestrator.core.supervisor"):
        result = supervisor.run_once(task=f"demo {secret}", repo=Path("."))

    assert result.status == "done"
    assert secret not in caplog.text
    assert "event=supervisor.iteration_started" in caplog.text
    assert "event=supervisor.run_done" in caplog.text


def test_supervisor_blocks_when_verification_fails() -> None:
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=VerificationRunner(),
        verification_commands=[
            VerificationCommand("fail", "python -c \"import sys; sys.exit(2)\""),
        ],
    )
    result = supervisor.run_once(task="demo", repo=Path("."))

    assert result.status == "blocked"
    assert "Verification failed after" in result.summary


def test_supervisor_continues_after_failed_verification() -> None:
    agent = RetryingAgent()
    verifier = SequencedVerifier(["failed", "passed"])
    supervisor = Supervisor(
        agent=agent,
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        max_iterations=2,
    )
    result = supervisor.run_once(task="demo", repo=Path("."))

    assert result.status == "done"
    assert verifier.calls == 2
    assert len(agent.continue_prompts) == 1
    assert "Previous verification failed" in agent.continue_prompts[0]


def test_supervisor_records_replan_decision_after_failed_verification(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    agent = RetryingAgent()
    verifier = SequencedVerifier(["failed", "passed"])
    supervisor = Supervisor(
        agent=agent,
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
        max_iterations=2,
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "done"
    assert result.task_id is not None
    decisions = store.list_replan_decisions(result.task_id)
    assert len(decisions) == 1
    assert decisions[0].source == "verification"
    assert decisions[0].status == "continue"
    assert decisions[0].reason == "Verification failed: unit: failed exit=1"
    assert decisions[0].failed_checks == [
        {
            "name": "unit",
            "status": "failed",
            "exit_code": 1,
            "error": None,
            "output_excerpt": "assertion failed",
        }
    ]
    assert decisions[0].follow_up_prompt is not None
    assert "Previous verification failed" in decisions[0].follow_up_prompt


def test_supervisor_persists_iterations_and_verification_runs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    verifier = SequencedVerifier(["passed"])
    supervisor = Supervisor(
        agent=MockAgentAdapter(
            scripted_output="structured output",
            scripted_files_changed=["README.md"],
            scripted_tool_actions=["write README.md"],
            scripted_uncertainty="low",
        ),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
        max_iterations=1,
    )
    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "done"
    assert result.task_id is not None
    task = store.get_task(result.task_id)
    iterations = store.list_iterations(result.task_id)
    verification_runs = store.list_verification_runs(result.task_id)
    action_records = store.list_action_records(result.task_id)

    assert task is not None
    assert task.status == "done"
    assert [item.decision_status for item in iterations] == ["done"]
    assert iterations[0].agent_summary == "structured output"
    assert iterations[0].files_changed == ["README.md"]
    assert iterations[0].tool_actions == ["write README.md"]
    assert iterations[0].exit_reason == "success"
    assert iterations[0].uncertainty == "low"
    assert [item.status for item in verification_runs] == ["passed"]
    assert len(action_records) == 1
    assert action_records[0].iteration_id == iterations[0].iteration_id
    assert action_records[0].action_type == "verification_command"
    assert action_records[0].status == "succeeded"
    assert action_records[0].command_string == "ignored"
    assert action_records[0].policy_action == "allow"
    assert action_records[0].payload["tool_name"] == "verification.run"
    assert action_records[0].payload["risk_tier"] == "read"
    assert action_records[0].payload["arguments"] == {
        "name": "unit",
        "verification_id": verification_runs[0].verification_id,
        "timeout_sec": 300,
        "command": "ignored",
    }
    assert action_records[0].result["tool_name"] == "verification.run"
    assert action_records[0].result["status"] == "succeeded"
    assert action_records[0].result["output"] == {
        "verification_id": verification_runs[0].verification_id,
        "status": "passed",
        "exit_code": 0,
        "error": None,
    }
    assert action_records[0].idempotency_key.startswith(
        f"task:{result.task_id}:iteration:{iterations[0].iteration_id}:verification:"
    )


def test_supervisor_persists_verification_approval_request(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    command = "git push origin main"
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=VerificationRunner(policy_engine=PolicyEngine()),
        verification_commands=[
            VerificationCommand("deploy", command),
        ],
        state_store=store,
        max_iterations=1,
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.task_id is not None
    approvals = store.list_approval_requests(task_id=result.task_id)
    iterations = store.list_iterations(result.task_id)
    assert len(approvals) == 1
    assert len(iterations) == 1
    assert approvals[0].status == "pending"
    assert approvals[0].source == "verification"
    assert approvals[0].command_string == command
    assert approvals[0].iteration_id == iterations[0].iteration_id
    assert "Requires approval" in approvals[0].reason


def test_supervisor_keeps_policy_denial_visible_in_event_log(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=VerificationRunner(policy_engine=PolicyEngine()),
        verification_commands=[
            VerificationCommand("danger", "rm -rf /"),
        ],
        state_store=store,
        max_iterations=1,
    )

    result = supervisor.run_once(task="demo denied policy", repo=tmp_path)

    assert result.status == "blocked"
    assert result.task_id is not None
    events = store.list_task_events(result.task_id)
    assert any(event.event_type == "command_denied" for event in events)
    assert any(
        event.event_type == "verification_finished"
        and event.payload["results"][0]["status"] == "policy_denied"
        for event in events
    )


def test_supervisor_resume_appends_next_iteration_index(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo",
        raw_output="previous",
        decision_status="blocked",
        decision_reason="previous failure",
    )
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=SequencedVerifier(["passed"]),
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
        max_iterations=1,
    )
    result = supervisor.run_existing(task_id=task.task_id, task="demo", repo=tmp_path)
    iterations = store.list_iterations(task.task_id)

    assert result.status == "done"
    assert [item.iteration_index for item in iterations] == [1, 2]


def test_supervisor_records_durable_lifecycle_events(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    supervisor = Supervisor(
        agent=MockAgentAdapter(),
        verifier=SequencedVerifier(["passed"]),
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
        max_iterations=1,
    )

    result = supervisor.run_once(task="demo lifecycle", repo=tmp_path)

    assert result.status == "done"
    assert result.task_id is not None
    events = store.list_task_events(result.task_id)
    event_types = [event.event_type for event in events]
    assert "task_created" in event_types
    assert "iteration_started" in event_types
    assert "agent_called" in event_types
    assert "agent_result_received" in event_types
    assert "verification_started" in event_types
    assert "verification_finished" in event_types
    assert "decision_made" in event_types
    assert "iteration_finished" in event_types
    assert "task_done" in event_types
    assert event_types.count("checkpoint_saved") >= 4
    assert all(event.run_id == store.run_id_for_task(result.task_id) for event in events)
    assert any(event.iteration_id == 1 for event in events if event.event_type == "task_done")


def test_supervisor_interrupted_task_can_be_inspected(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    supervisor = Supervisor(
        agent=InterruptingAgent(),
        verifier=VerificationRunner(),
        verification_commands=[],
        state_store=store,
    )

    try:
        supervisor.run_once(task="demo interrupt", repo=tmp_path)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("Expected KeyboardInterrupt")

    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].status == "running"
    event_types = [event.event_type for event in store.list_task_events(tasks[0].task_id)]
    assert "task_created" in event_types
    assert "agent_called" in event_types
    assert "checkpoint_saved" in event_types
    assert store.list_task_timeline(tasks[0].task_id)


def test_supervisor_blocks_when_agent_unavailable() -> None:
    supervisor = Supervisor(
        agent=UnavailableAgent(),
        verifier=VerificationRunner(),
        verification_commands=[
            VerificationCommand("ok", "python -c \"print('ok')\""),
        ],
    )
    result = supervisor.run_once(task="demo", repo=Path("."))

    assert result.status == "blocked"
    assert result.summary == "Agent is not available"


def test_supervisor_records_iteration_when_agent_unavailable(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    supervisor = Supervisor(
        agent=UnavailableAgent(),
        verifier=VerificationRunner(),
        verification_commands=[
            VerificationCommand("ok", "python -c \"print('ok')\""),
        ],
        state_store=store,
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.task_id is not None
    task = store.get_task(result.task_id)
    iterations = store.list_iterations(result.task_id)
    assert task is not None
    assert task.status == "blocked"
    assert len(iterations) == 1
    assert iterations[0].agent_name == "mock"
    assert iterations[0].agent_status == "unavailable"
    assert iterations[0].decision_status == "blocked"
    assert iterations[0].decision_reason == "Agent is not available"


def test_supervisor_skips_verification_when_agent_blocks(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    verifier = SequencedVerifier(["passed"])
    supervisor = Supervisor(
        agent=BlockedAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.task_id is not None
    assert verifier.calls == 0
    iterations = store.list_iterations(result.task_id)
    verification_runs = store.list_verification_runs(result.task_id)
    assert len(iterations) == 1
    assert iterations[0].agent_status == "blocked"
    assert iterations[0].decision_reason == "Denied by pattern: dangerous"
    assert verification_runs == []


def test_supervisor_blocks_after_repeated_no_change(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    verifier = SequencedVerifier(["failed", "failed", "passed"])
    supervisor = Supervisor(
        agent=NoChangeAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
        max_iterations=3,
        max_no_change_iterations=2,
        process_runner=SnapshotRunner([""]),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.task_id is not None
    assert result.summary == "No agent file or repository change detected for 2 iteration(s)"
    assert verifier.calls == 2
    iterations = store.list_iterations(result.task_id)
    assert [item.decision_status for item in iterations] == ["continue", "blocked"]


def test_supervisor_blocks_no_change_with_noisy_output(tmp_path: Path) -> None:
    verifier = SequencedVerifier(["failed", "failed", "passed"])
    supervisor = Supervisor(
        agent=NoisyNoChangeAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        max_iterations=3,
        max_no_change_iterations=2,
        process_runner=SnapshotRunner([""]),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.summary == "No agent file or repository change detected for 2 iteration(s)"
    assert verifier.calls == 2


def test_supervisor_repo_snapshot_change_resets_no_change_counter(tmp_path: Path) -> None:
    verifier = SequencedVerifier(["failed", "failed", "passed"])
    supervisor = Supervisor(
        agent=NoChangeAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        max_iterations=3,
        max_no_change_iterations=2,
        process_runner=SnapshotRunner([" M file.py", " M other.py"]),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "done"
    assert verifier.calls == 3


def test_supervisor_ignores_runtime_artifacts_in_repo_snapshot(tmp_path: Path) -> None:
    verifier = SequencedVerifier(["failed", "failed", "passed"])
    supervisor = Supervisor(
        agent=NoChangeAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        max_iterations=3,
        max_no_change_iterations=2,
        process_runner=SnapshotRunner(
            [
                "?? .ai-orch/state/ai-orch.db\n?? tests/__pycache__/test_supervisor.pyc",
                "?? .pytest_cache/v/cache/nodeids\n?? .ai-orch/reports/task.md",
            ]
        ),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.summary == "No agent file or repository change detected for 2 iteration(s)"
    assert verifier.calls == 2


def test_supervisor_ignores_failed_repo_snapshot_for_no_change(tmp_path: Path) -> None:
    verifier = SequencedVerifier(["failed", "failed", "passed"])
    supervisor = Supervisor(
        agent=NoChangeAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        max_iterations=3,
        max_no_change_iterations=2,
        process_runner=FailingSnapshotRunner(
            [
                "fatal: not a git repository",
                "fatal: bad revision",
            ]
        ),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "done"
    assert verifier.calls == 3


def test_supervisor_blocks_done_without_repo_change_when_required(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    verifier = SequencedVerifier(["passed"])
    supervisor = Supervisor(
        agent=NoChangeAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        state_store=store,
        require_repo_change=True,
        process_runner=SnapshotRunner(["", ""]),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "blocked"
    assert result.task_id is not None
    assert result.summary == "No agent file or repository change detected"
    assert verifier.calls == 1
    iterations = store.list_iterations(result.task_id)
    assert iterations[0].decision_status == "blocked"
    assert iterations[0].decision_reason == "No agent file or repository change detected"


def test_supervisor_allows_done_with_repo_change_when_required(tmp_path: Path) -> None:
    verifier = SequencedVerifier(["passed"])
    supervisor = Supervisor(
        agent=NoChangeAgent(),
        verifier=verifier,
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        require_repo_change=True,
        process_runner=SnapshotRunner(["", "?? docs/log.md"]),
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "done"
    assert verifier.calls == 1


def test_supervisor_emits_progress_events(tmp_path: Path) -> None:
    progress: list[str] = []
    supervisor = Supervisor(
        agent=NoChangeAgent(),
        verifier=SequencedVerifier(["passed"]),
        verification_commands=[
            VerificationCommand("unit", "ignored"),
        ],
        progress_callback=progress.append,
    )

    result = supervisor.run_once(task="demo", repo=tmp_path)

    assert result.status == "done"
    assert "iteration 1: agent mock started" in progress
    assert "iteration 1: verification started" in progress
    assert "iteration 1: verification finished" in progress
    assert "iteration 1: done" in progress
