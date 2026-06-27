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
        terminate_grace_sec: int = 5,
    ) -> ProcessResult:
        if not argv:
            logger.warning("event=process.empty_argv")
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error="No command provided",
            )

        try:
            logger.debug(
                "event=process.started executable=%s argc=%s cwd=%s timeout_sec=%s",
                argv[0],
                len(argv),
                str(cwd) if cwd else None,
                timeout_sec,
            )
            process = subprocess.Popen(
                argv,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=timeout_sec)
        except FileNotFoundError:
            logger.warning("event=process.command_not_found executable=%s", argv[0])
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error=f"Command not found: {argv[0]}",
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "event=process.timed_out executable=%s argc=%s timeout_sec=%s",
                argv[0],
                len(argv),
                timeout_sec,
            )
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=terminate_grace_sec)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "event=process.kill_after_timeout executable=%s argc=%s",
                    argv[0],
                    len(argv),
                )
                process.kill()
                stdout, stderr = process.communicate()
            return ProcessResult(
                status="timeout",
                exit_code=None,
                stdout=stdout or "",
                stderr=stderr or "",
                error=f"Command timed out after {timeout_sec}s",
            )
        except KeyboardInterrupt:
            logger.warning("event=process.interrupted executable=%s argc=%s", argv[0], len(argv))
            process.terminate()
            try:
                process.communicate(timeout=terminate_grace_sec)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "event=process.kill_after_interrupt executable=%s argc=%s",
                    argv[0],
                    len(argv),
                )
                process.kill()
                process.communicate()
            raise

        logger.debug(
            "event=process.exited executable=%s argc=%s exit_code=%s",
            argv[0],
            len(argv),
            process.returncode,
        )
        return ProcessResult(
            status="success" if process.returncode == 0 else "failed",
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
