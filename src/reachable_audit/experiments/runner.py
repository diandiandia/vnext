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
from ..models import ModelError, dynamic_execution_policy
from ..resource_cleanup import (
    create_campaign_temp_directory,
    register_process_group,
    release_campaign_resource,
)


_MAX_TIMEOUT_SECONDS = 300
_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_OPEN_FILES = 64
_MAX_PROVENANCE_ARTIFACTS = 32

_EXECUTION_ORIGINS = {
    "target_tree",
    "same_snapshot_build",
    "other_build",
    "mechanism_only",
}


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
    profile: str | None = None,
    execution_provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run explicit argv under bounded resources and record optional execution provenance.

    ``go-offline`` opts into private, offline Go build settings. ``jvm-bounded``
    raises the default address-space limit to 4 GiB for JVM startup; callers
    remain responsible for explicit JVM heap limits. Neither profile is an OS
    network sandbox. Optional execution provenance is an operator declaration
    backed by content-addressed artifacts, not proof that the command used them.
    Selecting a profile does not grant permission to execute target code.
    Eligibility means complete, hypothesis-bound capture with declared provenance,
    not a confirmed result; nonzero exits may represent intentional crash observations.
    """
    campaign = manager.store.get_campaign(campaign_id)
    if dynamic_execution_policy(campaign) == "STATIC_ONLY":
        raise ModelError("static-only Campaign forbids dynamic execution, including managed harnesses")
    if profile not in {None, "go-offline", "jvm-bounded"}:
        raise ModelError("unknown harness profile")
    normalized_provenance = validate_execution_provenance(
        manager, campaign.snapshot_id, execution_provenance
    )
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
        memory_limit_bytes = (
            8 if profile == "go-offline" else
            4 if profile == "jvm-bounded" else 2
        ) * 1024**3
    if memory_limit_bytes <= 0:
        raise ModelError("harness memory limit must be positive")
    if resource is None:
        raise ModelError("managed harness execution requires POSIX resource limits")

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
    if profile == "go-offline":
        # Keep every compiler cache and temporary file Campaign-owned.
        directories = {
            key: runtime_directory / name
            for key, name in (
                ("HOME", "home"), ("GOCACHE", "go-cache"), ("GOPATH", "go-path"),
                ("TMPDIR", "go-tmp"), ("GOTMPDIR", "go-tmp"),
            )
        }
        for directory in directories.values():
            directory.mkdir(exist_ok=True)
        allowed_environment.update({key: str(path) for key, path in directories.items()})
        allowed_environment.update({
            "GOENV": "off", "GOTOOLCHAIN": "local", "GOPROXY": "off",
            "GOSUMDB": "off", "GOTELEMETRY": "off", "GOWORK": "off",
            "GO111MODULE": "off", "GOFLAGS": "", "CGO_ENABLED": "0",
            "GOMAXPROCS": "2", "GOMEMLIMIT": "256MiB",
        })
    allowed_environment["VNA_HARNESS_TMP"] = str(runtime_directory)
    file_size_limit_bytes = 64 * 1024**2 if profile == "go-offline" else output_limit_bytes

    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    process_resource_id: str | None = None
    timed_out = False
    output_limit_exceeded = False
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
                    cpu_limit_seconds, memory_limit_bytes, file_size_limit_bytes
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
                if profile == "go-offline":
                    deadline = time.monotonic() + timeout_seconds
                    while process.poll() is None:
                        if max(stdout_path.stat().st_size, stderr_path.stat().st_size) > output_limit_bytes:
                            output_limit_exceeded = True
                            break
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(argv, timeout_seconds)
                        time.sleep(0.01)
                    if output_limit_exceeded:
                        assert process_resource_id is not None
                        release_campaign_resource(manager, campaign_id, process_resource_id)
                    exit_code = process.wait()
                else:
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

    with stdout_path.open("rb") as stream:
        stdout = stream.read(output_limit_bytes + 1)
    with stderr_path.open("rb") as stream:
        stderr = stream.read(output_limit_bytes + 1)
    stdout_truncated = len(stdout) > output_limit_bytes
    stderr_truncated = len(stderr) > output_limit_bytes
    output_limit_exceeded = output_limit_exceeded or stdout_truncated or stderr_truncated or (
        (len(stdout) >= output_limit_bytes or len(stderr) >= output_limit_bytes)
        and exit_code not in {0, None}
    )
    eligibility_notes = []
    if hypothesis_id is None:
        eligibility_notes.append(
            "no hypothesis_id was supplied; this run cannot support an R5 empirical upgrade"
        )
    if normalized_provenance is None or normalized_provenance["origin"] == "mechanism_only":
        eligibility_notes.append(
            "execution provenance is missing or mechanism-only"
        )
    if timed_out:
        eligibility_notes.append("timed out execution cannot support an R5 empirical upgrade")
    if output_limit_exceeded:
        eligibility_notes.append(
            "output-limited execution cannot support an R5 empirical upgrade"
        )
    stdout_artifact = manager.artifacts.put_bytes(stdout[:output_limit_bytes])
    stderr_artifact = manager.artifacts.put_bytes(stderr[:output_limit_bytes])
    result: dict[str, object] = {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "snapshot_id": campaign.snapshot_id,
        "hypothesis_id": hypothesis_id,
        "empirical_upgrade_eligible": (
            hypothesis_id is not None
            and normalized_provenance is not None
            and normalized_provenance["origin"] != "mechanism_only"
            and not timed_out
            and not output_limit_exceeded
        ),
        "empirical_upgrade_note": "; ".join(eligibility_notes) or None,
        "profile": profile,
        "execution_provenance": normalized_provenance,
        "command": list(argv),
        "working_directory": working_directory.relative_to(target_root).as_posix() or ".",
        "timeout_seconds": timeout_seconds,
        "resource_limits": {
            "cpu_seconds": cpu_limit_seconds,
            "address_space_bytes": memory_limit_bytes,
            "file_size_bytes": file_size_limit_bytes,
            "file_size_bytes_per_stream": file_size_limit_bytes,
            "captured_output_bytes_per_stream": output_limit_bytes,
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


def validate_execution_provenance(
    manager: CampaignManager,
    snapshot_id: str,
    value: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Normalize declared provenance and verify content-addressed evidence."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ModelError("execution provenance must be an object")
    origin = value.get("origin")
    if not isinstance(origin, str) or origin not in _EXECUTION_ORIGINS:
        raise ModelError("execution provenance origin is invalid")
    allowed_keys = {"origin", "source_snapshot_id", "artifact_refs"}
    if set(value) - allowed_keys:
        raise ModelError("execution provenance has unknown fields")
    source_snapshot_id = value.get("source_snapshot_id")
    artifact_refs = value.get("artifact_refs", [])
    if not isinstance(artifact_refs, (list, tuple)) or any(
        not isinstance(reference, str) or not reference
        for reference in artifact_refs
    ):
        raise ModelError("execution provenance artifact_refs must be non-empty strings")
    if len(artifact_refs) > _MAX_PROVENANCE_ARTIFACTS:
        raise ModelError("execution provenance has too many artifact references")
    if len(set(artifact_refs)) != len(artifact_refs):
        raise ModelError("execution provenance artifact_refs must be unique")
    if origin == "target_tree":
        if source_snapshot_id not in (None, snapshot_id) or artifact_refs:
            raise ModelError(
                "target_tree provenance cannot identify a separate build artifact"
            )
        return {
            "origin": origin,
            "source_snapshot_id": snapshot_id,
            "artifact_refs": [],
        }
    if origin == "same_snapshot_build":
        if source_snapshot_id != snapshot_id or not artifact_refs:
            raise ModelError(
                "same_snapshot_build requires the Campaign snapshot and build artifact refs"
            )
    elif origin == "other_build":
        if (
            not isinstance(source_snapshot_id, str)
            or not source_snapshot_id
            or source_snapshot_id == snapshot_id
            or not artifact_refs
        ):
            raise ModelError(
                "other_build requires a distinct source snapshot and build artifact refs"
            )
    elif origin == "mechanism_only" and (source_snapshot_id is not None or artifact_refs):
        raise ModelError("mechanism_only provenance cannot identify a target build")
    for reference in artifact_refs:
        try:
            manager.artifacts.get_bytes(reference)
        except (OSError, ValueError) as error:
            raise ModelError(
                f"execution provenance artifact is unavailable: {reference}"
            ) from error
    return {
        "origin": origin,
        "source_snapshot_id": source_snapshot_id,
        "artifact_refs": list(artifact_refs),
    }


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