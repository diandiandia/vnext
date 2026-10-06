"""Managed, bounded harness execution with Campaign resource ownership."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable, Mapping, Sequence

try:
    import resource
except ImportError:
    resource = None

from ..campaign import CampaignManager
from ..models import ModelError
from ..resource_cleanup import (
    create_campaign_temp_directory,
    register_process_group,
    release_campaign_resource,
)


_MAX_TIMEOUT_SECONDS = 300
_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_OPEN_FILES = 64


def run_harness(
    manager: CampaignManager,
    campaign_id: str,
    *,
    command: Sequence[str],
    cwd: str = ".",
    timeout_seconds: int = 30,
    environment: Mapping[str, str] | None = None,
    output_limit_bytes: int = _MAX_OUTPUT_BYTES,
    cpu_limit_seconds: int | None = None,
    memory_limit_bytes: int | None = None,
    hypothesis_id: str | None = None,
) -> dict[str, object]:
    argv = tuple(str(item) for item in command)
    if not argv or any(not item or "\x00" in item for item in argv):
        raise ModelError("harness command must be a non-empty argv array")
    if not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise ModelError(f"harness timeout must be between 1 and {_MAX_TIMEOUT_SECONDS} seconds")
    if not 0 < output_limit_bytes <= _MAX_OUTPUT_BYTES:
        raise ModelError(f"harness output limit must be between 1 and {_MAX_OUTPUT_BYTES} bytes")
    if cpu_limit_seconds is None:
        cpu_limit_seconds = timeout_seconds
    if not 0 < cpu_limit_seconds <= _MAX_TIMEOUT_SECONDS:
        raise ModelError(f"harness CPU limit must be between 1 and {_MAX_TIMEOUT_SECONDS} seconds")
    if memory_limit_bytes is None:
        memory_limit_bytes = 2 * 1024 * 1024 * 1024
    if memory_limit_bytes <= 0:
        raise ModelError("harness memory limit must be positive")
    if resource is None:
        raise ModelError("managed harness execution requires POSIX resource limits")

    campaign = manager.store.get_campaign(campaign_id)
    target_root = Path(campaign.target_root).resolve()
    working_directory = (target_root / cwd).resolve()
    if working_directory != target_root and target_root not in working_directory.parents:
        raise ModelError("harness working directory escapes the target root")
    if not working_directory.is_dir():
        raise ModelError("harness working directory does not exist")

    runtime_directory = create_campaign_temp_directory(
        manager, campaign_id, label="R5 harness execution"
    )
    stdout_path = runtime_directory / "stdout.bin"
    stderr_path = runtime_directory / "stderr.bin"
    allowed_environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR")
        if key in os.environ
    }
    if environment:
        allowed_environment.update({str(key): str(value) for key, value in environment.items()})
    allowed_environment["VNA_HARNESS_TMP"] = str(runtime_directory)

    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    process_resource_id: str | None = None
    timed_out = False
    exit_code: int | None = None
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        try:
            process = subprocess.Popen(
                argv,
                cwd=working_directory,
                env=allowed_environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                shell=False,
                start_new_session=True,
                preexec_fn=_child_limits(
                    cpu_limit_seconds, memory_limit_bytes, output_limit_bytes
                ),
            )
            try:
                register_process_group(
                    manager, campaign_id, process.pid,
                    label=f"R5 harness: {Path(argv[0]).name}",
                )
                events = manager.store.list_events(campaign_id)
                process_resource_id = next(
                    event.entity_id for event in reversed(events)
                    if event.event_type == "RESOURCE_REGISTERED"
                    and event.payload.get("kind") == "process_group"
                    and event.payload.get("process_group_id") == process.pid
                )
            except Exception:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    raise
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                if process_resource_id is not None:
                    release_campaign_resource(
                        manager, campaign_id, process_resource_id
                    )
                elif process.poll() is None:
                    process.kill()
                process.wait()
                exit_code = process.returncode
        finally:
            if process_resource_id is not None:
                release_campaign_resource(
                    manager, campaign_id, process_resource_id
                )

    stdout = stdout_path.read_bytes()
    stderr = stderr_path.read_bytes()
    stdout_truncated = len(stdout) > output_limit_bytes
    stderr_truncated = len(stderr) > output_limit_bytes
    output_limit_exceeded = (
        (len(stdout) >= output_limit_bytes or len(stderr) >= output_limit_bytes)
        and exit_code not in {0, None}
    )
    stdout_artifact = manager.artifacts.put_bytes(stdout[:output_limit_bytes])
    stderr_artifact = manager.artifacts.put_bytes(stderr[:output_limit_bytes])
    result: dict[str, object] = {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "snapshot_id": campaign.snapshot_id,
        "hypothesis_id": hypothesis_id,
        "empirical_upgrade_eligible": hypothesis_id is not None,
        "empirical_upgrade_note": (
            None if hypothesis_id is not None
            else "no hypothesis_id was supplied; this run cannot support an R5 empirical upgrade"
        ),
        "command": list(argv),
        "working_directory": working_directory.relative_to(target_root).as_posix() or ".",
        "timeout_seconds": timeout_seconds,
        "resource_limits": {
            "cpu_seconds": cpu_limit_seconds,
            "address_space_bytes": memory_limit_bytes,
            "file_size_bytes_per_stream": output_limit_bytes,
            "open_files": _MAX_OPEN_FILES,
            "core_dump_bytes": 0,
        },
        "duration_seconds": round(time.monotonic() - started, 6),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_artifact_id": stdout_artifact.artifact_id,
        "stdout_truncated": stdout_truncated,
        "stderr_artifact_id": stderr_artifact.artifact_id,
        "stderr_truncated": stderr_truncated,
        "output_limit_exceeded": output_limit_exceeded,
        "runtime_directory_ref": runtime_directory.relative_to(manager.state_dir).as_posix(),
        "observed_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    execution_artifact = manager.artifacts.put_text(json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ))
    manager.store.append_event(
        campaign_id=campaign_id,
        batch_id=None,
        entity_type="harness_execution",
        entity_id=execution_artifact.artifact_id,
        event_type="HARNESS_EXECUTION_COMPLETED",
        idempotency_key=f"harness-execution:{campaign_id}:{execution_artifact.artifact_id}",
        actor="tool",
        payload={
            "snapshot_id": campaign.snapshot_id,
            "hypothesis_id": hypothesis_id,
            "stdout_artifact_id": stdout_artifact.artifact_id,
            "stderr_artifact_id": stderr_artifact.artifact_id,
        },
        payload_ref=execution_artifact.artifact_id,
    )
    return {**result, "execution_artifact_id": execution_artifact.artifact_id}


def _child_limits(
    cpu_seconds: int,
    memory_bytes: int,
    output_bytes: int,
) -> Callable[[], None]:
    def apply() -> None:
        assert resource is not None
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (_MAX_OPEN_FILES, _MAX_OPEN_FILES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    return apply