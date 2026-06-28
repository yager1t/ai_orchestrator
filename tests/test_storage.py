import sqlite3
from pathlib import Path

import pytest

from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.storage.migrations import (
    SCHEMA_VERSION,
    migrate_between_versions,
    migrate_schema,
    schema_version,
)
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


def test_state_store_logs_metadata_without_payload(caplog, tmp_path: Path) -> None:
    secret = "secret-storage-token"
    store = StateStore(tmp_path / "state.db")

    with caplog.at_level("DEBUG", logger="ai_orchestrator.storage.db"):
        task = store.create_task(f"demo {secret}", repo_path=tmp_path)
        iteration = store.add_iteration(
            task_id=task.task_id,
            iteration_index=1,
            agent_name="mock",
            agent_status="success",
            prompt=f"prompt {secret}",
            raw_output=f"output {secret}",
            decision_status="done",
            decision_reason="ok",
        )
        store.add_verification_run(
            task_id=task.task_id,
            iteration_id=iteration.iteration_id,
            result=VerificationResult(
                name="unit",
                status="passed",
                exit_code=0,
                stdout=f"stdout {secret}",
                stderr="",
            ),
        )

    assert secret not in caplog.text
    assert task.task_id in caplog.text
    assert "state iteration added" in caplog.text
    assert "state verification added" in caplog.text


def test_state_store_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.initialize()

    with store._connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode == "wal"
    assert busy_timeout == 5000


def test_state_store_records_schema_version(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    store.initialize()

    assert store.schema_version() == SCHEMA_VERSION


def test_migrate_schema_sets_initial_version(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        version = migrate_schema(connection)

    assert version == SCHEMA_VERSION


def test_state_store_rejects_future_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    store = StateStore(db_path)

    with pytest.raises(RuntimeError, match="Unsupported state store schema version"):
        store.initialize()


def test_migrate_between_versions_runs_migrations_in_order(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    calls: list[str] = []

    def migration_1(connection: sqlite3.Connection) -> None:
        calls.append("1")
        connection.execute("CREATE TABLE migration_one (id INTEGER)")

    def migration_2(connection: sqlite3.Connection) -> None:
        calls.append("2")
        connection.execute("CREATE TABLE migration_two (id INTEGER)")

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 1")
        migrate_between_versions(
            connection,
            current_version=1,
            target_version=3,
            migrations={1: migration_1, 2: migration_2},
        )

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        version = schema_version(connection)

    assert calls == ["1", "2"]
    assert {"migration_one", "migration_two"}.issubset(tables)
    assert version == 3


def test_migrate_between_versions_rejects_missing_path(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        with pytest.raises(RuntimeError, match="Missing state store migration path: 1 -> 2"):
            migrate_between_versions(
                connection,
                current_version=1,
                target_version=2,
                migrations={},
            )


def test_state_store_lists_tasks_newest_first(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    first = store.create_task("first", repo_path=tmp_path, task_id="task-1")
    second = store.create_task("second", repo_path=tmp_path, task_id="task-2")
    store.update_task_status(first.task_id, "done")
    store.update_task_status(second.task_id, "blocked")

    tasks = store.list_tasks()

    assert [task.task_id for task in tasks] == [second.task_id, first.task_id]


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
    iteration_details = store.list_iteration_details(task.task_id)
    verification_runs = store.list_verification_runs(task.task_id)
    verification_details = store.list_verification_details(task.task_id)

    assert iterations == [iteration]
    assert iteration_details[0].prompt == "do it"
    assert iteration_details[0].raw_output == "done"
    assert verification_runs == [verification]
    assert verification_runs[0].iteration_id == iteration.iteration_id
    assert verification_details[0].stderr == "assertion failed"
    assert verification_details[0].stdout == ""
    assert verification_details[0].error is None


def test_state_store_redacts_secret_like_outputs(tmp_path: Path) -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)

    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo",
        raw_output=f"agent leaked {secret}",
        decision_status="blocked",
        decision_reason="failed",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout=f"stdout {secret}",
            stderr=f"stderr {secret}",
            error=f"error {secret}",
        ),
    )

    details = store.list_iteration_details(task.task_id)
    checks = store.list_verification_details(task.task_id)

    assert secret not in details[0].raw_output
    assert secret not in checks[0].stdout
    assert secret not in checks[0].stderr
    assert secret not in (checks[0].error or "")
    assert "***REDACTED***" in details[0].raw_output
    assert "***REDACTED***" in checks[0].stderr
