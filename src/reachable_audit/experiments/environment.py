"""Explicit, bounded toolchain probes; never execute through a shell."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import subprocess
from typing import Mapping, Sequence

from ..models import ModelError


@dataclass(frozen=True)
class ToolchainProbeResult:
    command: tuple[str, ...]
    available: bool
    exit_code: int | None
    output: str
    timed_out: bool


def probe_toolchain(
    command: str | Sequence[str],
    *,
    timeout_seconds: float = 5.0,
    environment: Mapping[str, str] | None = None,
) -> ToolchainProbeResult:
    argv = tuple(shlex.split(command) if isinstance(command, str) else command)
    if not argv or timeout_seconds <= 0:
        raise ModelError("toolchain probe requires a command and positive timeout")
    allowed = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR")
        if key in os.environ
    }
    if environment:
        allowed.update({str(key): str(value) for key, value in environment.items()})
    try:
        result = subprocess.run(
            argv,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=allowed,
        )
    except FileNotFoundError:
        return ToolchainProbeResult(argv, False, None, "executable not found", False)
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return ToolchainProbeResult(argv, True, None, str(output)[:4096], True)
    combined = (result.stdout + result.stderr)[:4096]
    return ToolchainProbeResult(argv, result.returncode == 0, result.returncode, combined, False)