from pathlib import Path

from ai_orchestrator.memory import CodebaseMemoryClient
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessResult


class FakeProcessRunner:
    def __init__(self) -> None:
        self.argv: list[str] | None = None
        self.cwd: Path | None = None

    def check_available(self, command: str) -> bool:
        return command == "codebase-memory-mcp"

    def run(self, argv, cwd=None, options=None):  # noqa: ANN001, ANN201
        self.argv = argv
        self.cwd = cwd
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout='{"ok":true}',
            stderr="",
        )


def test_codebase_memory_checks_binary_availability() -> None:
    client = CodebaseMemoryClient(process_runner=FakeProcessRunner())

    assert client.check_available() is True


def test_codebase_memory_runs_read_only_tool_with_json_args(tmp_path: Path) -> None:
    runner = FakeProcessRunner()
    client = CodebaseMemoryClient(process_runner=runner)

    result = client.run_tool(
        "search_graph",
        {"label": "Function", "name_pattern": ".*run.*"},
        cwd=tmp_path,
    )

    assert result.status == "passed"
    assert runner.argv == [
        "codebase-memory-mcp",
        "cli",
        "search_graph",
        '{"label": "Function", "name_pattern": ".*run.*"}',
    ]
    assert runner.cwd == tmp_path


def test_codebase_memory_requires_approval_for_index_repository() -> None:
    runner = FakeProcessRunner()
    client = CodebaseMemoryClient(process_runner=runner)

    result = client.run_tool("index_repository", {"repo_path": "."})

    assert result.status == "needs_approval"
    assert result.error == "Codebase Memory tool requires approval: index_repository"
    assert runner.argv is None


def test_codebase_memory_runs_approved_write_tool() -> None:
    command = (
        'codebase-memory-mcp cli index_repository "{\\"repo_path\\": \\".\\"}"'
    )
    runner = FakeProcessRunner()
    client = CodebaseMemoryClient(
        process_runner=runner,
        approved_commands={command},
    )

    result = client.run_tool("index_repository", {"repo_path": "."})

    assert result.status == "passed"
    assert runner.argv == [
        "codebase-memory-mcp",
        "cli",
        "index_repository",
        '{"repo_path": "."}',
    ]


def test_codebase_memory_honors_policy_denial() -> None:
    runner = FakeProcessRunner()
    client = CodebaseMemoryClient(
        command=["blocked-memory", "cli"],
        policy_engine=PolicyEngine(deny_patterns=["blocked-memory"]),
        process_runner=runner,
    )

    result = client.run_tool("search_graph", {"label": "Function"})

    assert result.status == "policy_denied"
    assert runner.argv is None
