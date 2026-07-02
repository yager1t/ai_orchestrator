from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ai_orchestrator.agents.base import AgentAdapter, ProgressCallback, SessionRef, TaskContext
from ai_orchestrator.core.decision import Decision, DecisionEngine
from ai_orchestrator.process.runner import ProcessRunner, RunOptions
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.runner import (
    VerificationCommand,
    VerificationResult,
    VerificationRunner,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorResult:
    status: str
    summary: str
    task_id: str | None = None


class Supervisor:
    MAX_PLANNING_CONTEXT_CHARS = 4000

    def __init__(
        self,
        agent: AgentAdapter,
        verifier: VerificationRunner,
        verification_commands: list[VerificationCommand] | None = None,
        decision_engine: DecisionEngine | None = None,
        state_store: StateStore | None = None,
        max_iterations: int = 2,
        max_no_change_iterations: int = 2,
        max_runtime_sec: int | None = None,
        require_repo_change: bool = False,
        progress_callback: ProgressCallback | None = None,
        process_runner: ProcessRunner | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.agent = agent
        self.verifier = verifier
        self.verification_commands = verification_commands or []
        self.decision_engine = decision_engine or DecisionEngine()
        self.state_store = state_store
        self.max_iterations = max_iterations
        self.max_no_change_iterations = max_no_change_iterations
        self.max_runtime_sec = max_runtime_sec
        self.require_repo_change = require_repo_change
        self.progress_callback = progress_callback
        self.process_runner = process_runner or ProcessRunner()
        self.clock = clock or time.monotonic

    def run_once(
        self,
        task: str,
        repo: Path,
        planning_context: str | None = None,
    ) -> SupervisorResult:
        return self._run(
            task=task,
            repo=repo,
            task_id=None,
            start_iteration=1,
            planning_context=planning_context,
        )

    def run_existing(
        self,
        task_id: str,
        task: str,
        repo: Path,
        planning_context: str | None = None,
    ) -> SupervisorResult:
        start_iteration = 1
        if self.state_store is not None:
            start_iteration = len(self.state_store.list_iterations(task_id)) + 1
        return self._run(
            task=task,
            repo=repo,
            task_id=task_id,
            start_iteration=start_iteration,
            planning_context=planning_context,
        )

    def _run(
        self,
        task: str,
        repo: Path,
        task_id: str | None,
        start_iteration: int,
        planning_context: str | None,
    ) -> SupervisorResult:
        logger.debug(
            "event=supervisor.run_started agent=%s task_id=%s start_iteration=%s max_iterations=%s",
            self.agent.name,
            task_id,
            start_iteration,
            self.max_iterations,
        )
        started_at = self.clock()
        stored_task_id = task_id
        if self.state_store is not None:
            if stored_task_id is None:
                stored_task_id = self.state_store.create_task(task=task, repo_path=repo).task_id
            else:
                if self._is_task_cancelled(stored_task_id):
                    return SupervisorResult(
                        status="cancelled",
                        summary="Task was cancelled",
                        task_id=stored_task_id,
                    )
                self.state_store.update_task_status(stored_task_id, "running")

        if not self.agent.check_available():
            logger.warning(
                "event=supervisor.agent_unavailable agent=%s task_id=%s",
                self.agent.name,
                stored_task_id,
            )
            if stored_task_id is not None and self.state_store is not None:
                self.state_store.add_iteration(
                    task_id=stored_task_id,
                    iteration_index=start_iteration,
                    agent_name=self.agent.name,
                    agent_status="unavailable",
                    prompt=task,
                    raw_output="",
                    decision_status="blocked",
                    decision_reason="Agent is not available",
                    exit_reason="agent_unavailable",
                )
                self.state_store.update_task_status(stored_task_id, "blocked")
            return SupervisorResult(
                status="blocked",
                summary="Agent is not available",
                task_id=stored_task_id,
            )

        context = TaskContext(
            task=task,
            repo_path=repo,
            metadata={"task_id": stored_task_id} if stored_task_id is not None else {},
            cancellation_requested=lambda: self._is_task_cancelled(stored_task_id),
            progress_callback=self.progress_callback,
        )
        session = self.agent.start_session(context)
        prompt = self._build_initial_prompt(task=task, planning_context=planning_context)
        initial_repo_snapshot = self._repo_snapshot(repo) if self.require_repo_change else None
        previous_signature: tuple[str, tuple[str, ...], str] | None = None
        no_change_count = 0

        for attempt in range(1, self.max_iterations + 1):
            iteration_index = start_iteration + attempt - 1
            if self._is_runtime_budget_exhausted(started_at):
                if stored_task_id is not None and self.state_store is not None:
                    self.state_store.update_task_status(stored_task_id, "blocked")
                logger.warning(
                    "event=supervisor.runtime_budget_exhausted task_id=%s iteration=%s",
                    stored_task_id,
                    iteration_index,
                )
                self._stop_session(session)
                return SupervisorResult(
                    status="blocked",
                    summary="Runtime budget exhausted",
                    task_id=stored_task_id,
                )
            if self._is_task_cancelled(stored_task_id):
                logger.warning(
                    "event=supervisor.task_cancelled task_id=%s iteration=%s",
                    stored_task_id,
                    iteration_index,
                )
                self._stop_session(session)
                return SupervisorResult(
                    status="cancelled",
                    summary="Task was cancelled",
                    task_id=stored_task_id,
                )
            logger.debug(
                "event=supervisor.iteration_started agent=%s task_id=%s iteration=%s attempt=%s",
                session.agent_name,
                stored_task_id,
                iteration_index,
                attempt,
            )
            self._progress(f"iteration {iteration_index}: agent {session.agent_name} started")
            try:
                if attempt == 1:
                    result = self.agent.run_step(session, prompt=prompt)
                else:
                    result = self.agent.continue_session(session, prompt=prompt)
            except KeyboardInterrupt:
                self._stop_session(session)
                raise
            logger.debug(
                "event=supervisor.agent_result agent=%s task_id=%s iteration=%s status=%s files_changed=%s",
                session.agent_name,
                stored_task_id,
                iteration_index,
                result.status,
                len(result.files_changed),
            )
            if result.status == "cancelled" or self._is_task_cancelled(stored_task_id):
                logger.warning(
                    "event=supervisor.task_cancelled task_id=%s iteration=%s",
                    stored_task_id,
                    iteration_index,
                )
                self._stop_session(session)
                return SupervisorResult(
                    status="cancelled",
                    summary="Task was cancelled",
                    task_id=stored_task_id,
                )

            verification_results = []
            if result.status == "success":
                if self._is_runtime_budget_exhausted(started_at):
                    if stored_task_id is not None and self.state_store is not None:
                        self.state_store.update_task_status(stored_task_id, "blocked")
                    logger.warning(
                        "event=supervisor.runtime_budget_exhausted task_id=%s iteration=%s",
                        stored_task_id,
                        iteration_index,
                    )
                    self._stop_session(session)
                    return SupervisorResult(
                        status="blocked",
                        summary="Runtime budget exhausted",
                        task_id=stored_task_id,
                    )
                if self._is_task_cancelled(stored_task_id):
                    logger.warning(
                        "event=supervisor.task_cancelled task_id=%s iteration=%s",
                        stored_task_id,
                        iteration_index,
                    )
                    self._stop_session(session)
                    return SupervisorResult(
                        status="cancelled",
                        summary="Task was cancelled",
                        task_id=stored_task_id,
                    )
                try:
                    self._progress(f"iteration {iteration_index}: verification started")
                    verification_results = self.verifier.run_many(
                        self.verification_commands,
                        cwd=repo,
                    )
                    self._progress(f"iteration {iteration_index}: verification finished")
                except KeyboardInterrupt:
                    self._stop_session(session)
                    raise
            decision = self.decision_engine.decide(
                result,
                verification_results,
                iteration=attempt,
                max_iterations=self.max_iterations,
                original_task=task,
            )
            logger.debug(
                "event=supervisor.decision task_id=%s iteration=%s status=%s",
                stored_task_id,
                iteration_index,
                decision.status,
            )
            if (
                decision.status == "done"
                and self.require_repo_change
                and not self._has_repo_change(repo, initial_repo_snapshot, result.files_changed)
            ):
                decision = Decision(
                    status="blocked",
                    reason="No agent file or repository change detected",
                )
                logger.warning(
                    "event=supervisor.no_change_blocked task_id=%s iteration=%s count=1",
                    stored_task_id,
                    iteration_index,
                )
            if decision.status == "continue":
                repo_snapshot = self._repo_snapshot(repo)
                if repo_snapshot is not None:
                    signature = (
                        result.status,
                        tuple(result.files_changed),
                        repo_snapshot,
                    )
                    if signature == previous_signature:
                        no_change_count += 1
                    else:
                        no_change_count = 1
                    previous_signature = signature
                    if (
                        self.max_no_change_iterations > 0
                        and no_change_count >= self.max_no_change_iterations
                    ):
                        decision = Decision(
                            status="blocked",
                            reason=(
                                "No agent file or repository change detected for "
                                f"{no_change_count} iteration(s)"
                            ),
                        )
                        logger.warning(
                            "event=supervisor.no_change_blocked task_id=%s iteration=%s count=%s",
                            stored_task_id,
                            iteration_index,
                            no_change_count,
                        )
            stored_iteration = None
            if stored_task_id is not None and self.state_store is not None:
                stored_iteration = self.state_store.add_iteration(
                    task_id=stored_task_id,
                    iteration_index=iteration_index,
                    agent_name=session.agent_name,
                    agent_status=result.status,
                    prompt=prompt,
                    raw_output=result.raw_output,
                    decision_status=decision.status,
                    decision_reason=decision.reason,
                    agent_summary=result.summary,
                    files_changed=result.files_changed,
                    tool_actions=result.tool_actions,
                    exit_reason=result.exit_reason,
                    uncertainty=result.uncertainty,
                )
                for verification_result in verification_results:
                    self.state_store.add_verification_run(
                        task_id=stored_task_id,
                        iteration_id=stored_iteration.iteration_id,
                        result=verification_result,
                    )
                    if verification_result.status == "needs_approval":
                        self._add_verification_approval_request(
                            task_id=stored_task_id,
                            iteration_id=stored_iteration.iteration_id,
                            verification_result=verification_result,
                        )

            if decision.status == "done":
                logger.debug(
                    "event=supervisor.run_done task_id=%s iteration=%s",
                    stored_task_id,
                    iteration_index,
                )
                if stored_task_id is not None and self.state_store is not None:
                    self.state_store.update_task_status(stored_task_id, "done")
                self._stop_session(session)
                self._progress(f"iteration {iteration_index}: done")
                return SupervisorResult(
                    status="done",
                    summary=f"Iteration {iteration_index}: {decision.reason}",
                    task_id=stored_task_id,
                )

            if decision.status == "blocked":
                logger.warning(
                    "event=supervisor.run_blocked task_id=%s iteration=%s",
                    stored_task_id,
                    iteration_index,
                )
                if stored_task_id is not None and self.state_store is not None:
                    self.state_store.update_task_status(stored_task_id, "blocked")
                self._stop_session(session)
                self._progress(f"iteration {iteration_index}: blocked")
                return SupervisorResult(
                    status="blocked",
                    summary=decision.reason,
                    task_id=stored_task_id,
                )

            prompt = decision.follow_up_prompt or task

        if stored_task_id is not None and self.state_store is not None:
            self.state_store.update_task_status(stored_task_id, "blocked")
        logger.warning("event=supervisor.max_iterations_exhausted task_id=%s", stored_task_id)
        self._stop_session(session)
        self._progress("max iterations exhausted")
        return SupervisorResult(
            status="blocked",
            summary="Max iterations exhausted",
            task_id=stored_task_id,
        )

    def _is_task_cancelled(self, task_id: str | None) -> bool:
        if task_id is None or self.state_store is None:
            return False
        task = self.state_store.get_task(task_id)
        return task is not None and task.status == "cancelled"

    def _add_verification_approval_request(
        self,
        task_id: str,
        iteration_id: int,
        verification_result: VerificationResult,
    ) -> None:
        if self.state_store is None or not verification_result.command_string:
            return
        self.state_store.add_approval_request(
            task_id=task_id,
            iteration_id=iteration_id,
            source="verification",
            command_string=verification_result.command_string,
            reason=verification_result.error or "Verification command requires approval",
        )

    def _is_runtime_budget_exhausted(self, started_at: float) -> bool:
        if self.max_runtime_sec is None:
            return False
        return self.clock() - started_at >= self.max_runtime_sec

    def _repo_snapshot(self, repo: Path) -> str | None:
        try:
            result = self.process_runner.run(
                ["git", "status", "--porcelain=v1"],
                cwd=repo,
                options=RunOptions(timeout_sec=30),
            )
        except Exception:
            return None
        if result.status == "success":
            return self._normalize_repo_snapshot(result.stdout)
        return None

    def _normalize_repo_snapshot(self, snapshot: str) -> str:
        kept = [
            line
            for line in snapshot.splitlines()
            if line and not self._is_ignored_snapshot_path(line[3:].strip())
        ]
        return "\n".join(kept)

    def _has_repo_change(
        self,
        repo: Path,
        initial_snapshot: str | None,
        files_changed: list[str],
    ) -> bool:
        if files_changed:
            return True
        current_snapshot = self._repo_snapshot(repo)
        if initial_snapshot is None or current_snapshot is None:
            return False
        return current_snapshot != initial_snapshot

    def _is_ignored_snapshot_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        return (
            normalized.startswith(".ai-orch/")
            or normalized == ".ai-orch"
            or normalized.startswith(".pytest_cache/")
            or normalized == ".pytest_cache"
            or "__pycache__/" in normalized
            or normalized.endswith("/__pycache__")
            or normalized.endswith(".pyc")
        )

    def _build_initial_prompt(self, task: str, planning_context: str | None) -> str:
        if not planning_context:
            return task
        context = self._excerpt(planning_context, self.MAX_PLANNING_CONTEXT_CHARS)
        return "\n\n".join(
            [
                task,
                "Planning context (read-only, non-authoritative):",
                context,
            ]
        )

    def _excerpt(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        suffix = "\n... truncated ..."
        if limit <= len(suffix):
            return suffix[:limit]
        return f"{text[: limit - len(suffix)]}{suffix}"

    def _stop_session(self, session: SessionRef) -> None:
        try:
            self.agent.stop_session(session)
            logger.debug(
                "event=supervisor.session_stopped agent=%s session_id=%s",
                session.agent_name,
                session.session_id,
            )
        except Exception:
            logger.warning(
                "event=supervisor.session_stop_failed agent=%s session_id=%s",
                session.agent_name,
                session.session_id,
            )

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)
