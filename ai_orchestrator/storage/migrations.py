from __future__ import annotations

import sqlite3
from collections.abc import Callable


SCHEMA_VERSION = 17
Migration = Callable[[sqlite3.Connection], None]


_PLAN_ITEM_STATUS_CHECK = "CHECK (status IN ('created', 'in_progress', 'done', 'blocked', 'skipped'))"
_PLAN_GRAPH_STATUS_CHECK = "CHECK (status IN ('active', 'done', 'blocked', 'archived'))"
_PLAN_GRAPH_NODE_STATUS_CHECK = "CHECK (status IN ('pending', 'in_progress', 'done', 'blocked', 'skipped'))"
_REPLAN_DECISION_STATUS_CHECK = "CHECK (status IN ('continue', 'blocked'))"


def _migrate_1_to_2(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            iteration_id INTEGER,
            source TEXT NOT NULL,
            command_string TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolution TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id),
            FOREIGN KEY (iteration_id) REFERENCES iterations(iteration_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_approval_requests_task_status
        ON approval_requests (task_id, status, approval_id)
        """
    )


def _migrate_2_to_3(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE approval_requests_v3 (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            iteration_id INTEGER,
            source TEXT NOT NULL,
            command_string TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'stale')),
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolution TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            last_retry_at TEXT,
            last_retry_status TEXT,
            last_retry_exit_code INTEGER,
            last_retry_error TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id),
            FOREIGN KEY (iteration_id) REFERENCES iterations(iteration_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO approval_requests_v3 (
            approval_id,
            task_id,
            iteration_id,
            source,
            command_string,
            reason,
            status,
            created_at,
            resolved_at,
            resolution
        )
        SELECT
            approval_id,
            task_id,
            iteration_id,
            source,
            command_string,
            reason,
            status,
            created_at,
            resolved_at,
            resolution
        FROM approval_requests
        """
    )
    connection.execute("DROP TABLE approval_requests")
    connection.execute("ALTER TABLE approval_requests_v3 RENAME TO approval_requests")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_approval_requests_task_status
        ON approval_requests (task_id, status, approval_id)
        """
    )


def _migrate_3_to_4(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "iterations"):
        return
    _add_column_if_missing(connection, "iterations", "agent_summary", "TEXT")
    _add_column_if_missing(
        connection,
        "iterations",
        "files_changed",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(
        connection,
        "iterations",
        "tool_actions",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(connection, "iterations", "exit_reason", "TEXT")
    _add_column_if_missing(connection, "iterations", "uncertainty", "TEXT")


def _migrate_4_to_5(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS plan_items (
            plan_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_path TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            section TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            status TEXT NOT NULL {_PLAN_ITEM_STATUS_CHECK},
            task_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plan_items_plan_status
        ON plan_items (plan_path, status, line_number)
        """
    )


def _migrate_5_to_6(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "plan_items"):
        return
    _add_column_if_missing(
        connection,
        "plan_items",
        "selected_worktree_path",
        "TEXT",
    )


def _migrate_6_to_7(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "plan_items"):
        return
    _add_column_if_missing(
        connection,
        "plan_items",
        "blocked_reason",
        "TEXT",
    )


def _migrate_7_to_8(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "plan_items"):
        return
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plan_items_status_id
        ON plan_items (status, plan_item_id)
        """
    )


def _migrate_8_to_9(connection: sqlite3.Connection) -> None:
    _create_task_events_table(connection)


def _migrate_9_to_10(connection: sqlite3.Connection) -> None:
    _create_action_records_table(connection)


def _migrate_10_to_11(connection: sqlite3.Connection) -> None:
    _add_action_lease_columns(connection)


def _migrate_11_to_12(connection: sqlite3.Connection) -> None:
    _create_plan_graph_tables(connection)


def _migrate_12_to_13(connection: sqlite3.Connection) -> None:
    _add_plan_item_graph_link_columns(connection)


def _migrate_13_to_14(connection: sqlite3.Connection) -> None:
    _create_replan_decisions_table(connection)


def _migrate_14_to_15(connection: sqlite3.Connection) -> None:
    _create_memory_tables(connection)


def _migrate_15_to_16(connection: sqlite3.Connection) -> None:
    _create_dead_letter_table(connection)


def _migrate_16_to_17(connection: sqlite3.Connection) -> None:
    _create_autopilot_loop_runs_table(connection)


def _create_autopilot_loop_runs_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS autopilot_loop_runs (
            loop_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_path TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('dry-run', 'execute')),
            max_runtime_sec INTEGER,
            max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
            max_actions INTEGER NOT NULL CHECK (max_actions >= 1),
            selected_count INTEGER NOT NULL DEFAULT 0 CHECK (selected_count >= 0),
            processed_count INTEGER NOT NULL DEFAULT 0 CHECK (processed_count >= 0),
            dead_letter_count INTEGER NOT NULL DEFAULT 0 CHECK (dead_letter_count >= 0),
            stop_reason TEXT NOT NULL,
            result_code INTEGER NOT NULL,
            selected_item_ids_json TEXT NOT NULL DEFAULT '[]',
            elapsed_sec REAL NOT NULL DEFAULT 0 CHECK (elapsed_sec >= 0),
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_autopilot_loop_runs_plan
        ON autopilot_loop_runs (plan_path, loop_run_id)
        """
    )


