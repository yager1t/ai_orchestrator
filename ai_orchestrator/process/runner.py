from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None = None


class ProcessRunner:
    def check_available(self, command: str) -> bool:
        return shutil.which(command) is not None

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
    ) -> ProcessResult:
        if not argv:
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error="No command provided",
            )

        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except FileNotFoundError:
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error=f"Command not found: {argv[0]}",
            )
        except subprocess.TimeoutExpired as exc:
            return ProcessResult(
                status="timeout",
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                error=f"Command timed out after {timeout_sec}s",
            )

        return ProcessResult(
            status="success" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
