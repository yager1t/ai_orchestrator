from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner, RunOptions


@dataclass(frozen=True)
class CodebaseMemoryResult:
    tool: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None = None


class CodebaseMemoryClient:
    READ_ONLY_TOOLS = frozenset(
        {
            "list_projects",
            "index_status",
            "get_architecture",
            "get_graph_schema",
            "search_graph",
            "trace_path",
            "trace_call_path",
            "search_code",
            "detect_changes",
            "query_graph",
            "get_code_snippet",
        }
    )
    APPROVAL_TOOLS = frozenset(
        {
            "index_repository",
            "manage_adr",
            "ingest_traces",
            "delete_project",
        }
    )

    def __init__(
        self,
        command: list[str] | None = None,
        policy_engine: PolicyEngine | None = None,
        process_runner: ProcessRunner | None = None,
        approved_commands: set[str] | None = None,
        timeout_sec: int = 120,
    ) -> None:
        self.command = command or ["codebase-memory-mcp", "cli"]
        self.policy_engine = policy_engine or PolicyEngine()
        self.process_runner = process_runner or ProcessRunner()
        self.approved_commands = frozenset(approved_commands or set())
        self.timeout_sec = timeout_sec

    def check_available(self) -> bool:
        return bool(self.command) and self.process_runner.check_available(self.command[0])

    def run_tool(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        cwd: Path | None = None,
    ) -> CodebaseMemoryResult:
        argv = self._build_argv(tool=tool, args=args)
        policy_command = self.build_command_string(tool=tool, args=args)

        decision = self.policy_engine.evaluate_argv(argv)
        if decision.action == "deny":
            return CodebaseMemoryResult(
                tool=tool,
                status="policy_denied",
                exit_code=None,
                stdout="",
                stderr="",
                error=decision.reason,
            )
        if decision.action == "ask" and policy_command not in self.approved_commands:
            return CodebaseMemoryResult(
                tool=tool,
                status="needs_approval",
                exit_code=None,
                stdout="",
                stderr="",
                error=decision.reason,
            )

        if self._requires_approval(tool) and policy_command not in self.approved_commands:
            return CodebaseMemoryResult(
                tool=tool,
                status="needs_approval",
                exit_code=None,
                stdout="",
                stderr="",
                error=f"Codebase Memory tool requires approval: {tool}",
            )

        completed = self.process_runner.run(
            argv,
            cwd=cwd,
            options=RunOptions(timeout_sec=self.timeout_sec),
        )
        return CodebaseMemoryResult(
            tool=tool,
            status="passed" if completed.status == "success" else completed.status,
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error=completed.error,
        )

    def _build_argv(self, tool: str, args: dict[str, Any] | None) -> list[str]:
        argv = [*self.command, tool]
        if args:
            argv.append(json.dumps(args, sort_keys=True))
        return argv

    def build_command_string(self, tool: str, args: dict[str, Any] | None = None) -> str:
        return subprocess.list2cmdline(self._build_argv(tool=tool, args=args))

    def _requires_approval(self, tool: str) -> bool:
        return tool in self.APPROVAL_TOOLS or tool not in self.READ_ONLY_TOOLS