def _create_dead_letter_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dead_letter_items (
            dead_letter_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_item_id INTEGER NOT NULL,
            task_id TEXT,
            reason TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
            created_at TEXT NOT NULL,
            FOREIGN KEY (plan_item_id) REFERENCES plan_items(plan_item_id),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dead_letter_items_plan_item
        ON dead_letter_items (plan_item_id, dead_letter_id)
        """
    )


def _create_memory_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_lessons (
            lesson_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_task_id TEXT NOT NULL,
            source_iteration_id INTEGER,
            lesson TEXT NOT NULL,
            outcome_status TEXT NOT NULL,
            failure_reason TEXT,
            failed_checks_json TEXT NOT NULL DEFAULT '[]',
            follow_up_prompt TEXT,
            helpful_count INTEGER NOT NULL DEFAULT 0 CHECK (helpful_count >= 0),
            unhelpful_count INTEGER NOT NULL DEFAULT 0 CHECK (unhelpful_count >= 0),
            stale_after_days INTEGER NOT NULL DEFAULT 90 CHECK (stale_after_days >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_task_id) REFERENCES tasks(task_id),
            FOREIGN KEY (source_iteration_id) REFERENCES iterations(iteration_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_lessons_source
        ON memory_lessons (source_task_id, source_iteration_id, lesson_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_lessons_recency
        ON memory_lessons (created_at, lesson_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reflection_records (
            reflection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            iteration_id INTEGER,
            reflection_type TEXT NOT NULL CHECK (
                reflection_type IN ('blocked_run', 'failed_verification')
            ),
            failure_reason TEXT NOT NULL,
            failed_checks_json TEXT NOT NULL DEFAULT '[]',
            follow_up_prompt TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id),
            FOREIGN KEY (iteration_id) REFERENCES iterations(iteration_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reflection_records_task
        ON reflection_records (task_id, iteration_id, reflection_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_influence_log (
            influence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            iteration_id INTEGER,
            lesson_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            injected INTEGER NOT NULL DEFAULT 1 CHECK (injected IN (0, 1)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id),
            FOREIGN KEY (iteration_id) REFERENCES iterations(iteration_id),
            FOREIGN KEY (lesson_id) REFERENCES memory_lessons(lesson_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_influence_task
        ON memory_influence_log (task_id, iteration_id, influence_id)
        """
    )


def _create_task_events_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE (task_id, sequence),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_events_task_sequence
        ON task_events (task_id, sequence)
        """
    )


def _create_action_records_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS action_records (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            iteration_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN (
                    'started',
                    'succeeded',
                    'failed',
                    'skipped',
                    'policy_denied',
                    'needs_approval'
                )
            ),
            command_string TEXT,
            policy_action TEXT,
            policy_reason TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            lease_owner TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id),
            FOREIGN KEY (iteration_id) REFERENCES iterations(iteration_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_action_records_task_iteration
        ON action_records (task_id, iteration_id, action_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_action_records_status
        ON action_records (status, action_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_action_records_lease_expiry
        ON action_records (status, lease_expires_at, action_id)
        """
    )


