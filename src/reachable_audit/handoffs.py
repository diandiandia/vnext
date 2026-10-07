"""Cross-Batch Handoff resolution and chain integration."""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any, Sequence

from .analysis_models import HandoffOutcome, HandoffResolution
from .campaign import CampaignManager
from .models import ModelError
from .plan_models import AuditPlan, Handoff


class HandoffResolver:
    def __init__(
        self, manager: CampaignManager, campaign_id: str, plan: AuditPlan
    ) -> None:
        if plan.campaign_id != campaign_id:
            raise ModelError("Handoff plan does not belong to Campaign")
        self.manager = manager
        self.campaign_id = campaign_id
        self.plan = plan
        self._handoffs_by_id = {item.handoff_id: item for item in plan.handoffs}

    def resolve(self, resolution: HandoffResolution) -> str:
        return self.resolve_many((resolution,))[0]

    def resolve_many(
        self, resolutions: Sequence[HandoffResolution]
    ) -> tuple[str, ...]:
        if not resolutions:
            return ()
        handoffs = [self._handoff(item.handoff_id) for item in resolutions]
        handoff_ids = [item.handoff_id for item in handoffs]
        if len(handoff_ids) != len(set(handoff_ids)):
            raise ModelError("Handoff batch contains duplicate handoff IDs")
        for handoff, resolution in zip(handoffs, resolutions):
            if resolution.owner_batch_id != handoff.owner_batch:
                raise ModelError(
                    f"Handoff resolution submitted by non-owner Batch: {resolution.handoff_id}"
                )

        completed_owner_batches = {
            batch_id
            for batch_id in {handoff.owner_batch for handoff in handoffs}
            if self.manager.store.list_batch_events(
                self.campaign_id, batch_id, event_type="R3_COMPLETED"
            )
        }
        missing_owners = sorted(
            {handoff.owner_batch for handoff in handoffs} - completed_owner_batches
        )
        if missing_owners:
            raise ModelError(
                f"Handoff owner has not completed R3: {missing_owners}"
            )

        artifact_ids = []
        events = []
        for handoff, resolution in zip(handoffs, resolutions):
            artifact_id = self._put_json({
                "schema_version": "1.0",
                **asdict(resolution),
                "edge_id": handoff.edge_id,
                "from_batch": handoff.from_batch,
            })
            artifact_ids.append(artifact_id)
            events.append({
                "batch_id": handoff.owner_batch,
                "entity_type": "handoff",
                "entity_id": handoff.handoff_id,
                "event_type": "HANDOFF_RESOLVED",
                "idempotency_key": (
                    f"handoff-resolve:{self.campaign_id}:{handoff.handoff_id}"
                ),
                "actor": "agent",
                "payload": {
                    "outcome": resolution.outcome.value,
                    "from_batch": handoff.from_batch,
                    "owner_batch": handoff.owner_batch,
                },
                "payload_ref": artifact_id,
            })
        self.manager.store.append_events_batch(self.campaign_id, events)
        return tuple(artifact_ids)

    def integrate(
        self,
        handoff_id: str,
        *,
        known_chain_prefix: Sequence[str],
        evidence_refs: Sequence[str],
    ) -> dict[str, Any]:
        handoff = self._handoff(handoff_id)
        if not known_chain_prefix or not evidence_refs:
            raise ModelError("Handoff integration requires chain prefix and evidence refs")
        resolution_events = self.manager.store.list_events(
            self.campaign_id,
            entity_type="handoff",
            entity_id=handoff_id,
            event_type="HANDOFF_RESOLVED",
        )
        resolution_event = resolution_events[-1] if resolution_events else None
        if resolution_event is None or resolution_event.payload_ref is None:
            raise ModelError(f"Handoff is not resolved: {handoff_id}")
        resolution = json.loads(
            self.manager.artifacts.get_bytes(resolution_event.payload_ref)
        )
        if resolution["outcome"] != HandoffOutcome.EDGE_PROVEN.value:
            raise ModelError(
                f"only EDGE_PROVEN Handoffs can form a call chain: {handoff_id}"
            )
        prefix = list(known_chain_prefix)
        suffix = list(resolution["chain_suffix"])
        if prefix[-1] == suffix[0]:
            suffix = suffix[1:]
        value = {
            "schema_version": "1.0",
            "handoff_id": handoff_id,
            "edge_id": handoff.edge_id,
            "from_batch": handoff.from_batch,
            "owner_batch": handoff.owner_batch,
            "call_chain": [*prefix, *suffix],
            "evidence_refs": list(dict.fromkeys([
                *evidence_refs,
                *resolution["evidence_refs"],
            ])),
            "resolution_event_id": resolution_event.event_id,
        }
        artifact_id = self._put_json(value)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=handoff.from_batch,
            entity_type="handoff",
            entity_id=handoff_id,
            event_type="HANDOFF_INTEGRATED",
            idempotency_key=(
                f"handoff-integrate:{self.campaign_id}:{handoff_id}:{artifact_id}"
            ),
            actor="tool",
            payload={"call_chain_length": len(value["call_chain"])},
            payload_ref=artifact_id,
        )
        return {**value, "artifact_id": artifact_id}

    def _handoff(self, handoff_id: str) -> Handoff:
        handoff = self._handoffs_by_id.get(handoff_id)
        if handoff is None:
            raise ModelError(f"Handoff is not part of plan: {handoff_id}")
        return handoff

    def _put_json(self, value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return self.manager.artifacts.put_text(encoded).artifact_id