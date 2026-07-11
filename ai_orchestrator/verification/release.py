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
        repo / "docs" / "SHIPPING_PACKET_TEMPLATE.md",
        repo / "docs" / "USER_GUIDE.md",
        repo / "docs" / "V0_3_GOAL_PLAN.md",
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
        (repo / "docs" / "MAC_INSTALL.md", "macOS"),
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
            "user guide, release checklist, and shipping template present"
        ),
    )


def _relative_label(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()
