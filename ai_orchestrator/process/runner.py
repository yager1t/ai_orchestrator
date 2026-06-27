from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


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
            logger.warning("process runner rejected empty argv")
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error="No command provided",
            )

        try:
            logger.debug(
                "running process executable=%s argc=%s cwd=%s timeout_sec=%s",
                argv[0],
                len(argv),
                str(cwd) if cwd else None,
                timeout_sec,
            )
            completed = subprocess.run(
                argv,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("process command not found: %s", argv[0])
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error=f"Command not found: {argv[0]}",
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning(
                "process timed out executable=%s argc=%s timeout_sec=%s",
                argv[0],
                len(argv),
                timeout_sec,
            )
            return ProcessResult(
                status="timeout",
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                error=f"Command timed out after {timeout_sec}s",
            )

        logger.debug(
            "process exited executable=%s argc=%s exit_code=%s",
            argv[0],
            len(argv),
            completed.returncode,
        )
        return ProcessResult(
            status="success" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
