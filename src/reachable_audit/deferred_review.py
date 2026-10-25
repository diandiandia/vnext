"""Derived unresolved review packets; stage artifacts remain the only source of truth."""

from __future__ import annotations

from typing import Any

from .batch_workflow import BatchWorkflow
from .campaign import CampaignManager


def batch_review_queue(workflow: BatchWorkflow) -> list[dict[str, Any]]:
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
