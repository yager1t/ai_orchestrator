import sqlite3
from datetime import UTC, datetime, timedelta
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


def test_migrate_schema_upgrades_v1_store_with_approval_requests(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 1")
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "approval_requests" in tables
    with sqlite3.connect(db_path) as connection:
        approval_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(approval_requests)")
        }
    assert {
        "retry_count",
        "last_retry_at",
        "last_retry_status",
        "last_retry_exit_code",
        "last_retry_error",
    }.issubset(approval_columns)


def test_migrate_schema_upgrades_v3_store_with_structured_iteration_fields(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 3")
        connection.execute(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                repo_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE iterations (
                iteration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                iteration_index INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                agent_status TEXT NOT NULL,
                prompt TEXT NOT NULL,
                raw_output TEXT NOT NULL,
                decision_status TEXT NOT NULL,
                decision_reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        version = migrate_schema(connection)
        iteration_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(iterations)")
        }

    assert version == SCHEMA_VERSION
    assert {
        "agent_summary",
        "files_changed",
        "tool_actions",
        "exit_reason",
        "uncertainty",
    }.issubset(iteration_columns)


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
    assert iteration_details[0].agent_summary is None
    assert iteration_details[0].files_changed == []
    assert iteration_details[0].tool_actions == []
    assert iteration_details[0].exit_reason is None
    assert iteration_details[0].uncertainty is None
    assert verification_runs == [verification]
    assert verification_runs[0].iteration_id == iteration.iteration_id
    assert verification_details[0].stderr == "assertion failed"
    assert verification_details[0].stdout == ""
    assert verification_details[0].error is None


def test_state_store_persists_structured_iteration_fields(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)

    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="generic",
        agent_status="success",
        prompt="do it",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed",
        agent_summary="updated docs",
        files_changed=["README.md"],
        tool_actions=["write README.md"],
        exit_reason="success",
        uncertainty="low",
    )

    iterations = store.list_iterations(task.task_id)
    details = store.list_iteration_details(task.task_id)

    assert iterations == [iteration]
    assert details[0].agent_summary == "updated docs"
    assert details[0].files_changed == ["README.md"]
    assert details[0].tool_actions == ["write README.md"]
    assert details[0].exit_reason == "success"
    assert details[0].uncertainty == "low"


def test_state_store_persists_and_resolves_approval_requests(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="do it",
        raw_output="done",
        decision_status="blocked",
        decision_reason="approval required",
    )

    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )
    resolved = store.resolve_approval_request(
        approval.approval_id,
        status="approved",
        resolution="approved by operator",
    )

    assert resolved is not None
    assert resolved.status == "approved"
    assert resolved.resolved_at is not None
    assert resolved.resolution == "approved by operator"
    assert store.get_approval_request(approval.approval_id) == resolved
    assert store.list_approval_requests(task_id=task.task_id) == [resolved]
    assert store.list_approval_requests(status="pending") == []
    assert store.list_approval_requests(status="approved") == [resolved]


def test_state_store_marks_old_pending_approval_requests_stale(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    old_approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )
    fresh_approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="pip install demo",
        reason="package install requires approval",
    )
    old_created_at = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE approval_requests SET created_at = ? WHERE approval_id = ?",
            (old_created_at, old_approval.approval_id),
        )

    stale = store.mark_stale_approval_requests(
        cutoff_created_at=cutoff,
        task_id=task.task_id,
        resolution="stale after operator review",
    )

    assert [approval.approval_id for approval in stale] == [old_approval.approval_id]
    assert stale[0].status == "stale"
    assert stale[0].resolved_at is not None
    assert stale[0].resolution == "stale after operator review"
    assert store.list_approval_requests(status="pending") == [fresh_approval]
    assert store.list_approval_requests(status="stale") == stale


