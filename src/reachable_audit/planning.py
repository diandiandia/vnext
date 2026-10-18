"""Deterministic Work Unit, Batch, and Handoff planning."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from .models import ModelError
from .plan_models import (
    AuditPlan,
    BatchReplacement,
    BoundaryEdge,
    Handoff,
    PlanAmendment,
    PlannedBatch,
    PlanPathDisposition,
    PlanPathState,
    ProjectInventory,
    WorkUnit,
)
from .runtime_policy import TASK_OUTPUT_MAX_BYTES


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
    """Estimate a minimal valid R1 JSON result, including each mandatory boundary review."""
    shortest_path = min(work_unit.source_files, key=len, default="")
    output = {
        "schema_version": "1.0",
        "reviewed_scope": "ALL_SOURCE_FILES",
        "surfaces": [],
        "boundary_reviews": [
            {
                "edge_id": edge_id,
                "work_unit_id": work_unit.work_unit_id,
                "disposition": "unresolved",
                "evidence_refs": [f"LOC-{shortest_path}:1"],
                "rationale": "x",
            }
            for edge_id in work_unit.boundary_edge_ids
        ],
    }
    return len(json.dumps(
        output, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8"))


def _largest_boundary_edge_prefix(
    work_unit: WorkUnit, edge_ids: Sequence[str], offset: int,
) -> int:
    low = 0
    high = len(edge_ids) - offset
    while low < high:
        middle = (low + high + 1) // 2
        candidate = replace(
            work_unit,
            boundary_edge_ids=tuple(edge_ids[offset:offset + middle]),
        )
        if discovery_output_floor_bytes(candidate) <= TASK_OUTPUT_MAX_BYTES:
            low = middle
        else:
            high = middle - 1
    return low


def _validate_boundary_edge_endpoints(
    boundary_edges: Sequence[BoundaryEdge],
    known_components: set[str],
    source_owner_by_path: Mapping[str, str],
) -> None:
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
        if edge.target_path and source_owner_by_path.get(edge.target_path) != edge.target_component_id:
            raise ModelError(
                f"boundary target path is not owned by target component: {edge.edge_id}"
            )


_FORECAST_BASE_OPERATIONS = (
    "discover_surfaces", "generate_hypotheses_compact", "verify_reachability",
    "refute_reachability", "adjudicate_refutations", "assess_experiment",
    "collect_batch_closure_evidence",
)


def _r4_task_count(units: Sequence[WorkUnit], bundle_size: int) -> int:
    plans_by_family: dict[str, int] = {}
    for unit in units:
        for family in unit.category_families:
            plans_by_family[family] = plans_by_family.get(family, 0) + 1
    return sum(math.ceil(count / bundle_size) for count in plans_by_family.values())


def forecast_plan_cost(plan: AuditPlan, profile: Mapping[str, Any]) -> dict[str, Any]:
    """Forecast task fanout/cost from explicit assumptions and caller-measured task rates."""
    profile_id = profile.get("profile_id")
    currency = profile.get("currency")
    assumptions = profile.get("assumptions")
    rates = profile.get("cost_per_task")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ModelError("cost profile requires a non-empty profile_id")
    if not isinstance(currency, str) or not currency.strip():
        raise ModelError("cost profile requires a currency label")
    if not isinstance(assumptions, dict) or not isinstance(rates, dict):
        raise ModelError("cost profile requires assumptions and cost_per_task objects")
    hypotheses_per_unit = assumptions.get("hypotheses_per_work_unit")
    if not isinstance(hypotheses_per_unit, dict) or set(hypotheses_per_unit) != {
        "low", "expected", "high",
    }:
        raise ModelError("hypotheses_per_work_unit requires low, expected, and high")
    hypothesis_rates = {}
    for label, value in hypotheses_per_unit.items():
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ModelError(f"invalid hypotheses_per_work_unit.{label}")
        hypothesis_rates[label] = float(value)
    if not hypothesis_rates["low"] <= hypothesis_rates["expected"] <= hypothesis_rates["high"]:
        raise ModelError("hypothesis scenario rates must satisfy low <= expected <= high")
    reachable_fraction = assumptions.get("reachable_fraction")
    if (
        not isinstance(reachable_fraction, (int, float))
        or not math.isfinite(reachable_fraction)
        or not 0 <= reachable_fraction <= 1
    ):
        raise ModelError("reachable_fraction must be between 0 and 1")
    bundle_size = assumptions.get("r4_bundle_work_units_per_task", 1)
    if not isinstance(bundle_size, int) or bundle_size < 1:
        raise ModelError("r4_bundle_work_units_per_task must be a positive integer")
    r4_operation = "run_category_audit_bundle" if bundle_size > 1 else "run_category_audit"
    operations = (*_FORECAST_BASE_OPERATIONS, r4_operation)
    missing_rates = sorted(set(operations) - set(rates))
    if missing_rates:
        raise ModelError(f"cost profile missing cost_per_task rates: {missing_rates}")
    for operation in operations:
        rate = rates[operation]
        if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
            raise ModelError(f"invalid cost_per_task rate for {operation}")

    units_by_batch = {
        batch.batch_id: [
            unit for unit in plan.work_units if unit.work_unit_id in batch.work_unit_ids
        ] for batch in plan.batches
    }

    def task_counts(units: Sequence[WorkUnit], hypothesis_rate: float, *, include_r6: bool) -> dict[str, int]:
        hypotheses = math.ceil(len(units) * hypothesis_rate)
        reachable = math.ceil(hypotheses * float(reachable_fraction))
        counts = {
            "discover_surfaces": len(units),
            "generate_hypotheses_compact": len(units),
            r4_operation: _r4_task_count(units, bundle_size),
            "verify_reachability": hypotheses,
            "refute_reachability": 2 * reachable,
            "adjudicate_refutations": reachable,
            "assess_experiment": hypotheses,
        }
        if include_r6:
            counts["collect_batch_closure_evidence"] = 1
        return counts

    total_units = len(plan.work_units)
    fixed_task_counts = {
        "discover_surfaces": total_units,
        "generate_hypotheses_compact": total_units,
        "run_category_audit_plan_upper_bound": sum(
            len(unit.category_families) for unit in plan.work_units
        ),
        "run_category_audit_task_upper_bound": sum(
            _r4_task_count(units, bundle_size) for units in units_by_batch.values()
        ),
        "collect_batch_closure_evidence": len(plan.batches),
        "omitted_empty_components": len(plan.omitted_empty_component_ids),
    }
    scenarios = {}
    for label, hypothesis_rate in hypothesis_rates.items():
        per_batch = {}
        for batch_id, units in units_by_batch.items():
            batch_counts = task_counts(units, hypothesis_rate, include_r6=True)
            per_batch[batch_id] = {
                "work_units": len(units),
                "estimated_hypotheses": math.ceil(len(units) * hypothesis_rate),
                "estimated_task_counts": batch_counts,
                "estimated_cost": round(sum(
                    batch_counts[op] * float(rates[op]) for op in operations
                ), 4),
            }
        counts = {
            operation: sum(
                batch["estimated_task_counts"][operation] for batch in per_batch.values()
            ) for operation in operations
        }
        scenarios[label] = {
            "hypotheses_per_work_unit": hypothesis_rate,
            "estimated_hypotheses": sum(batch["estimated_hypotheses"] for batch in per_batch.values()),
            "reachable_fraction": float(reachable_fraction),
            "estimated_task_counts": counts,
            "estimated_total_tasks": sum(counts.values()),
            "estimated_cost": round(sum(
                batch["estimated_cost"] for batch in per_batch.values()
            ), 4),
            "per_batch": per_batch,
        }
    return {
        "profile_id": profile_id,
        "currency": currency,
        "assumptions": assumptions,
        "fixed_task_counts": fixed_task_counts,
        "scenarios": scenarios,
        "limitations": [
            "R4 task counts are upper bounds; all-NOT_APPLICABLE plans can short-circuit.",
            "R3.5 revival reviews, retries, host repairs, and standalone findings tasks are not modeled.",
            "Hypothesis/reachability assumptions and measured per-task rates must match the host/model configuration.",
        ],
    }


def create_audit_plan(
    *,
    campaign_id: str,
    inventory: ProjectInventory,
    category_families: Sequence[str],
    boundary_edges: Sequence[BoundaryEdge] = (),
    path_dispositions: Sequence[PlanPathDisposition] = (),
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
    if set(axes) != set(DEFAULT_DISCOVERY_AXES):
        raise ModelError("only all-six discovery-axis plans are currently supported")
    if min(max_source_files_per_work_unit, max_source_files_per_batch, max_work_units_per_batch) <= 0:
        raise ModelError("planner limits must be positive")
    if max_source_files_per_work_unit > max_source_files_per_batch:
        raise ModelError("work unit file limit cannot exceed batch file limit")

    known_components = {component.component_id for component in inventory.components}
    if not known_components:
        raise ModelError("inventory must retain a root component for an empty repository")
    source_owner_by_path = {
        source_file.path: source_file.component_id for source_file in inventory.source_files
    }
    inventory_paths = {source_file.path for source_file in inventory.source_files}
    supplied_path_dispositions = {item.path: item for item in path_dispositions}
    if len(supplied_path_dispositions) != len(path_dispositions):
        raise ModelError("duplicate plan path dispositions")
    unknown_path_dispositions = set(supplied_path_dispositions) - inventory_paths
    if unknown_path_dispositions:
        raise ModelError(
            f"plan path disposition references unknown paths: "
            f"{sorted(unknown_path_dispositions)}"
        )
    normalized_path_dispositions = tuple(
        supplied_path_dispositions.get(
            source.path,
            PlanPathDisposition(
                source.path, PlanPathState.INCLUDED, "Included by default."
            ),
        )
        for source in sorted(inventory.source_files, key=lambda item: item.path)
    )
    path_state_by_path = {
        item.path: item.state for item in normalized_path_dispositions
    }
    _validate_boundary_edge_endpoints(
        boundary_edges, known_components, source_owner_by_path,
    )

    files_by_component: dict[str, list[tuple[str, str]]] = {
        component_id: [] for component_id in known_components
    }
    for source_file in inventory.source_files:
        if source_file.component_id not in known_components:
            raise ModelError(f"source file has unknown component owner: {source_file.path}")
        if path_state_by_path[source_file.path] is PlanPathState.INCLUDED:
            files_by_component[source_file.component_id].append(
                (source_file.path, source_file.language)
            )
    edges_by_component: dict[str, list[str]] = {
        component_id: [] for component_id in known_components
    }
    for edge in boundary_edges:
        edges_by_component[edge.source_component_id].append(edge.edge_id)
        edges_by_component[edge.target_component_id].append(edge.edge_id)

    components_by_id = {item.component_id: item for item in inventory.components}
    omitted_empty_component_ids = tuple(sorted(
        component_id
        for component_id, paths in files_by_component.items()
        if not paths
        and not components_by_id[component_id].build_manifests
        and not edges_by_component[component_id]
    ))
    if known_components and len(omitted_empty_component_ids) == len(known_components):
        omitted_empty_component_ids = omitted_empty_component_ids[1:]
    omitted_empty = set(omitted_empty_component_ids)

    work_units = []
    boundary_review_units: dict[tuple[str, str], WorkUnit] = {}
    for component_id in sorted(files_by_component):
        if component_id in omitted_empty:
            continue
        component_files = sorted(files_by_component[component_id])
        paths = [path for path, _ in component_files]
        languages_by_path = {path: language for path, language in component_files}
        file_chunks = tuple(_chunks(paths, max_source_files_per_work_unit)) or ((),)
        component_units = []
        for shard_index, file_chunk in enumerate(file_chunks, start=1):
            component_units.append(WorkUnit(
                work_unit_id=_stable_id("WU", inventory.snapshot_id, component_id, str(shard_index), *file_chunk),
                component_id=component_id,
                source_files=file_chunk,
                languages=tuple(sorted({languages_by_path[path] for path in file_chunk})),
                category_families=categories,
                discovery_axes=axes,
                boundary_edge_ids=(),
            ))
        component_edge_ids = tuple(sorted(edges_by_component[component_id]))
        edge_offset = 0
        for unit_index, unit in enumerate(component_units):
            fit_count = _largest_boundary_edge_prefix(
                unit, component_edge_ids, edge_offset,
            )
            component_units[unit_index] = replace(
                unit,
                boundary_edge_ids=component_edge_ids[
                    edge_offset:edge_offset + fit_count
                ],
            )
            edge_offset += fit_count

        boundary_shard_index = 0
        existing_unit_ids = {unit.work_unit_id for unit in component_units}
        while edge_offset < len(component_edge_ids):
            boundary_shard_index += 1
            boundary_work_unit = WorkUnit(
                work_unit_id=_stable_id(
                    "WU", inventory.snapshot_id, component_id,
                    "boundary", str(boundary_shard_index),
                ),
                component_id=component_id,
                source_files=(),
                languages=(),
                category_families=categories,
                discovery_axes=axes,
                boundary_edge_ids=(),
            )
            while boundary_work_unit.work_unit_id in existing_unit_ids:
                boundary_shard_index += 1
                boundary_work_unit = replace(
                    boundary_work_unit,
                    work_unit_id=_stable_id(
                        "WU", inventory.snapshot_id, component_id,
                        "boundary", str(boundary_shard_index),
                    ),
                )
            fit_count = _largest_boundary_edge_prefix(
                boundary_work_unit, component_edge_ids, edge_offset,
            )
            if fit_count == 0:
                fit_count = 1
            boundary_work_unit = replace(
                boundary_work_unit,
                boundary_edge_ids=component_edge_ids[
                    edge_offset:edge_offset + fit_count
                ],
            )
            component_units.append(boundary_work_unit)
            existing_unit_ids.add(boundary_work_unit.work_unit_id)
            edge_offset += fit_count

        for unit in component_units:
            work_units.append(unit)
            for edge_id in unit.boundary_edge_ids:
                boundary_review_units[(component_id, edge_id)] = unit

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
        "path_dispositions": [asdict(item) for item in normalized_path_dispositions],
        "omitted_empty_component_ids": omitted_empty_component_ids,
        "boundary_edge_sharding": "r1-minimum-output-floor-v1",
        "r1_output_ceiling_bytes": TASK_OUTPUT_MAX_BYTES,
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
        source_unit = boundary_review_units[(edge.source_component_id, edge.edge_id)]
        if edge.source_path:
            source_unit = next((
                unit for unit in units_by_component[edge.source_component_id]
                if edge.source_path in unit.source_files
            ), source_unit)
        target_unit = boundary_review_units[(edge.target_component_id, edge.edge_id)]
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
        omitted_empty_component_ids=omitted_empty_component_ids,
        path_dispositions=normalized_path_dispositions,
    )
    validate_plan(plan, inventory)
    return plan


def validate_plan(plan: AuditPlan, inventory: ProjectInventory) -> None:
    if plan.snapshot_id != inventory.snapshot_id:
        raise ModelError("plan snapshot does not match inventory")
    if plan.inventory_digest != inventory_digest(inventory):
        raise ModelError("plan inventory digest does not match inventory")
    components = {component.component_id: component for component in inventory.components}
    source_owner_by_path = {
        source.path: source.component_id for source in inventory.source_files
    }
    _validate_boundary_edge_endpoints(
        plan.boundary_edges, set(components), source_owner_by_path,
    )
    omitted = set(plan.omitted_empty_component_ids)
    if len(omitted) != len(plan.omitted_empty_component_ids):
        raise ModelError("plan duplicates omitted empty component IDs")
    unknown_omissions = omitted - set(components)
    if unknown_omissions:
        raise ModelError(f"plan omits unknown components: {sorted(unknown_omissions)}")
    boundary_components = {
        component_id
        for edge in plan.boundary_edges
        for component_id in (edge.source_component_id, edge.target_component_id)
    }
    path_state_by_path = {
        item.path: item.state for item in plan.path_dispositions
    }
    inventory_paths = {source.path for source in inventory.source_files}
    if len(path_state_by_path) != len(plan.path_dispositions):
        raise ModelError("plan duplicates path disposition records")
    if set(path_state_by_path) != inventory_paths:
        raise ModelError("plan path disposition coverage does not match inventory")
    source_components = {
        source.component_id for source in inventory.source_files
        if path_state_by_path[source.path] is PlanPathState.INCLUDED
    }
    invalid_omissions = sorted(
        component_id for component_id in omitted
        if components[component_id].build_manifests
        or component_id in boundary_components
        or component_id in source_components
    )
    if invalid_omissions:
        raise ModelError(
            f"plan omits components with analysis obligations: {invalid_omissions}"
        )
    planned_components = {unit.component_id for unit in plan.work_units}
    unassigned_components = set(components) - planned_components
    if unassigned_components != omitted:
        raise ModelError(
            "plan component ownership mismatch: "
            f"unassigned={sorted(unassigned_components)}, declared_omitted={sorted(omitted)}"
        )
    inventory_paths = {
        source.path for source in inventory.source_files
        if path_state_by_path[source.path] is PlanPathState.INCLUDED
    }
    source_owner_by_path = {
        source.path: source.component_id for source in inventory.source_files
    }
    planned_paths = [path for unit in plan.work_units for path in unit.source_files]
    if len(planned_paths) != len(set(planned_paths)):
        raise ModelError("a source file is owned by multiple work units")
    if set(planned_paths) != inventory_paths:
        missing = sorted(inventory_paths - set(planned_paths))
        extra = sorted(set(planned_paths) - inventory_paths)
        raise ModelError(f"plan source coverage mismatch: missing={missing}, extra={extra}")
    for unit in plan.work_units:
        if unit.component_id not in components:
            raise ModelError(f"Work Unit references an unknown component: {unit.work_unit_id}")
        wrong_owner_paths = [
            path for path in unit.source_files
            if source_owner_by_path.get(path) != unit.component_id
        ]
        if wrong_owner_paths:
            raise ModelError(
                f"Work Unit source paths are not owned by its component: {sorted(wrong_owner_paths)}"
            )
    known_work_units = {unit.work_unit_id for unit in plan.work_units}
    planned_work_units = [unit for batch in plan.batches for unit in batch.work_unit_ids]
    if len(planned_work_units) != len(set(planned_work_units)):
        raise ModelError("a work unit is assigned to multiple batches")
    if set(planned_work_units) != known_work_units:
        raise ModelError("batch work unit coverage mismatch")
    work_units_by_id = {unit.work_unit_id: unit for unit in plan.work_units}
    edges_by_id = {edge.edge_id: edge for edge in plan.boundary_edges}
    if len(edges_by_id) != len(plan.boundary_edges):
        raise ModelError("plan duplicates boundary edge IDs")
    expected_edge_reviews = {
        (component_id, edge.edge_id)
        for edge in plan.boundary_edges
        for component_id in (edge.source_component_id, edge.target_component_id)
    }
    actual_edge_reviews: dict[tuple[str, str], int] = {}
    edge_review_units: dict[tuple[str, str], WorkUnit] = {}
    for unit in plan.work_units:
        for edge_id in unit.boundary_edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                raise ModelError(
                    f"Work Unit references unknown boundary edge: {edge_id}"
                )
            if unit.component_id not in {
                edge.source_component_id, edge.target_component_id,
            }:
                raise ModelError(
                    f"Work Unit is not an endpoint for boundary edge: {edge_id}"
                )
            key = (unit.component_id, edge_id)
            actual_edge_reviews[key] = actual_edge_reviews.get(key, 0) + 1
            edge_review_units[key] = unit
    if (
        set(actual_edge_reviews) != expected_edge_reviews
        or any(count != 1 for count in actual_edge_reviews.values())
    ):
        raise ModelError("boundary edge review coverage must be exact per endpoint")
    known_batches = {batch.batch_id for batch in plan.batches}
    batch_by_work_unit = {
        work_unit_id: batch.batch_id
        for batch in plan.batches
        for work_unit_id in batch.work_unit_ids
    }
    for edge in plan.boundary_edges:
        if edge.owner_work_unit_id not in known_work_units:
            raise ModelError(f"boundary edge has no owning Work Unit: {edge.edge_id}")
        owner = work_units_by_id[edge.owner_work_unit_id]
        target_review_unit = edge_review_units[
            (edge.target_component_id, edge.edge_id)
        ]
        if (
            owner.component_id != edge.target_component_id
            or owner.work_unit_id != target_review_unit.work_unit_id
        ):
            raise ModelError(
                f"boundary edge owner is not its target review Work Unit: {edge.edge_id}"
            )
    handoff_by_edge = {handoff.edge_id: handoff for handoff in plan.handoffs}
    if len(handoff_by_edge) != len(plan.handoffs):
        raise ModelError("plan duplicates Handoffs for a boundary edge")
    expected_handoff_routes: dict[str, tuple[str, str]] = {}
    for edge in plan.boundary_edges:
        source_unit = edge_review_units[(edge.source_component_id, edge.edge_id)]
        if edge.source_path:
            source_unit = next((
                unit for unit in plan.work_units
                if unit.component_id == edge.source_component_id
                and edge.source_path in unit.source_files
            ), source_unit)
        target_unit = edge_review_units[(edge.target_component_id, edge.edge_id)]
        source_batch = batch_by_work_unit[source_unit.work_unit_id]
        owner_batch = batch_by_work_unit[target_unit.work_unit_id]
        if source_batch != owner_batch:
            expected_handoff_routes[edge.edge_id] = (source_batch, owner_batch)
    if set(handoff_by_edge) != set(expected_handoff_routes):
        raise ModelError("plan Handoff coverage does not match cross-Batch boundary edges")
    handoff_ids = [handoff.handoff_id for handoff in plan.handoffs]
    if len(handoff_ids) != len(set(handoff_ids)):
        raise ModelError("plan duplicates Handoff IDs")
    for handoff in plan.handoffs:
        if handoff.status != "OPEN":
            raise ModelError(f"planned Handoff status must be OPEN: {handoff.handoff_id}")
        if handoff.from_batch not in known_batches or handoff.owner_batch not in known_batches:
            raise ModelError(f"handoff references unknown batch: {handoff.handoff_id}")
        if handoff.from_batch == handoff.owner_batch:
            raise ModelError(f"handoff is not cross-batch: {handoff.handoff_id}")
        if handoff.edge_id not in expected_handoff_routes:
            raise ModelError(f"Handoff references a non-cross-Batch edge: {handoff.edge_id}")
        if (handoff.from_batch, handoff.owner_batch) != expected_handoff_routes[handoff.edge_id]:
            raise ModelError(f"Handoff route does not match boundary ownership: {handoff.edge_id}")


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
    work_units_by_id = {unit.work_unit_id: unit for unit in base_plan.work_units}
    handoffs = []
    for edge in base_plan.boundary_edges:
        source_unit = next((
            unit for unit in units_by_component.get(edge.source_component_id, [])
            if edge.edge_id in unit.boundary_edge_ids
        ), None)
        if source_unit is None:
            raise ModelError(
                f"base Plan has no source review Work Unit for edge: {edge.edge_id}"
            )
        if edge.owner_work_unit_id not in work_units_by_id:
            raise ModelError(
                f"base Plan has no target review Work Unit for edge: {edge.edge_id}"
            )
        target_unit = work_units_by_id[edge.owner_work_unit_id]
        if target_unit.component_id != edge.target_component_id or edge.edge_id not in target_unit.boundary_edge_ids:
            raise ModelError(
                f"base Plan target owner is not the review Work Unit for edge: {edge.edge_id}"
            )
        if edge.source_path:
            source_unit = next((
                unit
                for unit in units_by_component.get(edge.source_component_id, [])
                if edge.source_path in unit.source_files
            ), source_unit)
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
        omitted_empty_component_ids=base_plan.omitted_empty_component_ids,
        path_dispositions=base_plan.path_dispositions,
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
