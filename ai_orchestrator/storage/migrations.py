from __future__ import annotations

import sqlite3
from collections.abc import Callable


SCHEMA_VERSION = 3
Migration = Callable[[sqlite3.Connection], None]


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


MIGRATIONS: dict[int, Migration] = {
    1: _migrate_1_to_2,
    2: _migrate_2_to_3,
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
