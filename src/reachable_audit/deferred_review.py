"""Derived unresolved review packets; stage artifacts remain the only source of truth."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .batch_workflow import BatchWorkflow
from .campaign import CampaignManager
from .models import CampaignStatus, ModelError


def _review_binding(packet: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({
        key: packet.get(key) for key in (
            "r2_artifact_ref", "r3_artifact_ref", "adjudication_artifact_ref",
            "refutation_artifact_refs",
        )
    }, sort_keys=True).encode()).hexdigest()


def validate_review_delivery(value: dict[str, Any]) -> None:
    required = {"blockers", "validation_plan", "investigation_urgency", "priority_rationale"}
    if not isinstance(value, dict) or set(value) != required:
        raise ModelError("review delivery fields mismatch; severity is not permitted")
    blockers = value["blockers"]
    if not isinstance(blockers, list) or not blockers or len(blockers) > 64 or not all(
        isinstance(b, str) and b.strip() for b in blockers
    ):
        raise ModelError("review delivery requires substantive blockers")
    plan = value["validation_plan"]
    if not isinstance(plan, dict) or not plan or set(plan) - {"local", "owner"} or not all(
        isinstance(step, str) and step.strip() for step in plan.values()
    ):
        raise ModelError("review delivery requires an applicable local or owner validation plan")
    if not isinstance(value["investigation_urgency"], str) or value["investigation_urgency"] not in {
        "P0", "P1", "P2", "P3", "NOT_ASSESSED",
    }:
        raise ModelError("invalid investigation urgency")
    if not isinstance(value["priority_rationale"], str) or not value["priority_rationale"].strip():
        raise ModelError("review delivery requires a priority rationale")


def record_review_delivery(
    workflow: BatchWorkflow, hypothesis_id: str, value: dict[str, Any], *, actor: str,
) -> str:
    validate_review_delivery(value)
    if not isinstance(actor, str) or not actor.strip():
        raise ModelError("review delivery requires an actor")
    if workflow.campaign.status is CampaignStatus.COMPLETE or workflow.manager.store.list_events(
        workflow.campaign_id, event_type="CAMPAIGN_ABORTED",
    ):
        raise ModelError("completed Campaign review delivery is immutable; use a follow-up")
    packet = next((p for p in batch_review_queue(workflow)
                   if p["hypothesis_id"] == hypothesis_id), None)
    if packet is None:
        raise ModelError("review delivery requires a current unresolved hypothesis")
    binding = _review_binding(packet)
    artifact = workflow.manager.artifacts.put_text(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ))
    workflow.manager.store.append_event(
        campaign_id=workflow.campaign_id, batch_id=workflow.batch_id,
        entity_type="review_delivery", entity_id=hypothesis_id,
        event_type="REVIEW_DELIVERY_RECORDED",
        idempotency_key=f"review-delivery:{workflow.campaign_id}:{workflow.batch_id}:{hypothesis_id}:{binding}:{artifact.artifact_id}",
        actor=actor, payload={"binding": binding}, payload_ref=artifact.artifact_id,
    )
    return artifact.artifact_id


def batch_review_queue(workflow: BatchWorkflow) -> list[dict[str, Any]]:
    if any(event.event_type == "BATCH_SUPERSEDED" for event in workflow._events()):
        return []
    r2 = workflow._stage_event("R2_COMPLETED")
    r3 = workflow._stage_event("R3_COMPLETED")
    if r2 is None or r3 is None:
        return []
    hypotheses = {
        item["hypothesis_id"]: item
        for item in workflow._read_artifact(r2.payload_ref)["hypotheses"]
    }
    adjudications = {
        event.entity_id: event
        for event in workflow._active_events(event_type="ADJUDICATION_DECIDED")
    }
    refutations = workflow._active_events(event_type="REFUTATION_SUBMITTED")
    packets = []
    for verdict in workflow._read_artifact(r3.payload_ref)["verdicts"]:
        hypothesis_id = verdict["hypothesis_id"]
        hypothesis = hypotheses.get(hypothesis_id)
        event = adjudications.get(hypothesis_id)
        adjudication = workflow._read_artifact(event.payload_ref) if event else None
        effective = adjudication["final_verdict"] if adjudication else verdict["verdict"]
        if hypothesis is None or effective != "NEEDS_REVIEW":
            continue
        items = sorted(
            (
                (workflow._read_artifact(item.payload_ref), item.payload_ref)
                for item in refutations if item.entity_id == hypothesis_id
            ),
            key=lambda pair: pair[0]["refutation_id"],
        )
        packet = {
            "campaign_id": workflow.campaign_id,
            "batch_id": workflow.batch_id,
            "work_unit_id": hypothesis["work_unit_id"],
            "hypothesis_id": hypothesis_id,
            "hypothesis": hypothesis,
            "r2_artifact_ref": r2.payload_ref,
            "r3_verdict": verdict,
            "r3_artifact_ref": r3.payload_ref,
            "refutations": [item for item, _ in items],
            "refutation_artifact_refs": {
                item["refutation_id"]: reference for item, reference in items
            },
            "effective_verdict": effective,
            "provisional": True,
            "unresolved_rationale": (
                adjudication["rationale"] if adjudication else verdict["rationale"]
            ),
        }
        if adjudication is not None:
            packet["adjudication"] = adjudication
            packet["adjudication_artifact_ref"] = event.payload_ref
        packet["delivery_status"] = "NOT_RECORDED"
        packet["delivery"] = None
        for delivery_event in reversed(workflow._events()):
            if (
                delivery_event.event_type == "REVIEW_DELIVERY_RECORDED"
                and delivery_event.entity_id == hypothesis_id
                and delivery_event.payload["binding"] == _review_binding(packet)
            ):
                delivery = workflow._read_artifact(delivery_event.payload_ref)
                validate_review_delivery(delivery)
                packet["delivery_status"] = "RECORDED"
                packet["delivery"] = delivery
                break
        packets.append(packet)
    return sorted(packets, key=lambda item: item["hypothesis_id"])


def derive_review_queue(
    manager: CampaignManager, campaign_id: str,
) -> list[dict[str, Any]]:
    manager.store.get_campaign(campaign_id)
    return [
        packet
        for batch in sorted(
            manager.store.list_batches(campaign_id), key=lambda item: item.batch_id,
        )
        for packet in batch_review_queue(
            BatchWorkflow(manager, campaign_id, batch.batch_id),
        )
    ]


def review_aware_r3_verdicts(workflow: BatchWorkflow) -> list[dict[str, Any]]:
    """Preserve verifier evidence while exposing unresolved adjudications downstream."""
    packets = {item["hypothesis_id"]: item for item in batch_review_queue(workflow)}
    return [
        {
            **verdict,
            **({
                "verifier_verdict": verdict["verdict"],
                "verdict": "NEEDS_REVIEW",
                "unresolved_rationale": packets[verdict["hypothesis_id"]]["unresolved_rationale"],
            } if verdict["hypothesis_id"] in packets else {}),
        }
        for verdict in workflow._r3_verdicts()
    ]
