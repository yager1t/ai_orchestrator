from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ai_orchestrator.storage.migrations import SCHEMA_VERSION, migrate_schema, schema_version
from ai_orchestrator.storage.redaction import redact_secrets
from ai_orchestrator.verification.runner import VerificationResult


logger = logging.getLogger(__name__)
_MEMORY_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_MEMORY_STOP_WORDS = {
    "and",
    "for",
    "the",
    "this",
    "that",
    "with",
    "after",
    "before",
    "into",
    "from",
    "task",
}


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
class StoredTaskEvent:
    event_id: int
    task_id: str
    sequence: int
    run_id: str | None
    session_id: str | None
    iteration_id: int | None
    correlation_id: str | None
    idempotency_key: str | None
    event_type: str
    actor: str
    summary: str
    payload: dict[str, object]
    payload_preview: str
    created_at: str


@dataclass(frozen=True)
class StoredActionRecord:
    action_id: int
    task_id: str
    iteration_id: int | None
    idempotency_key: str
    action_type: str
    status: str
    command_string: str | None
    policy_action: str | None
    policy_reason: str | None
    payload: dict[str, object]
    result: dict[str, object]
    lease_owner: str | None
    lease_expires_at: str | None
    heartbeat_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredTimelineEntry:
    timeline_index: int
    occurred_at: str
    source: str
    source_id: str
    event_type: str
    status: str | None
    summary: str
    payload: dict[str, object]


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


@dataclass(frozen=True)
class StoredPlanItem:
    plan_item_id: int
    plan_path: str
    line_number: int
    section: str
    text: str
    status: str
    task_id: str | None
    selected_worktree_path: str | None
    blocked_reason: str | None
    plan_graph_id: int | None
    plan_graph_root_node_id: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredPlanGraph:
    graph_id: int
    task_id: str | None
    title: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredPlanGraphNode:
    node_id: int
    graph_id: int
    node_key: str
    title: str
    task_text: str
    acceptance_criteria: list[str]
    verification_requirement: str | None
    status: str
    blocked_reason: str | None
    task_id: str | None
    plan_item_id: int | None
    source_node_id: int | None
    node_type: str
    attempts: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredPlanGraphDependency:
    graph_id: int
    node_id: int
    depends_on_node_id: int
    created_at: str


@dataclass(frozen=True)
class StoredPlanGraphNodeReadiness:
    node: StoredPlanGraphNode
    ready: bool
    reason: str
    blocking_dependencies: list[StoredPlanGraphNode] = field(default_factory=list)


@dataclass(frozen=True)
class StoredReplanDecision:
    replan_id: int
    task_id: str
    iteration_id: int
    source: str
    status: str
    reason: str
    follow_up_prompt: str | None
    failed_checks: list[dict[str, object]]
    plan_graph_id: int | None
    plan_graph_node_id: int | None
    created_at: str


@dataclass(frozen=True)
class StoredMemoryLesson:
    lesson_id: int
    source_task_id: str
    source_iteration_id: int | None
    lesson: str
    outcome_status: str
    failure_reason: str | None
    failed_checks: list[dict[str, object]]
    follow_up_prompt: str | None
    helpful_count: int
    unhelpful_count: int
    stale_after_days: int
    created_at: str
    updated_at: str

    @property
    def is_stale(self) -> bool:
        if self.unhelpful_count >= 3:
            return True
        if self.stale_after_days == 0:
            return True
        try:
            created_at = datetime.fromisoformat(self.created_at)
        except ValueError:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - created_at > timedelta(days=self.stale_after_days)


@dataclass(frozen=True)
class StoredReflectionRecord:
    reflection_id: int
    task_id: str
    iteration_id: int | None
    reflection_type: str
    failure_reason: str
    failed_checks: list[dict[str, object]]
    follow_up_prompt: str | None
    created_at: str


@dataclass(frozen=True)
class StoredMemoryInfluence:
    influence_id: int
    task_id: str
    iteration_id: int | None
    lesson_id: int
    reason: str
    injected: bool
    created_at: str


@dataclass(frozen=True)
class StoredDeadLetterItem:
    dead_letter_id: int
    plan_item_id: int
    task_id: str | None
    reason: str
    attempts: int
    created_at: str


