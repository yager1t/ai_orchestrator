from __future__ import annotations

from pathlib import Path

import pytest

from ai_orchestrator.control import LocalOperatorClient, McpAcpRequest
from ai_orchestrator.process.runner import ProcessResult


class FakeRunner:
    def __init__(self, result: ProcessResult | list[ProcessResult]) -> None:
        self.results = result if isinstance(result, list) else [result]
        self.calls: list[tuple[list[str], Path | None, int]] = []

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
    ) -> ProcessResult:
        result = self.results[min(len(self.calls), len(self.results) - 1)]
        self.calls.append((argv, cwd, timeout_sec))
        return result


def test_local_operator_client_parses_control_json() -> None:
    repo = Path(".")
    resolved_repo = repo.resolve()
    runner = FakeRunner(
        ProcessResult(
            status="success",
            exit_code=0,
            stdout=(
                '{"schema_version":"1.0","command":"status","ok":true,'
                '"generated_at":"2026-07-17T00:00:00Z","error":null}'
            ),
            stderr="",
        )
    )
    client = LocalOperatorClient(
        repo=repo,
        runner=runner,
        python_executable="python",
        timeout_sec=12,
    )

    result = client.get_status("task-1")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload["command"] == "status"
    assert result.error is None
    assert runner.calls == [
        (
            [
                "python",
                "-m",
                "ai_orchestrator",
                "status",
                "task-1",
                "--repo",
                str(resolved_repo),
                "--json",
            ],
            resolved_repo,
            12,
        )
    ]


