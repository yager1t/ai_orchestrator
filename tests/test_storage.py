from pathlib import Path

from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.runner import VerificationResult


def test_state_store_persists_task(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    task = store.create_task("demo", repo_path=tmp_path)
    store.update_task_status(task.task_id, "done")
    loaded = store.get_task(task.task_id)

    assert loaded is not None
    assert loaded.task == "demo"
    assert loaded.repo_path == str(tmp_path)
    assert loaded.status == "done"


def test_state_store_persists_iteration_and_verification(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)

    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="do it",
        raw_output="done",
        decision_status="continue",
        decision_reason="Verification failed",
    )
    verification = store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="assertion failed",
        ),
    )

    iterations = store.list_iterations(task.task_id)
    verification_runs = store.list_verification_runs(task.task_id)
    verification_details = store.list_verification_details(task.task_id)

    assert iterations == [iteration]
    assert verification_runs == [verification]
    assert verification_runs[0].iteration_id == iteration.iteration_id
    assert verification_details[0].stderr == "assertion failed"
    assert verification_details[0].stdout == ""
    assert verification_details[0].error is None
