from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Protocol

from ai_orchestrator.memory import CodebaseMemoryClient, CodebaseMemoryResult
from ai_orchestrator.process.runner import ProcessRunner, RunOptions
from ai_orchestrator.tools.broker import ToolExecutor, ToolExecutorOutput
from ai_orchestrator.tools.types import ToolCall, ToolResult, ToolResultStatus


_SUPPORTED_FILE_TOOLS = {"fs.read", "fs.write"}


class MemoryToolClient(Protocol):
    def run_tool(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        cwd: Path | None = None,
    ) -> CodebaseMemoryResult: ...


class ToolExecutorRegistry:
    """Typed executor lookup for brokered tool calls."""

    def __init__(self) -> None:
        self._executors: dict[str, ToolExecutor] = {}
        self._prefix_executors: list[tuple[str, ToolExecutor]] = []

    def register(self, tool_name: str, executor: ToolExecutor) -> ToolExecutorRegistry:
        _validate_tool_name(tool_name)
        self._executors[tool_name.strip()] = executor
        return self

    def register_prefix(
        self,
        tool_name_prefix: str,
        executor: ToolExecutor,
    ) -> ToolExecutorRegistry:
        _validate_tool_name(tool_name_prefix)
        self._prefix_executors.append((tool_name_prefix.strip(), executor))
        return self

    def get(self, tool_name: str) -> ToolExecutor | None:
        _validate_tool_name(tool_name)
        normalized = tool_name.strip()
        executor = self._executors.get(normalized)
        if executor is not None:
            return executor

        for prefix, prefix_executor in self._prefix_executors:
            if normalized.startswith(prefix):
                return prefix_executor
        return None

    def run(self, call: ToolCall) -> ToolExecutorOutput:
        executor = self.get(call.spec.name)
        if executor is None:
            return ToolResult(
                call=call,
                status="failed",
                error=f"No executor registered for tool: {call.spec.name}",
            )
        return executor(call)


