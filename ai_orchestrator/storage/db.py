from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ai_orchestrator.storage.migrations import SCHEMA_VERSION, migrate_schema, schema_version
from ai_orchestrator.storage.redaction import redact_secrets
from ai_orchestrator.verification.runner import VerificationResult


logger = logging.getLogger(__name__)


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
    agent_summary: str | None = None
    files_changed: list[str] = field(default_factory=list)
    tool_actions: list[str] = field(default_factory=list)
    exit_reason: str | None = None
    uncertainty: str | None = None


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
    agent_summary: str | None = None
    files_changed: list[str] = field(default_factory=list)
    tool_actions: list[str] = field(default_factory=list)
    exit_reason: str | None = None
    uncertainty: str | None = None


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


@dataclass(frozen=True)
class StoredApprovalRequest:
    approval_id: int
    task_id: str
    iteration_id: int | None
    source: str
    command_string: str
    reason: str
    status: str
    created_at: str
    resolved_at: str | None
    resolution: str | None
    retry_count: int = 0
    last_retry_at: str | None = None
    last_retry_status: str | None = None
    last_retry_exit_code: int | None = None
    last_retry_error: str | None = None


@dataclass(frozen=True)
class StoredMetricsSummary:
    task_count: int
    iteration_count: int
    verification_count: int
    verification_passed_count: int
    approval_count: int
    approval_pending_count: int
    approval_approved_count: int
    approval_rejected_count: int
    approval_stale_count: int
    adapter_failure_count: int

    @property
    def verification_pass_rate(self) -> float:
        if self.verification_count == 0:
            return 0.0
        return self.verification_passed_count / self.verification_count


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
                    agent_summary TEXT,
                    files_changed TEXT NOT NULL DEFAULT '[]',
                    tool_actions TEXT NOT NULL DEFAULT '[]',
                    exit_reason TEXT,
                    uncertainty TEXT,
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

                CREATE TABLE IF NOT EXISTS approval_requests (
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
                );

                CREATE INDEX IF NOT EXISTS idx_approval_requests_task_status
                ON approval_requests (task_id, status, approval_id);
                """
            )
            migrate_schema(connection)
        logger.debug("state store initialized schema_version=%s", SCHEMA_VERSION)

    def schema_version(self) -> int:
        self.initialize()
        with self._connect() as connection:
            return schema_version(connection)

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
        logger.debug("state task created task_id=%s status=%s", record.task_id, record.status)
        return record

    def update_task_status(self, task_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, _now(), task_id),
            )
        logger.debug("state task status updated task_id=%s status=%s", task_id, status)

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
        agent_summary: str | None = None,
        files_changed: list[str] | None = None,
        tool_actions: list[str] | None = None,
        exit_reason: str | None = None,
        uncertainty: str | None = None,
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
                    agent_summary,
                    files_changed,
                    tool_actions,
                    exit_reason,
                    uncertainty,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    iteration_index,
                    agent_name,
                    agent_status,
                    prompt,
                    redact_secrets(raw_output) or "",
                    decision_status,
                    decision_reason,
                    redact_secrets(agent_summary),
                    _encode_json_list(files_changed),
                    _encode_json_list(tool_actions),
                    redact_secrets(exit_reason),
                    redact_secrets(uncertainty),
                    _now(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create state iteration")
            iteration_id = cursor.lastrowid
        logger.debug(
            "state iteration added task_id=%s iteration_id=%s iteration_index=%s agent=%s status=%s",
            task_id,
            iteration_id,
            iteration_index,
            agent_name,
            agent_status,
        )
        return StoredIteration(
            iteration_id=iteration_id,
            task_id=task_id,
            iteration_index=iteration_index,
            agent_name=agent_name,
            agent_status=agent_status,
            decision_status=decision_status,
            decision_reason=decision_reason,
            agent_summary=redact_secrets(agent_summary),
            files_changed=_decode_json_list(_encode_json_list(files_changed)),
            tool_actions=_decode_json_list(_encode_json_list(tool_actions)),
            exit_reason=redact_secrets(exit_reason),
            uncertainty=redact_secrets(uncertainty),
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
                    redact_secrets(result.stdout) or "",
                    redact_secrets(result.stderr) or "",
                    redact_secrets(result.error),
                    _now(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create verification run")
            verification_id = cursor.lastrowid
        logger.debug(
            "state verification added task_id=%s iteration_id=%s verification_id=%s name=%s status=%s",
            task_id,
            iteration_id,
            verification_id,
            result.name,
            result.status,
        )
        return StoredVerificationRun(
            verification_id=verification_id,
            task_id=task_id,
            iteration_id=iteration_id,
            name=result.name,
            status=result.status,
            exit_code=result.exit_code,
        )

    def add_approval_request(
        self,
        task_id: str,
        iteration_id: int | None,
        source: str,
        command_string: str,
        reason: str,
    ) -> StoredApprovalRequest:
        self.initialize()
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO approval_requests (
                    task_id,
                    iteration_id,
                    source,
                    command_string,
                    reason,
                    status,
                    created_at,
                    resolved_at,
                    resolution,
                    retry_count,
                    last_retry_at,
                    last_retry_status,
                    last_retry_exit_code,
                    last_retry_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    iteration_id,
                    source,
                    command_string,
                    redact_secrets(reason) or "",
                    "pending",
                    now,
                    None,
                    None,
                    0,
                    None,
                    None,
                    None,
                    None,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create approval request")
            approval_id = cursor.lastrowid
        logger.debug(
            "state approval added task_id=%s approval_id=%s source=%s status=pending",
            task_id,
            approval_id,
            source,
        )
        return StoredApprovalRequest(
            approval_id=approval_id,
            task_id=task_id,
            iteration_id=iteration_id,
            source=source,
            command_string=command_string,
            reason=redact_secrets(reason) or "",
            status="pending",
            created_at=now,
            resolved_at=None,
            resolution=None,
            retry_count=0,
            last_retry_at=None,
            last_retry_status=None,
            last_retry_exit_code=None,
            last_retry_error=None,
        )

    def get_approval_request(self, approval_id: int) -> StoredApprovalRequest | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
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
                    resolution,
                    retry_count,
                    last_retry_at,
                    last_retry_status,
                    last_retry_exit_code,
                    last_retry_error
                FROM approval_requests
                WHERE approval_id = ?
                """,
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredApprovalRequest(**dict(row))

    def list_approval_requests(
        self,
        task_id: str | None = None,
        status: str | None = None,
    ) -> list[StoredApprovalRequest]:
        self.initialize()
        if status is not None and status not in {"pending", "approved", "rejected", "stale"}:
            raise ValueError(f"Unsupported approval status: {status}")

        query = """
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
                resolution,
                retry_count,
                last_retry_at,
                last_retry_status,
                last_retry_exit_code,
                last_retry_error
            FROM approval_requests
            WHERE 1 = 1
        """
        params: list[str] = []
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at ASC, approval_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [StoredApprovalRequest(**dict(row)) for row in rows]

    def resolve_approval_request(
        self,
        approval_id: int,
        status: str,
        resolution: str | None = None,
    ) -> StoredApprovalRequest | None:
        self.initialize()
        if status not in {"approved", "rejected", "stale"}:
            raise ValueError(f"Unsupported approval resolution status: {status}")

        resolved_at = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE approval_requests
                SET status = ?, resolved_at = ?, resolution = ?
                WHERE approval_id = ?
                """,
                (
                    status,
                    resolved_at,
                    redact_secrets(resolution),
                    approval_id,
                ),
            )
            if cursor.rowcount == 0:
                return None

        logger.debug(
            "state approval resolved approval_id=%s status=%s",
            approval_id,
            status,
        )
        return self.get_approval_request(approval_id)

    def mark_stale_approval_requests(
        self,
        cutoff_created_at: str,
        task_id: str | None = None,
        resolution: str | None = None,
    ) -> list[StoredApprovalRequest]:
        self.initialize()
        resolved_at = _now()
        resolved_message = resolution or f"stale approval older than {cutoff_created_at}"
        query = """
            SELECT approval_id
            FROM approval_requests
            WHERE status = 'pending'
              AND created_at < ?
        """
        params: list[str] = [cutoff_created_at]
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)
        query += " ORDER BY created_at ASC, approval_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            approval_ids = [int(row["approval_id"]) for row in rows]
            if approval_ids:
                placeholders = ", ".join("?" for _ in approval_ids)
                connection.execute(
                    f"""
                    UPDATE approval_requests
                    SET status = 'stale', resolved_at = ?, resolution = ?
                    WHERE approval_id IN ({placeholders})
                    """,
                    (
                        resolved_at,
                        redact_secrets(resolved_message),
                        *approval_ids,
                    ),
                )

        return [
            approval
            for approval_id in approval_ids
            if (approval := self.get_approval_request(approval_id)) is not None
        ]

    def record_approval_retry(
        self,
        approval_id: int,
        status: str,
        exit_code: int | None,
        error: str | None = None,
    ) -> StoredApprovalRequest | None:
        self.initialize()
        retry_at = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE approval_requests
                SET
                    retry_count = retry_count + 1,
                    last_retry_at = ?,
                    last_retry_status = ?,
                    last_retry_exit_code = ?,
                    last_retry_error = ?
                WHERE approval_id = ?
                """,
                (
                    retry_at,
                    status,
                    exit_code,
                    redact_secrets(error),
                    approval_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_approval_request(approval_id)

    def metrics_summary(self) -> StoredMetricsSummary:
        self.initialize()
        with self._connect() as connection:
            approval_counts = _approval_status_counts(connection)
            verification_counts = _verification_status_counts(connection)
            return StoredMetricsSummary(
                task_count=_task_count(connection),
                iteration_count=_iteration_count(connection),
                verification_count=sum(verification_counts.values()),
                verification_passed_count=verification_counts.get("passed", 0),
                approval_count=sum(approval_counts.values()),
                approval_pending_count=approval_counts.get("pending", 0),
                approval_approved_count=approval_counts.get("approved", 0),
                approval_rejected_count=approval_counts.get("rejected", 0),
                approval_stale_count=approval_counts.get("stale", 0),
                adapter_failure_count=_adapter_failure_count(connection),
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
                    decision_reason,
                    agent_summary,
                    files_changed,
                    tool_actions,
                    exit_reason,
                    uncertainty
                FROM iterations
                WHERE task_id = ?
                ORDER BY iteration_index ASC, iteration_id ASC
                """,
                (task_id,),
            ).fetchall()
        return [_stored_iteration_from_row(row) for row in rows]

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
                    decision_reason,
                    agent_summary,
                    files_changed,
                    tool_actions,
                    exit_reason,
                    uncertainty
                FROM iterations
                WHERE task_id = ?
                ORDER BY iteration_index ASC, iteration_id ASC
                """,
                (task_id,),
            ).fetchall()
        return [_stored_iteration_detail_from_row(row) for row in rows]

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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _encode_json_list(values: list[str] | None) -> str:
    redacted = [redact_secrets(value) or "" for value in values or []]
    return json.dumps(redacted)


def _decode_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if isinstance(item, str)]


def _task_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()
    return int(row["count"])


def _iteration_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM iterations").fetchone()
    return int(row["count"])


def _verification_status_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        "SELECT status, COUNT(*) AS count FROM verification_runs GROUP BY status"
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _approval_status_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        "SELECT status, COUNT(*) AS count FROM approval_requests GROUP BY status"
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _adapter_failure_count(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM iterations
        WHERE agent_status IN ('failed', 'timeout', 'unavailable')
        """
    ).fetchone()
    return int(row["count"])


def _stored_iteration_from_row(row: sqlite3.Row) -> StoredIteration:
    values = dict(row)
    values["files_changed"] = _decode_json_list(values.get("files_changed"))
    values["tool_actions"] = _decode_json_list(values.get("tool_actions"))
    return StoredIteration(**values)


def _stored_iteration_detail_from_row(row: sqlite3.Row) -> StoredIterationDetail:
    values = dict(row)
    values["files_changed"] = _decode_json_list(values.get("files_changed"))
    values["tool_actions"] = _decode_json_list(values.get("tool_actions"))
    return StoredIterationDetail(**values)
