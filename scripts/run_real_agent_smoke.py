from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the real generic_cli smoke fixture through ai-orch.",
    )
    parser.add_argument(
        "--fixture",
        default="examples/real_agent_smoke",
        help="Fixture repo to copy before running the smoke test.",
    )
    parser.add_argument(
        "--task",
        default="Run the real-agent smoke fixture and stop after verification.",
        help="Task text passed to ai-orch start.",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep the copied fixture directory for inspection.",
    )
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[1]
    fixture = (project_root / args.fixture).resolve()
    if not fixture.exists():
        print(f"Fixture not found: {fixture}", file=sys.stderr)
        return 1

    temp_root = Path(tempfile.mkdtemp(prefix="ai-orch-real-agent-smoke-"))
    smoke_repo = temp_root / "repo"
    shutil.copytree(fixture, smoke_repo)

    command = [
        sys.executable,
        "-m",
        "ai_orchestrator",
        "start",
        "--repo",
        str(smoke_repo),
        "--task",
        args.task,
    ]
    print(f"Smoke repo: {smoke_repo}")
    print(f"Command: {' '.join(command)}")
    result = subprocess.run(
        command,
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)

    if result.returncode != 0:
        print(f"Smoke run failed with exit code {result.returncode}", file=sys.stderr)
        if args.keep_workdir:
            print(f"Kept smoke repo: {smoke_repo}")
        return result.returncode

    print("Real-agent smoke run passed.")
    if args.keep_workdir:
        print(f"Kept smoke repo: {smoke_repo}")
    else:
        shutil.rmtree(temp_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
