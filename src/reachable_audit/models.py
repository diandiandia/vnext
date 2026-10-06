"""Canonical Phase 1 models and state-transition rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class ModelError(ValueError):
    """Raised when canonical model data is invalid."""


class TransitionError(ModelError):
    """Raised when an entity attempts an illegal state transition."""


class CampaignStatus(StrEnum):
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    INTEGRATING = "INTEGRATING"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class CampaignAuditMode(StrEnum):
    FRESH = "fresh"
    FOLLOW_UP = "follow-up"
    LEGACY = "legacy"


class BatchStatus(StrEnum):
    PLANNED = "PLANNED"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"
    DEFERRED = "DEFERRED"


CAMPAIGN_TRANSITIONS: Mapping[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.PLANNING: frozenset({CampaignStatus.RUNNING, CampaignStatus.BLOCKED}),
    CampaignStatus.RUNNING: frozenset({CampaignStatus.INTEGRATING, CampaignStatus.BLOCKED}),
    CampaignStatus.INTEGRATING: frozenset({CampaignStatus.COMPLETE, CampaignStatus.BLOCKED}),
    CampaignStatus.BLOCKED: frozenset(
        {CampaignStatus.PLANNING, CampaignStatus.RUNNING, CampaignStatus.INTEGRATING}
    ),
    CampaignStatus.COMPLETE: frozenset(),
}

BATCH_TRANSITIONS: Mapping[BatchStatus, frozenset[BatchStatus]] = {
    BatchStatus.PLANNED: frozenset(
        {BatchStatus.READY, BatchStatus.BLOCKED, BatchStatus.DEFERRED}
    ),
    BatchStatus.READY: frozenset(
        {BatchStatus.RUNNING, BatchStatus.BLOCKED, BatchStatus.DEFERRED}
    ),
    BatchStatus.RUNNING: frozenset(
        {BatchStatus.COMPLETE, BatchStatus.BLOCKED, BatchStatus.DEFERRED}
    ),
    BatchStatus.BLOCKED: frozenset(
        {BatchStatus.PLANNED, BatchStatus.READY, BatchStatus.RUNNING, BatchStatus.DEFERRED}
    ),
    BatchStatus.DEFERRED: frozenset({BatchStatus.PLANNED}),
    BatchStatus.COMPLETE: frozenset(),
}


def require_transition(current: StrEnum, target: StrEnum) -> None:
    if type(current) is not type(target):
        raise TransitionError(
            f"state type mismatch: {type(current).__name__} -> {type(target).__name__}"
        )
    allowed = (
        CAMPAIGN_TRANSITIONS[current]
        if isinstance(current, CampaignStatus)
        else BATCH_TRANSITIONS[current]
    )
    if target not in allowed:
        raise TransitionError(f"illegal transition: {current.value} -> {target.value}")


@dataclass(frozen=True)
class CampaignRecord:
    campaign_id: str
    target_root: str
    snapshot_id: str
    audit_mode: CampaignAuditMode
    history_source_campaign_ids: tuple[str, ...]
    status: CampaignStatus
    budget: Mapping[str, Any]
    constraints: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class BatchRecord:
    campaign_id: str
    batch_id: str
    status: BatchStatus
    manifest: Mapping[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EventRecord:
    sequence: int
    event_id: str
    campaign_id: str
    batch_id: str | None
    entity_type: str
    entity_id: str
    event_type: str
    idempotency_key: str
    actor: str
    payload: Mapping[str, Any]
    payload_ref: str | None
    created_at: str


@dataclass(frozen=True)
class AppendResult:
    event_id: str
    inserted: bool
