from __future__ import annotations

from pathlib import Path

from ai_orchestrator import __version__
from ai_orchestrator.verification.release import run_release_checks


def test_release_checks_pass_for_minimal_release_tree(tmp_path: Path) -> None:
    write_release_tree(tmp_path)

    results = run_release_checks(tmp_path)

    assert [item.status for item in results] == [
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
    ]


def test_release_checks_report_version_mismatch(tmp_path: Path) -> None:
    write_release_tree(tmp_path, version="9.9.9")

    results = run_release_checks(tmp_path)

    version_result = next(item for item in results if item.name == "version")
    assert version_result.status == "failed"
    assert f"package={__version__}" in version_result.detail


def test_release_checks_require_unreleased_changelog_section(tmp_path: Path) -> None:
    write_release_tree(tmp_path, changelog="# Changelog\n\n## 0.1.0\n")

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "Unreleased" in docs_result.detail


def test_release_checks_require_console_script(tmp_path: Path) -> None:
    write_release_tree(tmp_path, include_console_script=False)

    results = run_release_checks(tmp_path)

    entrypoint_result = next(item for item in results if item.name == "entrypoints")
    assert entrypoint_result.status == "failed"
    assert "ai-orch" in entrypoint_result.detail


def test_release_checks_require_packaged_install_smoke(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / ".github" / "workflows" / "ci.yml").unlink()

    results = run_release_checks(tmp_path)

    smoke_result = next(
        item for item in results if item.name == "packaged-install-smoke"
    )
    assert smoke_result.status == "failed"
    assert ".github/workflows/ci.yml" in smoke_result.detail


def test_release_checks_require_packaged_install_smoke_no_deps(
    tmp_path: Path,
) -> None:
    write_release_tree(tmp_path)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\n\njobs:\n  test:\n    steps:\n      - name: Packaged install smoke\n",
        encoding="utf-8",
    )

    results = run_release_checks(tmp_path)

    smoke_result = next(
        item for item in results if item.name == "packaged-install-smoke"
    )
    assert smoke_result.status == "failed"
    assert "--no-deps" in smoke_result.detail


def test_release_checks_require_install_doc(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "INSTALL.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "docs/INSTALL.md" in docs_result.detail


def test_release_checks_require_release_notes_template(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "RELEASE_NOTES_TEMPLATE.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "docs/RELEASE_NOTES_TEMPLATE.md" in docs_result.detail


def test_release_checks_require_windows_install_doc(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "WINDOWS_INSTALL.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "docs/WINDOWS_INSTALL.md" in docs_result.detail


def test_release_checks_require_linux_install_doc(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "LINUX_INSTALL.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "docs/LINUX_INSTALL.md" in docs_result.detail


def test_release_checks_require_mac_install_doc(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "MAC_INSTALL.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "docs/MAC_INSTALL.md" in docs_result.detail


def test_release_checks_require_onboarding_content(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "INSTALL.md").write_text("# Install\n", encoding="utf-8")

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "pipx" in docs_result.detail


def test_release_checks_require_v0_8_goal_plan(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "V0_8_GOAL_PLAN.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v0.8-control-surface-docs"
    )
    assert docs_result.status == "failed"
    assert "docs/V0_8_GOAL_PLAN.md" in docs_result.detail


def test_release_checks_require_v0_8_json_contracts(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "V0_8_JSON_CONTRACTS.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v0.8-control-surface-docs"
    )
    assert docs_result.status == "failed"
    assert "docs/V0_8_JSON_CONTRACTS.md" in docs_result.detail


def test_release_checks_require_v0_8_mcp_acp_design_spike(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v0.8-control-surface-docs"
    )
    assert docs_result.status == "failed"
    assert "docs/V0_8_MCP_ACP_DESIGN_SPIKE.md" in docs_result.detail


def test_release_checks_v0_8_gate_reports_missing_user_guide(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "USER_GUIDE.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v0.8-control-surface-docs"
    )
    assert docs_result.status == "failed"
    assert "docs/USER_GUIDE.md" in docs_result.detail


def test_release_checks_require_v0_8_control_surface_content(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "V0_8_JSON_CONTRACTS.md").write_text(
        "# v0.8 JSON Contract Inventory\n",
        encoding="utf-8",
    )

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v0.8-control-surface-docs"
    )
    assert docs_result.status == "failed"
    assert "stable now" in docs_result.detail


def test_release_checks_require_v0_9_goal_plan(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "V0_9_GOAL_PLAN.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v0.9-operator-compatibility-docs"
    )
    assert docs_result.status == "failed"
    assert "docs/V0_9_GOAL_PLAN.md" in docs_result.detail


def test_release_checks_require_v0_9_operator_compatibility_content(
    tmp_path: Path,
) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "V0_9_GOAL_PLAN.md").write_text(
        "# v0.9 Goal Plan\n",
        encoding="utf-8",
    )

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v0.9-operator-compatibility-docs"
    )
    assert docs_result.status == "failed"
    assert "local operator compatibility" in docs_result.detail


def test_release_checks_require_v1_0_goal_plan(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "V1_0_GOAL_PLAN.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v1.0-local-operator-client-docs"
    )
    assert docs_result.status == "failed"
    assert "docs/V1_0_GOAL_PLAN.md" in docs_result.detail


def test_release_checks_require_v1_0_local_operator_client_content(
    tmp_path: Path,
) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "ai_orchestrator" / "control" / "client.py").write_text(
        "# local client placeholder\n",
        encoding="utf-8",
    )

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v1.0-local-operator-client-docs"
    )
    assert docs_result.status == "failed"
    assert "LocalOperatorClient" in docs_result.detail


