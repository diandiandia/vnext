"""Campaign-owned runtime resource registration and cleanup."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import shutil
import signal
import tempfile
import time
from typing import Any

from .campaign import CampaignManager
from .models import ModelError


def register_process_group(
    manager: CampaignManager,
    campaign_id: str,
    process_group_id: int,
    *,
    label: str,
) -> str:
    if os.name != "posix":
        raise ModelError("process-group resource registration requires POSIX")
    if process_group_id <= 0 or process_group_id == os.getpgrp():
        raise ModelError("refusing to register an unsafe process group")
    if not label.strip():
        raise ModelError("Campaign resource requires a label")
    start_time = _process_start_time(process_group_id)
    if start_time is None or os.getpgid(process_group_id) != process_group_id:
        raise ModelError("registered PID must be a live process-group leader")
    resource_id = f"process-group:{process_group_id}:{start_time}"
    result = manager.store.append_event(
        campaign_id=campaign_id,
        batch_id=None,
        entity_type="campaign_resource",
        entity_id=resource_id,
        event_type="RESOURCE_REGISTERED",
        idempotency_key=f"resource:register:{campaign_id}:{resource_id}",
        actor="tool",
        payload={
            "kind": "process_group",
            "process_group_id": process_group_id,
            "start_time_ticks": start_time,
            "label": label,
        },
        payload_ref=None,
    )
    return result.event_id


def create_campaign_temp_directory(
    manager: CampaignManager, campaign_id: str, *, label: str
) -> Path:
    if not label.strip():
        raise ModelError("Campaign resource requires a label")
    manager.store.get_campaign(campaign_id)
    runtime_root = manager.state_dir / "runtime" / campaign_id
    runtime_root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="resource-", dir=runtime_root))
    resource_id = f"temp-directory:{path.name}"
    manager.store.append_event(
        campaign_id=campaign_id,
        batch_id=None,
        entity_type="campaign_resource",
        entity_id=resource_id,
        event_type="RESOURCE_REGISTERED",
        idempotency_key=f"resource:register:{campaign_id}:{resource_id}",
        actor="tool",
        payload={
            "kind": "temp_directory",
            "relative_path": path.relative_to(manager.state_dir).as_posix(),
            "label": label,
        },
        payload_ref=None,
    )
    return path


def cleanup_campaign_resources(
    manager: CampaignManager,
    campaign_id: str,
    *,
    terminate_grace_seconds: float = 1,
) -> dict[str, Any]:
    if terminate_grace_seconds < 0:
        raise ModelError("cleanup grace period cannot be negative")
    events = manager.store.list_events(campaign_id)
    cancelled_task_ids = _cancel_unfinished_tasks(manager, campaign_id, events)
    registrations = {
        event.entity_id: event
        for event in events
        if event.entity_type == "campaign_resource"
        and event.event_type == "RESOURCE_REGISTERED"
    }
    existing_releases = {
        event.entity_id: event.payload
        for event in events
        if event.entity_type == "campaign_resource"
        and event.event_type == "RESOURCE_RELEASED"
    }
    released = dict(existing_releases)
    failures: list[dict[str, str]] = []
    for resource_id, event in registrations.items():
        if resource_id in released:
            continue
        try:
            outcome = _release_resource(
                manager, event.payload, terminate_grace_seconds
            )
            manager.store.append_event(
                campaign_id=campaign_id,
                batch_id=None,
                entity_type="campaign_resource",
                entity_id=resource_id,
                event_type="RESOURCE_RELEASED",
                idempotency_key=f"resource:release:{campaign_id}:{resource_id}",
                actor="tool",
                payload=outcome,
                payload_ref=None,
            )
            released[resource_id] = outcome
        except (OSError, ValueError) as error:
            failures.append({"resource_id": resource_id, "error": str(error)})
    report = {
        "cancelled_task_ids": sorted(cancelled_task_ids),
        "released_resources": [
            {"resource_id": resource_id, **released[resource_id]}
            for resource_id in sorted(released)
        ],
        "failures": failures,
    }
    if failures:
        raise ModelError(f"Campaign resource cleanup failed: {failures}")
    return report


def release_campaign_resource(
    manager: CampaignManager,
    campaign_id: str,
    resource_id: str,
    *,
    terminate_grace_seconds: float = 1,
) -> dict[str, Any]:
    if terminate_grace_seconds < 0:
        raise ModelError("cleanup grace period cannot be negative")
    events = manager.store.list_events(campaign_id)
    registration = next((
        event for event in events
        if event.entity_type == "campaign_resource"
        and event.event_type == "RESOURCE_REGISTERED"
        and event.entity_id == resource_id
    ), None)
    if registration is None:
        raise ModelError(f"Campaign resource is not registered: {resource_id}")
    existing = next((
        event for event in reversed(events)
        if event.entity_type == "campaign_resource"
        and event.event_type == "RESOURCE_RELEASED"
        and event.entity_id == resource_id
    ), None)
    if existing is not None:
        return {"resource_id": resource_id, **existing.payload}
    try:
        outcome = _release_resource(
            manager, registration.payload, terminate_grace_seconds
        )
    except (OSError, ValueError) as error:
        raise ModelError(f"Campaign resource cleanup failed: {resource_id}: {error}") from error
    manager.store.append_event(
        campaign_id=campaign_id,
        batch_id=None,
        entity_type="campaign_resource",
        entity_id=resource_id,
        event_type="RESOURCE_RELEASED",
        idempotency_key=f"resource:release:{campaign_id}:{resource_id}",
        actor="tool",
        payload=outcome,
        payload_ref=None,
    )
    return {"resource_id": resource_id, **outcome}


def _cancel_unfinished_tasks(
    manager: CampaignManager, campaign_id: str, events: list[Any]
) -> set[str]:
    task_events: dict[str, list[Any]] = {}
    for event in events:
        if event.entity_type == "execution_task":
            task_events.setdefault(event.entity_id, []).append(event)
    cancelled = {
        task_id
        for task_id, values in task_events.items()
        if any(event.event_type == "TASK_CANCELLED" for event in values)
    }
    now = dt.datetime.now(dt.UTC).isoformat()
    for task_id, values in task_events.items():
        if any(
            event.event_type in {"TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED"}
            for event in values
        ):
            continue
        manager.store.cancel_task(
            campaign_id=campaign_id,
            task_id=task_id,
            reason="Campaign resource cleanup",
            actor="campaign-cleanup",
            now=now,
        )
        cancelled.add(task_id)
    return cancelled


def _release_resource(
    manager: CampaignManager,
    payload: Any,
    terminate_grace_seconds: float,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("resource registration payload must be an object")
    kind = payload.get("kind")
    if kind == "process_group":
        process_group_id = int(payload["process_group_id"])
        expected_start = str(payload["start_time_ticks"])
        actual_start = _process_start_time(process_group_id)
        if actual_start is None:
            return {"kind": kind, "outcome": "already_absent"}
        if actual_start != expected_start:
            return {"kind": kind, "outcome": "identity_changed_not_signalled"}
        term_sent, kill_sent = _terminate_process_group(
            process_group_id, grace_seconds=terminate_grace_seconds
        )
        return {
            "kind": kind,
            "outcome": "released",
            "term_sent": term_sent,
            "kill_sent": kill_sent,
        }
    if kind == "temp_directory":
        runtime_root = (manager.state_dir / "runtime").resolve()
        path = (manager.state_dir / str(payload["relative_path"])).resolve()
        if path == runtime_root or runtime_root not in path.parents:
            raise ValueError("temporary resource is outside the Campaign runtime root")
        if not path.exists():
            return {"kind": kind, "outcome": "already_absent"}
        shutil.rmtree(path, ignore_errors=False)
        return {"kind": kind, "outcome": "released"}
    raise ValueError(f"unsupported Campaign resource kind: {kind}")


def _terminate_process_group(
    process_group_id: int, *, grace_seconds: float
) -> tuple[bool, bool]:
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return False, False
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if _process_start_time(process_group_id) is None:
            return True, False
        time.sleep(0.01)
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return True, False
    return True, True


def _process_start_time(process_id: int) -> str | None:
    try:
        fields = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8").split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    if len(fields) < 22:
        raise ValueError(f"invalid /proc stat for PID {process_id}")
    return fields[21]