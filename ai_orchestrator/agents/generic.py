from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from ai_orchestrator.agents.base import (
    AgentResult,
    SessionRef,
    TaskContext,
    summarize_agent_output,
)
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner, RunOptions


logger = logging.getLogger(__name__)


@dataclass
class GenericCLIAdapter:
    command: str
    args: list[str]
    timeout_sec: int = 300
    name: str = "generic"
    runner: ProcessRunner = field(default_factory=ProcessRunner)
    policy_engine: PolicyEngine = field(default_factory=PolicyEngine)

    def __post_init__(self) -> None:
        self._sessions: dict[str, TaskContext] = {}

    def check_available(self) -> bool:
        return self.runner.check_available(self.command)

    def start_session(self, context: TaskContext) -> SessionRef:
        session = SessionRef(session_id=f"generic-{uuid4()}", agent_name=self.name)
        self._sessions[session.session_id] = context
        logger.debug(
            "generic session started agent=%s session_id=%s",
            self.name,
            session.session_id,
        )
        return session

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        context = self._sessions.get(session.session_id)
        if context is None:
            logger.warning(
                "generic unknown session agent=%s session_id=%s",
                self.name,
                session.session_id,
            )
            return AgentResult(
                status="failed",
                raw_output="",
                session_id=session.session_id,
                exit_reason="unknown_session",
                error="Unknown generic CLI session",
            )

        argv = [self.command, *self._render_args(prompt=prompt, repo=context.repo_path)]
        policy_decision = self.policy_engine.evaluate_argv(argv)
        if policy_decision.action == "deny":
            logger.warning(
                "generic policy denied agent=%s session_id=%s",
                self.name,
                session.session_id,
            )
            return AgentResult(
                status="blocked",
                raw_output="",
                session_id=session.session_id,
                summary=policy_decision.reason,
                exit_reason="policy_denied",
                error=policy_decision.reason,
            )
        if policy_decision.action == "ask":
            logger.warning(
                "generic policy needs approval agent=%s session_id=%s",
                self.name,
                session.session_id,
            )
            return AgentResult(
                status="needs_approval",
                raw_output="",
                session_id=session.session_id,
                summary=policy_decision.reason,
                exit_reason="policy_needs_approval",
                error=policy_decision.reason,
            )

        result = self.runner.run(
            argv,
            cwd=context.repo_path,
            options=RunOptions(
                timeout_sec=self.timeout_sec,
                should_cancel=context.cancellation_requested,
            ),
        )
        logger.debug(
            "generic run finished agent=%s session_id=%s status=%s exit_code=%s",
            self.name,
            session.session_id,
            result.status,
            result.exit_code,
        )
        raw_output = result.stdout if result.stdout else result.stderr
        return AgentResult(
            status=result.status,
            raw_output=raw_output,
            session_id=session.session_id,
            summary=summarize_agent_output(raw_output),
            exit_reason=result.error or result.status,
            error=result.error,
        )

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        return self.run_step(session, prompt)

    def stop_session(self, session: SessionRef) -> None:
        self._sessions.pop(session.session_id, None)
        logger.debug(
            "generic session stopped agent=%s session_id=%s",
            self.name,
            session.session_id,
        )

    def _render_args(self, prompt: str, repo: Path) -> list[str]:
        return [
            item.replace("{prompt}", prompt).replace("{repo}", str(repo))
            for item in self.args
        ]
