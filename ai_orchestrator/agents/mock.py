from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from ai_orchestrator.agents.base import (
    AgentResult,
    SessionRef,
    TaskContext,
    summarize_agent_output,
)


@dataclass
class MockAgentAdapter:
    name: str = "mock"
    scripted_status: str = "success"
    scripted_output: str | None = None
    scripted_error: str | None = None
    scripted_files_changed: list[str] = field(default_factory=list)
    scripted_tool_actions: list[str] = field(default_factory=list)
    scripted_uncertainty: str | None = None

    def check_available(self) -> bool:
        return True

    def start_session(self, context: TaskContext) -> SessionRef:
        return SessionRef(session_id=f"mock-{uuid4()}", agent_name=self.name)

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        raw_output = getattr(self, "scripted_output", None)
        if raw_output is None:
            raw_output = f"Mock agent received prompt: {prompt}"
        return AgentResult(
            status=getattr(self, "scripted_status", "success"),
            raw_output=raw_output,
            session_id=session.session_id,
            files_changed=list(getattr(self, "scripted_files_changed", [])),
            tool_actions=list(getattr(self, "scripted_tool_actions", [])),
            summary=summarize_agent_output(raw_output),
            exit_reason=getattr(self, "scripted_status", "success"),
            uncertainty=getattr(self, "scripted_uncertainty", None),
            error=getattr(self, "scripted_error", None),
        )

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        return self.run_step(session, prompt)

    def stop_session(self, session: SessionRef) -> None:
        return None