def test_release_checks_require_v1_0_changelog_content(tmp_path: Path) -> None:
    write_release_tree(tmp_path, changelog="# Changelog\n\n## Unreleased\n\n- Demo.\n")

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v1.0-local-operator-client-docs"
    )
    assert docs_result.status == "failed"
    assert "stable local operator client" in docs_result.detail


def test_release_checks_require_v1_0_runtime_proposal_content(
    tmp_path: Path,
) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "MCP_ACP_RESEARCH.md").write_text(
        "# MCP / ACP research notes\n",
        encoding="utf-8",
    )

    results = run_release_checks(tmp_path)

    docs_result = next(
        item for item in results if item.name == "v1.0-local-operator-client-docs"
    )
    assert docs_result.status == "failed"
    assert "v1.0 future runtime proposal draft" in docs_result.detail


def test_windows_installer_scripts_are_safe_repo_helpers() -> None:
    repo = Path(__file__).resolve().parents[1]
    ps1 = repo / "scripts" / "install_windows.ps1"
    cmd = repo / "scripts" / "install_windows.cmd"
    root_installer = repo / "INSTALL_WINDOWS.cmd"
    launcher = repo / "ai-orch.cmd"
    linux_root_installer = repo / "INSTALL_LINUX.sh"
    linux_installer = repo / "scripts" / "install_linux.sh"

    assert ps1.exists()
    assert cmd.exists()
    assert root_installer.exists()
    assert launcher.exists()
    assert linux_root_installer.exists()
    assert linux_installer.exists()
    combined = (
        ps1.read_text(encoding="utf-8")
        + "\n"
        + cmd.read_text(encoding="utf-8")
        + "\n"
        + root_installer.read_text(encoding="utf-8")
        + "\n"
        + launcher.read_text(encoding="utf-8")
        + "\n"
        + linux_root_installer.read_text(encoding="utf-8")
        + "\n"
        + linux_installer.read_text(encoding="utf-8")
    )
    assert "pause" in combined
    assert "/nopause" in combined
    assert "/install-python" in combined
    assert "Python.Python.3.12" in combined
    assert "Install Python 3.12 now" in combined
    assert "INSTALL_WINDOWS.cmd" in combined
    assert "INSTALL_LINUX.sh" in combined
    assert "python3.12-venv" in combined
    assert "KeepConfig" in combined
    assert "install-logs" in combined
    assert ".venv" in combined
    assert "PATH" in combined
    assert "Common commands" in combined
    assert "state" in combined
    assert "reports" in combined
    assert "setup" in combined
    assert "doctor" in combined
    assert "OPENAI_API_KEY" not in combined
    assert "ANTHROPIC_API_KEY" not in combined
    assert "Remove-Item" not in combined


