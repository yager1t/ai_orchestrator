from __future__ import annotations

import sqlite3
from collections.abc import Callable


SCHEMA_VERSION = 1
Migration = Callable[[sqlite3.Connection], None]
MIGRATIONS: dict[int, Migration] = {}


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
