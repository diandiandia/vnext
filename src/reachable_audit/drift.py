"""Snapshot drift impact analysis and explicit entity invalidation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Mapping, Sequence

from .campaign import CampaignManager
from .models import BatchStatus, ModelError
from .plan_models import AuditPlan


@dataclass(frozen=True)
class DriftImpact:
    changed_paths: tuple[str, ...]
    affected_component_ids: tuple[str, ...]
    affected_work_unit_ids: tuple[str, ...]
    affected_handoff_ids: tuple[str, ...]
    affected_finding_ids: tuple[str, ...]


def compute_drift_impact(
    plan: AuditPlan,
    changed_paths: Sequence[str],
    findings: Sequence[Mapping[str, object]],
) -> DriftImpact:
    changed = set(changed_paths)
    directly_affected = {
        unit.component_id
        for unit in plan.work_units
        if changed.intersection(unit.source_files)
    }
    affected_components = set(directly_affected)
    changed_graph = True
    while changed_graph:
        changed_graph = False
        for edge in plan.boundary_edges:
            if (
                edge.target_component_id in affected_components
                and edge.source_component_id not in affected_components
            ):
                affected_components.add(edge.source_component_id)
                changed_graph = True
    affected_work_units = {
        unit.work_unit_id
        for unit in plan.work_units
        if unit.component_id in affected_components
    }
    affected_edges = {
        edge.edge_id
        for edge in plan.boundary_edges
        if edge.source_component_id in affected_components
        or edge.target_component_id in affected_components
    }
    affected_handoffs = {
        handoff.handoff_id
        for handoff in plan.handoffs
        if handoff.edge_id in affected_edges
    }
    affected_findings = {
        str(finding["finding_id"])
        for finding in findings
        if affected_components.intersection(
            str(item) for item in finding.get("affected_component_ids", [])  # type: ignore[union-attr]
        )
    }
    return DriftImpact(
        changed_paths=tuple(sorted(changed)),
        affected_component_ids=tuple(sorted(affected_components)),
        affected_work_unit_ids=tuple(sorted(affected_work_units)),
        affected_handoff_ids=tuple(sorted(affected_handoffs)),
        affected_finding_ids=tuple(sorted(affected_findings)),
    )


def record_snapshot_drift(
    manager: CampaignManager,
    *,
    campaign_id: str,
    detecting_batch_id: str,
    plan: AuditPlan,
    changed_paths: Sequence[str],
    expected_digests: Mapping[str, str],
    observed_digests: Mapping[str, str | None],
    detecting_batch_status: BatchStatus,
) -> tuple[str, DriftImpact]:
    finding_events = [
        event
        for event in manager.store.list_events(campaign_id)
        if event.event_type == "FINDING_RECORDED" and event.payload_ref
    ]
    findings = [
        json.loads(manager.artifacts.get_bytes(event.payload_ref))
        for event in finding_events
        if event.payload_ref
    ]
    impact = compute_drift_impact(plan, changed_paths, findings)
    value = {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "detecting_batch_id": detecting_batch_id,
        "plan_id": plan.plan_id,
        "detecting_batch_status": detecting_batch_status.value,
        "expected_digests": dict(sorted(expected_digests.items())),
        "observed_digests": dict(sorted(observed_digests.items())),
        "impact": asdict(impact),
    }
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    artifact = manager.artifacts.put_text(encoded)
    drift = manager.store.append_event(
        campaign_id=campaign_id,
        batch_id=detecting_batch_id,
        entity_type="snapshot_drift",
        entity_id=artifact.artifact_id,
        event_type="SNAPSHOT_DRIFT",
        idempotency_key=f"snapshot-drift:{campaign_id}:{artifact.artifact_id}",
        actor="tool",
        payload={
            "plan_id": plan.plan_id,
            "changed_paths": list(impact.changed_paths),
        },
        payload_ref=artifact.artifact_id,
    )
    batch_by_work_unit = {
        work_unit_id: batch.batch_id
        for batch in plan.batches
        for work_unit_id in batch.work_unit_ids
    }
    for work_unit_id in impact.affected_work_unit_ids:
        manager.store.append_event(
            campaign_id=campaign_id,
            batch_id=batch_by_work_unit[work_unit_id],
            entity_type="work_unit",
            entity_id=work_unit_id,
            event_type="WORK_UNIT_INVALIDATED",
            idempotency_key=f"invalidate:work-unit:{drift.event_id}:{work_unit_id}",
            actor="tool",
            payload={"drift_event_id": drift.event_id},
        )
    handoff_by_id = {handoff.handoff_id: handoff for handoff in plan.handoffs}
    for handoff_id in impact.affected_handoff_ids:
        manager.store.append_event(
            campaign_id=campaign_id,
            batch_id=handoff_by_id[handoff_id].owner_batch,
            entity_type="handoff",
            entity_id=handoff_id,
            event_type="HANDOFF_INVALIDATED",
            idempotency_key=f"invalidate:handoff:{drift.event_id}:{handoff_id}",
            actor="tool",
            payload={"drift_event_id": drift.event_id},
        )
    finding_batch = {
        event.entity_id: event.batch_id for event in finding_events
    }
    for finding_id in impact.affected_finding_ids:
        manager.store.append_event(
            campaign_id=campaign_id,
            batch_id=finding_batch[finding_id],
            entity_type="finding",
            entity_id=finding_id,
            event_type="FINDING_INVALIDATED",
            idempotency_key=f"invalidate:finding:{drift.event_id}:{finding_id}",
            actor="tool",
            payload={"drift_event_id": drift.event_id},
        )
    return drift.event_id, impact


def resolve_snapshot_drift(
    manager: CampaignManager,
    *,
    campaign_id: str,
    drift_event_id: str,
    evidence_refs: Sequence[str],
) -> str:
    if not evidence_refs:
        raise ModelError("snapshot drift resolution requires evidence references")
    events = manager.store.list_events(campaign_id)
    drift = next((
        event
        for event in events
        if event.event_id == drift_event_id and event.event_type == "SNAPSHOT_DRIFT"
    ), None)
    if drift is None or drift.payload_ref is None or drift.batch_id is None:
        raise ModelError(f"snapshot drift event not found: {drift_event_id}")
    value = json.loads(manager.artifacts.get_bytes(drift.payload_ref))
    expected = value.get("expected_digests", {})
    changed_paths = value.get("impact", {}).get("changed_paths", [])
    mismatches = []
    for source_path in changed_paths:
        path = manager.target_root / str(source_path)
        observed = None
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            observed = digest.hexdigest()
        if observed != expected.get(source_path):
            mismatches.append(str(source_path))
    if mismatches:
        raise ModelError(
            f"snapshot drift remains unresolved for paths: {sorted(mismatches)}"
        )
    resolution = manager.store.append_event(
        campaign_id=campaign_id,
        batch_id=drift.batch_id,
        entity_type="snapshot_drift",
        entity_id=drift.entity_id,
        event_type="SNAPSHOT_DRIFT_RESOLVED",
        idempotency_key=f"snapshot-drift-resolve:{campaign_id}:{drift_event_id}",
        actor="tool",
        payload={
            "drift_event_id": drift_event_id,
            "evidence_refs": list(evidence_refs),
            "resolution": "SOURCE_RESTORED_TO_BASELINE",
        },
    )
    event_type_by_invalidation = {
        "WORK_UNIT_INVALIDATED": "WORK_UNIT_REVALIDATED",
        "HANDOFF_INVALIDATED": "HANDOFF_REVALIDATED",
        "FINDING_INVALIDATED": "FINDING_REVALIDATED",
    }
    for event in events:
        revalidation_type = event_type_by_invalidation.get(event.event_type)
        if revalidation_type is None or event.payload.get("drift_event_id") != drift_event_id:
            continue
        manager.store.append_event(
            campaign_id=campaign_id,
            batch_id=event.batch_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=revalidation_type,
            idempotency_key=f"revalidate:{resolution.event_id}:{event.event_id}",
            actor="tool",
            payload={
                "drift_event_id": drift_event_id,
                "resolution_event_id": resolution.event_id,
            },
        )
    batch = manager.store.get_batch(campaign_id, drift.batch_id)
    if batch.status is BatchStatus.BLOCKED:
        manager.store.transition_batch(
            campaign_id,
            drift.batch_id,
            BatchStatus(str(value["detecting_batch_status"])),
        )
    return resolution.event_id