@dataclass(frozen=True)
class StoredAutopilotLoopRun:
    loop_run_id: int
    plan_path: str
    mode: str
    max_runtime_sec: int | None
    max_attempts: int
    max_actions: int
    selected_count: int
    processed_count: int
    dead_letter_count: int
    stop_reason: str
    result_code: int
    selected_item_ids: list[int]
    elapsed_sec: float
    started_at: str
    completed_at: str


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

                CREATE TABLE IF NOT EXISTS plan_items (
                    plan_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_path TEXT NOT NULL,
                    line_number INTEGER NOT NULL,
                    section TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('created', 'in_progress', 'done', 'blocked', 'skipped')),
                    task_id TEXT,
                    selected_worktree_path TEXT,
                    blocked_reason TEXT,
                    plan_graph_id INTEGER,
                    plan_graph_root_node_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id),
                    FOREIGN KEY (plan_graph_id) REFERENCES plan_graphs(graph_id),
                    FOREIGN KEY (plan_graph_root_node_id) REFERENCES plan_graph_nodes(node_id)
                );

                CREATE INDEX IF NOT EXISTS idx_plan_items_plan_status
                ON plan_items (plan_path, status, line_number);

                CREATE INDEX IF NOT EXISTS idx_plan_items_status_id
                ON plan_items (status, plan_item_id);

                CREATE TABLE IF NOT EXISTS task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    run_id TEXT,
                    session_id TEXT,
                    iteration_id INTEGER,
                    correlation_id TEXT,
                    idempotency_key TEXT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    summary TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    payload_preview TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE (task_id, sequence),
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                );

                CREATE INDEX IF NOT EXISTS idx_task_events_task_sequence
                ON task_events (task_id, sequence);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_events_task_idempotency
                ON task_events (task_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL;

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
                );

                CREATE INDEX IF NOT EXISTS idx_action_records_task_iteration
                ON action_records (task_id, iteration_id, action_id);

                CREATE INDEX IF NOT EXISTS idx_action_records_status
                ON action_records (status, action_id);

                CREATE INDEX IF NOT EXISTS idx_action_records_lease_expiry
                ON action_records (status, lease_expires_at, action_id);

                CREATE TABLE IF NOT EXISTS plan_graphs (
                    graph_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active', 'done', 'blocked', 'archived')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                );

                CREATE INDEX IF NOT EXISTS idx_plan_graphs_task_status
                ON plan_graphs (task_id, status, graph_id);

                CREATE TABLE IF NOT EXISTS plan_graph_nodes (
                    node_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    graph_id INTEGER NOT NULL,
                    node_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_text TEXT NOT NULL DEFAULT '',
                    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
                    verification_requirement TEXT,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'done', 'blocked', 'failed', 'skipped')),
                    blocked_reason TEXT,
                    task_id TEXT,
                    plan_item_id INTEGER,
                    source_node_id INTEGER,
                    node_type TEXT NOT NULL DEFAULT 'task',
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (graph_id, node_key),
                    FOREIGN KEY (graph_id) REFERENCES plan_graphs(graph_id)
                );

                CREATE INDEX IF NOT EXISTS idx_plan_graph_nodes_graph_status
                ON plan_graph_nodes (graph_id, status, node_id);

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
                );

                CREATE INDEX IF NOT EXISTS idx_plan_graph_dependencies_graph
                ON plan_graph_dependencies (graph_id, node_id, depends_on_node_id);

                CREATE TABLE IF NOT EXISTS replan_decisions (
                    replan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    iteration_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('continue', 'blocked')),
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
                );

                CREATE INDEX IF NOT EXISTS idx_replan_decisions_task_iteration
                ON replan_decisions (task_id, iteration_id, replan_id);

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
                );

                CREATE INDEX IF NOT EXISTS idx_memory_lessons_source
                ON memory_lessons (source_task_id, source_iteration_id, lesson_id);

                CREATE INDEX IF NOT EXISTS idx_memory_lessons_recency
                ON memory_lessons (created_at, lesson_id);

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
                );

                CREATE INDEX IF NOT EXISTS idx_reflection_records_task
                ON reflection_records (task_id, iteration_id, reflection_id);

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
                );

                CREATE INDEX IF NOT EXISTS idx_memory_influence_task
                ON memory_influence_log (task_id, iteration_id, influence_id);

                CREATE TABLE IF NOT EXISTS dead_letter_items (
                    dead_letter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_item_id INTEGER NOT NULL,
                    task_id TEXT,
                    reason TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (plan_item_id) REFERENCES plan_items(plan_item_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                );

                CREATE INDEX IF NOT EXISTS idx_dead_letter_items_plan_item
                ON dead_letter_items (plan_item_id, dead_letter_id);

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
                );

                CREATE INDEX IF NOT EXISTS idx_autopilot_loop_runs_plan
                ON autopilot_loop_runs (plan_path, loop_run_id);
                """
            )
            migrate_schema(connection)
            _ensure_current_indexes(connection)
        logger.debug("state store initialized schema_version=%s", SCHEMA_VERSION)

    def schema_version(self) -> int:
        self.initialize()
        with self._connect() as connection:
            return schema_version(connection)

    def run_id_for_task(self, task_id: str) -> str:
        return _run_id_for_task(task_id)

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

    def append_task_event(
        self,
        task_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        iteration_id: int | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        actor: str = "system",
        summary: str | None = None,
        payload_preview: str | None = None,
    ) -> StoredTaskEvent:
        self.initialize()
        if not event_type.strip():
            raise ValueError("Task event type cannot be empty")
        if not actor.strip():
            raise ValueError("Task event actor cannot be empty")

        now = _now()
        payload_json = _encode_json_payload(payload)
        normalized_event_type = event_type.strip()
        normalized_actor = actor.strip()
        normalized_idempotency_key = (
            idempotency_key.strip()
            if idempotency_key is not None and idempotency_key.strip()
            else None
        )
        normalized_summary = redact_secrets(summary or normalized_event_type) or ""
        normalized_preview = _event_payload_preview(
            payload_preview if payload_preview is not None else payload
        )
        with self._connect() as connection:
            if normalized_idempotency_key is not None:
                existing = self._task_event_by_idempotency_key(
                    connection,
                    task_id,
                    normalized_idempotency_key,
                )
                if existing is not None:
                    return _stored_task_event_from_row(existing)
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
                FROM task_events
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            sequence = int(row["sequence"])
            cursor = connection.execute(
                """
                INSERT INTO task_events (
                    task_id,
                    sequence,
                    run_id,
                    session_id,
                    iteration_id,
                    correlation_id,
                    idempotency_key,
                    event_type,
                    actor,
                    summary,
                    payload_json,
                    payload_preview,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    sequence,
                    run_id or _run_id_for_task(task_id),
                    session_id,
                    iteration_id,
                    correlation_id,
                    normalized_idempotency_key,
                    normalized_event_type,
                    normalized_actor,
                    normalized_summary,
                    payload_json,
                    normalized_preview,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create task event")
            event_id = cursor.lastrowid

        logger.debug(
            "state task event added task_id=%s event_id=%s sequence=%s type=%s",
            task_id,
            event_id,
            sequence,
            normalized_event_type,
        )
        return StoredTaskEvent(
            event_id=event_id,
            task_id=task_id,
            sequence=sequence,
            run_id=run_id or _run_id_for_task(task_id),
            session_id=session_id,
            iteration_id=iteration_id,
            correlation_id=correlation_id,
            idempotency_key=normalized_idempotency_key,
            event_type=normalized_event_type,
            actor=normalized_actor,
            summary=normalized_summary,
            payload=_decode_json_payload(payload_json),
            payload_preview=normalized_preview,
            created_at=now,
        )

    def list_task_events(self, task_id: str) -> list[StoredTaskEvent]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    task_id,
                    sequence,
                    run_id,
                    session_id,
                    iteration_id,
                    correlation_id,
                    idempotency_key,
                    event_type,
                    actor,
                    summary,
                    payload_json,
                    payload_preview,
                    created_at
                FROM task_events
                WHERE task_id = ?
                ORDER BY sequence ASC, event_id ASC
                """,
                (task_id,),
            ).fetchall()
        return [_stored_task_event_from_row(row) for row in rows]

    def _task_event_by_idempotency_key(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        idempotency_key: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT
                event_id,
                task_id,
                sequence,
                run_id,
                session_id,
                iteration_id,
                correlation_id,
                idempotency_key,
                event_type,
                actor,
                summary,
                payload_json,
                payload_preview,
                created_at
            FROM task_events
            WHERE task_id = ?
              AND idempotency_key = ?
            """,
            (task_id, idempotency_key),
        ).fetchone()

    def record_action(
        self,
        task_id: str,
        idempotency_key: str,
        action_type: str,
        status: str = "started",
        iteration_id: int | None = None,
        command_string: str | None = None,
        policy_action: str | None = None,
        policy_reason: str | None = None,
        payload: dict[str, object] | None = None,
        result: dict[str, object] | None = None,
    ) -> StoredActionRecord:
        self.initialize()
        _validate_action_status(status)
        if not idempotency_key.strip():
            raise ValueError("Action idempotency key cannot be empty")
        if not action_type.strip():
            raise ValueError("Action type cannot be empty")

        now = _now()
        payload_json = _encode_json_payload(payload)
        result_json = _encode_json_payload(result)
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO action_records (
                        task_id,
                        iteration_id,
                        idempotency_key,
                        action_type,
                        status,
                        command_string,
                        policy_action,
                        policy_reason,
                        payload_json,
                        result_json,
                        lease_owner,
                        lease_expires_at,
                        heartbeat_at,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        iteration_id,
                        idempotency_key.strip(),
                        action_type.strip(),
                        status,
                        redact_secrets(command_string),
                        redact_secrets(policy_action),
                        redact_secrets(policy_reason),
                        payload_json,
                        result_json,
                        None,
                        None,
                        None,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT
                        action_id,
                        task_id,
                        iteration_id,
                        idempotency_key,
                        action_type,
                        status,
                        command_string,
                        policy_action,
                        policy_reason,
                        payload_json,
                        result_json,
                        lease_owner,
                        lease_expires_at,
                        heartbeat_at,
                        created_at,
                        updated_at
                    FROM action_records
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key.strip(),),
                ).fetchone()
                if row is not None:
                    return _stored_action_record_from_row(row)
                raise
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create action record")
            action_id = cursor.lastrowid

        logger.debug(
            "state action recorded task_id=%s action_id=%s type=%s status=%s",
            task_id,
            action_id,
            action_type.strip(),
            status,
        )
        action = self.get_action_record(action_id)
        if action is None:
            raise RuntimeError("Failed to load recorded action")
        return action

    def complete_action_record(
        self,
        action_id: int,
        status: str,
        result: dict[str, object] | None = None,
    ) -> StoredActionRecord | None:
        self.initialize()
        _validate_action_status(status)
        updated_at = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE action_records
                SET status = ?,
                    result_json = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    updated_at = ?
                WHERE action_id = ?
                """,
                (
                    status,
                    _encode_json_payload(result),
                    updated_at,
                    action_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_action_record(action_id)

    def acquire_action_lease(
        self,
        action_id: int,
        lease_owner: str,
        ttl_sec: int,
        now: str | None = None,
    ) -> StoredActionRecord | None:
        self.initialize()
        _validate_lease_owner(lease_owner)
        _validate_lease_ttl(ttl_sec)
        heartbeat_at = now or _now()
        lease_expires_at = _expires_at(heartbeat_at, ttl_sec)
        owner = lease_owner.strip()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE action_records
                SET lease_owner = ?,
                    lease_expires_at = ?,
                    heartbeat_at = ?,
                    updated_at = ?
                WHERE action_id = ?
                  AND status = 'started'
                  AND (
                    lease_owner IS NULL
                    OR lease_owner = ?
                    OR lease_expires_at IS NULL
                    OR lease_expires_at <= ?
                  )
                """,
                (
                    owner,
                    lease_expires_at,
                    heartbeat_at,
                    heartbeat_at,
                    action_id,
                    owner,
                    heartbeat_at,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_action_record(action_id)

    def heartbeat_action_lease(
        self,
        action_id: int,
        lease_owner: str,
        ttl_sec: int,
        now: str | None = None,
    ) -> StoredActionRecord | None:
        self.initialize()
        _validate_lease_owner(lease_owner)
        _validate_lease_ttl(ttl_sec)
        heartbeat_at = now or _now()
        lease_expires_at = _expires_at(heartbeat_at, ttl_sec)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE action_records
                SET lease_expires_at = ?,
                    heartbeat_at = ?,
                    updated_at = ?
                WHERE action_id = ?
                  AND status = 'started'
                  AND lease_owner = ?
                  AND lease_expires_at > ?
                """,
                (
                    lease_expires_at,
                    heartbeat_at,
                    heartbeat_at,
                    action_id,
                    lease_owner.strip(),
                    heartbeat_at,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_action_record(action_id)

    def release_action_lease(
        self,
        action_id: int,
        lease_owner: str,
    ) -> StoredActionRecord | None:
        self.initialize()
        _validate_lease_owner(lease_owner)
        updated_at = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE action_records
                SET lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    updated_at = ?
                WHERE action_id = ?
                  AND lease_owner = ?
                """,
                (updated_at, action_id, lease_owner.strip()),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_action_record(action_id)

    def list_expired_action_leases(
        self,
        cutoff_at: str | None = None,
    ) -> list[StoredActionRecord]:
        self.initialize()
        cutoff = cutoff_at or _now()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    action_id,
                    task_id,
                    iteration_id,
                    idempotency_key,
                    action_type,
                    status,
                    command_string,
                    policy_action,
                    policy_reason,
                    payload_json,
                    result_json,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    created_at,
                    updated_at
                FROM action_records
                WHERE status = 'started'
                  AND lease_owner IS NOT NULL
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY lease_expires_at ASC, action_id ASC
                """,
                (cutoff,),
            ).fetchall()
        return [_stored_action_record_from_row(row) for row in rows]

    def list_stale_action_records(
        self,
        cutoff_at: str | None = None,
    ) -> list[StoredActionRecord]:
        self.initialize()
        cutoff = cutoff_at or (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        now = _now()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    action_id,
                    task_id,
                    iteration_id,
                    idempotency_key,
                    action_type,
                    status,
                    command_string,
                    policy_action,
                    policy_reason,
                    payload_json,
                    result_json,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    created_at,
                    updated_at
                FROM action_records
                WHERE status = 'started'
                  AND (
                    (
                      lease_owner IS NOT NULL
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= ?
                    )
                    OR (
                      (lease_owner IS NULL OR lease_expires_at IS NULL)
                      AND updated_at <= ?
                    )
                  )
                ORDER BY updated_at ASC, action_id ASC
                """,
                (now, cutoff),
            ).fetchall()
        return [_stored_action_record_from_row(row) for row in rows]

    def get_action_record(self, action_id: int) -> StoredActionRecord | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    action_id,
                    task_id,
                    iteration_id,
                    idempotency_key,
                    action_type,
                    status,
                    command_string,
                    policy_action,
                    policy_reason,
                    payload_json,
                    result_json,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    created_at,
                    updated_at
                FROM action_records
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_action_record_from_row(row)

    def get_action_record_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredActionRecord | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    action_id,
                    task_id,
                    iteration_id,
                    idempotency_key,
                    action_type,
                    status,
                    command_string,
                    policy_action,
                    policy_reason,
                    payload_json,
                    result_json,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    created_at,
                    updated_at
                FROM action_records
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return _stored_action_record_from_row(row)

    def list_action_records(
        self,
        task_id: str,
        iteration_id: int | None = None,
    ) -> list[StoredActionRecord]:
        self.initialize()
        query = """
            SELECT
                action_id,
                task_id,
                iteration_id,
                idempotency_key,
                action_type,
                status,
                command_string,
                policy_action,
                policy_reason,
                payload_json,
                result_json,
                lease_owner,
                lease_expires_at,
                heartbeat_at,
                created_at,
                updated_at
            FROM action_records
            WHERE task_id = ?
        """
        params: tuple[str] | tuple[str, int] = (task_id,)
        if iteration_id is not None:
            query += " AND iteration_id = ?"
            params = (task_id, iteration_id)
        query += " ORDER BY action_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_stored_action_record_from_row(row) for row in rows]

    def record_replan_decision(
        self,
        task_id: str,
        iteration_id: int,
        source: str,
        status: str,
        reason: str,
        failed_checks: list[dict[str, object]],
        follow_up_prompt: str | None = None,
        plan_graph_id: int | None = None,
        plan_graph_node_id: int | None = None,
    ) -> StoredReplanDecision:
        self.initialize()
        _validate_replan_decision_status(status)
        _validate_non_empty(source, "Replan decision source")
        now = _now()
        with self._connect() as connection:
            if plan_graph_id is not None:
                _validate_plan_item_graph_link(
                    connection,
                    plan_graph_id,
                    plan_graph_node_id,
                )
            elif plan_graph_node_id is not None:
                raise ValueError("Replan decision graph node requires plan graph id")
            cursor = connection.execute(
                """
                INSERT INTO replan_decisions (
                    task_id,
                    iteration_id,
                    source,
                    status,
                    reason,
                    follow_up_prompt,
                    failed_checks_json,
                    plan_graph_id,
                    plan_graph_node_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    iteration_id,
                    source.strip(),
                    status,
                    redact_secrets(reason) or "",
                    redact_secrets(follow_up_prompt) if follow_up_prompt else None,
                    _encode_json_array_payload(failed_checks),
                    plan_graph_id,
                    plan_graph_node_id,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create replan decision")
            replan_id = cursor.lastrowid

        decision = self.get_replan_decision(replan_id)
        if decision is None:
            raise RuntimeError("Failed to load created replan decision")
        return decision

    def get_replan_decision(
        self,
        replan_id: int,
    ) -> StoredReplanDecision | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    replan_id,
                    task_id,
                    iteration_id,
                    source,
                    status,
                    reason,
                    follow_up_prompt,
                    failed_checks_json,
                    plan_graph_id,
                    plan_graph_node_id,
                    created_at
                FROM replan_decisions
                WHERE replan_id = ?
                """,
                (replan_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_replan_decision_from_row(row)

    def list_replan_decisions(
        self,
        task_id: str,
        iteration_id: int | None = None,
    ) -> list[StoredReplanDecision]:
        self.initialize()
        query = """
            SELECT
                replan_id,
                task_id,
                iteration_id,
                source,
                status,
                reason,
                follow_up_prompt,
                failed_checks_json,
                plan_graph_id,
                plan_graph_node_id,
                created_at
            FROM replan_decisions
            WHERE task_id = ?
        """
        params: tuple[str] | tuple[str, int] = (task_id,)
        if iteration_id is not None:
            query += " AND iteration_id = ?"
            params = (task_id, iteration_id)
        query += " ORDER BY replan_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_stored_replan_decision_from_row(row) for row in rows]

    def record_memory_lesson(
        self,
        source_task_id: str,
        lesson: str,
        outcome_status: str,
        source_iteration_id: int | None = None,
        failure_reason: str | None = None,
        failed_checks: list[dict[str, object]] | None = None,
        follow_up_prompt: str | None = None,
        stale_after_days: int = 90,
    ) -> StoredMemoryLesson:
        self.initialize()
        _validate_non_empty(lesson, "Memory lesson")
        _validate_non_empty(outcome_status, "Memory outcome status")
        if stale_after_days < 0:
            raise ValueError("Memory stale-after days cannot be negative")
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_lessons (
                    source_task_id,
                    source_iteration_id,
                    lesson,
                    outcome_status,
                    failure_reason,
                    failed_checks_json,
                    follow_up_prompt,
                    helpful_count,
                    unhelpful_count,
                    stale_after_days,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_task_id,
                    source_iteration_id,
                    redact_secrets(lesson) or "",
                    outcome_status.strip(),
                    redact_secrets(failure_reason) if failure_reason else None,
                    _encode_json_array_payload(failed_checks),
                    redact_secrets(follow_up_prompt) if follow_up_prompt else None,
                    0,
                    0,
                    stale_after_days,
                    now,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create memory lesson")
            lesson_id = cursor.lastrowid
        loaded = self.get_memory_lesson(lesson_id)
        if loaded is None:
            raise RuntimeError("Failed to load memory lesson")
        return loaded

    def get_memory_lesson(self, lesson_id: int) -> StoredMemoryLesson | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    lesson_id,
                    source_task_id,
                    source_iteration_id,
                    lesson,
                    outcome_status,
                    failure_reason,
                    failed_checks_json,
                    follow_up_prompt,
                    helpful_count,
                    unhelpful_count,
                    stale_after_days,
                    created_at,
                    updated_at
                FROM memory_lessons
                WHERE lesson_id = ?
                """,
                (lesson_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_memory_lesson_from_row(row)

    def list_memory_lessons(
        self,
        *,
        include_stale: bool = False,
        limit: int | None = None,
    ) -> list[StoredMemoryLesson]:
        self.initialize()
        if limit is not None and limit < 0:
            raise ValueError("Memory lesson limit cannot be negative")
        query = """
            SELECT
                lesson_id,
                source_task_id,
                source_iteration_id,
                lesson,
                outcome_status,
                failure_reason,
                failed_checks_json,
                follow_up_prompt,
                helpful_count,
                unhelpful_count,
                stale_after_days,
                created_at,
                updated_at
            FROM memory_lessons
            ORDER BY lesson_id DESC
        """
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        lessons = [_stored_memory_lesson_from_row(row) for row in rows]
        if not include_stale:
            lessons = [lesson for lesson in lessons if not lesson.is_stale]
        if limit is not None:
            lessons = lessons[:limit]
        return lessons

    def search_memory_lessons(
        self,
        query: str,
        *,
        include_stale: bool = False,
        limit: int = 5,
    ) -> list[StoredMemoryLesson]:
        self.initialize()
        if limit < 0:
            raise ValueError("Memory lesson search limit cannot be negative")
        if limit == 0:
            return []
        lessons = self.list_memory_lessons(include_stale=include_stale)
        query_tokens = _memory_search_tokens(query)
        if not query_tokens:
            return lessons[:limit]
        scored = [
            (_memory_lesson_relevance_score(lesson, query_tokens), lesson)
            for lesson in lessons
        ]
        scored.sort(key=lambda item: (item[0], item[1].lesson_id), reverse=True)
        return [lesson for _, lesson in scored[:limit]]

    def record_memory_feedback(
        self,
        lesson_id: int,
        *,
        helpful_delta: int = 0,
        unhelpful_delta: int = 0,
    ) -> StoredMemoryLesson | None:
        self.initialize()
        if helpful_delta < 0 or unhelpful_delta < 0:
            raise ValueError("Memory feedback deltas cannot be negative")
        updated_at = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memory_lessons
                SET helpful_count = helpful_count + ?,
                    unhelpful_count = unhelpful_count + ?,
                    updated_at = ?
                WHERE lesson_id = ?
                """,
                (helpful_delta, unhelpful_delta, updated_at, lesson_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_memory_lesson(lesson_id)

    def add_reflection_record(
        self,
        task_id: str,
        reflection_type: str,
        failure_reason: str,
        iteration_id: int | None = None,
        failed_checks: list[dict[str, object]] | None = None,
        follow_up_prompt: str | None = None,
    ) -> StoredReflectionRecord:
        self.initialize()
        _validate_reflection_type(reflection_type)
        _validate_non_empty(failure_reason, "Reflection failure reason")
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reflection_records (
                    task_id,
                    iteration_id,
                    reflection_type,
                    failure_reason,
                    failed_checks_json,
                    follow_up_prompt,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    iteration_id,
                    reflection_type,
                    redact_secrets(failure_reason) or "",
                    _encode_json_array_payload(failed_checks),
                    redact_secrets(follow_up_prompt) if follow_up_prompt else None,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create reflection record")
            reflection_id = cursor.lastrowid
        loaded = self.get_reflection_record(reflection_id)
        if loaded is None:
            raise RuntimeError("Failed to load reflection record")
        return loaded

    def get_reflection_record(
        self,
        reflection_id: int,
    ) -> StoredReflectionRecord | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    reflection_id,
                    task_id,
                    iteration_id,
                    reflection_type,
                    failure_reason,
                    failed_checks_json,
                    follow_up_prompt,
                    created_at
                FROM reflection_records
                WHERE reflection_id = ?
                """,
                (reflection_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_reflection_record_from_row(row)

    def list_reflection_records(
        self,
        task_id: str | None = None,
    ) -> list[StoredReflectionRecord]:
        self.initialize()
        query = """
            SELECT
                reflection_id,
                task_id,
                iteration_id,
                reflection_type,
                failure_reason,
                failed_checks_json,
                follow_up_prompt,
                created_at
            FROM reflection_records
        """
        params: tuple[object, ...] = ()
        if task_id is not None:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY reflection_id DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_stored_reflection_record_from_row(row) for row in rows]

    def record_memory_influence(
        self,
        task_id: str,
        lesson_id: int,
        reason: str,
        iteration_id: int | None = None,
        injected: bool = True,
    ) -> StoredMemoryInfluence:
        self.initialize()
        _validate_non_empty(reason, "Memory influence reason")
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_influence_log (
                    task_id,
                    iteration_id,
                    lesson_id,
                    reason,
                    injected,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    iteration_id,
                    lesson_id,
                    redact_secrets(reason) or "",
                    1 if injected else 0,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create memory influence record")
            influence_id = cursor.lastrowid
        loaded = self.get_memory_influence(influence_id)
        if loaded is None:
            raise RuntimeError("Failed to load memory influence")
        return loaded

    def get_memory_influence(
        self,
        influence_id: int,
    ) -> StoredMemoryInfluence | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    influence_id,
                    task_id,
                    iteration_id,
                    lesson_id,
                    reason,
                    injected,
                    created_at
                FROM memory_influence_log
                WHERE influence_id = ?
                """,
                (influence_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_memory_influence_from_row(row)

    def list_memory_influence(
        self,
        task_id: str | None = None,
    ) -> list[StoredMemoryInfluence]:
        self.initialize()
        query = """
            SELECT
                influence_id,
                task_id,
                iteration_id,
                lesson_id,
                reason,
                injected,
                created_at
            FROM memory_influence_log
        """
        params: tuple[object, ...] = ()
        if task_id is not None:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY influence_id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_stored_memory_influence_from_row(row) for row in rows]

    def add_dead_letter_item(
        self,
        plan_item_id: int,
        reason: str,
        *,
        task_id: str | None = None,
        attempts: int = 1,
    ) -> StoredDeadLetterItem:
        self.initialize()
        _validate_non_empty(reason, "Dead-letter reason")
        if attempts < 1:
            raise ValueError("Dead-letter attempts must be at least 1")
        now = _now()
        with self._connect() as connection:
            plan_item = connection.execute(
                "SELECT plan_item_id FROM plan_items WHERE plan_item_id = ?",
                (plan_item_id,),
            ).fetchone()
            if plan_item is None:
                raise ValueError(f"Plan item not found: {plan_item_id}")
            cursor = connection.execute(
                """
                INSERT INTO dead_letter_items (
                    plan_item_id,
                    task_id,
                    reason,
                    attempts,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    plan_item_id,
                    task_id,
                    redact_secrets(reason) or "",
                    attempts,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create dead-letter item")
            dead_letter_id = cursor.lastrowid
        loaded = self.get_dead_letter_item(dead_letter_id)
        if loaded is None:
            raise RuntimeError("Failed to load dead-letter item")
        return loaded

    def get_dead_letter_item(
        self,
        dead_letter_id: int,
    ) -> StoredDeadLetterItem | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    dead_letter_id,
                    plan_item_id,
                    task_id,
                    reason,
                    attempts,
                    created_at
                FROM dead_letter_items
                WHERE dead_letter_id = ?
                """,
                (dead_letter_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_dead_letter_item_from_row(row)

    def list_dead_letter_items(
        self,
        plan_item_id: int | None = None,
    ) -> list[StoredDeadLetterItem]:
        self.initialize()
        query = """
            SELECT
                dead_letter_id,
                plan_item_id,
                task_id,
                reason,
                attempts,
                created_at
            FROM dead_letter_items
        """
        params: tuple[object, ...] = ()
        if plan_item_id is not None:
            query += " WHERE plan_item_id = ?"
            params = (plan_item_id,)
        query += " ORDER BY dead_letter_id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_stored_dead_letter_item_from_row(row) for row in rows]

    def record_autopilot_loop_run(
        self,
        *,
        plan_path: Path,
        mode: str,
        max_runtime_sec: int | None,
        max_attempts: int,
        max_actions: int,
        selected_count: int,
        processed_count: int,
        dead_letter_count: int,
        stop_reason: str,
        result_code: int,
        selected_item_ids: list[int] | None = None,
        elapsed_sec: float = 0.0,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> StoredAutopilotLoopRun:
        self.initialize()
        _validate_autopilot_loop_mode(mode)
        _validate_non_empty(stop_reason, "Autopilot loop stop reason")
        if max_attempts < 1:
            raise ValueError("Autopilot loop max attempts must be at least 1")
        if max_actions < 1:
            raise ValueError("Autopilot loop max actions must be at least 1")
        if selected_count < 0 or processed_count < 0 or dead_letter_count < 0:
            raise ValueError("Autopilot loop counts cannot be negative")
        if elapsed_sec < 0:
            raise ValueError("Autopilot loop elapsed seconds cannot be negative")
        now = _now()
        started = started_at or now
        completed = completed_at or now
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO autopilot_loop_runs (
                    plan_path,
                    mode,
                    max_runtime_sec,
                    max_attempts,
                    max_actions,
                    selected_count,
                    processed_count,
                    dead_letter_count,
                    stop_reason,
                    result_code,
                    selected_item_ids_json,
                    elapsed_sec,
                    started_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(plan_path),
                    mode,
                    max_runtime_sec,
                    max_attempts,
                    max_actions,
                    selected_count,
                    processed_count,
                    dead_letter_count,
                    redact_secrets(stop_reason) or "",
                    result_code,
                    _encode_json_int_list(selected_item_ids),
                    elapsed_sec,
                    started,
                    completed,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create autopilot loop run")
            loop_run_id = cursor.lastrowid
        loaded = self.get_autopilot_loop_run(loop_run_id)
        if loaded is None:
            raise RuntimeError("Failed to load autopilot loop run")
        return loaded

    def get_autopilot_loop_run(
        self,
        loop_run_id: int,
    ) -> StoredAutopilotLoopRun | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    loop_run_id,
                    plan_path,
                    mode,
                    max_runtime_sec,
                    max_attempts,
                    max_actions,
                    selected_count,
                    processed_count,
                    dead_letter_count,
                    stop_reason,
                    result_code,
                    selected_item_ids_json,
                    elapsed_sec,
                    started_at,
                    completed_at
                FROM autopilot_loop_runs
                WHERE loop_run_id = ?
                """,
                (loop_run_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_autopilot_loop_run_from_row(row)

    def list_autopilot_loop_runs(
        self,
        *,
        plan_path: Path | None = None,
        limit: int | None = None,
    ) -> list[StoredAutopilotLoopRun]:
        self.initialize()
        if limit is not None and limit < 0:
            raise ValueError("Autopilot loop run limit cannot be negative")
        query = """
            SELECT
                loop_run_id,
                plan_path,
                mode,
                max_runtime_sec,
                max_attempts,
                max_actions,
                selected_count,
                processed_count,
                dead_letter_count,
                stop_reason,
                result_code,
                selected_item_ids_json,
                elapsed_sec,
                started_at,
                completed_at
            FROM autopilot_loop_runs
        """
        params: list[object] = []
        if plan_path is not None:
            query += " WHERE plan_path = ?"
            params.append(str(plan_path))
        query += " ORDER BY loop_run_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_stored_autopilot_loop_run_from_row(row) for row in rows]

    def link_replan_decisions_to_plan_graph(
        self,
        task_id: str,
        plan_graph_id: int,
        plan_graph_node_id: int | None = None,
    ) -> list[StoredReplanDecision]:
        """Attach unlinked task replan decisions to a PlanGraph node lifecycle."""
        self.initialize()
        with self._connect() as connection:
            _validate_plan_item_graph_link(
                connection,
                plan_graph_id,
                plan_graph_node_id,
            )
            connection.execute(
                """
                UPDATE replan_decisions
                SET plan_graph_id = ?,
                    plan_graph_node_id = ?
                WHERE task_id = ? AND plan_graph_id IS NULL
                """,
                (plan_graph_id, plan_graph_node_id, task_id),
            )
        return self.list_replan_decisions(task_id)

    def create_replan_follow_up_nodes(
        self,
        task_id: str,
        plan_graph_id: int,
    ) -> list[StoredPlanGraphNode]:
        """Create idempotent pending PlanGraph nodes for linked replan decisions."""
        self.initialize()
        now = _now()
        node_ids: list[int] = []
        with self._connect() as connection:
            _validate_plan_item_graph_link(connection, plan_graph_id, None)
            rows = connection.execute(
                """
                SELECT
                    replan_id,
                    reason,
                    follow_up_prompt,
                    plan_graph_node_id
                FROM replan_decisions
                WHERE task_id = ?
                  AND plan_graph_id = ?
                  AND plan_graph_node_id IS NOT NULL
                ORDER BY replan_id ASC
                """,
                (task_id, plan_graph_id),
            ).fetchall()

            for row in rows:
                replan_id = int(row["replan_id"])
                parent_node_id = int(row["plan_graph_node_id"])
                _validate_plan_graph_dependency_ids(
                    connection,
                    plan_graph_id,
                    [parent_node_id],
                )
                node_key = f"replan-{replan_id}"
                existing = connection.execute(
                    """
                    SELECT node_id
                    FROM plan_graph_nodes
                    WHERE graph_id = ? AND node_key = ?
                    """,
                    (plan_graph_id, node_key),
                ).fetchone()
                if existing is not None:
                    node_id = int(existing["node_id"])
                else:
                    title_source = row["follow_up_prompt"] or row["reason"] or ""
                    cursor = connection.execute(
                        """
                        INSERT INTO plan_graph_nodes (
                            graph_id,
                            node_key,
                            title,
                            task_text,
                            acceptance_criteria_json,
                            verification_requirement,
                            status,
                            blocked_reason,
                            task_id,
                            plan_item_id,
                            source_node_id,
                            node_type,
                            attempts,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, '[]', NULL, 'pending', NULL, ?, NULL, ?, 'repair', 0, ?, ?)
                        """,
                        (
                            plan_graph_id,
                            node_key,
                            _replan_follow_up_node_title(replan_id, str(title_source)),
                            redact_secrets(str(title_source)) or "",
                            task_id,
                            parent_node_id,
                            now,
                            now,
                        ),
                    )
                    if cursor.lastrowid is None:
                        raise RuntimeError("Failed to create replan follow-up node")
                    node_id = cursor.lastrowid
                connection.execute(
                    """
                    INSERT OR IGNORE INTO plan_graph_dependencies (
                        graph_id,
                        node_id,
                        depends_on_node_id,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (plan_graph_id, node_id, parent_node_id, now),
                )
                node_ids.append(node_id)

            if node_ids:
                connection.execute(
                    "UPDATE plan_graphs SET updated_at = ? WHERE graph_id = ?",
                    (now, plan_graph_id),
                )

        nodes = [self.get_plan_graph_node(node_id) for node_id in node_ids]
        return [node for node in nodes if node is not None]

    def list_task_timeline(self, task_id: str) -> list[StoredTimelineEntry]:
        self.initialize()
        entries: list[StoredTimelineEntry] = []
        with self._connect() as connection:
            task = connection.execute(
                """
                SELECT task_id, task, repo_path, status, created_at, updated_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if task is None:
                return []

            _append_timeline_entry(
                entries,
                occurred_at=str(task["created_at"]),
                source="task",
                source_id=str(task["task_id"]),
                event_type="task.created",
                status=str(task["status"]),
                summary="Task created",
                payload={
                    "task": str(task["task"]),
                    "repo_path": str(task["repo_path"]),
                },
            )
            if task["updated_at"] != task["created_at"]:
                _append_timeline_entry(
                    entries,
                    occurred_at=str(task["updated_at"]),
                    source="task",
                    source_id=str(task["task_id"]),
                    event_type="task.current_status",
                    status=str(task["status"]),
                    summary=f"Task current status: {task['status']}",
                    payload={},
                )

            for row in connection.execute(
                """
                SELECT
                    event_id,
                    sequence,
                    run_id,
                    session_id,
                    iteration_id,
                    correlation_id,
                    idempotency_key,
                    event_type,
                    actor,
                    summary,
                    payload_json,
                    payload_preview,
                    created_at
                FROM task_events
                WHERE task_id = ?
                ORDER BY sequence ASC, event_id ASC
                """,
                (task_id,),
            ).fetchall():
                payload = {
                    "sequence": int(row["sequence"]),
                    "payload": _decode_json_payload(row["payload_json"]),
                }
                for key in (
                    "run_id",
                    "session_id",
                    "iteration_id",
                    "correlation_id",
                    "idempotency_key",
                ):
                    if row[key] not in (None, ""):
                        payload[key] = row[key]
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="task_event",
                    source_id=str(row["event_id"]),
                    event_type=str(row["event_type"]),
                    status=None,
                    summary=str(row["summary"] or row["event_type"]),
                    payload=payload,
                )

            for row in connection.execute(
                """
                SELECT
                    iteration_id,
                    iteration_index,
                    agent_name,
                    agent_status,
                    decision_status,
                    decision_reason,
                    created_at
                FROM iterations
                WHERE task_id = ?
                ORDER BY iteration_index ASC, iteration_id ASC
                """,
                (task_id,),
            ).fetchall():
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="iteration",
                    source_id=str(row["iteration_id"]),
                    event_type="iteration.recorded",
                    status=str(row["decision_status"]),
                    summary=(
                        f"Iteration {row['iteration_index']}: "
                        f"{row['decision_status']}"
                    ),
                    payload={
                        "iteration_index": int(row["iteration_index"]),
                        "agent_name": str(row["agent_name"]),
                        "agent_status": str(row["agent_status"]),
                        "decision_reason": redact_secrets(row["decision_reason"]) or "",
                    },
                )

            for row in connection.execute(
                """
                SELECT verification_id, iteration_id, name, status, exit_code, created_at
                FROM verification_runs
                WHERE task_id = ?
                ORDER BY verification_id ASC
                """,
                (task_id,),
            ).fetchall():
                exit_code = row["exit_code"]
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="verification",
                    source_id=str(row["verification_id"]),
                    event_type="verification.recorded",
                    status=str(row["status"]),
                    summary=f"Verification {row['name']}: {row['status']}",
                    payload={
                        "iteration_id": int(row["iteration_id"]),
                        "name": str(row["name"]),
                        "exit_code": None if exit_code is None else int(exit_code),
                    },
                )

            for row in connection.execute(
                """
                SELECT
                    replan_id,
                    iteration_id,
                    source,
                    status,
                    reason,
                    follow_up_prompt,
                    failed_checks_json,
                    plan_graph_id,
                    plan_graph_node_id,
                    created_at
                FROM replan_decisions
                WHERE task_id = ?
                ORDER BY replan_id ASC
                """,
                (task_id,),
            ).fetchall():
                failed_checks = _decode_json_array_payload(row["failed_checks_json"])
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="replan",
                    source_id=str(row["replan_id"]),
                    event_type="replan.decision",
                    status=str(row["status"]),
                    summary=f"Replan decision: {row['status']}",
                    payload={
                        "iteration_id": int(row["iteration_id"]),
                        "source": str(row["source"]),
                        "reason": redact_secrets(row["reason"]) or "",
                        "failed_checks": failed_checks,
                        "follow_up_prompt": (
                            redact_secrets(row["follow_up_prompt"])
                            if row["follow_up_prompt"]
                            else None
                        ),
                        "plan_graph_id": row["plan_graph_id"],
                        "plan_graph_node_id": row["plan_graph_node_id"],
                    },
                )

            for row in connection.execute(
                """
                SELECT
                    reflection_id,
                    iteration_id,
                    reflection_type,
                    failure_reason,
                    failed_checks_json,
                    follow_up_prompt,
                    created_at
                FROM reflection_records
                WHERE task_id = ?
                ORDER BY reflection_id ASC
                """,
                (task_id,),
            ).fetchall():
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="reflection",
                    source_id=str(row["reflection_id"]),
                    event_type=f"reflection.{row['reflection_type']}",
                    status=None,
                    summary=f"Reflection recorded: {row['reflection_type']}",
                    payload={
                        "iteration_id": row["iteration_id"],
                        "failure_reason": redact_secrets(row["failure_reason"]) or "",
                        "failed_checks": _decode_json_array_payload(
                            row["failed_checks_json"]
                        ),
                        "follow_up_prompt": (
                            redact_secrets(row["follow_up_prompt"])
                            if row["follow_up_prompt"]
                            else None
                        ),
                    },
                )

            for row in connection.execute(
                """
                SELECT
                    influence_id,
                    iteration_id,
                    lesson_id,
                    reason,
                    injected,
                    created_at
                FROM memory_influence_log
                WHERE task_id = ?
                ORDER BY influence_id ASC
                """,
                (task_id,),
            ).fetchall():
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="memory",
                    source_id=str(row["influence_id"]),
                    event_type="memory.influence",
                    status="injected" if int(row["injected"]) else "skipped",
                    summary=f"Memory influence: lesson {row['lesson_id']}",
                    payload={
                        "iteration_id": row["iteration_id"],
                        "lesson_id": int(row["lesson_id"]),
                        "reason": redact_secrets(row["reason"]) or "",
                        "injected": bool(row["injected"]),
                    },
                )

            for row in connection.execute(
                """
                SELECT
                    approval_id,
                    iteration_id,
                    source,
                    command_string,
                    reason,
                    status,
                    created_at,
                    resolved_at,
                    resolution
                FROM approval_requests
                WHERE task_id = ?
                ORDER BY created_at ASC, approval_id ASC
                """,
                (task_id,),
            ).fetchall():
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="approval",
                    source_id=str(row["approval_id"]),
                    event_type="approval.requested",
                    status=str(row["status"]),
                    summary=f"Approval requested: {row['source']}",
                    payload={
                        "iteration_id": row["iteration_id"],
                        "source": str(row["source"]),
                        "command_string": redact_secrets(row["command_string"]) or "",
                        "reason": redact_secrets(row["reason"]) or "",
                    },
                )
                if row["resolved_at"] is not None:
                    _append_timeline_entry(
                        entries,
                        occurred_at=str(row["resolved_at"]),
                        source="approval",
                        source_id=str(row["approval_id"]),
                        event_type="approval.resolved",
                        status=str(row["status"]),
                        summary=f"Approval resolved: {row['status']}",
                        payload={
                            "resolution": redact_secrets(row["resolution"]) or "",
                        },
                    )

            for row in connection.execute(
                """
                SELECT
                    action_id,
                    iteration_id,
                    idempotency_key,
                    action_type,
                    status,
                    command_string,
                    policy_action,
                    policy_reason,
                    payload_json,
                    result_json,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    created_at,
                    updated_at
                FROM action_records
                WHERE task_id = ?
                ORDER BY action_id ASC
                """,
                (task_id,),
            ).fetchall():
                action_payload = _action_timeline_payload(row)
                _append_timeline_entry(
                    entries,
                    occurred_at=str(row["created_at"]),
                    source="action",
                    source_id=str(row["action_id"]),
                    event_type="action.recorded",
                    status=str(row["status"]),
                    summary=f"Action {row['action_type']}: {row['status']}",
                    payload=action_payload,
                )
                if row["updated_at"] != row["created_at"]:
                    _append_timeline_entry(
                        entries,
                        occurred_at=str(row["updated_at"]),
                        source="action",
                        source_id=str(row["action_id"]),
                        event_type="action.updated",
                        status=str(row["status"]),
                        summary=f"Action updated: {row['status']}",
                        payload=action_payload,
                    )

        entries.sort(
            key=lambda entry: (
                entry.occurred_at,
                entry.source,
                entry.source_id,
                entry.event_type,
            )
        )
        return [
            StoredTimelineEntry(
                timeline_index=index,
                occurred_at=entry.occurred_at,
                source=entry.source,
                source_id=entry.source_id,
                event_type=entry.event_type,
                status=entry.status,
                summary=entry.summary,
                payload={**entry.payload, "run_id": _run_id_for_task(task_id)},
            )
            for index, entry in enumerate(entries, start=1)
        ]

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

    def record_plan_item(
        self,
        plan_path: Path,
        line_number: int,
        section: str,
        text: str,
        status: str = "created",
        task_id: str | None = None,
        selected_worktree_path: Path | str | None = None,
        blocked_reason: str | None = None,
        plan_graph_id: int | None = None,
        plan_graph_root_node_id: int | None = None,
    ) -> StoredPlanItem:
        self.initialize()
        _validate_plan_item_status(status)
        now = _now()
        selected_worktree = (
            str(selected_worktree_path) if selected_worktree_path is not None else None
        )
        with self._connect() as connection:
            if plan_graph_id is not None:
                _validate_plan_item_graph_link(
                    connection,
                    plan_graph_id,
                    plan_graph_root_node_id,
                )
            elif plan_graph_root_node_id is not None:
                raise ValueError("Plan graph root node requires plan graph id")
            cursor = connection.execute(
                """
                INSERT INTO plan_items (
                    plan_path,
                    line_number,
                    section,
                    text,
                    status,
                    task_id,
                    selected_worktree_path,
                    blocked_reason,
                    plan_graph_id,
                    plan_graph_root_node_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(plan_path),
                    line_number,
                    section,
                    text,
                    status,
                    task_id,
                    selected_worktree,
                    redact_secrets(blocked_reason),
                    plan_graph_id,
                    plan_graph_root_node_id,
                    now,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create plan item")
            plan_item_id = cursor.lastrowid
        logger.debug(
            "state plan item recorded plan_item_id=%s plan_path=%s line=%s status=%s",
            plan_item_id,
            plan_path,
            line_number,
            status,
        )
        plan_item = self.get_plan_item(plan_item_id)
        if plan_item is None:
            raise RuntimeError("Failed to load recorded plan item")
        return plan_item

    def get_plan_item(self, plan_item_id: int) -> StoredPlanItem | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    plan_item_id,
                    plan_path,
                    line_number,
                    section,
                    text,
                    status,
                    task_id,
                    selected_worktree_path,
                    blocked_reason,
                    plan_graph_id,
                    plan_graph_root_node_id,
                    created_at,
                    updated_at
                FROM plan_items
                WHERE plan_item_id = ?
                """,
                (plan_item_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredPlanItem(**dict(row))

    def list_plan_items(
        self,
        plan_path: Path | None = None,
        status: str | None = None,
    ) -> list[StoredPlanItem]:
        self.initialize()
        if status is not None:
            _validate_plan_item_status(status)

        query = """
            SELECT
                plan_item_id,
                plan_path,
                line_number,
                section,
                text,
                status,
                task_id,
                selected_worktree_path,
                blocked_reason,
                plan_graph_id,
                plan_graph_root_node_id,
                created_at,
                updated_at
            FROM plan_items
            WHERE 1 = 1
        """
        params: list[str] = []
        if plan_path is not None:
            query += " AND plan_path = ?"
            params.append(str(plan_path))
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY plan_path ASC, line_number ASC, plan_item_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [StoredPlanItem(**dict(row)) for row in rows]

    def update_plan_item_status(
        self,
        plan_item_id: int,
        status: str,
        task_id: str | None = None,
        selected_worktree_path: Path | str | None = None,
        blocked_reason: str | None = None,
    ) -> StoredPlanItem | None:
        self.initialize()
        _validate_plan_item_status(status)

        set_clause = "status = ?, updated_at = ?"
        params: list[object] = [status, _now()]
        if task_id is not None:
            set_clause += ", task_id = ?"
            params.append(task_id)
        if selected_worktree_path is not None:
            set_clause += ", selected_worktree_path = ?"
            params.append(str(selected_worktree_path))
        if blocked_reason is not None:
            set_clause += ", blocked_reason = ?"
            params.append(redact_secrets(blocked_reason))
        params.append(plan_item_id)

        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE plan_items
                SET {set_clause}
                WHERE plan_item_id = ?
                """,
                tuple(params),
            )
            if cursor.rowcount == 0:
                return None

        logger.debug(
            "state plan item status updated plan_item_id=%s status=%s",
            plan_item_id,
            status,
        )
        return self.get_plan_item(plan_item_id)

    def link_plan_item_to_plan_graph(
        self,
        plan_item_id: int,
        plan_graph_id: int,
        plan_graph_root_node_id: int | None = None,
    ) -> StoredPlanItem | None:
        """Link a queue item to a durable plan graph root.

        Returns ``None`` when the queue item does not exist. Raises
        ``ValueError`` when the graph or root node reference is invalid.
        """
        self.initialize()
        now = _now()
        with self._connect() as connection:
            _validate_plan_item_graph_link(
                connection,
                plan_graph_id,
                plan_graph_root_node_id,
            )
            cursor = connection.execute(
                """
                UPDATE plan_items
                SET plan_graph_id = ?,
                    plan_graph_root_node_id = ?,
                    updated_at = ?
                WHERE plan_item_id = ?
                """,
                (plan_graph_id, plan_graph_root_node_id, now, plan_item_id),
            )
            if cursor.rowcount == 0:
                return None

        logger.debug(
            "state plan item linked to plan graph plan_item_id=%s graph_id=%s root_node_id=%s",
            plan_item_id,
            plan_graph_id,
            plan_graph_root_node_id,
        )
        return self.get_plan_item(plan_item_id)

    def update_created_plan_item_source_ref(
        self,
        plan_item_id: int,
        line_number: int,
        section: str,
    ) -> StoredPlanItem | None:
        """Refresh the source reference for a ``created`` queue item.

        The item id, status, task text, task metadata, and worktree metadata are
        preserved. Returns ``None`` when the item does not exist or is no longer
        in ``created`` status.
        """
        self.initialize()
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE plan_items
                SET line_number = ?,
                    section = ?,
                    updated_at = ?
                WHERE plan_item_id = ? AND status = 'created'
                """,
                (line_number, section, now, plan_item_id),
            )
            if cursor.rowcount == 0:
                return None

        logger.debug(
            "state plan item source ref updated plan_item_id=%s line_number=%s",
            plan_item_id,
            line_number,
        )
        return self.get_plan_item(plan_item_id)

    def requeue_plan_item(self, plan_item_id: int) -> StoredPlanItem | None:
        """Move a blocked queue item back to ``created`` and clear stale metadata.

        Only items whose current status is ``blocked`` are affected. The
        associated task, selected worktree, and blocker reason are all reset so
        the item can be reviewed and later processed as a fresh queue entry.
        Returns the updated item, or ``None`` when no blocked item with the
        given id exists.
        """
        self.initialize()
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE plan_items
                SET status = 'created',
                    task_id = NULL,
                    selected_worktree_path = NULL,
                    blocked_reason = NULL,
                    updated_at = ?
                WHERE plan_item_id = ? AND status = 'blocked'
                """,
                (now, plan_item_id),
            )
            if cursor.rowcount == 0:
                return None

        logger.debug(
            "state plan item requeued plan_item_id=%s status=created",
            plan_item_id,
        )
        return self.get_plan_item(plan_item_id)

    def skip_plan_item(
        self,
        plan_item_id: int,
        reason: str,
    ) -> StoredPlanItem | None:
        """Mark a ``created`` or ``blocked`` queue item as ``skipped``.

        The persisted item is updated in place: its status becomes ``skipped``,
        the supplied reason is recorded, and the update timestamp is refreshed.
        Existing task and worktree metadata are preserved for audit. Returns
        ``None`` when the item does not exist or is not in a skippable status.
        """
        self.initialize()
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE plan_items
                SET status = 'skipped',
                    blocked_reason = ?,
                    updated_at = ?
                WHERE plan_item_id = ?
                  AND status IN ('created', 'blocked')
                """,
                (redact_secrets(reason), now, plan_item_id),
            )
            if cursor.rowcount == 0:
                return None

        logger.debug(
            "state plan item skipped plan_item_id=%s reason=%s",
            plan_item_id,
            reason,
        )
        return self.get_plan_item(plan_item_id)

    def create_plan_graph(
        self,
        title: str,
        task_id: str | None = None,
        status: str = "active",
    ) -> StoredPlanGraph:
        self.initialize()
        _validate_non_empty(title, "Plan graph title")
        _validate_plan_graph_status(status)
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO plan_graphs (task_id, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    redact_secrets(title) or "",
                    status,
                    now,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create plan graph")
            graph_id = cursor.lastrowid
        graph = self.get_plan_graph(graph_id)
        if graph is None:
            raise RuntimeError("Failed to load created plan graph")
        return graph

    def get_plan_graph(self, graph_id: int) -> StoredPlanGraph | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT graph_id, task_id, title, status, created_at, updated_at
                FROM plan_graphs
                WHERE graph_id = ?
                """,
                (graph_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredPlanGraph(**dict(row))

    def list_plan_graphs(
        self,
        task_id: str | None = None,
        status: str | None = None,
    ) -> list[StoredPlanGraph]:
        self.initialize()
        if status is not None:
            _validate_plan_graph_status(status)

        query = """
            SELECT graph_id, task_id, title, status, created_at, updated_at
            FROM plan_graphs
            WHERE 1 = 1
        """
        params: list[str] = []
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, graph_id DESC"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [StoredPlanGraph(**dict(row)) for row in rows]

    def update_plan_graph_status(
        self,
        graph_id: int,
        status: str,
    ) -> StoredPlanGraph | None:
        self.initialize()
        _validate_plan_graph_status(status)
        updated_at = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE plan_graphs
                SET status = ?, updated_at = ?
                WHERE graph_id = ?
                """,
                (status, updated_at, graph_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_plan_graph(graph_id)

    def add_plan_graph_node(
        self,
        graph_id: int,
        node_key: str,
        title: str,
        status: str = "pending",
        attempts: int = 0,
        depends_on_node_ids: list[int] | None = None,
        *,
        task_text: str | None = None,
        acceptance_criteria: list[str] | None = None,
        verification_requirement: str | None = None,
        blocked_reason: str | None = None,
        task_id: str | None = None,
        plan_item_id: int | None = None,
        source_node_id: int | None = None,
        node_type: str = "task",
    ) -> StoredPlanGraphNode:
        self.initialize()
        _validate_plan_graph_node_key(node_key)
        _validate_non_empty(title, "Plan graph node title")
        _validate_non_empty(node_type, "Plan graph node type")
        _validate_plan_graph_node_status(status)
        _validate_plan_graph_attempts(attempts)
        dependency_ids = depends_on_node_ids or []
        now = _now()
        with self._connect() as connection:
            if not _plan_graph_exists(connection, graph_id):
                raise ValueError(f"Plan graph not found: {graph_id}")
            _validate_plan_graph_dependency_ids(connection, graph_id, dependency_ids)
            if source_node_id is not None:
                _validate_plan_graph_dependency_ids(connection, graph_id, [source_node_id])
            cursor = connection.execute(
                """
                INSERT INTO plan_graph_nodes (
                    graph_id,
                    node_key,
                    title,
                    task_text,
                    acceptance_criteria_json,
                    verification_requirement,
                    status,
                    blocked_reason,
                    task_id,
                    plan_item_id,
                    source_node_id,
                    node_type,
                    attempts,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    graph_id,
                    node_key.strip(),
                    redact_secrets(title) or "",
                    redact_secrets(task_text if task_text is not None else title)
                    or "",
                    _encode_json_list(acceptance_criteria),
                    redact_secrets(verification_requirement),
                    status,
                    redact_secrets(blocked_reason),
                    task_id,
                    plan_item_id,
                    source_node_id,
                    redact_secrets(node_type) or "",
                    attempts,
                    now,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create plan graph node")
            node_id = cursor.lastrowid
            for depends_on_node_id in dependency_ids:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO plan_graph_dependencies (
                        graph_id,
                        node_id,
                        depends_on_node_id,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (graph_id, node_id, depends_on_node_id, now),
                )
            connection.execute(
                "UPDATE plan_graphs SET updated_at = ? WHERE graph_id = ?",
                (now, graph_id),
            )

        node = self.get_plan_graph_node(node_id)
        if node is None:
            raise RuntimeError("Failed to load created plan graph node")
        return node

    def get_plan_graph_node(self, node_id: int) -> StoredPlanGraphNode | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    node_id,
                    graph_id,
                    node_key,
                    title,
                    task_text,
                    acceptance_criteria_json,
                    verification_requirement,
                    status,
                    blocked_reason,
                    task_id,
                    plan_item_id,
                    source_node_id,
                    node_type,
                    attempts,
                    created_at,
                    updated_at
                FROM plan_graph_nodes
                WHERE node_id = ?
                """,
                (node_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored_plan_graph_node_from_row(row)

    def list_plan_graph_nodes(
        self,
        graph_id: int,
        status: str | None = None,
    ) -> list[StoredPlanGraphNode]:
        self.initialize()
        if status is not None:
            _validate_plan_graph_node_status(status)
        query = """
            SELECT
                node_id,
                graph_id,
                node_key,
                title,
                task_text,
                acceptance_criteria_json,
                verification_requirement,
                status,
                blocked_reason,
                task_id,
                plan_item_id,
                source_node_id,
                node_type,
                attempts,
                created_at,
                updated_at
            FROM plan_graph_nodes
            WHERE graph_id = ?
        """
        params: list[object] = [graph_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY node_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_stored_plan_graph_node_from_row(row) for row in rows]

    def list_ready_plan_graph_nodes(
        self,
        graph_id: int,
        limit: int | None = None,
    ) -> list[StoredPlanGraphNode]:
        """Return pending PlanGraph nodes whose dependencies are all done."""
        if limit is not None and limit < 0:
            raise ValueError("Ready PlanGraph node limit cannot be negative")

        ready_nodes = [
            readiness.node
            for readiness in self.list_plan_graph_node_readiness(graph_id)
            if readiness.ready
        ]
        if limit is not None:
            return ready_nodes[:limit]
        return ready_nodes

    def list_plan_graph_node_readiness(
        self,
        graph_id: int,
    ) -> list[StoredPlanGraphNodeReadiness]:
        """Return readiness decisions for every node in deterministic node order."""
        nodes = self.list_plan_graph_nodes(graph_id)
        dependencies = self.list_plan_graph_dependencies(graph_id)
        nodes_by_id = {node.node_id: node for node in nodes}
        dependencies_by_node: dict[int, list[int]] = {}
        for dependency in dependencies:
            dependencies_by_node.setdefault(dependency.node_id, []).append(
                dependency.depends_on_node_id
            )

        readiness: list[StoredPlanGraphNodeReadiness] = []
        for node in nodes:
            blocking_dependencies = [
                dependency_node
                for dependency_node_id in dependencies_by_node.get(node.node_id, [])
                if (
                    dependency_node := nodes_by_id.get(dependency_node_id)
                ) is not None
                and dependency_node.status != "done"
            ]
            if node.status != "pending":
                ready = False
                reason = f"node_status_{node.status}"
            elif blocking_dependencies:
                ready = False
                reason = "blocked_dependencies"
            else:
                ready = True
                reason = "ready"
            readiness.append(
                StoredPlanGraphNodeReadiness(
                    node=node,
                    ready=ready,
                    reason=reason,
                    blocking_dependencies=blocking_dependencies,
                )
            )
        return readiness

    def list_stale_plan_graph_nodes(
        self,
        graph_id: int,
        older_than_hours: int | None = None,
        now: datetime | None = None,
    ) -> list[StoredPlanGraphNode]:
        """Return in-progress PlanGraph nodes that are candidates for recovery."""
        self.initialize()
        if older_than_hours is not None and older_than_hours < 0:
            raise ValueError("Plan graph stale node age cannot be negative")

        query = """
            SELECT
                node_id,
                graph_id,
                node_key,
                title,
                task_text,
                acceptance_criteria_json,
                verification_requirement,
                status,
                blocked_reason,
                task_id,
                plan_item_id,
                source_node_id,
                node_type,
                attempts,
                created_at,
                updated_at
            FROM plan_graph_nodes
            WHERE graph_id = ?
              AND status = 'in_progress'
        """
        params: list[object] = [graph_id]
        if older_than_hours is not None:
            reference = now or datetime.now(UTC)
            cutoff = reference - timedelta(hours=older_than_hours)
            query += " AND updated_at <= ?"
            params.append(cutoff.isoformat())
        query += " ORDER BY node_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_stored_plan_graph_node_from_row(row) for row in rows]

    def update_plan_graph_node_status(
        self,
        node_id: int,
        status: str,
        attempts: int | None = None,
        increment_attempts: bool = False,
        blocked_reason: str | None = None,
        task_id: str | None = None,
        plan_item_id: int | None = None,
    ) -> StoredPlanGraphNode | None:
        self.initialize()
        _validate_plan_graph_node_status(status)
        if attempts is not None and increment_attempts:
            raise ValueError("Use either attempts or increment_attempts, not both")
        if attempts is not None:
            _validate_plan_graph_attempts(attempts)

        updated_at = _now()
        set_clause = "status = ?, updated_at = ?"
        params: list[object] = [status, updated_at]
        if attempts is not None:
            set_clause += ", attempts = ?"
            params.append(attempts)
        elif increment_attempts:
            set_clause += ", attempts = attempts + 1"
        if blocked_reason is not None:
            set_clause += ", blocked_reason = ?"
            params.append(redact_secrets(blocked_reason))
        if task_id is not None:
            set_clause += ", task_id = ?"
            params.append(task_id)
        if plan_item_id is not None:
            set_clause += ", plan_item_id = ?"
            params.append(plan_item_id)
        params.append(node_id)

        with self._connect() as connection:
            row = connection.execute(
                "SELECT graph_id FROM plan_graph_nodes WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                return None
            cursor = connection.execute(
                f"""
                UPDATE plan_graph_nodes
                SET {set_clause}
                WHERE node_id = ?
                """,
                tuple(params),
            )
            if cursor.rowcount == 0:
                return None
            connection.execute(
                "UPDATE plan_graphs SET updated_at = ? WHERE graph_id = ?",
                (updated_at, int(row["graph_id"])),
            )
        return self.get_plan_graph_node(node_id)

    def add_plan_graph_dependency(
        self,
        graph_id: int,
        node_id: int,
        depends_on_node_id: int,
    ) -> StoredPlanGraphDependency | None:
        self.initialize()
        if node_id == depends_on_node_id:
            raise ValueError("Plan graph node cannot depend on itself")
        now = _now()
        with self._connect() as connection:
            _validate_plan_graph_dependency_ids(connection, graph_id, [node_id])
            _validate_plan_graph_dependency_ids(
                connection,
                graph_id,
                [depends_on_node_id],
            )
            if _plan_graph_dependency_creates_cycle(
                connection,
                graph_id,
                node_id,
                depends_on_node_id,
            ):
                raise ValueError("Plan graph dependency would create a cycle")
            connection.execute(
                """
                INSERT OR IGNORE INTO plan_graph_dependencies (
                    graph_id,
                    node_id,
                    depends_on_node_id,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (graph_id, node_id, depends_on_node_id, now),
            )
            connection.execute(
                "UPDATE plan_graphs SET updated_at = ? WHERE graph_id = ?",
                (now, graph_id),
            )
        dependencies = self.list_plan_graph_dependencies(graph_id, node_id=node_id)
        return next(
            (
                dependency
                for dependency in dependencies
                if dependency.depends_on_node_id == depends_on_node_id
            ),
            None,
        )

    def list_plan_graph_dependencies(
        self,
        graph_id: int,
        node_id: int | None = None,
    ) -> list[StoredPlanGraphDependency]:
        self.initialize()
        query = """
            SELECT graph_id, node_id, depends_on_node_id, created_at
            FROM plan_graph_dependencies
            WHERE graph_id = ?
        """
        params: list[object] = [graph_id]
        if node_id is not None:
            query += " AND node_id = ?"
            params.append(node_id)
        query += " ORDER BY node_id ASC, depends_on_node_id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [StoredPlanGraphDependency(**dict(row)) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


def _validate_plan_item_status(status: str) -> None:
    if status not in {"created", "in_progress", "done", "blocked", "skipped"}:
        raise ValueError(f"Unsupported plan item status: {status}")


def _ensure_current_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_plan_items_plan_graph
        ON plan_items (plan_graph_id, plan_graph_root_node_id, plan_item_id);

        CREATE INDEX IF NOT EXISTS idx_replan_decisions_plan_graph
        ON replan_decisions (plan_graph_id, plan_graph_node_id, replan_id);

        CREATE INDEX IF NOT EXISTS idx_plan_graph_nodes_links
        ON plan_graph_nodes (task_id, plan_item_id, source_node_id);
        """
    )


def _validate_autopilot_loop_mode(mode: str) -> None:
    if mode not in {"dry-run", "execute"}:
        raise ValueError("Autopilot loop mode must be 'dry-run' or 'execute'")


def _run_id_for_task(task_id: str) -> str:
    normalized = task_id.strip() or "unknown"
    if normalized.startswith("task-"):
        normalized = normalized.removeprefix("task-")
    return f"run-{normalized}"


def _validate_plan_graph_status(status: str) -> None:
    if status not in {"active", "done", "blocked", "archived"}:
        raise ValueError(f"Unsupported plan graph status: {status}")


def _validate_plan_graph_node_status(status: str) -> None:
    if status not in {
        "pending",
        "in_progress",
        "done",
        "blocked",
        "failed",
        "skipped",
    }:
        raise ValueError(f"Unsupported plan graph node status: {status}")


def _validate_plan_graph_node_key(node_key: str) -> None:
    _validate_non_empty(node_key, "Plan graph node key")


def _validate_plan_graph_attempts(attempts: int) -> None:
    if attempts < 0:
        raise ValueError("Plan graph node attempts cannot be negative")


def _validate_replan_decision_status(status: str) -> None:
    if status not in {"continue", "blocked"}:
        raise ValueError(f"Unsupported replan decision status: {status}")


def _validate_non_empty(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} cannot be empty")


def _plan_graph_exists(connection: sqlite3.Connection, graph_id: int) -> bool:
    row = connection.execute(
        "SELECT graph_id FROM plan_graphs WHERE graph_id = ?",
        (graph_id,),
    ).fetchone()
    return row is not None


def _validate_plan_item_graph_link(
    connection: sqlite3.Connection,
    graph_id: int,
    root_node_id: int | None,
) -> None:
    if not _plan_graph_exists(connection, graph_id):
        raise ValueError(f"Plan graph not found: {graph_id}")
    if root_node_id is not None:
        _validate_plan_graph_dependency_ids(connection, graph_id, [root_node_id])


def _validate_plan_graph_dependency_ids(
    connection: sqlite3.Connection,
    graph_id: int,
    node_ids: list[int],
) -> None:
    if not node_ids:
        return
    unique_node_ids = sorted(set(node_ids))
    placeholders = ", ".join("?" for _ in unique_node_ids)
    rows = connection.execute(
        f"""
        SELECT node_id
        FROM plan_graph_nodes
        WHERE graph_id = ?
          AND node_id IN ({placeholders})
        """,
        (graph_id, *unique_node_ids),
    ).fetchall()
    found = {int(row["node_id"]) for row in rows}
    missing = [node_id for node_id in unique_node_ids if node_id not in found]
    if missing:
        raise ValueError(
            "Plan graph dependency nodes not found in graph "
            f"{graph_id}: {', '.join(str(node_id) for node_id in missing)}"
        )


def _plan_graph_dependency_creates_cycle(
    connection: sqlite3.Connection,
    graph_id: int,
    node_id: int,
    depends_on_node_id: int,
) -> bool:
    row = connection.execute(
        """
        WITH RECURSIVE upstream(node_id) AS (
            SELECT depends_on_node_id
            FROM plan_graph_dependencies
            WHERE graph_id = ?
              AND node_id = ?
            UNION
            SELECT dependency.depends_on_node_id
            FROM plan_graph_dependencies AS dependency
            JOIN upstream ON upstream.node_id = dependency.node_id
            WHERE dependency.graph_id = ?
        )
        SELECT 1
        FROM upstream
        WHERE node_id = ?
        LIMIT 1
        """,
        (graph_id, depends_on_node_id, graph_id, node_id),
    ).fetchone()
    return row is not None


def _replan_follow_up_node_title(replan_id: int, source: str) -> str:
    summary = " ".join(source.split())
    if not summary:
        summary = f"Replan decision {replan_id}"
    title = f"Follow-up for replan {replan_id}: {summary}"
    if len(title) > 180:
        title = f"{title[:177]}..."
    return redact_secrets(title) or f"Follow-up for replan {replan_id}"


def _validate_action_status(status: str) -> None:
    if status not in {
        "started",
        "succeeded",
        "failed",
        "skipped",
        "policy_denied",
        "needs_approval",
    }:
        raise ValueError(f"Unsupported action status: {status}")


def _validate_reflection_type(reflection_type: str) -> None:
    if reflection_type not in {"blocked_run", "failed_verification"}:
        raise ValueError(f"Unsupported reflection type: {reflection_type}")


def _validate_lease_owner(lease_owner: str) -> None:
    if not lease_owner.strip():
        raise ValueError("Action lease owner cannot be empty")


def _validate_lease_ttl(ttl_sec: int) -> None:
    if ttl_sec <= 0:
        raise ValueError("Action lease TTL must be positive")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _expires_at(timestamp: str, ttl_sec: int) -> str:
    return (datetime.fromisoformat(timestamp) + timedelta(seconds=ttl_sec)).isoformat()


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


def _stored_plan_graph_node_from_row(row: sqlite3.Row) -> StoredPlanGraphNode:
    data = dict(row)
    data["acceptance_criteria"] = _decode_json_list(
        data.pop("acceptance_criteria_json", None)
    )
    return StoredPlanGraphNode(**data)


def _encode_json_int_list(values: list[int] | None) -> str:
    return json.dumps([int(value) for value in values or []])


def _decode_json_int_list(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [int(item) for item in decoded if isinstance(item, int) and not isinstance(item, bool)]


def _memory_search_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        token
        for token in _MEMORY_TOKEN_RE.findall(text.casefold())
        if len(token) > 2 and token not in _MEMORY_STOP_WORDS
    }


def _memory_lesson_relevance_score(
    lesson: StoredMemoryLesson,
    query_tokens: set[str],
) -> int:
    lesson_tokens = _memory_search_tokens(_memory_lesson_relevance_text(lesson))
    overlap = query_tokens & lesson_tokens
    substring_bonus = 0
    lesson_text = _memory_lesson_relevance_text(lesson).casefold()
    for token in query_tokens:
        if token in lesson_text:
            substring_bonus += 1
    return (
        len(overlap) * 100
        + substring_bonus * 10
        + lesson.helpful_count * 5
        - lesson.unhelpful_count * 10
    )


def _memory_lesson_relevance_text(lesson: StoredMemoryLesson) -> str:
    parts = [
        lesson.lesson,
        lesson.outcome_status,
        lesson.failure_reason or "",
        lesson.follow_up_prompt or "",
    ]
    for check in lesson.failed_checks:
        parts.extend(str(value) for value in check.values())
    return " ".join(parts)


def _encode_json_payload(value: dict[str, object] | None) -> str:
    redacted = _redact_json_value(value or {})
    return json.dumps(redacted, sort_keys=True)


def _event_payload_preview(value: object, limit: int = 500) -> str:
    redacted = _redact_json_value(value)
    if redacted in (None, "", {}, []):
        return ""
    if isinstance(redacted, str):
        preview = redacted
    else:
        preview = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
    if len(preview) <= limit:
        return preview
    return f"{preview[:limit]}\n... truncated ..."


def _decode_json_payload(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(key): item for key, item in decoded.items()}


def _encode_json_array_payload(value: list[dict[str, object]] | None) -> str:
    redacted = _redact_json_value(value or [])
    return json.dumps(redacted, sort_keys=True)


def _decode_json_array_payload(value: str | None) -> list[dict[str, object]]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    result: list[dict[str, object]] = []
    for item in decoded:
        if isinstance(item, dict):
            result.append({str(key): value for key, value in item.items()})
    return result


def _append_timeline_entry(
    entries: list[StoredTimelineEntry],
    *,
    occurred_at: str,
    source: str,
    source_id: str,
    event_type: str,
    status: str | None,
    summary: str,
    payload: dict[str, object],
) -> None:
    redacted_payload = _redact_json_value(payload)
    if not isinstance(redacted_payload, dict):
        redacted_payload = {}
    entries.append(
        StoredTimelineEntry(
            timeline_index=0,
            occurred_at=occurred_at,
            source=source,
            source_id=source_id,
            event_type=event_type,
            status=status,
            summary=redact_secrets(summary) or "",
            payload={str(key): item for key, item in redacted_payload.items()},
        )
    )


def _action_timeline_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "iteration_id": row["iteration_id"],
        "idempotency_key": str(row["idempotency_key"]),
        "action_type": str(row["action_type"]),
        "command_string": redact_secrets(row["command_string"]) or "",
        "policy_action": row["policy_action"],
        "policy_reason": redact_secrets(row["policy_reason"]) or "",
        "payload": _decode_json_payload(row["payload_json"]),
        "result": _decode_json_payload(row["result_json"]),
        "lease_owner": redact_secrets(row["lease_owner"]),
        "lease_expires_at": row["lease_expires_at"],
        "heartbeat_at": row["heartbeat_at"],
    }


def _redact_json_value(value: object) -> object:
    if isinstance(value, str):
        return redact_secrets(value) or ""
    if isinstance(value, dict):
        return {str(key): _redact_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_json_value(item) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)


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


def _stored_task_event_from_row(row: sqlite3.Row) -> StoredTaskEvent:
    values = dict(row)
    values["payload"] = _decode_json_payload(values.pop("payload_json", None))
    return StoredTaskEvent(**values)


def _stored_action_record_from_row(row: sqlite3.Row) -> StoredActionRecord:
    values = dict(row)
    values["payload"] = _decode_json_payload(values.pop("payload_json", None))
    values["result"] = _decode_json_payload(values.pop("result_json", None))
    return StoredActionRecord(**values)


def _stored_replan_decision_from_row(row: sqlite3.Row) -> StoredReplanDecision:
    values = dict(row)
    values["failed_checks"] = _decode_json_array_payload(
        values.pop("failed_checks_json", None)
    )
    return StoredReplanDecision(**values)


def _stored_memory_lesson_from_row(row: sqlite3.Row) -> StoredMemoryLesson:
    values = dict(row)
    values["failed_checks"] = _decode_json_array_payload(
        values.pop("failed_checks_json", None)
    )
    return StoredMemoryLesson(**values)


def _stored_autopilot_loop_run_from_row(row: sqlite3.Row) -> StoredAutopilotLoopRun:
    values = dict(row)
    values["selected_item_ids"] = _decode_json_int_list(
        values.pop("selected_item_ids_json", None)
    )
    return StoredAutopilotLoopRun(**values)


def _stored_reflection_record_from_row(row: sqlite3.Row) -> StoredReflectionRecord:
    values = dict(row)
    values["failed_checks"] = _decode_json_array_payload(
        values.pop("failed_checks_json", None)
    )
    return StoredReflectionRecord(**values)


def _stored_memory_influence_from_row(row: sqlite3.Row) -> StoredMemoryInfluence:
    values = dict(row)
    values["injected"] = bool(values["injected"])
    return StoredMemoryInfluence(**values)


def _stored_dead_letter_item_from_row(row: sqlite3.Row) -> StoredDeadLetterItem:
    return StoredDeadLetterItem(**dict(row))