def process_tool_executor(
    repo: Path,
    *,
    process_runner: ProcessRunner | None = None,
    default_timeout_sec: int = 300,
) -> ToolExecutor:
    runner = process_runner or ProcessRunner()

    def execute(call: ToolCall) -> ToolResult:
        argv = tool_process_argv(call)
        if argv is None:
            return ToolResult(
                call=call,
                status="failed",
                error="Approved tool retry only supports command or argv arguments",
            )

        completed = runner.run(
            argv,
            cwd=repo,
            options=RunOptions(timeout_sec=tool_timeout_sec(call, default_timeout_sec)),
        )
        output: dict[str, object] = {
            "argv": argv,
            "process_status": completed.status,
            "exit_code": completed.exit_code,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.status == "success":
            return ToolResult(call=call, status="succeeded", output=output)
        return ToolResult(
            call=call,
            status="failed",
            output=output,
            error=completed.error or completed.stderr or f"Process status: {completed.status}",
        )

    return execute


def memory_tool_executor(
    client: MemoryToolClient,
    *,
    cwd: Path | None = None,
) -> ToolExecutor:
    def execute(call: ToolCall) -> ToolResult:
        tool = tool_memory_name(call)
        if tool is None:
            return ToolResult(
                call=call,
                status="failed",
                error="Memory tool call must use memory.<tool> or a string tool argument",
            )

        result = client.run_tool(tool, tool_memory_args(call), cwd=cwd)
        return ToolResult(
            call=call,
            status=_memory_result_status(result),
            output={
                "tool": result.tool,
                "memory_status": result.status,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            error=result.error,
        )

    return execute


def approved_memory_commands_for_call(
    client: CodebaseMemoryClient,
    call: ToolCall,
) -> set[str]:
    tool = tool_memory_name(call)
    if tool is None:
        return set()
    return {client.build_command_string(tool=tool, args=tool_memory_args(call))}


def tool_memory_name(call: ToolCall) -> str | None:
    if call.spec.name.startswith("memory."):
        tool = call.spec.name.removeprefix("memory.").strip()
        return tool or None

    raw_tool = call.arguments.get("tool")
    if isinstance(raw_tool, str) and raw_tool.strip():
        return raw_tool.strip()
    return None


def tool_memory_args(call: ToolCall) -> dict[str, Any]:
    nested_args = call.arguments.get("args")
    if isinstance(nested_args, dict) and all(
        isinstance(key, str) for key in nested_args
    ):
        return dict(nested_args)

    return {
        key: value
        for key, value in call.arguments.items()
        if key not in {"tool", "args"}
    }


def _memory_result_status(result: CodebaseMemoryResult) -> ToolResultStatus:
    if result.status == "passed":
        return "succeeded"
    if result.status == "needs_approval":
        return "needs_approval"
    if result.status == "policy_denied":
        return "policy_denied"
    return "failed"


def file_tool_executor(repo: Path) -> ToolExecutor:
    repo_root = repo.resolve()

    def execute(call: ToolCall) -> ToolResult:
        if call.spec.name not in _SUPPORTED_FILE_TOOLS:
            return ToolResult(
                call=call,
                status="failed",
                error=f"Unsupported file tool: {call.spec.name}",
            )

        resolved_path = _repo_tool_path(repo_root, call)
        if resolved_path is None:
            return ToolResult(
                call=call,
                status="failed",
                error="File tool path must be inside the repository",
            )

        if call.spec.name == "fs.read":
            return _run_fs_read(call, resolved_path, repo_root)
        return _run_fs_write(call, resolved_path, repo_root)

    return execute


def _run_fs_read(call: ToolCall, path: Path, repo_root: Path) -> ToolResult:
    if not path.exists():
        return ToolResult(call=call, status="failed", error=f"File not found: {path}")
    if not path.is_file():
        return ToolResult(call=call, status="failed", error=f"Path is not a file: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(call=call, status="failed", error=str(exc))

    return ToolResult(
        call=call,
        status="succeeded",
        output={
            "path": path.relative_to(repo_root).as_posix(),
            "content": content,
            "bytes": len(content.encode("utf-8")),
        },
    )


def _run_fs_write(call: ToolCall, path: Path, repo_root: Path) -> ToolResult:
    content = call.arguments.get("content")
    if not isinstance(content, str):
        return ToolResult(
            call=call,
            status="failed",
            error="fs.write requires string content",
        )

    create_parents = call.arguments.get("create_parents", False)
    if not isinstance(create_parents, bool):
        return ToolResult(
            call=call,
            status="failed",
            error="fs.write create_parents must be boolean",
        )

    try:
        if create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(call=call, status="failed", error=str(exc))

    return ToolResult(
        call=call,
        status="succeeded",
        output={
            "path": path.relative_to(repo_root).as_posix(),
            "bytes": len(content.encode("utf-8")),
        },
    )


def _repo_tool_path(repo_root: Path, call: ToolCall) -> Path | None:
    raw_path = call.arguments.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate

    try:
        parent = candidate.parent.resolve(strict=False)
        resolved = parent / candidate.name
        resolved.relative_to(repo_root)
    except (OSError, ValueError):
        return None
    return resolved


def tool_process_argv(call: ToolCall) -> list[str] | None:
    argv = call.arguments.get("argv")
    if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
        return argv

    command = call.arguments.get("command")
    if isinstance(command, str):
        try:
            return shlex.split(command)
        except ValueError:
            return None
    return None


def tool_timeout_sec(call: ToolCall, default_timeout_sec: int = 300) -> int:
    timeout_sec = call.arguments.get("timeout_sec")
    if isinstance(timeout_sec, int) and not isinstance(timeout_sec, bool) and timeout_sec > 0:
        return timeout_sec
    return default_timeout_sec


def _validate_tool_name(tool_name: str) -> None:
    if not tool_name.strip():
        raise ValueError("Tool name cannot be empty")
