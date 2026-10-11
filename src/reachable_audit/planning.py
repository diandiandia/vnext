"""Deterministic Work Unit, Batch, and Handoff planning."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from typing import Iterable, Sequence

from .models import ModelError
from .plan_models import (
    AuditPlan,
    BatchReplacement,
    BoundaryEdge,
    Handoff,
    PlanAmendment,
    PlannedBatch,
    ProjectInventory,
    WorkUnit,
)


REQUIRED_STAGES = ("R0", "R1", "R2", "R3", "R3.5", "R4", "R5", "R6")
DEFAULT_DISCOVERY_AXES = (
    "surface",
    "mechanism",
    "state",
    "fix_variant",
    "boundary",
    "differential",
)


def _stable_id(prefix: str, *parts: str, length: int = 16) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


def inventory_digest(inventory: ProjectInventory) -> str:
    encoded = json.dumps(asdict(inventory), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _chunks(values: Sequence[str], size: int) -> Iterable[tuple[str, ...]]:
    for offset in range(0, len(values), size):
        yield tuple(values[offset:offset + size])


def discovery_output_floor_bytes(work_unit: WorkUnit) -> int:
    """Lower bound on a valid R1 result: reviewed paths plus one minimal review per owned edge."""
    per_review = len(json.dumps({
        "disposition": "unresolved",
        "edge_id": "",
        "evidence_refs": ["LOC-:1"],
        "rationale": "x",
        "work_unit_id": work_unit.work_unit_id,
    }, separators=(",", ":")))
    edge_bytes = sum(per_review + len(edge_id) for edge_id in work_unit.boundary_edge_ids)
    path_bytes = sum(len(path) + 3 for path in work_unit.source_files)
    return 64 + path_bytes + edge_bytes


def create_audit_plan(
    *,
    campaign_id: str,
    inventory: ProjectInventory,
    category_families: Sequence[str],
    boundary_edges: Sequence[BoundaryEdge] = (),
    discovery_axes: Sequence[str] = DEFAULT_DISCOVERY_AXES,
    max_source_files_per_work_unit: int = 1000,
    max_source_files_per_batch: int = 2000,
    max_work_units_per_batch: int = 4,
) -> AuditPlan:
    categories = tuple(sorted({item.strip().upper() for item in category_families if item.strip()}))
    axes = tuple(dict.fromkeys(item.strip() for item in discovery_axes if item.strip()))
    if not categories:
        raise ModelError("at least one category family is required")
    if not axes:
        raise ModelError("at least one discovery axis is required")
    if min(max_source_files_per_work_unit, max_source_files_per_batch, max_work_units_per_batch) <= 0:
        raise ModelError("planner limits must be positive")
    if max_source_files_per_work_unit > max_source_files_per_batch:
        raise ModelError("work unit file limit cannot exceed batch file limit")

    known_components = {component.component_id for component in inventory.components}
    source_owner_by_path = {
        source_file.path: source_file.component_id for source_file in inventory.source_files
    }
    edge_ids: set[str] = set()
    for edge in boundary_edges:
        if edge.edge_id in edge_ids:
            raise ModelError(f"duplicate boundary edge ID: {edge.edge_id}")
        edge_ids.add(edge.edge_id)
        if edge.source_component_id not in known_components:
            raise ModelError(f"unknown boundary source component: {edge.source_component_id}")
        if edge.target_component_id not in known_components:
            raise ModelError(f"unknown boundary target component: {edge.target_component_id}")
        if edge.source_component_id == edge.target_component_id:
            raise ModelError(f"boundary edge is not cross-component: {edge.edge_id}")
        if edge.source_path and source_owner_by_path.get(edge.source_path) != edge.source_component_id:
            raise ModelError(
                f"boundary source path is not owned by source component: {edge.edge_id}"
            )

    files_by_component: dict[str, list[tuple[str, str]]] = {
        component_id: [] for component_id in known_components
    }
    for source_file in inventory.source_files:
        if source_file.component_id not in known_components:
            raise ModelError(f"source file has unknown component owner: {source_file.path}")
        files_by_component[source_file.component_id].append((source_file.path, source_file.language))
    edges_by_component: dict[str, list[str]] = {
        component_id: [] for component_id in known_components
    }
    for edge in boundary_edges:
        edges_by_component[edge.source_component_id].append(edge.edge_id)
        edges_by_component[edge.target_component_id].append(edge.edge_id)

    work_units = []
    for component_id in sorted(files_by_component):
        component_files = sorted(files_by_component[component_id])
        paths = [path for path, _ in component_files]
        languages_by_path = {path: language for path, language in component_files}
        file_chunks = tuple(_chunks(paths, max_source_files_per_work_unit)) or ((),)
        for shard_index, file_chunk in enumerate(file_chunks, start=1):
            work_units.append(WorkUnit(
                work_unit_id=_stable_id("WU", inventory.snapshot_id, component_id, str(shard_index), *file_chunk),
                component_id=component_id,
                source_files=file_chunk,
                languages=tuple(sorted({languages_by_path[path] for path in file_chunk})),
                category_families=categories,
                discovery_axes=axes,
                boundary_edge_ids=(
                    tuple(sorted(edges_by_component[component_id]))
                    if shard_index == 1 else ()
                ),
            ))

    work_units.sort(key=lambda unit: (-len(unit.source_files), unit.work_unit_id))
    packed: list[list[WorkUnit]] = []
    for work_unit in work_units:
        destination = next((
            batch for batch in packed
            if len(batch) < max_work_units_per_batch
            and sum(len(item.source_files) for item in batch) + len(work_unit.source_files)
            <= max_source_files_per_batch
        ), None)
        if destination is None:
            destination = []
            packed.append(destination)
        destination.append(work_unit)

    digest = inventory_digest(inventory)
    plan_seed = json.dumps({
        "campaign_id": campaign_id,
        "snapshot_id": inventory.snapshot_id,
        "inventory_digest": digest,
        "categories": categories,
        "axes": axes,
        "edges": [asdict(edge) for edge in boundary_edges],
        "limits": [max_source_files_per_work_unit, max_source_files_per_batch, max_work_units_per_batch],
    }, sort_keys=True, separators=(",", ":"))
    plan_id = _stable_id("PLAN", plan_seed)
    batch_prefix = plan_id.split("-", 1)[1][:6]
    batches = []
    batch_by_work_unit: dict[str, str] = {}
    for index, packed_work_units in enumerate(packed, start=1):
        batch_id = f"B-{batch_prefix}-{index:04d}"
        ids = tuple(sorted(item.work_unit_id for item in packed_work_units))
        batch_by_work_unit.update({work_unit_id: batch_id for work_unit_id in ids})
        batches.append(PlannedBatch(
            batch_id=batch_id,
            work_unit_ids=ids,
            source_file_count=sum(len(item.source_files) for item in packed_work_units),
            dependencies=(),
            required_stages=REQUIRED_STAGES,
        ))

    units_by_component: dict[str, list[WorkUnit]] = {
        component_id: [] for component_id in known_components
    }
    for work_unit in work_units:
        units_by_component[work_unit.component_id].append(work_unit)
    for units in units_by_component.values():
        units.sort(key=lambda item: item.work_unit_id)

    handoffs = []
    owned_edges = []
    for edge in sorted(boundary_edges, key=lambda item: item.edge_id):
        source_unit = units_by_component[edge.source_component_id][0]
        if edge.source_path:
            source_unit = next((
                unit for unit in units_by_component[edge.source_component_id]
                if edge.source_path in unit.source_files
            ), source_unit)
        target_unit = units_by_component[edge.target_component_id][0]
        owned_edges.append(replace(edge, owner_work_unit_id=target_unit.work_unit_id))
        from_batch = batch_by_work_unit[source_unit.work_unit_id]
        owner_batch = batch_by_work_unit[target_unit.work_unit_id]
        if from_batch != owner_batch:
            handoffs.append(Handoff(
                handoff_id=_stable_id("HO", plan_id, edge.edge_id),
                edge_id=edge.edge_id,
                from_batch=from_batch,
                owner_batch=owner_batch,
                status="OPEN",
            ))

    plan = AuditPlan(
        schema_version="1.0",
        plan_id=plan_id,
        campaign_id=campaign_id,
        snapshot_id=inventory.snapshot_id,
        inventory_digest=digest,
        category_families=categories,
        discovery_axes=axes,
        work_units=tuple(sorted(work_units, key=lambda item: item.work_unit_id)),
        batches=tuple(batches),
        handoffs=tuple(handoffs),
        boundary_edges=tuple(sorted(owned_edges, key=lambda item: item.edge_id)),
    )
    validate_plan(plan, inventory)
    return plan


def validate_plan(plan: AuditPlan, inventory: ProjectInventory) -> None:
    inventory_paths = [source_file.path for source_file in inventory.source_files]
    planned_paths = [path for unit in plan.work_units for path in unit.source_files]
    if len(planned_paths) != len(set(planned_paths)):
        raise ModelError("a source file is owned by multiple work units")
    if set(planned_paths) != set(inventory_paths):
        missing = sorted(set(inventory_paths) - set(planned_paths))
        extra = sorted(set(planned_paths) - set(inventory_paths))
        raise ModelError(f"plan source coverage mismatch: missing={missing}, extra={extra}")
    known_work_units = {unit.work_unit_id for unit in plan.work_units}
    planned_work_units = [unit for batch in plan.batches for unit in batch.work_unit_ids]
    if len(planned_work_units) != len(set(planned_work_units)):
        raise ModelError("a work unit is assigned to multiple batches")
    if set(planned_work_units) != known_work_units:
        raise ModelError("batch work unit coverage mismatch")
    known_batches = {batch.batch_id for batch in plan.batches}
    for edge in plan.boundary_edges:
        if edge.owner_work_unit_id not in known_work_units:
            raise ModelError(f"boundary edge has no owning Work Unit: {edge.edge_id}")
    for handoff in plan.handoffs:
        if handoff.from_batch not in known_batches or handoff.owner_batch not in known_batches:
            raise ModelError(f"handoff references unknown batch: {handoff.handoff_id}")
        if handoff.from_batch == handoff.owner_batch:
            raise ModelError(f"handoff is not cross-batch: {handoff.handoff_id}")


def batch_manifest(plan: AuditPlan, batch: PlannedBatch) -> dict[str, object]:
    units = {unit.work_unit_id: unit for unit in plan.work_units if unit.work_unit_id in batch.work_unit_ids}
    return {
        "schema_version": "1.0",
        "plan_id": plan.plan_id,
        "batch_id": batch.batch_id,
        "work_unit_ids": list(batch.work_unit_ids),
        "source_file_count": batch.source_file_count,
        "dependencies": list(batch.dependencies),
        "required_stages": list(batch.required_stages),
        "work_units": [asdict(units[work_unit_id]) for work_unit_id in batch.work_unit_ids],
        "handoff_ids": [
            handoff.handoff_id for handoff in plan.handoffs
            if batch.batch_id in (handoff.from_batch, handoff.owner_batch)
        ],
    }


def amend_plan(
    base_plan: AuditPlan,
    *,
    reason: str,
    max_source_files_per_batch: int,
    max_work_units_per_batch: int,
) -> tuple[AuditPlan, PlanAmendment]:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ModelError("Plan Amendment reason is required")
    if min(max_source_files_per_batch, max_work_units_per_batch) <= 0:
        raise ModelError("amendment planner limits must be positive")
    oversized = [
        unit.work_unit_id
        for unit in base_plan.work_units
        if len(unit.source_files) > max_source_files_per_batch
    ]
    if oversized:
        raise ModelError(
            "amendment cannot split Work Units; batch file limit is too small for "
            + ", ".join(oversized)
        )

    packed: list[list[WorkUnit]] = []
    ordered_units = sorted(
        base_plan.work_units,
        key=lambda unit: (-len(unit.source_files), unit.work_unit_id),
    )
    for work_unit in ordered_units:
        destination = next((
            batch for batch in packed
            if len(batch) < max_work_units_per_batch
            and sum(len(item.source_files) for item in batch) + len(work_unit.source_files)
            <= max_source_files_per_batch
        ), None)
        if destination is None:
            destination = []
            packed.append(destination)
        destination.append(work_unit)

    plan_id = _stable_id(
        "PLAN",
        base_plan.plan_id,
        "amendment",
        str(max_source_files_per_batch),
        str(max_work_units_per_batch),
    )
    batch_prefix = plan_id.split("-", 1)[1][:6]
    batches = []
    batch_by_work_unit: dict[str, str] = {}
    for index, packed_work_units in enumerate(packed, start=1):
        batch_id = f"B-{batch_prefix}-{index:04d}"
        work_unit_ids = tuple(sorted(unit.work_unit_id for unit in packed_work_units))
        batch_by_work_unit.update({item: batch_id for item in work_unit_ids})
        batches.append(PlannedBatch(
            batch_id=batch_id,
            work_unit_ids=work_unit_ids,
            source_file_count=sum(len(unit.source_files) for unit in packed_work_units),
            dependencies=(),
            required_stages=REQUIRED_STAGES,
        ))

    units_by_component: dict[str, list[WorkUnit]] = {}
    for work_unit in base_plan.work_units:
        units_by_component.setdefault(work_unit.component_id, []).append(work_unit)
    for units in units_by_component.values():
        units.sort(key=lambda item: item.work_unit_id)
    handoffs = []
    for edge in base_plan.boundary_edges:
        source_unit = units_by_component[edge.source_component_id][0]
        if edge.source_path:
            source_unit = next(
                unit
                for unit in units_by_component[edge.source_component_id]
                if edge.source_path in unit.source_files
            )
        target_unit = units_by_component[edge.target_component_id][0]
        from_batch = batch_by_work_unit[source_unit.work_unit_id]
        owner_batch = batch_by_work_unit[target_unit.work_unit_id]
        if from_batch != owner_batch:
            handoffs.append(Handoff(
                handoff_id=_stable_id("HO", plan_id, edge.edge_id),
                edge_id=edge.edge_id,
                from_batch=from_batch,
                owner_batch=owner_batch,
                status="OPEN",
            ))

    amended_plan = AuditPlan(
        schema_version=base_plan.schema_version,
        plan_id=plan_id,
        campaign_id=base_plan.campaign_id,
        snapshot_id=base_plan.snapshot_id,
        inventory_digest=base_plan.inventory_digest,
        category_families=base_plan.category_families,
        discovery_axes=base_plan.discovery_axes,
        work_units=base_plan.work_units,
        batches=tuple(batches),
        handoffs=tuple(handoffs),
        boundary_edges=base_plan.boundary_edges,
    )

    new_batches_by_work_unit = {
        work_unit_id: batch.batch_id
        for batch in amended_plan.batches
        for work_unit_id in batch.work_unit_ids
    }
    replacements = tuple(BatchReplacement(
        retired_batch_id=batch.batch_id,
        replacement_batch_ids=tuple(sorted({
            new_batches_by_work_unit[work_unit_id]
            for work_unit_id in batch.work_unit_ids
        })),
    ) for batch in base_plan.batches)
    amendment = PlanAmendment(
        schema_version="1.0",
        amendment_id=_stable_id(
            "AMD", base_plan.plan_id, amended_plan.plan_id, normalized_reason
        ),
        campaign_id=base_plan.campaign_id,
        base_plan_id=base_plan.plan_id,
        amended_plan_id=amended_plan.plan_id,
        reason=normalized_reason,
        preserved_work_unit_ids=tuple(sorted(
            unit.work_unit_id for unit in base_plan.work_units
        )),
        batch_replacements=replacements,
    )
    return amended_plan, amendment
