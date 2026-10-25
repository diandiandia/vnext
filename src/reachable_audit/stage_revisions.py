"""Helpers for append-only Batch stage revision history."""

from __future__ import annotations

from typing import Any, Iterable


STAGE_INVALIDATION_DEPENDENTS = {
    "R1_COMPLETED": (
        "R1_COMPLETED",
        "R2_COMPLETED",
        "R3_COMPLETED",
        "VERDICT_ADJUDICATED",
        "REFUTATION_SUBMITTED",
        "ADJUDICATION_DECIDED",
        "REVIVAL_SAMPLE_SELECTED",
        "REVIVAL_REVIEWED",
        "R3_5_COMPLETED",
        "R4_SCREENING_COVERAGE_RECORDED",
        "R4_COMPLETED",
        "R5_COMPLETED",
        "R6_COMPLETED",
        "TRANSMISSION_METRICS_RECORDED",
    ),
    "R2_COMPLETED": (
        "R2_COMPLETED",
        "R3_COMPLETED",
        "VERDICT_ADJUDICATED",
        "REFUTATION_SUBMITTED",
        "ADJUDICATION_DECIDED",
        "REVIVAL_SAMPLE_SELECTED",
        "REVIVAL_REVIEWED",
        "R3_5_COMPLETED",
        "R4_SCREENING_COVERAGE_RECORDED",
        "R4_COMPLETED",
        "R5_COMPLETED",
        "R6_COMPLETED",
        "TRANSMISSION_METRICS_RECORDED",
    ),
    "R3_COMPLETED": (
        "R3_COMPLETED",
        "VERDICT_ADJUDICATED",
        "REFUTATION_SUBMITTED",
        "ADJUDICATION_DECIDED",
        "REVIVAL_SAMPLE_SELECTED",
        "REVIVAL_REVIEWED",
        "R3_5_COMPLETED",
        "R4_COMPLETED",
        "R5_COMPLETED",
        "R6_COMPLETED",
        "TRANSMISSION_METRICS_RECORDED",
    ),
    "R4_COMPLETED": (
        "R4_COMPLETED",
        "R5_COMPLETED",
        "R6_COMPLETED",
        "TRANSMISSION_METRICS_RECORDED",
    ),
    "R5_COMPLETED": (
        "R5_COMPLETED",
        "R6_COMPLETED",
        "TRANSMISSION_METRICS_RECORDED",
    ),
}


def invalidated_stage_event_ids(events: Iterable[Any]) -> set[str]:
    return {
        str(event.payload["target_event_id"])
        for event in events
        if event.event_type == "STAGE_PROJECTION_INVALIDATED"
        and isinstance(event.payload.get("target_event_id"), str)
    }


def active_stage_events(
    events: Iterable[Any], event_type: str | None = None
) -> list[Any]:
    event_list = list(events)
    invalidated = invalidated_stage_event_ids(event_list)
    return [
        event for event in event_list
        if event.event_id not in invalidated
        and (event_type is None or event.event_type == event_type)
    ]


def unresolved_stage_invalidations(events: Iterable[Any]) -> list[Any]:
    event_list = list(events)
    invalidated = invalidated_stage_event_ids(event_list)
    by_id = {event.event_id: event for event in event_list}
    unresolved = []
    for marker in event_list:
        if marker.event_type != "STAGE_PROJECTION_INVALIDATED":
            continue
        target_stage = marker.payload.get("target_stage")
        target = by_id.get(marker.payload.get("target_event_id"))
        replacement_exists = any(
            event.event_id not in invalidated
            and event.batch_id == marker.batch_id
            and event.event_type == target_stage
            and (
                target is None
                or (
                    getattr(event, "entity_type", None) == getattr(target, "entity_type", None)
                    and getattr(event, "entity_id", None) == getattr(target, "entity_id", None)
                )
            )
            and event.sequence > marker.sequence
            for event in event_list
        )
        if not replacement_exists:
            unresolved.append(marker)
    return unresolved