def _add_action_lease_columns(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "action_records"):
        return
    _add_column_if_missing(connection, "action_records", "lease_owner", "TEXT")
    _add_column_if_missing(connection, "action_records", "lease_expires_at", "TEXT")
    _add_column_if_missing(connection, "action_records", "heartbeat_at", "TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_action_records_lease_expiry
        ON action_records (status, lease_expires_at, action_id)
        """
    )


def _add_plan_item_graph_link_columns(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "plan_items"):
        return
    _add_column_if_missing(connection, "plan_items", "plan_graph_id", "INTEGER")
    _add_column_if_missing(
        connection,
        "plan_items",
        "plan_graph_root_node_id",
        "INTEGER",
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plan_items_plan_graph
        ON plan_items (plan_graph_id, plan_graph_root_node_id, plan_item_id)
        """
    )


def _create_replan_decisions_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS replan_decisions (
            replan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            iteration_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL {_REPLAN_DECISION_STATUS_CHECK},
            reason TEXT NOT NULL,
            follow_up_prompt TEXT,
            failed_checks_json TEXT NOT NULL DEFAULT '[]',
            plan_graph_id INTEGER,
            plan_graph_node_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id),
            FOREIGN KEY (iteration_id) REFERENCES iterations(iteration_id),
            FOREIGN KEY (plan_graph_id) REFERENCES plan_graphs(graph_id),
            FOREIGN KEY (plan_graph_node_id) REFERENCES plan_graph_nodes(node_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_replan_decisions_task_iteration
        ON replan_decisions (task_id, iteration_id, replan_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_replan_decisions_plan_graph
        ON replan_decisions (plan_graph_id, plan_graph_node_id, replan_id)
        """
    )


def _create_plan_graph_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS plan_graphs (
            graph_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            title TEXT NOT NULL,
            status TEXT NOT NULL {_PLAN_GRAPH_STATUS_CHECK},
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plan_graphs_task_status
        ON plan_graphs (task_id, status, graph_id)
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS plan_graph_nodes (
            node_id INTEGER PRIMARY KEY AUTOINCREMENT,
            graph_id INTEGER NOT NULL,
            node_key TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL {_PLAN_GRAPH_NODE_STATUS_CHECK},
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
        CREATE INDEX IF NOT EXISTS idx_plan_graph_nodes_graph_status
        ON plan_graph_nodes (graph_id, status, node_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_graph_dependencies (
            graph_id INTEGER NOT NULL,
            node_id INTEGER NOT NULL,
            depends_on_node_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (node_id, depends_on_node_id),
            CHECK (node_id <> depends_on_node_id),
            FOREIGN KEY (graph_id) REFERENCES plan_graphs(graph_id),
            FOREIGN KEY (node_id) REFERENCES plan_graph_nodes(node_id),
            FOREIGN KEY (depends_on_node_id) REFERENCES plan_graph_nodes(node_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plan_graph_dependencies_graph
        ON plan_graph_dependencies (graph_id, node_id, depends_on_node_id)
        """
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


MIGRATIONS: dict[int, Migration] = {
    1: _migrate_1_to_2,
    2: _migrate_2_to_3,
    3: _migrate_3_to_4,
    4: _migrate_4_to_5,
    5: _migrate_5_to_6,
    6: _migrate_6_to_7,
    7: _migrate_7_to_8,
    8: _migrate_8_to_9,
    9: _migrate_9_to_10,
    10: _migrate_10_to_11,
    11: _migrate_11_to_12,
    12: _migrate_12_to_13,
    13: _migrate_13_to_14,
    14: _migrate_14_to_15,
    15: _migrate_15_to_16,
    16: _migrate_16_to_17,
}


def migrate_schema(connection: sqlite3.Connection) -> int:
    current_version = schema_version(connection)
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported state store schema version: {current_version}")
    if current_version == 0:
        set_schema_version(connection, SCHEMA_VERSION)
    else:
        migrate_between_versions(connection, current_version, SCHEMA_VERSION)
    return schema_version(connection)


def schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def set_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(f"PRAGMA user_version = {version}")


def migrate_between_versions(
    connection: sqlite3.Connection,
    current_version: int,
    target_version: int,
    migrations: dict[int, Migration] | None = None,
) -> None:
    if current_version >= target_version:
        return

    migration_map = migrations if migrations is not None else MIGRATIONS
    version = current_version
    while version < target_version:
        migration = migration_map.get(version)
        if migration is None:
            raise RuntimeError(
                f"Missing state store migration path: {version} -> {version + 1}"
            )
        migration(connection)
        version += 1
        set_schema_version(connection, version)
