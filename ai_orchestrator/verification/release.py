from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_orchestrator import __version__


@dataclass(frozen=True)
class ReleaseCheckResult:
    name: str
    status: str
    detail: str


def run_release_checks(repo: Path) -> list[ReleaseCheckResult]:
    pyproject_path = repo / "pyproject.toml"
    pyproject = _load_pyproject(pyproject_path)
    return [
        _check_pyproject_metadata(pyproject_path, pyproject),
        _check_version_sync(pyproject),
        _check_package_entrypoints(repo, pyproject),
        _check_release_docs(repo),
        _check_v0_8_control_surface_docs(repo),
    ]


def _load_pyproject(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None


def _check_pyproject_metadata(
    pyproject_path: Path,
    pyproject: dict[str, Any] | None,
) -> ReleaseCheckResult:
    if pyproject is None:
        return ReleaseCheckResult(
            name="pyproject",
            status="failed",
            detail=f"Missing or invalid: {pyproject_path}",
        )

    project = pyproject.get("project")
    build_system = pyproject.get("build-system")
    if not isinstance(project, dict) or not isinstance(build_system, dict):
        return ReleaseCheckResult(
            name="pyproject",
            status="failed",
            detail="Missing [project] or [build-system] metadata",
        )

    missing = [
        key
        for key in ("name", "version", "description", "requires-python")
        if not project.get(key)
    ]
    if missing:
        return ReleaseCheckResult(
            name="pyproject",
            status="failed",
            detail=f"Missing project metadata: {', '.join(missing)}",
        )
    if not build_system.get("build-backend"):
        return ReleaseCheckResult(
            name="pyproject",
            status="failed",
            detail="Missing build-system.build-backend",
        )
    return ReleaseCheckResult(
        name="pyproject",
        status="passed",
        detail=f"{project['name']} {project['version']}",
    )


def _check_version_sync(pyproject: dict[str, Any] | None) -> ReleaseCheckResult:
    project = pyproject.get("project") if pyproject is not None else None
    pyproject_version = project.get("version") if isinstance(project, dict) else None
    if pyproject_version != __version__:
        return ReleaseCheckResult(
            name="version",
            status="failed",
            detail=f"pyproject={pyproject_version or '(missing)'} package={__version__}",
        )
    return ReleaseCheckResult(
        name="version",
        status="passed",
        detail=f"package version {__version__}",
    )


def _check_package_entrypoints(
    repo: Path,
    pyproject: dict[str, Any] | None,
) -> ReleaseCheckResult:
    required_files = [
        repo / "ai_orchestrator" / "__init__.py",
        repo / "ai_orchestrator" / "__main__.py",
        repo / "ai_orchestrator" / "cli" / "app.py",
    ]
    missing = [_relative_label(path, repo) for path in required_files if not path.exists()]
    if missing:
        return ReleaseCheckResult(
            name="entrypoints",
            status="failed",
            detail=f"Missing files: {', '.join(missing)}",
        )

    project = pyproject.get("project") if pyproject is not None else None
    scripts = project.get("scripts") if isinstance(project, dict) else None
    console_script = scripts.get("ai-orch") if isinstance(scripts, dict) else None
    expected_script = "ai_orchestrator.cli.app:main"
    if console_script != expected_script:
        return ReleaseCheckResult(
            name="entrypoints",
            status="failed",
            detail=(
                "Missing project script: "
                f"ai-orch = {expected_script}"
            ),
        )
    return ReleaseCheckResult(
        name="entrypoints",
        status="passed",
        detail="python -m ai_orchestrator and ai-orch console entrypoints present",
    )


def _check_release_docs(repo: Path) -> ReleaseCheckResult:
    required_docs = [
        repo / "README.md",
        repo / "CHANGELOG.md",
        repo / "docs" / "INSTALL.md",
        repo / "docs" / "LINUX_INSTALL.md",
        repo / "docs" / "MAC_INSTALL.md",
        repo / "docs" / "ONBOARDING_GOAL_PLAN.md",
        repo / "docs" / "WINDOWS_INSTALL.md",
        repo / "docs" / "RELEASE.md",
        repo / "docs" / "RELEASE_NOTES_TEMPLATE.md",
        repo / "docs" / "SHIPPING_PACKET_TEMPLATE.md",
        repo / "docs" / "USER_GUIDE.md",
        repo / "docs" / "V0_3_GOAL_PLAN.md",
        repo / "docs" / "V0_5_GOAL_PLAN.md",
    ]
    missing = [_relative_label(path, repo) for path in required_docs if not path.exists()]
    if missing:
        return ReleaseCheckResult(
            name="release-docs",
            status="failed",
            detail=f"Missing docs: {', '.join(missing)}",
        )

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    if "## Unreleased" not in changelog:
        return ReleaseCheckResult(
            name="release-docs",
            status="failed",
            detail="CHANGELOG.md is missing an Unreleased section",
        )

    content_requirements = [
        (repo / "README.md", "ai-orch demo"),
        (repo / "README.md", "ai-orch onboard"),
        (repo / "README.md", "ai-orch fix"),
        (repo / "docs" / "INSTALL.md", "pipx"),
        (repo / "docs" / "USER_GUIDE.md", "ai-orch demo"),
        (repo / "docs" / "USER_GUIDE.md", "ai-orch onboard"),
        (repo / "docs" / "USER_GUIDE.md", "ai-orch fix"),
        (repo / "docs" / "USER_GUIDE.md", "action_journal"),
        (repo / "docs" / "V0_5_GOAL_PLAN.md", "Typed Action Broker"),
        (repo / "docs" / "MAC_INSTALL.md", "macOS"),
        (repo / "docs" / "RELEASE.md", "RELEASE_NOTES_TEMPLATE"),
        (repo / "docs" / "RELEASE_NOTES_TEMPLATE.md", "Operator impact"),
        (repo / "docs" / "RELEASE_NOTES_TEMPLATE.md", "Safety notes"),
        (repo / "docs" / "RELEASE_NOTES_TEMPLATE.md", "Full diff"),
    ]
    missing_content = [
        f"{_relative_label(path, repo)} missing {needle!r}"
        for path, needle in content_requirements
        if needle not in path.read_text(encoding="utf-8")
    ]
    if missing_content:
        return ReleaseCheckResult(
            name="release-docs",
            status="failed",
            detail=f"Missing onboarding content: {', '.join(missing_content)}",
        )
    return ReleaseCheckResult(
        name="release-docs",
        status="passed",
        detail=(
            "README, changelog, platform install guides, onboarding plan, "
            "v0.5 action broker plan, user guide, release checklist, and "
            "release-notes/shipping templates present"
        ),
    )


def _check_v0_8_control_surface_docs(repo: Path) -> ReleaseCheckResult:
    required_docs = [
        repo / "docs" / "RELEASE.md",
        repo / "docs" / "USER_GUIDE.md",
        repo / "docs" / "V0_8_GOAL_PLAN.md",
        repo / "docs" / "V0_8_JSON_CONTRACTS.md",
        repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md",
    ]
    missing = [_relative_label(path, repo) for path in required_docs if not path.exists()]
    if missing:
        return ReleaseCheckResult(
            name="v0.8-control-surface-docs",
            status="failed",
            detail=f"Missing docs: {', '.join(missing)}",
        )

    content_requirements = [
        (repo / "docs" / "V0_8_GOAL_PLAN.md", "stable control surface"),
        (repo / "docs" / "V0_8_GOAL_PLAN.md", "subagent workflow"),
        (repo / "docs" / "V0_8_GOAL_PLAN.md", "hard release stops"),
        (repo / "docs" / "V0_8_GOAL_PLAN.md", "testable p0 tasks"),
        (
            repo / "docs" / "V0_8_GOAL_PLAN.md",
            "supervisor, not the worker agent, decides done",
        ),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "stable now"),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "stable candidate"),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "experimental or internal"),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "schema_version"),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "generated_at"),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "path/redaction"),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "timeline --json"),
        (repo / "docs" / "V0_8_JSON_CONTRACTS.md", "recover --json"),
        (repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md", "start_task"),
        (repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md", "get_status"),
        (repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md", "list_approvals"),
        (repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md", "approve_action"),
        (repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md", "export_trace"),
        (repo / "docs" / "V0_8_MCP_ACP_DESIGN_SPIKE.md", "no long-running mcp server"),
        (repo / "docs" / "RELEASE.md", "v0.8 control surface gate"),
        (repo / "docs" / "RELEASE.md", "python -m pytest"),
        (repo / "docs" / "RELEASE.md", "ruff check ."),
        (repo / "docs" / "RELEASE.md", "mypy ai_orchestrator"),
        (repo / "docs" / "USER_GUIDE.md", "external local operator workflow"),
        (repo / "docs" / "USER_GUIDE.md", "ai-orch status <task-id> --repo . --json"),
        (repo / "docs" / "USER_GUIDE.md", "ai-orch approvals list --repo . --json"),
        (repo / "docs" / "USER_GUIDE.md", "ai-orch export <task-id> --repo . --redact"),
    ]
    missing_content = [
        f"{_relative_label(path, repo)} missing {needle!r}"
        for path, needle in content_requirements
        if needle.lower() not in path.read_text(encoding="utf-8").lower()
    ]
    if missing_content:
        return ReleaseCheckResult(
            name="v0.8-control-surface-docs",
            status="failed",
            detail=f"Missing v0.8 control surface content: {', '.join(missing_content)}",
        )
    return ReleaseCheckResult(
        name="v0.8-control-surface-docs",
        status="passed",
        detail=(
            "v0.8 goal plan, JSON contract inventory, release gate, and "
            "external operator workflow documented"
        ),
    )


def _relative_label(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()
