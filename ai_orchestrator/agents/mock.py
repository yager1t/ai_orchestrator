from __future__ import annotations

from uuid import uuid4

from ai_orchestrator.agents.base import AgentResult, SessionRef, TaskContext


class MockAgentAdapter:
    name = "mock"

    def check_available(self) -> bool:
        return True

    def start_session(self, context: TaskContext) -> SessionRef:
        return SessionRef(session_id=f"mock-{uuid4()}", agent_name=self.name)

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        return AgentResult(
            status="success",
            raw_output=f"Mock agent received prompt: {prompt}",
            session_id=session.session_id,
            files_changed=[],
        )

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        return self.run_step(session, prompt)

    def stop_session(self, session: SessionRef) -> None:
        return None