def write_release_tree(
    repo: Path,
    version: str = __version__,
    changelog: str = (
        "# Changelog\n\n"
        "## Unreleased\n\n"
        "- Added the stable local operator client.\n"
    ),
    include_console_script: bool = True,
) -> None:
    (repo / "ai_orchestrator" / "cli").mkdir(parents=True)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "docs").mkdir()
    scripts_section = (
        """
[project.scripts]
ai-orch = "ai_orchestrator.cli.app:main"
"""
        if include_console_script
        else ""
    )
    (repo / "pyproject.toml").write_text(
        f"""
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-orchestrator"
version = "{version}"
description = "Local supervisor orchestrator for CLI AI agents"
requires-python = ">=3.12"
{scripts_section}
""".strip(),
        encoding="utf-8",
    )
    (repo / "ai_orchestrator" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "ai_orchestrator" / "__main__.py").write_text("", encoding="utf-8")
    (repo / "ai_orchestrator" / "cli" / "app.py").write_text(
        "def start(json_output=False):\n    pass\n",
        encoding="utf-8",
    )
    (repo / ".github" / "workflows" / "ci.yml").write_text(
        (
            "name: CI\n\n"
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - name: Packaged install smoke\n"
            "        run: |\n"
            "          python -m venv .package-smoke-venv\n"
            "          .package-smoke-venv/bin/python -m pip install . --no-deps\n"
            "          .package-smoke-venv/bin/ai-orch --version\n"
            "          .package-smoke-venv/bin/ai-orch --help\n"
        ),
        encoding="utf-8",
    )
    (repo / "ai_orchestrator" / "control").mkdir()
    (repo / "ai_orchestrator" / "control" / "__init__.py").write_text(
        "from .client import LocalOperatorClient, LocalOperatorResult\n",
        encoding="utf-8",
    )
    (repo / "ai_orchestrator" / "control" / "mcp_acp.py").write_text(
        (
            "# Boundary\n"
            "This module does not run commands or start a server.\n"
            "def cli_args_for_operation():\n"
            "    task = 'demo'\n"
            "    repo_args = []\n"
            "    return [\"start\", \"--task\", task, *repo_args, \"--json\"]\n"
            "    pass\n"
        ),
        encoding="utf-8",
    )
    (repo / "ai_orchestrator" / "control" / "client.py").write_text(
        (
            "class LocalOperatorResult:\n"
            "    pass\n\n"
            "class LocalOperatorClient:\n"
            "    module = 'ai_orchestrator'\n"
            "    error = 'Invalid JSON output'\n"
            "    def __post_init__(self):\n"
            "        pass\n"
            "    expected_command = 'expected command'\n"
            "    expected_ok = 'expected boolean ok'\n"
            "    expected_generated_at = 'expected non-empty generated_at'\n"
        ),
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_cli.py").write_text(
        (
            "def assert_control_envelope():\n"
            "    pass\n\n"
            "def test_external_local_operator_smoke_reads_control_surface():\n"
            "    pass\n\n"
            "def test_start_json_emits_control_envelope():\n"
            "    pass\n\n"
            "def test_start_json_reports_missing_config():\n"
            "    pass\n\n"
            "def test_start_json_blocks_invalid_worktree_before_execution():\n"
            "    pass\n"
        ),
        encoding="utf-8",
    )
    (repo / "tests" / "test_local_operator_client.py").write_text(
        (
            "def test_local_operator_client_parses_control_json():\n"
            "    pass\n\n"
            "def test_local_operator_client_starts_task_with_control_json():\n"
            "    pass\n\n"
            "def test_local_operator_client_preserves_start_payload_on_nonzero_exit():\n"
            "    pass\n\n"
            "def test_local_operator_client_approval_methods_parse_control_json():\n"
            "    pass\n\n"
            "def test_local_operator_client_reports_process_failure():\n"
            "    pass\n\n"
            "def test_local_operator_client_reports_invalid_json():\n"
            "    pass\n\n"
            "def test_local_operator_client_allows_export_trace_text_output():\n"
            "    pass\n"
            "def test_local_operator_client_rejects_invalid_control_envelope():\n"
            "    pass\n"
            "def test_local_operator_client_pins_repo_before_chdir():\n"
            "    pass\n"
        ),
        encoding="utf-8",
    )
    (repo / "tests" / "test_mcp_acp_boundary.py").write_text(
        (
            "def test_mcp_acp_boundary_maps_operations_to_cli_json_contracts():\n"
            "    pass\n"
        ),
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# Demo\n\nRun `ai-orch demo`, `ai-orch onboard`, and `ai-orch fix`.\n",
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (repo / "docs" / "INSTALL.md").write_text(
        "# Install\n\nUse `pipx install ai-orchestrator`.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "LINUX_INSTALL.md").write_text(
        "# Linux Install\n",
        encoding="utf-8",
    )
    (repo / "docs" / "MAC_INSTALL.md").write_text(
        "# macOS Install\n",
        encoding="utf-8",
    )
    (repo / "docs" / "MCP_ACP_RESEARCH.md").write_text(
        (
            "# MCP / ACP research notes\n\n"
            "## v1.0 future runtime proposal draft\n\n"
            "Status: draft / documentation-only / no implementation.\n"
            "Future protocol operations preserve policy deny precedence.\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "ONBOARDING_GOAL_PLAN.md").write_text(
        "# Onboarding Goal Plan\n",
        encoding="utf-8",
    )
    (repo / "docs" / "V0_3_GOAL_PLAN.md").write_text(
        "# v0.3 Goal Plan\n",
        encoding="utf-8",
    )
    (repo / "docs" / "V0_5_GOAL_PLAN.md").write_text(
        "# v0.5 Typed Action Broker Goal Plan\n",
        encoding="utf-8",
    )
    (repo / "docs" / "WINDOWS_INSTALL.md").write_text(
        "# Windows Install\n",
        encoding="utf-8",
    )
    (repo / "docs" / "RELEASE.md").write_text(
        (
            "# Release\n\n"
            "Use `docs/RELEASE_NOTES_TEMPLATE.md` before publishing.\n\n"
            "## v0.8 Control Surface Gate\n\n"
            "Run `python -m pytest`, `python -m compileall ai_orchestrator`, "
            "`ruff check .`, `mypy ai_orchestrator`, "
            "`python -m ai_orchestrator release-check --repo .`, and "
            "`git diff --check`.\n\n"
            "## v0.9 Operator Compatibility Gate\n\n"
            "Confirm the v0.8 JSON compatibility tests, local operator smoke, "
            "and MCP/ACP adapter boundary before tagging.\n"
            "\n"
            "## v1.0 Stable Local Operator Client Gate\n\n"
            "Confirm the stable local operator client, focused tests, and "
            "operator workflow docs before tagging.\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "SHIPPING_PACKET_TEMPLATE.md").write_text(
        "# Shipping\n",
        encoding="utf-8",
    )
    (repo / "docs" / "RELEASE_NOTES_TEMPLATE.md").write_text(
        (
            "# GitHub Release Notes Template\n\n"
            "## vX.Y.Z - Short Release Theme\n\n"
            "### Operator impact\n\n"
            "### Safety notes\n\n"
            "Full diff: https://github.com/yager1t/ai_orchestrator/compare/"
            "vPREVIOUS...vX.Y.Z\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "USER_GUIDE.md").write_text(
        (
            "# User Guide\n\nRun `ai-orch demo`, `ai-orch onboard`, and "
            "`ai-orch fix`. Trace exports include `action_journal`.\n\n"
            "## External Local Operator Workflow\n\n"
            "Use `ai-orch start --task \"Demo\" --repo . --json`, "
            "`ai-orch status <task-id> --repo . --json`, "
            "`ai-orch approvals list --repo . --json`, and "
            "`ai-orch export <task-id> --repo . --redact`. Run the local "
            "operator smoke before release. Python integrations may use "
            "`LocalOperatorClient` for this external local operator workflow.\n"
            "Example payload includes \"command\": \"start\".\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "V0_8_GOAL_PLAN.md").write_text(
        (
            "# v0.8 Goal Plan\n\n"
            "Stable control surface. Subagent workflow. Hard release stops. "
            "Testable P0 Tasks. The supervisor, not the worker agent, decides done.\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "V0_8_JSON_CONTRACTS.md").write_text(
        (
            "# v0.8 JSON Contract Inventory\n\n"
            "Stable Now. Stable candidate. Experimental or internal. "
            "`schema_version`, `command`, `generated_at`, `ok`, `error`. "
            "Path/redaction policy. `export`, `timeline --json`, `recover --json`.\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md").write_text(
        (
            "# v0.8 MCP/ACP Design Spike\n\n"
            "start_task, get_status, list_approvals, approve_action, "
            "export_trace. No long-running MCP server.\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "V0_9_GOAL_PLAN.md").write_text(
        (
            "# v0.9 Goal Plan: Local Operator Compatibility\n\n"
            "v0.8 JSON compatibility. External local operator integration "
            "smoke. MCP/ACP adapter boundary. No long-running server. "
            "The supervisor decides done.\n"
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "V1_0_GOAL_PLAN.md").write_text(
        (
            "# v1.0 Goal Plan: Stable Local Operator Client\n\n"
            "Stable local operator client. No-server MCP/ACP readiness. "
            "The supervisor decides done. No direct state-store mutation.\n"
        ),
        encoding="utf-8",
    )
