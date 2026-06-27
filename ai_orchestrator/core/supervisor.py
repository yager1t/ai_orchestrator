from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ai_orchestrator.agents.base import AgentAdapter, SessionRef, TaskContext
from ai_orchestrator.core.decision import Decision, DecisionEngine
from ai_orchestrator.process.runner import ProcessRunner
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.runner import VerificationCommand, VerificationRunner


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorResult:
    status: str
    summary: str
    task_id: str | None = None


class Supervisor:
    def __init__(
        self,
        agent: AgentAdapter,
        verifier: VerificationRunner,
        verification_commands: list[VerificationCommand] | None = None,
        decision_engine: DecisionEngine | None = None,
        state_store: StateStore | None = None,
        max_iterations: int = 2,
        max_no_change_iterations: int = 2,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.agent = agent
        self.verifier = verifier
        self.verification_commands = verification_commands or []
        self.decision_engine = decision_engine or DecisionEngine()
        self.state_store = state_store
        self.max_iterations = max_iterations
        self.max_no_change_iterations = max_no_change_iterations
        self.process_runner = process_runner or ProcessRunner()

    def run_once(self, task: str, repo: Path) -> SupervisorResult:
        return self._run(task=task, repo=repo, task_id=None, start_iteration=1)

    def run_existing(self, task_id: str, task: str, repo: Path) -> SupervisorResult:
        start_iteration = 1
        if self.state_store is not None:
            start_iteration = len(self.state_store.list_iterations(task_id)) + 1
        return self._run(
            task=task,
            repo=repo,
            task_id=task_id,
            start_iteration=start_iteration,
        )

    def _run(
        self,
        task: str,
        repo: Path,
        task_id: str | None,
        start_iteration: int,
    ) -> SupervisorResult:
        logger.debug(
            "supervisor run started agent=%s task_id=%s start_iteration=%s max_iterations=%s",
            self.agent.name,
            task_id,
            start_iteration,
            self.max_iterations,
        )
        stored_task_id = task_id
        if self.state_store is not None:
            if stored_task_id is None:
                stored_task_id = self.state_store.create_task(task=task, repo_path=repo).task_id
            else:
                self.state_store.update_task_status(stored_task_id, "running")

        if not self.agent.check_available():
            logger.warning(
                "supervisor agent unavailable agent=%s task_id=%s",
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
                )
                self.state_store.update_task_status(stored_task_id, "blocked")
            return SupervisorResult(
                status="blocked",
                summary="Agent is not available",
                task_id=stored_task_id,
            )

        context = TaskContext(task=task, repo_path=repo)
        session = self.agent.start_session(context)
        prompt = task
        previous_signature: tuple[str, tuple[str, ...], str] | None = None
        no_change_count = 0

        for attempt in range(1, self.max_iterations + 1):
            iteration_index = start_iteration + attempt - 1
            logger.debug(
                "supervisor iteration started agent=%s task_id=%s iteration=%s attempt=%s",
                session.agent_name,
                stored_task_id,
                iteration_index,
                attempt,
            )
            try:
                if attempt == 1:
                    result = self.agent.run_step(session, prompt=prompt)
                else:
                    result = self.agent.continue_session(session, prompt=prompt)
            except KeyboardInterrupt:
                self._stop_session(session)
                raise
            logger.debug(
                "supervisor agent result agent=%s task_id=%s iteration=%s status=%s files_changed=%s",
                session.agent_name,
                stored_task_id,
                iteration_index,
                result.status,
                len(result.files_changed),
            )

            verification_results = []
            if result.status == "success":
                try:
                    verification_results = self.verifier.run_many(
                        self.verification_commands,
                        cwd=repo,
                    )
                except KeyboardInterrupt:
                    self._stop_session(session)
                    raise
            decision = self.decision_engine.decide(
                result,
                verification_results,
                iteration=attempt,
                max_iterations=self.max_iterations,
            )
            logger.debug(
                "supervisor decision task_id=%s iteration=%s status=%s",
                stored_task_id,
                iteration_index,
                decision.status,
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
                            "supervisor blocked no-change task_id=%s iteration=%s count=%s",
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
                )
                for verification_result in verification_results:
                    self.state_store.add_verification_run(
                        task_id=stored_task_id,
                        iteration_id=stored_iteration.iteration_id,
                        result=verification_result,
                    )

            if decision.status == "done":
                logger.debug(
                    "supervisor run done task_id=%s iteration=%s",
                    stored_task_id,
                    iteration_index,
                )
                if stored_task_id is not None and self.state_store is not None:
                    self.state_store.update_task_status(stored_task_id, "done")
                self._stop_session(session)
                return SupervisorResult(
                    status="done",
                    summary=f"Iteration {iteration_index}: {decision.reason}",
                    task_id=stored_task_id,
                )

            if decision.status == "blocked":
                logger.warning(
                    "supervisor run blocked task_id=%s iteration=%s",
                    stored_task_id,
                    iteration_index,
                )
                if stored_task_id is not None and self.state_store is not None:
                    self.state_store.update_task_status(stored_task_id, "blocked")
                self._stop_session(session)
                return SupervisorResult(
                    status="blocked",
                    summary=decision.reason,
                    task_id=stored_task_id,
                )

            prompt = decision.follow_up_prompt or task

        if stored_task_id is not None and self.state_store is not None:
            self.state_store.update_task_status(stored_task_id, "blocked")
        logger.warning("supervisor max iterations exhausted task_id=%s", stored_task_id)
        self._stop_session(session)
        return SupervisorResult(
            status="blocked",
            summary="Max iterations exhausted",
            task_id=stored_task_id,
        )

    def _repo_snapshot(self, repo: Path) -> str | None:
        try:
            result = self.process_runner.run(
                ["git", "status", "--porcelain=v1"],
                cwd=repo,
                timeout_sec=30,
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

    def _stop_session(self, session: SessionRef) -> None:
        try:
            self.agent.stop_session(session)
            logger.debug(
                "supervisor session stopped agent=%s session_id=%s",
                session.agent_name,
                session.session_id,
            )
        except Exception:
            logger.warning(
                "supervisor session stop failed agent=%s session_id=%s",
                session.agent_name,
                session.session_id,
            )