def test_state_store_records_approval_retry_history(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="python -m pytest",
        reason="policy requires approval",
    )

    retried = store.record_approval_retry(
        approval.approval_id,
        status="failed",
        exit_code=1,
        error="assertion failed",
    )

    assert retried is not None
    assert retried.retry_count == 1
    assert retried.last_retry_at is not None
    assert retried.last_retry_status == "failed"
    assert retried.last_retry_exit_code == 1
    assert retried.last_retry_error == "assertion failed"


def test_state_store_summarizes_local_metrics(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    first_task = store.create_task("first", repo_path=tmp_path)
    second_task = store.create_task("second", repo_path=tmp_path)
    success_iteration = store.add_iteration(
        task_id=first_task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="do it",
        raw_output="done",
        decision_status="continue",
        decision_reason="verification failed",
    )
    failed_iteration = store.add_iteration(
        task_id=second_task.task_id,
        iteration_index=1,
        agent_name="generic",
        agent_status="failed",
        prompt="do it",
        raw_output="error",
        decision_status="blocked",
        decision_reason="agent failed",
    )
    unavailable_iteration = store.add_iteration(
        task_id=second_task.task_id,
        iteration_index=2,
        agent_name="generic",
        agent_status="unavailable",
        prompt="do it",
        raw_output="",
        decision_status="blocked",
        decision_reason="agent unavailable",
    )
    store.add_verification_run(
        task_id=first_task.task_id,
        iteration_id=success_iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="",
            stderr="",
        ),
    )
    store.add_verification_run(
        task_id=first_task.task_id,
        iteration_id=success_iteration.iteration_id,
        result=VerificationResult(
            name="lint",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="lint failed",
        ),
    )
    store.add_verification_run(
        task_id=second_task.task_id,
        iteration_id=failed_iteration.iteration_id,
        result=VerificationResult(
            name="approval",
            status="needs_approval",
            exit_code=None,
            stdout="",
            stderr="",
        ),
    )
    pending = store.add_approval_request(
        task_id=first_task.task_id,
        iteration_id=success_iteration.iteration_id,
        source="verification",
        command_string="git push",
        reason="approval required",
    )
    approved = store.add_approval_request(
        task_id=first_task.task_id,
        iteration_id=success_iteration.iteration_id,
        source="verification",
        command_string="pip install demo",
        reason="approval required",
    )
    rejected = store.add_approval_request(
        task_id=second_task.task_id,
        iteration_id=failed_iteration.iteration_id,
        source="verification",
        command_string="deploy",
        reason="approval required",
    )
    stale = store.add_approval_request(
        task_id=second_task.task_id,
        iteration_id=unavailable_iteration.iteration_id,
        source="memory",
        command_string="codebase-memory-mcp cli index_repository",
        reason="approval required",
    )
    store.resolve_approval_request(approved.approval_id, status="approved")
    store.resolve_approval_request(rejected.approval_id, status="rejected")
    store.resolve_approval_request(stale.approval_id, status="stale")

    summary = store.metrics_summary()

    assert pending.status == "pending"
    assert summary.task_count == 2
    assert summary.iteration_count == 3
    assert summary.verification_count == 3
    assert summary.verification_passed_count == 1
    assert summary.verification_pass_rate == pytest.approx(1 / 3)
    assert summary.approval_count == 4
    assert summary.approval_pending_count == 1
    assert summary.approval_approved_count == 1
    assert summary.approval_rejected_count == 1
    assert summary.approval_stale_count == 1
    assert summary.adapter_failure_count == 2


def test_state_store_lists_pending_approval_requests_in_creation_order(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)

    first = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="memory",
        command_string="codebase-memory-mcp cli index_repository",
        reason="memory indexing requires approval",
    )
    second = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="pip install demo",
        reason="package install requires approval",
    )

    assert store.list_approval_requests(status="pending") == [first, second]


def test_state_store_rejects_invalid_approval_status(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )

    with pytest.raises(ValueError, match="Unsupported approval status"):
        store.list_approval_requests(status="done")

    with pytest.raises(ValueError, match="Unsupported approval resolution status"):
        store.resolve_approval_request(approval.approval_id, status="pending")


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
