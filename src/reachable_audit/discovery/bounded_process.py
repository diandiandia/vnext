"""Shared POSIX process boundary for trusted, offline parser helpers."""

from __future__ import annotations

import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
from typing import Callable
import uuid

if os.name == "posix":
    import resource


def create_workspace(prefix: str, target_root: Path | None = None) -> Path:
    excluded = [Path.cwd().resolve()]
    if target_root is not None:
        excluded.append(target_root.resolve())
    for candidate in (Path("/tmp"), Path("/var/tmp")):
        base = candidate.resolve()
        if base.is_dir() and not any(base.is_relative_to(root) for root in excluded):
            return Path(tempfile.mkdtemp(prefix=prefix, dir=base))
    raise OSError("no private parser temporary directory outside target and working directory")


def child_limits() -> None:
    for kind, limit in (
        (resource.RLIMIT_CPU, 60),
        (resource.RLIMIT_AS, 4 * 1024**3),
        (resource.RLIMIT_FSIZE, 64 * 1024**2),
        (resource.RLIMIT_NOFILE, 128),
        (resource.RLIMIT_CORE, 0),
    ):
        soft, hard = resource.getrlimit(kind)
        if soft != resource.RLIM_INFINITY:
            limit = min(limit, soft)
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        resource.setrlimit(kind, (limit, limit))


def run_bounded(
    command: list[str], workspace: Path, input_bytes: bytes, timeout: int,
    *, environment: dict[str, str], child_limits: Callable[[], None],
    error_type: type[Exception], label: str, output_limit: int,
) -> bytes:
    """Drain both pipes under one output/deadline cap; always reap the group."""
    input_path = workspace / f"request-{uuid.uuid4().hex}.json"
    try:
        input_path.write_bytes(input_bytes)
        with input_path.open("rb") as stdin:
            process = subprocess.Popen(
                command, cwd=workspace, env=environment, stdin=stdin,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                start_new_session=True, preexec_fn=child_limits,
            )
        output = bytearray()
        size = 0
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                assert process.stdout is not None and process.stderr is not None
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise error_type(f"{label} helper timed out")
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        size += len(chunk)
                        if size > output_limit:
                            raise error_type(f"{label} helper output limit exceeded")
                        if key.data:
                            output.extend(chunk)
                try:
                    status = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as error:
                    raise error_type(f"{label} helper timed out") from error
                if status:
                    raise error_type(f"{label} helper exited with status {status}")
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        return bytes(output)
    finally:
        input_path.unlink(missing_ok=True)
