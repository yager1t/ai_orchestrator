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


def test_state_store_creates_plan_item_status_index(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    store.initialize()

    with sqlite3.connect(tmp_path / "state.db") as connection:
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_items)").fetchall()
        }

    assert "idx_plan_items_status_id" in indexes


def test_migrate_schema_creates_autopilot_loop_runs_from_v16(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 16")
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(autopilot_loop_runs)"
            ).fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "autopilot_loop_runs" in tables
    assert "idx_autopilot_loop_runs_plan" in indexes


def test_state_store_creates_plan_item_graph_link_columns_and_index(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")

    store.initialize()

    with sqlite3.connect(tmp_path / "state.db") as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(plan_items)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_items)").fetchall()
        }

    assert {"plan_graph_id", "plan_graph_root_node_id"}.issubset(columns)
    assert "idx_plan_items_plan_graph" in indexes


def test_state_store_initializes_existing_v12_plan_items_before_graph_index(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE plan_items (
                plan_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_path TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_id TEXT,
                selected_worktree_path TEXT,
                blocked_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("PRAGMA user_version = 12")

    store = StateStore(db_path)
    store.initialize()

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(plan_items)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_items)").fetchall()
        }
        version = schema_version(connection)

    assert version == SCHEMA_VERSION
    assert {"plan_graph_id", "plan_graph_root_node_id"}.issubset(columns)
    assert "idx_plan_items_plan_graph" in indexes


def test_state_store_records_memory_reflection_and_influence(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="prompt",
        raw_output="output",
        decision_status="blocked",
        decision_reason="failed checks",
    )
    failed_checks = [{"name": "unit", "status": "failed", "exit_code": 1}]

    lesson = store.record_memory_lesson(
        source_task_id=task.task_id,
        source_iteration_id=iteration.iteration_id,
        lesson="Retry after fixing unit failure",
        outcome_status="blocked",
        failure_reason="failed checks",
        failed_checks=failed_checks,
        follow_up_prompt="Fix unit",
    )
    reflection = store.add_reflection_record(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        reflection_type="failed_verification",
        failure_reason="failed checks",
        failed_checks=failed_checks,
        follow_up_prompt="Fix unit",
    )
    influence = store.record_memory_influence(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        lesson_id=lesson.lesson_id,
        reason="selected for planning",
    )

    assert store.list_memory_lessons()[0] == lesson
    assert store.list_reflection_records(task.task_id) == [reflection]
    assert store.list_memory_influence(task.task_id) == [influence]
    assert influence.injected is True


def test_state_store_records_dead_letter_items(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Poisoned task",
    )

    dead_letter = store.add_dead_letter_item(
        item.plan_item_id,
        "blocked repeatedly",
        task_id=task.task_id,
        attempts=2,
    )

    assert store.get_dead_letter_item(dead_letter.dead_letter_id) == dead_letter
    assert store.list_dead_letter_items() == [dead_letter]
    assert store.list_dead_letter_items(plan_item_id=item.plan_item_id) == [dead_letter]
    assert dead_letter.task_id == task.task_id
    assert dead_letter.attempts == 2


def test_state_store_rejects_invalid_dead_letter_items(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    with pytest.raises(ValueError, match="Plan item not found"):
        store.add_dead_letter_item(999, "missing")

    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Poisoned task",
    )
    with pytest.raises(ValueError, match="attempts must be at least 1"):
        store.add_dead_letter_item(item.plan_item_id, "blocked", attempts=0)


def test_state_store_records_autopilot_loop_runs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    plan_path = tmp_path / "ROADMAP.md"

    first = store.record_autopilot_loop_run(
        plan_path=plan_path,
        mode="dry-run",
        max_runtime_sec=None,
        max_attempts=1,
        max_actions=5,
        selected_count=2,
        processed_count=0,
        dead_letter_count=0,
        stop_reason="complete",
        result_code=0,
        selected_item_ids=[11, 12],
        elapsed_sec=0.5,
    )
    second = store.record_autopilot_loop_run(
        plan_path=plan_path,
        mode="execute",
        max_runtime_sec=60,
        max_attempts=2,
        max_actions=5,
        selected_count=1,
        processed_count=1,
        dead_letter_count=0,
        stop_reason="budget exhausted",
        result_code=0,
        selected_item_ids=[13],
        elapsed_sec=1.25,
    )

    assert store.get_autopilot_loop_run(first.loop_run_id) == first
    assert first.selected_item_ids == [11, 12]
    assert second.max_runtime_sec == 60
    assert [run.loop_run_id for run in store.list_autopilot_loop_runs(plan_path=plan_path)] == [
        second.loop_run_id,
        first.loop_run_id,
    ]
    assert store.list_autopilot_loop_runs(plan_path=plan_path, limit=1) == [second]


def test_state_store_rejects_invalid_autopilot_loop_runs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    with pytest.raises(ValueError, match="mode"):
        store.record_autopilot_loop_run(
            plan_path=tmp_path / "ROADMAP.md",
            mode="unsafe",
            max_runtime_sec=None,
            max_attempts=1,
            max_actions=1,
            selected_count=0,
            processed_count=0,
            dead_letter_count=0,
            stop_reason="complete",
            result_code=0,
        )
    with pytest.raises(ValueError, match="max actions"):
        store.record_autopilot_loop_run(
            plan_path=tmp_path / "ROADMAP.md",
            mode="dry-run",
            max_runtime_sec=None,
            max_attempts=1,
            max_actions=0,
            selected_count=0,
            processed_count=0,
            dead_letter_count=0,
            stop_reason="complete",
            result_code=0,
        )


