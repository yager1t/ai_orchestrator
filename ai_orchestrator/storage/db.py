from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ai_orchestrator.verification.runner import VerificationResult


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StoredTask:
    task_id: str
    task: str
    repo_path: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredIteration:
    iteration_id: int
    task_id: str
    iteration_index: int
    agent_name: str
    agent_status: str
    decision_status: str
    decision_reason: str


@dataclass(frozen=True)
class StoredIterationDetail:
    iteration_id: int
    task_id: str
    iteration_index: int
    agent_name: str
    agent_status: str
    prompt: str
    raw_output: str
    decision_status: str
    decision_reason: str


@dataclass(frozen=True)
class StoredVerificationRun:
    verification_id: int
    task_id: str
    iteration_id: int
    name: str
    status: str
    exit_code: int | None


@dataclass(frozen=True)
class StoredVerificationDetail:
    verification_id: int
    task_id: str
    iteration_id: int
    name: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS iterations (
                    iteration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    iteration_index INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    agent_status TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    raw_output TEXT NOT NULL,
                    decision_status TEXT NOT NULL,
                    decision_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS verification_runs (
                    verification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    iteration_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    stdout TEXT NOT NULL,
                    stderr TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id),
                    FOREIGN KEY (iteration_id) REFERENCES iterations(iteration_id)
                );
                """
            )
            current_version = self._schema_version(connection)
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported state store schema version: {current_version}"
                )
            if current_version == 0:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        self.initialize()
        with self._connect() as connection:
            return self._schema_version(connection)

    def create_task(
        self,
        task: str,
        repo_path: Path,
        status: str = "created",
        task_id: str | None = None,
    ) -> StoredTask:
        self.initialize()
        now = _now()
        record = StoredTask(
            task_id=task_id or f"task-{uuid4()}",
            task=task,
            repo_path=str(repo_path),
            status=status,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (task_id, task, repo_path, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    record.task,
                    record.repo_path,
                    record.status,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def update_task_status(self, task_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, _now(), task_id),
            )

    def get_task(self, task_id: str) -> StoredTask | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT task_id, task, repo_path, status, created_at, updated_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredTask(**dict(row))

    def list_tasks(self) -> list[StoredTask]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, task, repo_path, status, created_at, updated_at
                FROM tasks
                ORDER BY updated_at DESC, created_at DESC, task_id DESC
                """
            ).fetchall()
        return [StoredTask(**dict(row)) for row in rows]

    def add_iteration(
        self,
        task_id: str,
        iteration_index: int,
        agent_name: str,
        agent_status: str,
        prompt: str,
        raw_output: str,
        decision_status: str,
        decision_reason: str,
    ) -> StoredIteration:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO iterations (
                    task_id,
                    iteration_index,
                    agent_name,
                    agent_status,
                    prompt,
                    raw_output,
                    decision_status,
                    decision_reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    iteration_index,
                    agent_name,
                    agent_status,
                    prompt,
                    raw_output,
                    decision_status,
                    decision_reason,
                    _now(),
                ),
            )
            iteration_id = int(cursor.lastrowid)
        return StoredIteration(
            iteration_id=iteration_id,
            task_id=task_id,
            iteration_index=iteration_index,
            agent_name=agent_name,
            agent_status=agent_status,
            decision_status=decision_status,
            decision_reason=decision_reason,
        )

    def add_verification_run(
        self,
        task_id: str,
        iteration_id: int,
        result: VerificationResult,
    ) -> StoredVerificationRun:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO verification_runs (
                    task_id,
                    iteration_id,
                    name,
                    status,
                    exit_code,
                    stdout,
                    stderr,
                    error,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    iteration_id,
                    result.name,
                    result.status,
                    result.exit_code,
                    result.stdout,
                    result.stderr,
                    result.error,
                    _now(),
                ),
            )
            verification_id = int(cursor.lastrowid)
        return StoredVerificationRun(
            verification_id=verification_id,
            task_id=task_id,
            iteration_id=iteration_id,
            name=result.name,
            status=result.status,
            exit_code=result.exit_code,
        )

    def list_iterations(self, task_id: str) -> list[StoredIteration]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    iteration_id,
                    task_id,
                    iteration_index,
                    agent_name,
                    agent_status,
                    decision_status,
                    decision_reason
                FROM iterations
                WHERE task_id = ?
                ORDER BY iteration_index ASC, iteration_id ASC
                """,
                (task_id,),
            ).fetchall()
        return [StoredIteration(**dict(row)) for row in rows]

    def list_iteration_details(self, task_id: str) -> list[StoredIterationDetail]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    iteration_id,
                    task_id,
                    iteration_index,
                    agent_name,
                    agent_status,
                    prompt,
                    raw_output,
                    decision_status,
                    decision_reason
                FROM iterations
                WHERE task_id = ?
                ORDER BY iteration_index ASC, iteration_id ASC
                """,
                (task_id,),
            ).fetchall()
        return [StoredIterationDetail(**dict(row)) for row in rows]

    def list_verification_runs(
        self,
        task_id: str,
        iteration_id: int | None = None,
    ) -> list[StoredVerificationRun]:
        self.initialize()
        query = """
            SELECT verification_id, task_id, iteration_id, name, status, exit_code
            FROM verification_runs
            WHERE task_id = ?
        """
        params: tuple[str] | tuple[str, int] = (task_id,)
        if iteration_id is not None:
            query += " AND iteration_id = ?"
            params = (task_id, iteration_id)
        query += " ORDER BY verification_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [StoredVerificationRun(**dict(row)) for row in rows]

    def list_verification_details(
        self,
        task_id: str,
        iteration_id: int | None = None,
    ) -> list[StoredVerificationDetail]:
        self.initialize()
        query = """
            SELECT
                verification_id,
                task_id,
                iteration_id,
                name,
                status,
                exit_code,
                stdout,
                stderr,
                error
            FROM verification_runs
            WHERE task_id = ?
        """
        params: tuple[str] | tuple[str, int] = (task_id,)
        if iteration_id is not None:
            query += " AND iteration_id = ?"
            params = (task_id, iteration_id)
        query += " ORDER BY verification_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [StoredVerificationDetail(**dict(row)) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _schema_version(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _now() -> str:
    return datetime.now(UTC).isoformat()
