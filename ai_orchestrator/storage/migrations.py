from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 1


def migrate_schema(connection: sqlite3.Connection) -> int:
    current_version = schema_version(connection)
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported state store schema version: {current_version}")
    if current_version == 0:
        set_schema_version(connection, SCHEMA_VERSION)
    return schema_version(connection)


def schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def set_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(f"PRAGMA user_version = {version}")