def test_state_store_filters_stale_memory_without_deleting_history(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    fresh = store.record_memory_lesson(
        source_task_id=task.task_id,
        lesson="Fresh lesson",
        outcome_status="blocked",
    )
    old = store.record_memory_lesson(
        source_task_id=task.task_id,
        lesson="Old lesson",
        outcome_status="blocked",
    )
    repeated = store.record_memory_lesson(
        source_task_id=task.task_id,
        lesson="Unhelpful lesson",
        outcome_status="blocked",
    )
    old_timestamp = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE memory_lessons SET created_at = ?, updated_at = ? WHERE lesson_id = ?",
            (old_timestamp, old_timestamp, old.lesson_id),
        )
    store.record_memory_feedback(repeated.lesson_id, unhelpful_delta=3)

    active_ids = {lesson.lesson_id for lesson in store.list_memory_lessons()}
    all_ids = {
        lesson.lesson_id
        for lesson in store.list_memory_lessons(include_stale=True)
    }

    assert active_ids == {fresh.lesson_id}
    assert all_ids == {fresh.lesson_id, old.lesson_id, repeated.lesson_id}


def test_state_store_searches_memory_lessons_by_task_relevance(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("seed", repo_path=tmp_path)
    relevant = store.record_memory_lesson(
        source_task_id=task.task_id,
        lesson="Retry flaky verifier after writing a recovery marker",
        outcome_status="blocked",
        failure_reason="flaky verifier failed before marker",
        follow_up_prompt="Create recovery marker before retry",
    )
    store.record_memory_lesson(
        source_task_id=task.task_id,
        lesson="Check approval request list before retry",
        outcome_status="blocked",
    )
    store.record_memory_lesson(
        source_task_id=task.task_id,
        lesson="Update documentation heading after release notes",
        outcome_status="blocked",
    )

    results = store.search_memory_lessons("fix flaky verifier recovery", limit=1)

    assert results[0].lesson_id == relevant.lesson_id


def test_state_store_creates_task_events_table_and_index(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    store.initialize()

    with sqlite3.connect(tmp_path / "state.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(task_events)").fetchall()
        }

    assert "task_events" in tables
    assert "idx_task_events_task_sequence" in indexes
    assert "idx_task_events_task_idempotency" in indexes


def test_migrate_schema_upgrades_v17_store_with_task_event_trace_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 17")
        connection.execute(
            """
            CREATE TABLE task_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE (task_id, sequence)
            )
            """
        )

        version = migrate_schema(connection)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(task_events)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(task_events)").fetchall()
        }

    assert version == SCHEMA_VERSION
    assert {
        "run_id",
        "session_id",
        "iteration_id",
        "correlation_id",
        "idempotency_key",
        "actor",
        "summary",
        "payload_preview",
    } <= columns
    assert "idx_task_events_task_idempotency" in indexes


def test_state_store_creates_action_records_table_and_indexes(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    store.initialize()

    with sqlite3.connect(tmp_path / "state.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(action_records)").fetchall()
        }

    assert "action_records" in tables
    assert "idx_action_records_task_iteration" in indexes
    assert "idx_action_records_status" in indexes
    assert "idx_action_records_lease_expiry" in indexes


def test_state_store_creates_plan_graph_tables_and_indexes(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    store.initialize()

    with sqlite3.connect(tmp_path / "state.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        graph_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_graphs)").fetchall()
        }
        node_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_graph_nodes)").fetchall()
        }
        dependency_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(plan_graph_dependencies)"
            ).fetchall()
        }

    assert {
        "plan_graphs",
        "plan_graph_nodes",
        "plan_graph_dependencies",
    }.issubset(tables)
    assert "idx_plan_graphs_task_status" in graph_indexes
    assert "idx_plan_graph_nodes_graph_status" in node_indexes
    assert "idx_plan_graph_dependencies_graph" in dependency_indexes


def test_state_store_creates_replan_decisions_table_and_indexes(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")

    store.initialize()

    with sqlite3.connect(tmp_path / "state.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(replan_decisions)"
            ).fetchall()
        }

    assert "replan_decisions" in tables
    assert "idx_replan_decisions_task_iteration" in indexes
    assert "idx_replan_decisions_plan_graph" in indexes


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


