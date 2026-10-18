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
    unresolved = []
    for marker in event_list:
        if marker.event_type != "STAGE_PROJECTION_INVALIDATED":
            continue
        target_stage = marker.payload.get("target_stage")
        replacement_exists = any(
            event.event_id not in invalidated
            and event.batch_id == marker.batch_id
            and event.event_type == target_stage
            and event.sequence > marker.sequence
            for event in event_list
        )
        if not replacement_exists:
            unresolved.append(marker)
    return unresolved


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