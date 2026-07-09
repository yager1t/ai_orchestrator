from __future__ import annotations

from pathlib import Path

from ai_orchestrator import __version__
from ai_orchestrator.verification.release import run_release_checks


def test_release_checks_pass_for_minimal_release_tree(tmp_path: Path) -> None:
    write_release_tree(tmp_path)

    results = run_release_checks(tmp_path)

    assert [item.status for item in results] == ["passed", "passed", "passed", "passed"]


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


def test_release_checks_require_install_doc(tmp_path: Path) -> None:
    write_release_tree(tmp_path)
    (tmp_path / "docs" / "INSTALL.md").unlink()

    results = run_release_checks(tmp_path)

    docs_result = next(item for item in results if item.name == "release-docs")
    assert docs_result.status == "failed"
    assert "docs/INSTALL.md" in docs_result.detail


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
    changelog: str = "# Changelog\n\n## Unreleased\n\n- Demo.\n",
    include_console_script: bool = True,
) -> None:
    (repo / "ai_orchestrator" / "cli").mkdir(parents=True)
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
    (repo / "ai_orchestrator" / "cli" / "app.py").write_text("", encoding="utf-8")
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (repo / "docs" / "INSTALL.md").write_text("# Install\n", encoding="utf-8")
    (repo / "docs" / "LINUX_INSTALL.md").write_text(
        "# Linux Install\n",
        encoding="utf-8",
    )
    (repo / "docs" / "WINDOWS_INSTALL.md").write_text(
        "# Windows Install\n",
        encoding="utf-8",
    )
    (repo / "docs" / "RELEASE.md").write_text("# Release\n", encoding="utf-8")
    (repo / "docs" / "SHIPPING_PACKET_TEMPLATE.md").write_text(
        "# Shipping\n",
        encoding="utf-8",
    )