def test_local_operator_client_starts_task_with_control_json() -> None:
    repo = Path(".")
    resolved_repo = repo.resolve()
    runner = FakeRunner(
        ProcessResult(
            status="success",
            exit_code=0,
            stdout=(
                '{"schema_version":"1.0","command":"start","ok":true,'
                '"generated_at":"2026-07-17T00:00:00Z","error":null,'
                '"task_id":"task-1","status":"done"}'
            ),
            stderr="",
        )
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.start_task("Fix tests")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload["task_id"] == "task-1"
    assert result.payload["status"] == "done"
    assert runner.calls[0][0] == [
        "python",
        "-m",
        "ai_orchestrator",
        "start",
        "--task",
        "Fix tests",
        "--repo",
        str(resolved_repo),
        "--json",
    ]


def test_local_operator_client_preserves_start_payload_on_nonzero_exit() -> None:
    repo = Path(".")
    runner = FakeRunner(
        ProcessResult(
            status="success",
            exit_code=1,
            stdout=(
                '{"schema_version":"1.0","command":"start","ok":true,'
                '"generated_at":"2026-07-17T00:00:00Z","error":null,'
                '"task_id":"task-1","status":"blocked"}'
            ),
            stderr="",
        )
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.start_task("Fix tests")

    assert result.ok is False
    assert result.payload is not None
    assert result.payload["task_id"] == "task-1"
    assert result.payload["status"] == "blocked"
    assert result.error == "Command failed with exit code 1"


def test_local_operator_client_reports_process_failure() -> None:
    repo = Path(".")
    runner = FakeRunner(
        ProcessResult(
            status="failed",
            exit_code=1,
            stdout=(
                '{"schema_version":"1.0","command":"status","ok":false,'
                '"generated_at":"2026-07-17T00:00:00Z",'
                '"error":{"code":"task_not_found","message":"missing"}}'
            ),
            stderr="",
        )
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.get_status("missing")

    assert result.ok is False
    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.payload is not None
    assert result.payload["error"]["code"] == "task_not_found"


def test_local_operator_client_reports_control_payload_failure() -> None:
    repo = Path(".")
    runner = FakeRunner(
        ProcessResult(
            status="success",
            exit_code=0,
            stdout=(
                '{"schema_version":"1.0","command":"status","ok":false,'
                '"generated_at":"2026-07-17T00:00:00Z",'
                '"error":{"code":"task_not_found","message":"missing"}}'
            ),
            stderr="",
        )
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.get_status("missing")

    assert result.ok is False
    assert result.payload is not None
    assert result.payload["ok"] is False
    assert result.error == "Control operation failed: task_not_found: missing"


def test_local_operator_client_reports_schema_mismatch() -> None:
    repo = Path(".")
    runner = FakeRunner(
        ProcessResult(
            status="success",
            exit_code=0,
            stdout='{"schema_version":"2.0","command":"status","ok":true}',
            stderr="",
        )
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.get_status("task-1")

    assert result.ok is False
    assert result.payload is not None
    assert result.error == "Invalid JSON output: expected schema_version '1.0', got '2.0'"


def test_local_operator_client_preserves_process_error_with_invalid_json() -> None:
    repo = Path(".")
    runner = FakeRunner(
        ProcessResult(
            status="failed",
            exit_code=2,
            stdout="not json",
            stderr="command failed",
        )
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.get_status("task-1")

    assert result.ok is False
    assert result.payload is None
    assert result.error == "command failed; Invalid JSON output: Expecting value"


def test_local_operator_client_approval_methods_parse_control_json() -> None:
    repo = Path(".")
    resolved_repo = repo.resolve()
    runner = FakeRunner(
        [
            ProcessResult(
                status="success",
                exit_code=0,
                stdout=(
                    '{"schema_version":"1.0","command":"approvals approve",'
                    '"ok":true,"generated_at":"2026-07-17T00:00:00Z",'
                    '"error":null}'
                ),
                stderr="",
            ),
            ProcessResult(
                status="success",
                exit_code=0,
                stdout=(
                    '{"schema_version":"1.0","command":"approvals reject",'
                    '"ok":true,"generated_at":"2026-07-17T00:00:00Z",'
                    '"error":null}'
                ),
                stderr="",
            ),
            ProcessResult(
                status="success",
                exit_code=0,
                stdout=(
                    '{"schema_version":"1.0","command":"approvals retry",'
                    '"ok":true,"generated_at":"2026-07-17T00:00:00Z",'
                    '"error":null}'
                ),
                stderr="",
            ),
        ]
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    approved = client.approve_action(7, resolution="operator approved")
    rejected = client.reject_action(8, resolution="operator rejected")
    retried = client.retry_approval(9)

    assert approved.ok is True
    assert rejected.ok is True
    assert retried.ok is True
    assert runner.calls[0][0] == [
        "python",
        "-m",
        "ai_orchestrator",
        "approvals",
        "approve",
        "7",
        "--repo",
        str(resolved_repo),
        "--resolution",
        "operator approved",
        "--json",
    ]
    assert runner.calls[1][0] == [
        "python",
        "-m",
        "ai_orchestrator",
        "approvals",
        "reject",
        "8",
        "--repo",
        str(resolved_repo),
        "--resolution",
        "operator rejected",
        "--json",
    ]
    assert runner.calls[2][0] == [
        "python",
        "-m",
        "ai_orchestrator",
        "approvals",
        "retry",
        "9",
        "--repo",
        str(resolved_repo),
        "--json",
    ]


def test_local_operator_client_reports_invalid_json() -> None:
    repo = Path(".")
    runner = FakeRunner(
        ProcessResult(status="success", exit_code=0, stdout="not json", stderr="")
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.list_approvals()

    assert result.ok is False
    assert result.payload is None
    assert result.error is not None
    assert result.error.startswith("Invalid JSON output:")


def test_local_operator_client_allows_export_trace_text_output() -> None:
    repo = Path(".")
    resolved_repo = repo.resolve()
    runner = FakeRunner(
        ProcessResult(
            status="success",
            exit_code=0,
            stdout="Trace: .ai-orch/traces/task-1.json\n",
            stderr="",
        )
    )
    client = LocalOperatorClient(repo=repo, runner=runner, python_executable="python")

    result = client.export_trace("task-1")

    assert result.ok is True
    assert result.payload is None
    assert result.stdout.startswith("Trace:")
    assert runner.calls[0][0] == [
        "python",
        "-m",
        "ai_orchestrator",
        "export",
        "task-1",
        "--repo",
        str(resolved_repo),
        "--redact",
    ]


def test_local_operator_client_rejects_mismatched_repo() -> None:
    client = LocalOperatorClient(repo=Path("repo-a"), python_executable="python")

    try:
        client.run(McpAcpRequest(operation="list_approvals", repo=Path("repo-b")))
    except ValueError as exc:
        assert "request repo must match" in str(exc)
    else:
        raise AssertionError("Expected mismatched repo to be rejected")


@pytest.mark.parametrize(
    ("stdout", "expected_error"),
    [
        (
            (
                '{"schema_version":"1.0","command":"timeline","ok":true,'
                '"generated_at":"2026-07-17T00:00:00Z","error":null}'
            ),
            "Invalid JSON output: expected command 'status', got 'timeline'",
        ),
        (
            (
                '{"schema_version":"1.0","command":"status",'
                '"generated_at":"2026-07-17T00:00:00Z","error":null}'
            ),
            "Invalid JSON output: expected boolean ok, got None",
        ),
        (
            (
                '{"schema_version":"1.0","command":"status","ok":"true",'
                '"generated_at":"2026-07-17T00:00:00Z","error":null}'
            ),
            "Invalid JSON output: expected boolean ok, got 'true'",
        ),
        (
            '{"schema_version":"1.0","command":"status","ok":true,"error":null}',
            "Invalid JSON output: expected non-empty generated_at",
        ),
        (
            (
                '{"schema_version":"1.0","command":"status","ok":true,'
                '"generated_at":"2026-07-17T00:00:00Z",'
                '"error":{"code":"unexpected"}}'
            ),
            "Invalid JSON output: expected null error for successful operation",
        ),
    ],
)
def test_local_operator_client_rejects_invalid_control_envelope(
    stdout: str,
    expected_error: str,
) -> None:
    runner = FakeRunner(
        ProcessResult(status="success", exit_code=0, stdout=stdout, stderr="")
    )
    client = LocalOperatorClient(
        repo=Path("."),
        runner=runner,
        python_executable="python",
    )

    result = client.get_status("task-1")

    assert result.ok is False
    assert result.payload is not None
    assert result.error == expected_error


def test_local_operator_client_pins_repo_before_chdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    repo.mkdir()
    other.mkdir()
    monkeypatch.chdir(repo)
    runner = FakeRunner(
        ProcessResult(
            status="success",
            exit_code=0,
            stdout=(
                '{"schema_version":"1.0","command":"status","ok":true,'
                '"generated_at":"2026-07-17T00:00:00Z","error":null}'
            ),
            stderr="",
        )
    )
    client = LocalOperatorClient(
        repo=Path("."),
        runner=runner,
        python_executable="python",
    )

    monkeypatch.chdir(other)
    result = client.get_status("task-1")

    assert result.ok is True
    assert client.repo == repo.resolve()
    assert runner.calls[0][1] == repo.resolve()
    assert runner.calls[0][0] == [
        "python",
        "-m",
        "ai_orchestrator",
        "status",
        "task-1",
        "--repo",
        str(repo.resolve()),
        "--json",
    ]
