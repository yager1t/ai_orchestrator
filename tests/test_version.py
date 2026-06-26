from pathlib import Path
import tomllib

from ai_orchestrator import __version__


def test_package_version_matches_project_metadata() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == __version__
