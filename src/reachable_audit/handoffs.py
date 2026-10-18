"""Cross-Batch Handoff resolution and chain integration."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Sequence

from .analysis_models import BoundaryProof, HandoffOutcome, HandoffResolution
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
        self._edges_by_id = {item.edge_id: item for item in plan.boundary_edges}

    def resolve(self, resolution: HandoffResolution) -> str:
        return self.resolve_many((resolution,))[0]

    def resolve_many(
        self, resolutions: Sequence[HandoffResolution]
    ) -> tuple[str, ...]:
        if not resolutions:
            return ()
        normalized_resolutions = [
            HandoffResolution.from_dict(asdict(item)) for item in resolutions
        ]
        handoffs = [
            self._handoff(item.handoff_id) for item in normalized_resolutions
        ]
        handoff_ids = [item.handoff_id for item in handoffs]
        if len(handoff_ids) != len(set(handoff_ids)):
            raise ModelError("Handoff batch contains duplicate handoff IDs")
        for handoff, resolution in zip(handoffs, normalized_resolutions):
            if resolution.owner_batch_id != handoff.owner_batch:
                raise ModelError(
                    f"Handoff resolution submitted by non-owner Batch: {resolution.handoff_id}"
                )
            if resolution.outcome is HandoffOutcome.EDGE_PROVEN:
                if resolution.boundary_proof is None:
                    raise ModelError("EDGE_PROVEN Handoff requires a boundary proof")
                self._validate_boundary_proof(
                    handoff.edge_id, resolution.boundary_proof
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
        for handoff, resolution in zip(handoffs, normalized_resolutions):
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
        if not suffix or prefix[-1] != suffix[0]:
            raise ModelError("Handoff chain suffix must join the supplied prefix")
        suffix = suffix[1:]
        proof = resolution.get("boundary_proof")
        if not isinstance(proof, dict):
            raise ModelError(f"EDGE_PROVEN Handoff is missing its boundary proof: {handoff_id}")
        proof_evidence_refs = [
            *proof["source_evidence_refs"],
            *proof["target_evidence_refs"],
            *(
                ref
                for mapping in proof["data_mappings"]
                for ref in mapping["evidence_refs"]
            ),
        ]
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
                *proof_evidence_refs,
            ])),
            "boundary_proof": proof,
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

    def _validate_boundary_proof(self, edge_id: str, proof: BoundaryProof) -> None:
        edge = self._edges_by_id.get(edge_id)
        if edge is None:
            raise ModelError(f"Handoff proof references unknown plan edge: {edge_id}")
        if (
            proof.edge_id != edge.edge_id
            or proof.source_component_id != edge.source_component_id
            or proof.target_component_id != edge.target_component_id
            or proof.interface_kind != edge.kind
        ):
            raise ModelError(
                f"Handoff boundary proof does not match planned edge endpoints: {edge_id}"
            )
        for edge_path, evidence_refs, endpoint in (
            (edge.source_path, proof.source_evidence_refs, "source"),
            (edge.target_path, proof.target_evidence_refs, "target"),
        ):
            if edge_path and not any(
                ref.startswith(f"LOC-{edge_path}:") for ref in evidence_refs
            ):
                raise ModelError(
                    f"Handoff {endpoint} proof evidence does not anchor planned path: "
                    f"{edge_path}"
                )

        inventory = self.manager.load_inventory(self.campaign_id)
        valid_paths = {item.path for item in inventory.source_files}
        component_by_path = {
            item.path: item.component_id for item in inventory.source_files
        }
        valid_paths.update(
            path
            for component in inventory.components
            for path in component.build_manifests
        )
        component_by_path.update({
            path: component.component_id
            for component in inventory.components
            for path in component.build_manifests
        })
        for endpoint, component_id, refs in (
            ("source", edge.source_component_id, proof.source_evidence_refs),
            ("target", edge.target_component_id, proof.target_evidence_refs),
        ):
            for ref in refs:
                if not ref.startswith("LOC-"):
                    continue
                evidence_path = ref[4:].rpartition(":")[0]
                if component_by_path.get(evidence_path) != component_id:
                    raise ModelError(
                        f"Handoff {endpoint} proof evidence is not owned by the "
                        f"planned endpoint component: {ref}"
                    )
        proof_refs = (
            *proof.source_evidence_refs,
            *proof.target_evidence_refs,
            *(
                ref
                for mapping in proof.data_mappings
                for ref in mapping.evidence_refs
            ),
        )
        artifact_refs = {ref for ref in proof_refs if ref.startswith("sha256:")}
        artifact_owners = self.manager.store.artifact_campaign_owners(artifact_refs)
        for evidence_ref in proof_refs:
            if evidence_ref.startswith("LOC-"):
                if not self._valid_source_anchor(evidence_ref, valid_paths):
                    raise ModelError(
                        f"Handoff boundary proof has invalid source evidence: {evidence_ref}"
                    )
            elif evidence_ref.startswith("sha256:"):
                try:
                    self.manager.artifacts.get_bytes(evidence_ref)
                except (OSError, ValueError) as error:
                    raise ModelError(
                        f"Handoff boundary proof artifact is missing: {evidence_ref}"
                    ) from error
                if artifact_owners.get(evidence_ref, set()) != {self.campaign_id}:
                    raise ModelError(
                        "Handoff boundary proof artifact is not owned by this Campaign: "
                        f"{evidence_ref}"
                    )
            else:
                raise ModelError(
                    "Handoff boundary proof evidence must be a LOC anchor or "
                    f"Campaign artifact: {evidence_ref}"
                )

    def _valid_source_anchor(self, evidence_ref: str, valid_paths: set[str]) -> bool:
        path_text, separator, line_text = evidence_ref[4:].rpartition(":")
        if not separator or not line_text.isdigit() or int(line_text) < 1:
            return False
        relative_path = Path(path_text)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return False
        if relative_path.as_posix() not in valid_paths:
            return False
        target_root = self.manager.target_root.resolve()
        source_path = (target_root / relative_path).resolve()
        if not source_path.is_relative_to(target_root) or not source_path.is_file():
            return False
        try:
            with source_path.open("rb") as source:
                for _ in range(int(line_text)):
                    if not source.readline():
                        return False
        except OSError:
            return False
        return True

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