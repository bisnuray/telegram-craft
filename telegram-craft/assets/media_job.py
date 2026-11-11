"""Run a media conversion safely from an async bot (standard library only).

Copy and adapt. It provides a per-job directory that is always removed, a global
concurrency cap, a wall-clock timeout that kills the whole process group, an
output-size check, and argv-only subprocess calls.

Requires FFmpeg on PATH when used with ffmpeg.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path


class MediaJobError(Exception):
    """Conversion failed. `user_message` is safe to show; details are for logs."""

    def __init__(self, user_message: str, detail: str = "") -> None:
        super().__init__(detail or user_message)
        self.user_message = user_message


@contextlib.asynccontextmanager
async def job_workspace(root: str | os.PathLike[str] | None = None) -> AsyncIterator[Path]:
    """Yield a private directory and delete it on success, error, or cancellation."""
    path = Path(tempfile.mkdtemp(prefix="tgjob-", dir=root))
    try:
        yield path
    finally:
        # Blocking delete of a large tree must not stall the event loop.
        await asyncio.shield(asyncio.to_thread(shutil.rmtree, path, True))


async def run_tool(
    argv: Sequence[str],
    limiter: asyncio.Semaphore,
    timeout_seconds: float = 300,
    cwd: str | os.PathLike[str] | None = None,
) -> str:
    """Run argv with no shell. Return stderr tail; raise MediaJobError on failure.

    Share one `limiter` across the process: size it from CPU cores, because
    every encode is CPU-bound and queueing beats oversubscribing.
    """
    async with limiter:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so children die too
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
        except asyncio.TimeoutError as exc:
            _kill_group(process)
            await process.wait()
            raise MediaJobError("That took too long, so I stopped it.", "timeout") from exc
        except asyncio.CancelledError:
            _kill_group(process)
            await process.wait()
            raise

    tail = stderr.decode(errors="replace")[-2000:]
    if process.returncode != 0:
        raise MediaJobError("I couldn't process that file.", f"exit {process.returncode}: {tail}")
    return tail


def _kill_group(process: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


def ffmpeg_to_voice_argv(source: Path, target: Path, max_seconds: int = 3600) -> list[str]:
    """Build argv for OGG/Opus, the format Telegram renders as a voice message.

    `-protocol_whitelist file,pipe` stops a crafted playlist from making FFmpeg
    fetch URLs or read other local files. Keep it on untrusted input.
    """
    return [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-protocol_whitelist", "file,pipe",
        "-i", str(source),
        "-t", str(max_seconds),
        "-vn", "-map_metadata", "-1",
        "-c:a", "libopus", "-b:a", "64k", "-ac", "1", "-ar", "48000",
        str(target),
    ]


def assert_uploadable(path: Path, limit_bytes: int = 50_000_000) -> int:
    """Raise a user-safe error if the output exceeds the cloud Bot API upload limit."""
    if not path.is_file() or path.stat().st_size == 0:
        raise MediaJobError("I couldn't process that file.", f"no output at {path}")
    size = path.stat().st_size
    if size > limit_bytes:
        raise MediaJobError(
            f"The result is {size / 1_000_000:.0f} MB, over the {limit_bytes // 1_000_000} MB limit."
            " Try a shorter clip.",
            "output too large",
        )
    return size