def test_migrate_schema_upgrades_v8_store_with_task_events(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 8")
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
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(task_events)").fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "task_events" in tables
    assert "idx_task_events_task_sequence" in indexes


def test_migrate_schema_upgrades_v9_store_with_action_records(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 9")
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
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(action_records)").fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "action_records" in tables
    assert "idx_action_records_task_iteration" in indexes
    assert "idx_action_records_status" in indexes
    assert "idx_action_records_lease_expiry" in indexes


def test_migrate_schema_upgrades_v10_store_with_action_leases(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 10")
        connection.execute(
            """
            CREATE TABLE action_records (
                action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                iteration_id INTEGER,
                idempotency_key TEXT NOT NULL UNIQUE,
                action_type TEXT NOT NULL,
                status TEXT NOT NULL,
                command_string TEXT,
                policy_action TEXT,
                policy_reason TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        version = migrate_schema(connection)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(action_records)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(action_records)")
        }

    assert version == SCHEMA_VERSION
    assert {"lease_owner", "lease_expires_at", "heartbeat_at"}.issubset(columns)
    assert "idx_action_records_lease_expiry" in indexes


def test_migrate_schema_upgrades_v11_store_with_plan_graphs(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 11")
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        graph_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_graphs)").fetchall()
        }
        node_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_graph_nodes)").fetchall()
        }
        dependency_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(plan_graph_dependencies)"
            ).fetchall()
        }

    assert version == SCHEMA_VERSION
    assert {
        "plan_graphs",
        "plan_graph_nodes",
        "plan_graph_dependencies",
    }.issubset(tables)
    assert "idx_plan_graphs_task_status" in graph_indexes
    assert "idx_plan_graph_nodes_graph_status" in node_indexes
    assert "idx_plan_graph_dependencies_graph" in dependency_indexes


def test_migrate_schema_upgrades_v18_plan_graph_node_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA user_version = 18")
        connection.execute(
            """
            CREATE TABLE plan_graphs (
                graph_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE plan_graph_nodes (
                node_id INTEGER PRIMARY KEY AUTOINCREMENT,
                graph_id INTEGER NOT NULL,
                node_key TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending', 'in_progress', 'done', 'blocked', 'skipped')
                ),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (graph_id, node_key),
                FOREIGN KEY (graph_id) REFERENCES plan_graphs(graph_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE plan_graph_dependencies (
                graph_id INTEGER NOT NULL,
                node_id INTEGER NOT NULL,
                depends_on_node_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (node_id, depends_on_node_id),
                FOREIGN KEY (graph_id) REFERENCES plan_graphs(graph_id),
                FOREIGN KEY (node_id) REFERENCES plan_graph_nodes(node_id),
                FOREIGN KEY (depends_on_node_id) REFERENCES plan_graph_nodes(node_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO plan_graphs (
                graph_id, task_id, title, status, created_at, updated_at
            )
            VALUES (1, NULL, 'Old graph', 'active', 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO plan_graph_nodes (
                node_id, graph_id, node_key, title, status, attempts, created_at, updated_at
            )
            VALUES (1, 1, 'old-node', 'Old node', 'pending', 0, 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO plan_graph_nodes (
                node_id, graph_id, node_key, title, status, attempts, created_at, updated_at
            )
            VALUES (2, 1, 'dependency-node', 'Dependency node', 'done', 0, 'now', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO plan_graph_dependencies (
                graph_id, node_id, depends_on_node_id, created_at
            )
            VALUES (1, 1, 2, 'now')
            """
        )

        version = migrate_schema(connection)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(plan_graph_nodes)")
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_graph_nodes)").fetchall()
        }
        migrated = connection.execute(
            """
            SELECT task_text, acceptance_criteria_json, node_type
            FROM plan_graph_nodes
            WHERE node_id = 1
            """
        ).fetchone()
        dependency_count = connection.execute(
            "SELECT COUNT(*) FROM plan_graph_dependencies"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO plan_graph_nodes (
                graph_id,
                node_key,
                title,
                task_text,
                acceptance_criteria_json,
                status,
                node_type,
                attempts,
                created_at,
                updated_at
            )
            VALUES (1, 'failed-node', 'Failed node', 'Failed task', '[]', 'failed', 'task', 0, 'now', 'now')
            """
        )

    assert version == SCHEMA_VERSION
    assert {
        "task_text",
        "acceptance_criteria_json",
        "verification_requirement",
        "blocked_reason",
        "task_id",
        "plan_item_id",
        "source_node_id",
        "node_type",
    }.issubset(columns)
    assert "idx_plan_graph_nodes_links" in indexes
    assert migrated == ("Old node", "[]", "task")
    assert dependency_count == 1


def test_migrate_schema_upgrades_v12_plan_items_with_graph_links(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE plan_items (
                plan_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_path TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_id TEXT,
                selected_worktree_path TEXT,
                blocked_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("PRAGMA user_version = 12")
        version = migrate_schema(connection)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(plan_items)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_items)").fetchall()
        }

    assert version == SCHEMA_VERSION
    assert {"plan_graph_id", "plan_graph_root_node_id"}.issubset(columns)
    assert "idx_plan_items_plan_graph" in indexes


def test_migrate_schema_upgrades_v13_store_with_replan_decisions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 13")
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(replan_decisions)"
            ).fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "replan_decisions" in tables
    assert "idx_replan_decisions_task_iteration" in indexes
    assert "idx_replan_decisions_plan_graph" in indexes


def test_migrate_schema_upgrades_v15_store_with_dead_letter_items(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 15")
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(dead_letter_items)"
            ).fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "dead_letter_items" in tables
    assert "idx_dead_letter_items_plan_item" in indexes


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


def test_migrate_between_versions_noops_when_versions_match(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 1")
        migrate_between_versions(
            connection,
            current_version=1,
            target_version=1,
            migrations={},
        )
        version = schema_version(connection)

    assert version == 1


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


def test_state_store_appends_task_events_in_sequence(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo events", repo_path=tmp_path)

    first = store.append_task_event(
        task.task_id,
        "task.created",
        {"source": "cli", "attempt": 1},
    )
    second = store.append_task_event(
        task.task_id,
        "verification.started",
        {"checks": ["unit", "compile"]},
    )

    events = store.list_task_events(task.task_id)

    assert [event.sequence for event in events] == [1, 2]
    assert events == [first, second]
    assert events[0].event_type == "task.created"
    assert events[0].payload == {"source": "cli", "attempt": 1}
    assert events[1].payload == {"checks": ["unit", "compile"]}


def test_state_store_records_task_event_trace_metadata_and_idempotency(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo event metadata", repo_path=tmp_path)

    first = store.append_task_event(
        task.task_id,
        "checkpoint_saved",
        {"phase": "before_agent_execution", "status": "started"},
        session_id="session-1",
        iteration_id=7,
        correlation_id="corr-1",
        idempotency_key="checkpoint-1",
        actor="supervisor",
        summary="Checkpoint saved before agent execution",
    )
    duplicate = store.append_task_event(
        task.task_id,
        "checkpoint_saved",
        {"phase": "changed"},
        idempotency_key="checkpoint-1",
        actor="supervisor",
    )

    events = store.list_task_events(task.task_id)

    assert duplicate == first
    assert len(events) == 1
    assert events[0].run_id == store.run_id_for_task(task.task_id)
    assert events[0].session_id == "session-1"
    assert events[0].iteration_id == 7
    assert events[0].correlation_id == "corr-1"
    assert events[0].idempotency_key == "checkpoint-1"
    assert events[0].actor == "supervisor"
    assert events[0].summary == "Checkpoint saved before agent execution"
    assert "before_agent_execution" in events[0].payload_preview


def test_state_store_redacts_task_event_payload(tmp_path: Path) -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo event secret", repo_path=tmp_path)

    event = store.append_task_event(
        task.task_id,
        "agent.output",
        {"message": f"token {secret}", "nested": {"value": secret}},
    )

    assert secret not in str(event.payload)
    assert secret not in str(store.list_task_events(task.task_id)[0].payload)


def test_state_store_rejects_empty_task_event_type(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo empty event type", repo_path=tmp_path)

    with pytest.raises(ValueError, match="Task event type cannot be empty"):
        store.append_task_event(task.task_id, " ")


def test_state_store_records_action_with_idempotency_key(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo action", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="do it",
        raw_output="done",
        decision_status="done",
        decision_reason="ok",
    )

    first = store.record_action(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="demo-action-1",
        action_type="verification_command",
        command_string="python -m pytest",
        payload={"name": "unit"},
    )
    duplicate = store.record_action(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="demo-action-1",
        action_type="verification_command",
        status="failed",
        payload={"name": "changed"},
    )

    assert duplicate == first
    assert store.get_action_record_by_idempotency_key("demo-action-1") == first
    assert store.list_action_records(task.task_id) == [first]
    assert first.status == "started"
    assert first.command_string == "python -m pytest"
    assert first.payload == {"name": "unit"}
    assert first.result == {}


def test_state_store_completes_action_record(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo action complete", repo_path=tmp_path)
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-action-complete",
        action_type="verification_command",
    )

    completed = store.complete_action_record(
        action.action_id,
        "succeeded",
        result={"exit_code": 0},
    )

    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.result == {"exit_code": 0}
    assert completed.lease_owner is None
    assert completed.lease_expires_at is None
    assert completed.heartbeat_at is None
    assert completed.updated_at >= completed.created_at


def test_state_store_acquires_and_heartbeats_action_lease(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo action lease", repo_path=tmp_path)
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-action-lease",
        action_type="verification_command",
    )

    acquired = store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )
    blocked = store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-2",
        ttl_sec=30,
        now="2026-01-01T00:00:10+00:00",
    )
    heartbeat = store.heartbeat_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=60,
        now="2026-01-01T00:00:20+00:00",
    )

    assert acquired is not None
    assert acquired.lease_owner == "worker-1"
    assert acquired.lease_expires_at == "2026-01-01T00:00:30+00:00"
    assert acquired.heartbeat_at == "2026-01-01T00:00:00+00:00"
    assert blocked is None
    assert heartbeat is not None
    assert heartbeat.lease_owner == "worker-1"
    assert heartbeat.lease_expires_at == "2026-01-01T00:01:20+00:00"
    assert heartbeat.heartbeat_at == "2026-01-01T00:00:20+00:00"


def test_state_store_allows_reacquiring_expired_action_lease(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo expired lease", repo_path=tmp_path)
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-expired-lease",
        action_type="verification_command",
    )
    store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )

    expired = store.list_expired_action_leases("2026-01-01T00:00:30+00:00")
    reacquired = store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-2",
        ttl_sec=30,
        now="2026-01-01T00:00:31+00:00",
    )

    assert [item.action_id for item in expired] == [action.action_id]
    assert reacquired is not None
    assert reacquired.lease_owner == "worker-2"
    assert reacquired.lease_expires_at == "2026-01-01T00:01:01+00:00"


def test_state_store_lists_stale_started_actions_without_lease(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo stale action", repo_path=tmp_path)
    stale = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-stale-action",
        action_type="process.approval_retry",
    )
    fresh = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-fresh-action",
        action_type="process.approval_retry",
    )
    completed = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-completed-action",
        action_type="process.approval_retry",
        status="succeeded",
        result={"status": "succeeded"},
    )
    with store._connect() as connection:
        connection.execute(
            "UPDATE action_records SET updated_at = ? WHERE action_id IN (?, ?)",
            (
                "2026-01-01T00:00:00+00:00",
                stale.action_id,
                completed.action_id,
            ),
        )

    loaded = store.list_stale_action_records("2026-01-01T00:30:00+00:00")

    assert [action.action_id for action in loaded] == [stale.action_id]
    assert fresh.action_id not in {action.action_id for action in loaded}
    assert completed.action_id not in {action.action_id for action in loaded}


def test_state_store_releases_action_lease(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo release lease", repo_path=tmp_path)
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-release-lease",
        action_type="verification_command",
    )
    store.acquire_action_lease(
        action.action_id,
        lease_owner="worker-1",
        ttl_sec=30,
        now="2026-01-01T00:00:00+00:00",
    )

    wrong_owner = store.release_action_lease(action.action_id, "worker-2")
    released = store.release_action_lease(action.action_id, "worker-1")

    assert wrong_owner is None
    assert released is not None
    assert released.lease_owner is None
    assert released.lease_expires_at is None
    assert released.heartbeat_at is None


def test_state_store_rejects_invalid_action_lease_inputs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo invalid lease", repo_path=tmp_path)
    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-invalid-lease",
        action_type="verification_command",
    )

    with pytest.raises(ValueError, match="Action lease owner cannot be empty"):
        store.acquire_action_lease(action.action_id, " ", ttl_sec=30)
    with pytest.raises(ValueError, match="Action lease TTL must be positive"):
        store.acquire_action_lease(action.action_id, "worker-1", ttl_sec=0)


def test_state_store_redacts_action_record_payloads(tmp_path: Path) -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo action secret", repo_path=tmp_path)

    action = store.record_action(
        task_id=task.task_id,
        idempotency_key="demo-action-secret",
        action_type="verification_command",
        command_string=f"echo {secret}",
        policy_reason=f"blocked {secret}",
        payload={"secret": secret},
        result={"error": secret},
    )

    assert secret not in str(action)
    loaded = store.list_action_records(task.task_id)[0]
    assert secret not in str(loaded)


def test_state_store_rejects_invalid_action_record_inputs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo invalid action", repo_path=tmp_path)

    with pytest.raises(ValueError, match="Action idempotency key cannot be empty"):
        store.record_action(task.task_id, " ", "verification_command")
    with pytest.raises(ValueError, match="Action type cannot be empty"):
        store.record_action(task.task_id, "key", " ")
    with pytest.raises(ValueError, match="Unsupported action status"):
        store.record_action(task.task_id, "key", "verification_command", status="weird")


def test_state_store_builds_replay_task_timeline(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo timeline", repo_path=tmp_path)
    event = store.append_task_event(task.task_id, "task.recovered", {"reason": "test"})
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="do it",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed",
    )
    verification = store.add_verification_run(
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
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push",
        reason="approval required",
    )
    action = store.record_action(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        idempotency_key="timeline-action",
        action_type="verification_command",
        status="succeeded",
        command_string="python -m pytest",
        result={"exit_code": 0},
    )
    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ? WHERE task_id = ?",
            (
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                task.task_id,
            ),
        )
        connection.execute(
            "UPDATE task_events SET created_at = ? WHERE event_id = ?",
            ("2026-01-01T00:00:01+00:00", event.event_id),
        )
        connection.execute(
            "UPDATE iterations SET created_at = ? WHERE iteration_id = ?",
            ("2026-01-01T00:00:02+00:00", iteration.iteration_id),
        )
        connection.execute(
            "UPDATE verification_runs SET created_at = ? WHERE verification_id = ?",
            ("2026-01-01T00:00:03+00:00", verification.verification_id),
        )
        connection.execute(
            "UPDATE approval_requests SET created_at = ? WHERE approval_id = ?",
            ("2026-01-01T00:00:04+00:00", approval.approval_id),
        )
        connection.execute(
            "UPDATE action_records SET created_at = ?, updated_at = ? WHERE action_id = ?",
            (
                "2026-01-01T00:00:05+00:00",
                "2026-01-01T00:00:05+00:00",
                action.action_id,
            ),
        )

    timeline = store.list_task_timeline(task.task_id)

    assert [entry.timeline_index for entry in timeline] == list(range(1, 7))
    assert [entry.event_type for entry in timeline] == [
        "task.created",
        "task.recovered",
        "iteration.recorded",
        "verification.recorded",
        "approval.requested",
        "action.recorded",
    ]
    assert timeline[1].payload == {
        "sequence": 1,
        "payload": {"reason": "test"},
        "run_id": store.run_id_for_task(task.task_id),
    }
    assert timeline[-1].payload["idempotency_key"] == "timeline-action"


def test_state_store_task_timeline_returns_empty_for_missing_task(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    assert store.list_task_timeline("missing-task") == []


def test_state_store_persists_plan_graph_nodes_and_dependencies(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo plan graph", repo_path=tmp_path)

    graph = store.create_plan_graph("Implement durable graph", task_id=task.task_id)
    first = store.add_plan_graph_node(
        graph.graph_id,
        node_key="discover",
        title="Read current storage design",
    )
    second = store.add_plan_graph_node(
        graph.graph_id,
        node_key="implement",
        title="Add PlanGraph storage",
        depends_on_node_ids=[first.node_id],
    )
    dependency = store.add_plan_graph_dependency(
        graph.graph_id,
        node_id=second.node_id,
        depends_on_node_id=first.node_id,
    )
    updated_node = store.update_plan_graph_node_status(
        second.node_id,
        "in_progress",
        increment_attempts=True,
    )
    updated_graph = store.update_plan_graph_status(graph.graph_id, "blocked")

    assert graph.task_id == task.task_id
    assert graph.status == "active"
    assert store.list_plan_graphs(task_id=task.task_id) == [updated_graph]
    assert [node.node_key for node in store.list_plan_graph_nodes(graph.graph_id)] == [
        "discover",
        "implement",
    ]
    assert store.list_plan_graph_nodes(graph.graph_id, status="in_progress") == [
        updated_node
    ]
    assert dependency is not None
    assert dependency.node_id == second.node_id
    assert dependency.depends_on_node_id == first.node_id
    assert store.list_plan_graph_dependencies(graph.graph_id) == [dependency]
    assert updated_node is not None
    assert updated_node.status == "in_progress"
    assert updated_node.attempts == 1
    assert updated_graph is not None
    assert updated_graph.status == "blocked"


def test_state_store_lists_ready_plan_graph_nodes(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    graph = store.create_plan_graph("Ready graph")
    first = store.add_plan_graph_node(graph.graph_id, "first", "First step")
    second = store.add_plan_graph_node(
        graph.graph_id,
        "second",
        "Second step",
        depends_on_node_ids=[first.node_id],
    )
    third = store.add_plan_graph_node(graph.graph_id, "third", "Third step")
    store.update_plan_graph_node_status(third.node_id, "blocked")
    fourth = store.add_plan_graph_node(
        graph.graph_id,
        "fourth",
        "Fourth step",
        depends_on_node_ids=[third.node_id],
    )

    ready_before = store.list_ready_plan_graph_nodes(graph.graph_id)
    readiness_before = store.list_plan_graph_node_readiness(graph.graph_id)
    store.update_plan_graph_node_status(first.node_id, "done")
    ready_after = store.list_ready_plan_graph_nodes(graph.graph_id)
    limited = store.list_ready_plan_graph_nodes(graph.graph_id, limit=1)

    assert [node.node_id for node in ready_before] == [first.node_id]
    assert [node.node_id for node in ready_after] == [second.node_id]
    assert [node.node_id for node in limited] == [second.node_id]
    assert [item.node.node_id for item in readiness_before] == [
        first.node_id,
        second.node_id,
        third.node_id,
        fourth.node_id,
    ]
    assert [(item.node.node_key, item.ready, item.reason) for item in readiness_before] == [
        ("first", True, "ready"),
        ("second", False, "blocked_dependencies"),
        ("third", False, "node_status_blocked"),
        ("fourth", False, "blocked_dependencies"),
    ]
    fourth_readiness = readiness_before[3]
    assert [node.node_id for node in fourth_readiness.blocking_dependencies] == [
        third.node_id
    ]


def test_state_store_plan_graph_node_metadata_and_cycle_guard(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    graph = store.create_plan_graph("Metadata graph")
    first = store.add_plan_graph_node(graph.graph_id, "first", "First")
    second = store.add_plan_graph_node(
        graph.graph_id,
        "second",
        "Second",
        depends_on_node_ids=[first.node_id],
        task_text="Implement the second step",
        acceptance_criteria=["tests pass", "report explains the decision"],
        verification_requirement="python -m pytest",
        blocked_reason="waiting for first",
        source_node_id=first.node_id,
        node_type="repair",
    )
    third = store.add_plan_graph_node(
        graph.graph_id,
        "third",
        "Third",
        depends_on_node_ids=[second.node_id],
    )

    assert second.task_text == "Implement the second step"
    assert second.acceptance_criteria == [
        "tests pass",
        "report explains the decision",
    ]
    assert second.verification_requirement == "python -m pytest"
    assert second.blocked_reason == "waiting for first"
    assert second.source_node_id == first.node_id
    assert second.node_type == "repair"

    with pytest.raises(ValueError, match="Plan graph dependency would create a cycle"):
        store.add_plan_graph_dependency(
            graph.graph_id,
            node_id=first.node_id,
            depends_on_node_id=third.node_id,
        )


def test_state_store_rejects_invalid_plan_graph_inputs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    with pytest.raises(ValueError, match="Plan graph title cannot be empty"):
        store.create_plan_graph(" ")

    graph = store.create_plan_graph("Demo graph")
    with pytest.raises(ValueError, match="Unsupported plan graph status"):
        store.update_plan_graph_status(graph.graph_id, "weird")
    with pytest.raises(ValueError, match="Plan graph node key cannot be empty"):
        store.add_plan_graph_node(graph.graph_id, " ", "Demo node")
    with pytest.raises(ValueError, match="Plan graph node title cannot be empty"):
        store.add_plan_graph_node(graph.graph_id, "demo", " ")
    with pytest.raises(ValueError, match="Unsupported plan graph node status"):
        store.add_plan_graph_node(graph.graph_id, "demo", "Demo node", status="weird")
    with pytest.raises(ValueError, match="Plan graph node attempts cannot be negative"):
        store.add_plan_graph_node(graph.graph_id, "demo", "Demo node", attempts=-1)
    with pytest.raises(ValueError, match="Plan graph not found"):
        store.add_plan_graph_node(999, "demo", "Demo node")


def test_state_store_rejects_cross_graph_plan_graph_dependency(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    first_graph = store.create_plan_graph("First graph")
    second_graph = store.create_plan_graph("Second graph")
    first_node = store.add_plan_graph_node(first_graph.graph_id, "first", "First")
    second_node = store.add_plan_graph_node(second_graph.graph_id, "second", "Second")

    with pytest.raises(ValueError, match="Plan graph dependency nodes not found"):
        store.add_plan_graph_dependency(
            first_graph.graph_id,
            node_id=first_node.node_id,
            depends_on_node_id=second_node.node_id,
        )
    with pytest.raises(ValueError, match="Plan graph node cannot depend on itself"):
        store.add_plan_graph_dependency(
            first_graph.graph_id,
            node_id=first_node.node_id,
            depends_on_node_id=first_node.node_id,
        )


def test_state_store_links_plan_item_to_plan_graph_root_node(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    graph = store.create_plan_graph("Queue item graph")
    root = store.add_plan_graph_node(graph.graph_id, "root", "Root step")
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo item",
    )

    linked = store.link_plan_item_to_plan_graph(
        item.plan_item_id,
        graph.graph_id,
        plan_graph_root_node_id=root.node_id,
    )

    assert linked is not None
    assert linked.plan_graph_id == graph.graph_id
    assert linked.plan_graph_root_node_id == root.node_id
    assert store.get_plan_item(item.plan_item_id) == linked


def test_state_store_rejects_invalid_plan_item_graph_links(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    first_graph = store.create_plan_graph("First graph")
    second_graph = store.create_plan_graph("Second graph")
    second_root = store.add_plan_graph_node(second_graph.graph_id, "root", "Root")
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo item",
    )

    with pytest.raises(ValueError, match="Plan graph not found: 999"):
        store.link_plan_item_to_plan_graph(item.plan_item_id, 999)
    with pytest.raises(ValueError, match="Plan graph dependency nodes not found"):
        store.link_plan_item_to_plan_graph(
            item.plan_item_id,
            first_graph.graph_id,
            plan_graph_root_node_id=second_root.node_id,
        )
    with pytest.raises(ValueError, match="Plan graph root node requires plan graph id"):
        store.record_plan_item(
            plan_path=tmp_path / "ROADMAP.md",
            line_number=2,
            section="",
            text="Invalid root-only item",
            plan_graph_root_node_id=second_root.node_id,
        )
    assert store.link_plan_item_to_plan_graph(999, first_graph.graph_id) is None


def test_state_store_records_replan_decision_and_timeline_entry(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo",
        raw_output="ok",
        decision_status="continue",
        decision_reason="Verification failed",
    )
    graph = store.create_plan_graph("Demo graph", task_id=task.task_id)
    root = store.add_plan_graph_node(graph.graph_id, "fix", "Fix failed test")

    decision = store.record_replan_decision(
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
        plan_graph_id=graph.graph_id,
        plan_graph_node_id=root.node_id,
    )

    assert decision.status == "continue"
    assert decision.failed_checks[0]["name"] == "unit"
    assert decision.plan_graph_id == graph.graph_id
    assert decision.plan_graph_node_id == root.node_id
    assert store.get_replan_decision(decision.replan_id) == decision
    assert store.list_replan_decisions(task.task_id) == [decision]
    assert store.list_replan_decisions(
        task.task_id,
        iteration_id=iteration.iteration_id,
    ) == [decision]

    timeline = store.list_task_timeline(task.task_id)
    replan_entries = [
        entry for entry in timeline if entry.event_type == "replan.decision"
    ]
    assert len(replan_entries) == 1
    assert replan_entries[0].status == "continue"
    assert replan_entries[0].payload["failed_checks"] == decision.failed_checks


def test_state_store_links_replan_decisions_to_plan_graph_node(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo",
        raw_output="ok",
        decision_status="continue",
        decision_reason="Verification failed",
    )
    graph = store.create_plan_graph("Demo graph", task_id=task.task_id)
    root = store.add_plan_graph_node(graph.graph_id, "fix", "Fix failed test")
    decision = store.record_replan_decision(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        status="continue",
        reason="Verification failed: unit",
        failed_checks=[{"name": "unit", "status": "failed"}],
    )

    linked = store.link_replan_decisions_to_plan_graph(
        task.task_id,
        graph.graph_id,
        plan_graph_node_id=root.node_id,
    )

    assert len(linked) == 1
    assert linked[0].replan_id == decision.replan_id
    assert linked[0].plan_graph_id == graph.graph_id
    assert linked[0].plan_graph_node_id == root.node_id


def test_state_store_creates_idempotent_replan_follow_up_nodes(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo",
        raw_output="ok",
        decision_status="continue",
        decision_reason="Verification failed",
    )
    graph = store.create_plan_graph("Demo graph", task_id=task.task_id)
    root = store.add_plan_graph_node(graph.graph_id, "fix", "Fix failed test")
    decision = store.record_replan_decision(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        status="continue",
        reason="Verification failed: unit",
        follow_up_prompt="Fix the failing unit test",
        failed_checks=[{"name": "unit", "status": "failed"}],
        plan_graph_id=graph.graph_id,
        plan_graph_node_id=root.node_id,
    )

    created = store.create_replan_follow_up_nodes(task.task_id, graph.graph_id)
    repeated = store.create_replan_follow_up_nodes(task.task_id, graph.graph_id)

    dependencies = store.list_plan_graph_dependencies(
        graph.graph_id,
        node_id=created[0].node_id,
    )

    assert len(created) == 1
    assert repeated == created
    assert created[0].node_key == f"replan-{decision.replan_id}"
    assert created[0].status == "pending"
    assert created[0].attempts == 0
    assert "Fix the failing unit test" in created[0].title
    assert len(dependencies) == 1
    assert dependencies[0].depends_on_node_id == root.node_id


def test_state_store_rejects_invalid_replan_decisions(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo",
        raw_output="ok",
        decision_status="continue",
        decision_reason="Verification failed",
    )

    with pytest.raises(ValueError, match="Unsupported replan decision status"):
        store.record_replan_decision(
            task_id=task.task_id,
            iteration_id=iteration.iteration_id,
            source="verification",
            status="weird",
            reason="Verification failed",
            failed_checks=[],
        )
    with pytest.raises(ValueError, match="Replan decision source cannot be empty"):
        store.record_replan_decision(
            task_id=task.task_id,
            iteration_id=iteration.iteration_id,
            source=" ",
            status="continue",
            reason="Verification failed",
            failed_checks=[],
        )


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


def test_state_store_records_and_lists_plan_items(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    plan_a = tmp_path / "roadmap.md"
    plan_b = tmp_path / "z_backlog.md"
    task = store.create_task("demo", repo_path=tmp_path)

    first = store.record_plan_item(
        plan_path=plan_a,
        line_number=12,
        section="Post-v0.1.0 Development",
        text="Add the first persisted autopilot queue model slice",
        status="created",
    )
    second = store.record_plan_item(
        plan_path=plan_a,
        line_number=13,
        section="Post-v0.1.0 Development",
        text="Integrate queue selection with plan items",
        status="in_progress",
        task_id=task.task_id,
    )
    third = store.record_plan_item(
        plan_path=plan_b,
        line_number=5,
        section="Deferred",
        text="Document advanced autopilot workflows",
        status="skipped",
    )

    all_items = store.list_plan_items()
    assert all_items == [first, second, third]

    plan_a_items = store.list_plan_items(plan_path=plan_a)
    assert plan_a_items == [first, second]

    in_progress_items = store.list_plan_items(status="in_progress")
    assert in_progress_items == [second]
    assert in_progress_items[0].task_id == task.task_id

    assert store.get_plan_item(first.plan_item_id) == first


def test_state_store_records_selected_worktree_path_for_plan_items(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    worktree = tmp_path / "worktrees" / "task-1"

    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo item",
        selected_worktree_path=worktree,
    )

    assert item.selected_worktree_path == str(worktree)
    assert store.get_plan_item(item.plan_item_id) == item

    next_worktree = tmp_path / "worktrees" / "task-2"
    updated = store.update_plan_item_status(
        item.plan_item_id,
        status="in_progress",
        task_id=task.task_id,
        selected_worktree_path=next_worktree,
    )

    assert updated is not None
    assert updated.task_id == task.task_id
    assert updated.selected_worktree_path == str(next_worktree)
    assert store.list_plan_items(status="in_progress") == [updated]


def test_state_store_records_blocked_reason_for_plan_items(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo item",
        blocked_reason="initial timeout",
    )

    assert item.blocked_reason == "initial timeout"
    assert store.get_plan_item(item.plan_item_id) == item

    updated = store.update_plan_item_status(
        item.plan_item_id,
        status="blocked",
        blocked_reason="interrupted batch run",
    )

    assert updated is not None
    assert updated.status == "blocked"
    assert updated.blocked_reason == "interrupted batch run"
    assert store.list_plan_items(status="blocked") == [updated]


def test_state_store_requeues_blocked_plan_item_and_clears_metadata(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo item",
    )
    blocked = store.update_plan_item_status(
        item.plan_item_id,
        status="blocked",
        task_id=task.task_id,
        selected_worktree_path=tmp_path / "old-worktree",
        blocked_reason="operator review",
    )

    assert blocked is not None

    requeued = store.requeue_plan_item(item.plan_item_id)

    assert requeued is not None
    assert requeued.status == "created"
    assert requeued.task_id is None
    assert requeued.selected_worktree_path is None
    assert requeued.blocked_reason is None
    assert store.requeue_plan_item(item.plan_item_id) is None


def test_state_store_skips_created_or_blocked_plan_item_with_reason(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    created_item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Created item",
    )
    blocked_item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=2,
        section="",
        text="Blocked item",
    )
    done_item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=3,
        section="",
        text="Done item",
    )
    store.update_plan_item_status(blocked_item.plan_item_id, "blocked")
    store.update_plan_item_status(done_item.plan_item_id, "done")

    skipped_created = store.skip_plan_item(
        created_item.plan_item_id,
        reason="operator reviewed: out of scope",
    )
    skipped_blocked = store.skip_plan_item(
        blocked_item.plan_item_id,
        reason="operator reviewed: blocked for now",
    )

    assert skipped_created is not None
    assert skipped_created.status == "skipped"
    assert skipped_created.blocked_reason == "operator reviewed: out of scope"
    assert skipped_blocked is not None
    assert skipped_blocked.status == "skipped"
    assert skipped_blocked.blocked_reason == "operator reviewed: blocked for now"
    assert store.skip_plan_item(done_item.plan_item_id, reason="nope") is None


def test_state_store_updates_plan_item_status(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo", repo_path=tmp_path)
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo item",
    )

    updated = store.update_plan_item_status(
        item.plan_item_id,
        status="done",
        task_id=task.task_id,
    )

    assert updated is not None
    assert updated.status == "done"
    assert updated.task_id == task.task_id
    assert updated.updated_at >= item.updated_at
    assert store.list_plan_items(status="done") == [updated]


def test_state_store_rejects_invalid_plan_item_status(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    item = store.record_plan_item(
        plan_path=tmp_path / "ROADMAP.md",
        line_number=1,
        section="",
        text="Demo item",
    )

    with pytest.raises(ValueError, match="Unsupported plan item status"):
        store.record_plan_item(
            plan_path=tmp_path / "ROADMAP.md",
            line_number=2,
            section="",
            text="Bad status",
            status="unknown",
        )

    with pytest.raises(ValueError, match="Unsupported plan item status"):
        store.update_plan_item_status(item.plan_item_id, status="unknown")

    with pytest.raises(ValueError, match="Unsupported plan item status"):
        store.list_plan_items(status="unknown")


def test_state_store_plan_items_are_ordered_by_path_and_line(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    plan = tmp_path / "ROADMAP.md"

    third = store.record_plan_item(plan, line_number=30, section="", text="Third")
    first = store.record_plan_item(plan, line_number=10, section="", text="First")
    second = store.record_plan_item(plan, line_number=20, section="", text="Second")

    assert store.list_plan_items() == [first, second, third]


def test_migrate_schema_upgrades_v4_store_with_plan_items(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 4")
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
        version = migrate_schema(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(plan_items)")
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "plan_items" in tables
    assert {
        "plan_item_id",
        "plan_path",
        "line_number",
        "section",
        "text",
        "status",
        "task_id",
        "selected_worktree_path",
        "created_at",
        "updated_at",
    }.issubset(columns)
    assert "idx_plan_items_plan_status" in indexes
    assert "idx_plan_items_status_id" in indexes


def test_migrate_schema_upgrades_v5_store_with_plan_item_worktree_path(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 5")
        connection.execute(
            """
            CREATE TABLE plan_items (
                plan_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_path TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        version = migrate_schema(connection)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(plan_items)")
        }

    assert version == SCHEMA_VERSION
    assert "selected_worktree_path" in columns


def test_migrate_schema_upgrades_v6_store_with_plan_item_blocked_reason(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 6")
        connection.execute(
            """
            CREATE TABLE plan_items (
                plan_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_path TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_id TEXT,
                selected_worktree_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        version = migrate_schema(connection)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(plan_items)")
        }

    assert version == SCHEMA_VERSION
    assert "blocked_reason" in columns


def test_migrate_schema_upgrades_v7_store_with_plan_item_status_index(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 7")
        connection.execute(
            """
            CREATE TABLE plan_items (
                plan_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_path TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_id TEXT,
                selected_worktree_path TEXT,
                blocked_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        version = migrate_schema(connection)
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(plan_items)").fetchall()
        }

    assert version == SCHEMA_VERSION
    assert "idx_plan_items_status_id" in indexes
