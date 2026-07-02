from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None = None


@dataclass(frozen=True)
class RunOptions:
    timeout_sec: int = 300
    terminate_grace_sec: int = 5
    should_cancel: Callable[[], bool] | None = None
    on_progress: Callable[[str], None] | None = None
    progress_label: str = "process"
    progress_interval_sec: float = 30.0
    env: dict[str, str] | None = None


class ProcessRunner:
    def check_available(self, command: str) -> bool:
        return shutil.which(os.path.expandvars(command)) is not None

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        terminate_grace_sec: int = 5,
        should_cancel: Callable[[], bool] | None = None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        if options is not None:
            timeout_sec = options.timeout_sec
            terminate_grace_sec = options.terminate_grace_sec
            should_cancel = options.should_cancel
            on_progress = options.on_progress
            progress_label = options.progress_label
            progress_interval_sec = options.progress_interval_sec
            run_env = options.env
        else:
            on_progress = None
            progress_label = "process"
            progress_interval_sec = 30.0
            run_env = None

        if not argv:
            logger.warning("event=process.empty_argv")
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error="No command provided",
            )

        run_argv = _resolve_executable(argv)
        if run_argv is None:
            logger.warning("event=process.command_not_found executable=%s", argv[0])
            return ProcessResult(
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                error=f"Command not found: {argv[0]}",
            )

        try:
            logger.debug(
                "event=process.started executable=%s argc=%s cwd=%s timeout_sec=%s",
                argv[0],
                len(argv),
                str(cwd) if cwd else None,
                timeout_sec,
            )
            process_env = None
            if run_env is not None:
                process_env = os.environ.copy()
                process_env.update(
                    {key: os.path.expandvars(value) for key, value in run_env.items()}
                )

            process = subprocess.Popen(
                run_argv,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=process_env,
            )
            if should_cancel is None and on_progress is None:
                stdout, stderr = process.communicate(timeout=timeout_sec)
            else:
                cancel_result = self._communicate_with_progress(
                    process=process,
                    argv=argv,
                    timeout_sec=timeout_sec,
                    terminate_grace_sec=terminate_grace_sec,
                    should_cancel=should_cancel,
                    on_progress=on_progress,
                    progress_label=progress_label,
                    progress_interval_sec=progress_interval_sec,
                )
                if isinstance(cancel_result, ProcessResult):
                    return cancel_result
                stdout, stderr = cancel_result
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
    def _communicate_with_progress(
        self,
        process: subprocess.Popen[str],
        argv: list[str],
        timeout_sec: int,
        terminate_grace_sec: int,
        should_cancel: Callable[[], bool] | None,
        on_progress: Callable[[str], None] | None,
        progress_label: str,
        progress_interval_sec: float,
    ) -> tuple[str, str] | ProcessResult:
        started_at = time.monotonic()
        deadline = time.monotonic() + timeout_sec
        next_progress_at = started_at + max(progress_interval_sec, 0.1)
        while True:
            if should_cancel is not None and should_cancel():
                logger.warning(
                    "event=process.cancel_requested executable=%s argc=%s",
                    argv[0],
                    len(argv),
                )
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=terminate_grace_sec)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "event=process.kill_after_cancel executable=%s argc=%s",
                        argv[0],
                        len(argv),
                    )
                    process.kill()
                    stdout, stderr = process.communicate()
                return ProcessResult(
                    status="cancelled",
                    exit_code=None,
                    stdout=stdout or "",
                    stderr=stderr or "",
                    error="Command cancelled",
                )

            now = time.monotonic()
            if on_progress is not None and now >= next_progress_at:
                elapsed_sec = int(now - started_at)
                on_progress(f"{progress_label} running for {elapsed_sec}s")
                next_progress_at = now + max(progress_interval_sec, 0.1)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout_sec)
            try:
                return process.communicate(timeout=min(0.2, remaining))
            except subprocess.TimeoutExpired:
                continue


def _resolve_executable(argv: list[str]) -> list[str] | None:
    executable = os.path.expandvars(argv[0])
    resolved = shutil.which(executable)
    if resolved is None:
        return None
    return [resolved, *argv[1:]]