def stage_recovery_plan(events: Iterable[Any]) -> dict[str, Any]:
    """Derive recovery instructions without restoring invalidated results."""
    steps = (
        ("R1_COMPLETED", ("task-schedule-r1", "task-commit-r1")),
        ("R2_COMPLETED", ("task-schedule-r2", "task-commit-r2")),
        ("R3_COMPLETED", ("task-schedule-r3", "task-commit-r3")),
        ("REFUTATION_SUBMITTED", (
            "task-schedule-r35-refutations", "task-commit-r35-refutations",
        )),
        ("ADJUDICATION_DECIDED", (
            "task-schedule-r35-adjudications", "task-commit-r35-adjudications",
        )),
        ("REVIVAL_SAMPLE_SELECTED", ("r35-revival-select",)),
        ("REVIVAL_REVIEWED", (
            "task-schedule-r35-revivals", "task-commit-r35-revivals",
        )),
        ("R3_5_COMPLETED", ("r35-complete",)),
        ("R4_SCREENING_COVERAGE_RECORDED", ("task-schedule-r4",)),
        ("R4_COMPLETED", ("task-schedule-r4", "task-commit-r4")),
        ("R5_COMPLETED", ("task-schedule-r5", "task-commit-r5")),
        ("TRANSMISSION_METRICS_RECORDED", ("metrics",)),
        ("R6_COMPLETED", ("task-schedule-r6", "task-commit-r6")),
    )
    pending = unresolved_stage_invalidations(events)
    batches = sorted({str(event.batch_id) for event in pending})
    return {
        "schema_version": "1.0",
        "read_only": True,
        "automatic_result_reuse": False,
        "instructions": [
            "Recommit the corrected stage from its current task output first.",
            "Schedule downstream stages against current upstream revisions; collect "
            "and validate new results before committing. Do not copy old output into new tasks.",
            "R2 commands shown use compact mode; use the per-axis schedule/commit pair "
            "for an existing per-axis layout, with the explicit entrypoint checklist.",
            "R3 recommit also restores VERDICT_ADJUDICATED. R3.5 refutation and revival "
            "work is conditional on current R3 eligibility, not the old hypothesis set.",
            "A retired per-hypothesis marker may remain when its hypothesis is no "
            "longer eligible; never fabricate a replacement to clear it. Re-run gates.",
            "Preserve the frozen category plan and execution constraints. Re-run Batch "
            "and Campaign gates after recovery; this checklist does not certify completion.",
        ],
        "batches": [
            {
                "batch_id": batch_id,
                "invalidations": [
                    {
                        "marker_event_id": event.event_id,
                        "target_event_id": event.payload["target_event_id"],
                        "target_stage": event.payload["target_stage"],
                        "invalidation_payload": dict(event.payload),
                    }
                    for event in pending if str(event.batch_id) == batch_id
                ],
                "steps": [
                    {"stage": stage, "commands": list(commands)}
                    for stage, commands in steps
                    if any(
                        str(event.batch_id) == batch_id
                        and event.payload["target_stage"] == stage
                        for event in pending
                    )
                ],
            }
            for batch_id in batches
        ],
    }


def stage_revision_ancestry_errors(events: Iterable[Any]) -> list[str]:
    active = active_stage_events(events)
    events_by_batch: dict[str, list[Any]] = {}
    for event in active:
        if event.batch_id is not None:
            events_by_batch.setdefault(str(event.batch_id), []).append(event)
    errors = []
    for batch_events in events_by_batch.values():
        latest_by_type = {}
        latest_versioned_by_type = {}
        for event in batch_events:
            latest_by_type[event.event_type] = event
            if event.payload.get("revision_id"):
                latest_versioned_by_type[event.event_type] = event
        latest_by_type = {
            event_type: latest_versioned_by_type.get(event_type, event)
            for event_type, event in latest_by_type.items()
        }
        for event in batch_events:
            upstream_revisions = event.payload.get("upstream_revision_ids")
            if not isinstance(upstream_revisions, dict):
                continue
            for upstream_type, pinned_revision_id in upstream_revisions.items():
                upstream_event = latest_by_type.get(str(upstream_type))
                if upstream_event is None:
                    errors.append(
                        f"{event.event_type} {event.event_id} has missing upstream "
                        f"{upstream_type}"
                    )
                    continue
                active_revision_id = str(
                    upstream_event.payload.get("revision_id", upstream_event.event_id)
                )
                if str(pinned_revision_id) != active_revision_id:
                    errors.append(
                        f"{event.event_type} {event.event_id} pins stale "
                        f"{upstream_type} revision {pinned_revision_id}; "
                        f"active revision is {active_revision_id}"
                    )
    return errors