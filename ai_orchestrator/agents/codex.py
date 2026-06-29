from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_orchestrator.agents.base import AgentResult, SessionRef, TaskContext
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner, RunOptions


logger = logging.getLogger(__name__)


@dataclass
class CodexExecAdapter:
    command: str = "codex"
    args: list[str] = field(
        default_factory=lambda: [
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "{prompt}",
        ]
    )
    timeout_sec: int = 1800
    name: str = "codex"
    runner: ProcessRunner = field(default_factory=ProcessRunner)
    policy_engine: PolicyEngine = field(default_factory=PolicyEngine)

    def __post_init__(self) -> None:
        self._sessions: dict[str, TaskContext] = {}
        self._codex_session_ids: dict[str, str] = {}

    def check_available(self) -> bool:
        return self.runner.check_available(self.command)

    def start_session(self, context: TaskContext) -> SessionRef:
        session = SessionRef(session_id=f"codex-{uuid4()}", agent_name=self.name)
        self._sessions[session.session_id] = context
        logger.debug("codex session started agent=%s session_id=%s", self.name, session.session_id)
        return session

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        context = self._sessions.get(session.session_id)
        if context is None:
            logger.warning(
                "codex unknown session agent=%s session_id=%s",
                self.name,
                session.session_id,
            )
            return AgentResult(
                status="failed",
                raw_output="",
                session_id=session.session_id,
                error="Unknown Codex exec session",
            )

        argv = [self.command, *self._render_args(prompt=prompt, repo=context.repo_path)]
        return self._run_argv(session=session, context=context, argv=argv)

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        context = self._sessions.get(session.session_id)
        if context is None:
            logger.warning(
                "codex unknown session agent=%s session_id=%s",
                self.name,
                session.session_id,
            )
            return AgentResult(
                status="failed",
                raw_output="",
                session_id=session.session_id,
                error="Unknown Codex exec session",
            )

        argv = self._build_resume_argv(session=session, prompt=prompt)
        return self._run_argv(session=session, context=context, argv=argv)

    def stop_session(self, session: SessionRef) -> None:
        self._sessions.pop(session.session_id, None)
        self._codex_session_ids.pop(session.session_id, None)
        logger.debug("codex session stopped agent=%s session_id=%s", self.name, session.session_id)

    def _run_argv(
        self,
        session: SessionRef,
        context: TaskContext,
        argv: list[str],
    ) -> AgentResult:
        policy_decision = self.policy_engine.evaluate_argv(argv)
        if policy_decision.action == "deny":
            logger.warning(
                "codex policy denied agent=%s session_id=%s",
                self.name,
                session.session_id,
            )
            return AgentResult(
                status="blocked",
                raw_output="",
                session_id=session.session_id,
                error=policy_decision.reason,
            )
        if policy_decision.action == "ask":
            logger.warning(
                "codex policy needs approval agent=%s session_id=%s",
                self.name,
                session.session_id,
            )
            return AgentResult(
                status="needs_approval",
                raw_output="",
                session_id=session.session_id,
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
            "codex run finished agent=%s session_id=%s status=%s exit_code=%s",
            self.name,
            session.session_id,
            result.status,
            result.exit_code,
        )
        codex_session_id = self._extract_session_id(result.stdout)
        if codex_session_id:
            self._codex_session_ids[session.session_id] = codex_session_id
        raw_output = self._normalize_output(stdout=result.stdout, stderr=result.stderr)
        return AgentResult(
            status=result.status,
            raw_output=raw_output,
            session_id=session.session_id,
            error=result.error,
        )

    def _render_args(self, prompt: str, repo: Path) -> list[str]:
        return [
            item.replace("{prompt}", prompt).replace("{repo}", str(repo))
            for item in self.args
        ]

    def _build_resume_argv(self, session: SessionRef, prompt: str) -> list[str]:
        argv = [self.command, "exec", *self._resume_exec_options(), "resume"]
        codex_session_id = self._codex_session_ids.get(session.session_id)
        if codex_session_id:
            argv.append(codex_session_id)
        else:
            argv.append("--last")
        argv.append(prompt)
        return argv

    def _resume_exec_options(self) -> list[str]:
        options: list[str] = []
        index = 0
        while index < len(self.args):
            item = self.args[index]
            if item == "{prompt}":
                break
            if item in {"--json", "--experimental-json"}:
                options.append(item)
                index += 1
                continue
            if item in {"--sandbox", "-s"} and index + 1 < len(self.args):
                options.extend([item, self.args[index + 1]])
                index += 2
                continue
            index += 1
        return options

    def _normalize_output(self, stdout: str, stderr: str) -> str:
        if not stdout:
            return stderr

        events = self._parse_json_events(stdout)
        if not events:
            return stdout

        text_parts = [part for event in events for part in self._extract_text(event)]
        return "\n".join(text_parts) if text_parts else stdout

    def _extract_session_id(self, output: str) -> str | None:
        for event in self._parse_json_events(output):
            session_id = self._find_string(event, keys={"session_id", "sessionId"})
            if session_id:
                return session_id
        return None

    def _parse_json_events(self, output: str) -> list[Any]:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            return parsed if isinstance(parsed, list) else [parsed]

        events: list[Any] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                return []
        return events

    def _extract_text(self, event: Any) -> list[str]:
        if isinstance(event, str):
            return [event]
        if isinstance(event, list):
            return [part for item in event for part in self._extract_text(item)]
        if not isinstance(event, dict):
            return []

        parts: list[str] = []
        for key in ("output_text", "text", "content", "message", "summary"):
            value = event.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
            elif isinstance(value, (dict, list)):
                parts.extend(self._extract_text(value))
        return parts

    def _find_string(self, event: Any, keys: set[str]) -> str | None:
        if isinstance(event, list):
            for item in event:
                found = self._find_string(item, keys)
                if found:
                    return found
            return None
        if not isinstance(event, dict):
            return None

        for key in keys:
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        for value in event.values():
            if isinstance(value, (dict, list)):
                found = self._find_string(value, keys)
                if found:
                    return found
        return None
