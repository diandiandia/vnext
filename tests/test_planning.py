from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from reachable_audit.plan_models import (
    BoundaryEdge,
    ComponentGraph,
    Component,
    PlanPathDisposition,
    PlanPathState,
)
from reachable_audit.planning import (
    amend_plan,
    create_audit_plan,
    discovery_output_floor_bytes,
    forecast_plan_cost,
    validate_plan,
)
from reachable_audit.runtime_policy import TASK_OUTPUT_MAX_BYTES


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_monorepo(root: Path) -> None:
    _write(root / "services" / "api" / "pyproject.toml", "[project]\nname='api'\n")
    _write(root / "services" / "api" / "main.py", "print('api')\n")
    _write(root / "libs" / "core" / "Cargo.toml", "[package]\nname='core'\n")
    _write(root / "libs" / "core" / "src" / "lib.rs", "pub fn parse() {}\n")
    _write(root / "libs" / "core" / "src" / "state.rs", "pub struct State;\n")
    _write(root / "tools" / "go.mod", "module example/tools\n")
    _write(root / "tools" / "main.go", "package main\n")
    _write(root / "node_modules" / "ignored.js", "ignored\n")


def test_inventory_assigns_each_source_to_deepest_build_component(tmp_path: Path) -> None:
    target = tmp_path / "monorepo"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:mono")
    roots = {component.root: component for component in inventory.components}
    assert set(roots) == {"services/api", "libs/core", "tools"}
    assert roots["services/api"].languages == ("python",)
    assert roots["libs/core"].source_file_count == 2
    assert {source.path for source in inventory.source_files} == {
        "services/api/main.py", "libs/core/src/lib.rs", "libs/core/src/state.rs", "tools/main.go",
    }
    assert "node_modules" in inventory.skipped_directories
    assert inventory.repository_size_bytes == sum(
        path.stat().st_size for path in target.rglob("*") if path.is_file()
    )


def test_inventory_uses_root_component_when_no_build_manifest_exists(tmp_path: Path) -> None:
    target = tmp_path / "scripts"
    target.mkdir()
    _write(target / "jobs" / "cleanup.py", "print('clean')\n")

    inventory = build_inventory(target, "fixture:fallback")

    assert len(inventory.components) == 1
    assert inventory.components[0].root == "."
    assert inventory.components[0].build_manifests == ()
    assert inventory.source_files[0].component_id == inventory.components[0].component_id


def test_empty_repository_retains_one_planned_work_unit(tmp_path: Path) -> None:
    inventory = build_inventory(tmp_path, "fixture:empty-root")
    plan = create_audit_plan(
        campaign_id="CMP-empty-root", inventory=inventory, category_families=["STATE"],
    )
    assert len(inventory.components) == 1
    assert inventory.components[0].root == "."
    assert len(plan.work_units) == len(plan.batches) == 1
    assert plan.work_units[0].source_files == ()
    assert plan.omitted_empty_component_ids == ()
    with pytest.raises(ModelError, match="root component"):
        create_audit_plan(
            campaign_id="CMP-invalid-empty", inventory=replace(inventory, components=()),
            category_families=["STATE"],
        )


def test_validate_plan_binds_plan_to_inventory_snapshot_and_digest(
    tmp_path: Path,
) -> None:
    target = tmp_path / "inventory-binding"
    target.mkdir()
    _write(target / "app.py", "VALUE = 1\n")
    inventory = build_inventory(target, "fixture:inventory-binding")
    plan = create_audit_plan(
        campaign_id="CMP-inventory-binding",
        inventory=inventory,
        category_families=["STATE"],
    )

    changed_inventory = replace(
        inventory,
        source_files=(replace(inventory.source_files[0], language="rust"),),
    )
    with pytest.raises(ModelError, match="inventory digest does not match"):
        validate_plan(plan, changed_inventory)

    other_snapshot = replace(inventory, snapshot_id="fixture:other-snapshot")
    with pytest.raises(ModelError, match="snapshot does not match"):
        validate_plan(plan, other_snapshot)


def test_validate_plan_rejects_duplicate_inventory_component_ids(
    tmp_path: Path,
) -> None:
    target = tmp_path / "duplicate-component-ids"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:duplicate-component-ids")
    duplicated_inventory = replace(
        inventory,
        components=(*inventory.components, inventory.components[0]),
    )

    with pytest.raises(ModelError, match="inventory duplicates component IDs"):
        create_audit_plan(
            campaign_id="CMP-duplicate-component-ids",
            inventory=duplicated_inventory,
            category_families=["STATE"],
        )


def test_validate_plan_rejects_inconsistent_inventory_summaries(tmp_path: Path) -> None:
    target = tmp_path / "inventory-summaries"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:inventory-summaries")
    with pytest.raises(ModelError, match="component source_file_count"):
        create_audit_plan(
            campaign_id="CMP-bad-component-count",
            inventory=replace(
                inventory,
                components=(replace(
                    inventory.components[0],
                    source_file_count=inventory.components[0].source_file_count + 1,
                ), *inventory.components[1:]),
            ),
            category_families=["STATE"],
        )

    with pytest.raises(ModelError, match="component languages"):
        create_audit_plan(
            campaign_id="CMP-bad-component-languages",
            inventory=replace(
                inventory,
                components=(replace(
                    inventory.components[0], languages=("unknown",),
                ), *inventory.components[1:]),
            ),
            category_families=["STATE"],
        )

    with pytest.raises(ModelError, match="duplicates source paths"):
        create_audit_plan(
            campaign_id="CMP-duplicate-source-path",
            inventory=replace(
                inventory,
                source_files=(*inventory.source_files, inventory.source_files[0]),
            ),
            category_families=["STATE"],
        )


def test_validate_plan_binds_work_unit_paths_to_component_owners(
    tmp_path: Path,
) -> None:
    target = tmp_path / "work-unit-owners"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:work-unit-owners")
    plan = create_audit_plan(
        campaign_id="CMP-work-unit-owners",
        inventory=inventory,
        category_families=["STATE"],
    )
    first_unit, second_unit = plan.work_units[:2]
    swapped_owners = replace(
        plan,
        work_units=tuple(
            replace(unit, component_id=(
                second_unit.component_id
                if unit.work_unit_id == first_unit.work_unit_id
                else first_unit.component_id
            ))
            if unit.work_unit_id in {
                first_unit.work_unit_id, second_unit.work_unit_id,
            }
            else unit
            for unit in plan.work_units
        ),
    )

    with pytest.raises(ModelError, match="source paths are not owned by its component"):
        validate_plan(swapped_owners, inventory)


def test_validate_plan_rejects_duplicate_work_unit_and_batch_ids(
    tmp_path: Path,
) -> None:
    target = tmp_path / "duplicate-plan-ids"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:duplicate-plan-ids")
    plan = create_audit_plan(
        campaign_id="CMP-duplicate-plan-ids",
        inventory=inventory,
        category_families=["STATE"],
        max_source_files_per_work_unit=1,
        max_work_units_per_batch=1,
    )
    assert len(plan.work_units) > 1
    assert len(plan.batches) > 1

    duplicate_work_unit = replace(
        plan,
        work_units=(*plan.work_units[:-1], plan.work_units[0]),
    )
    with pytest.raises(ModelError, match="duplicates Work Unit IDs"):
        validate_plan(duplicate_work_unit, inventory)

    duplicate_batch = replace(
        plan,
        batches=(*plan.batches[:-1], plan.batches[0]),
    )
    with pytest.raises(ModelError, match="duplicates Batch IDs"):
        validate_plan(duplicate_batch, inventory)


def test_validate_plan_checks_work_unit_analysis_metadata(tmp_path: Path) -> None:
    target = tmp_path / "work-unit-metadata"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:work-unit-metadata")
    plan = create_audit_plan(
        campaign_id="CMP-work-unit-metadata",
        inventory=inventory,
        category_families=["STATE", "PARSING"],
    )

    with pytest.raises(ModelError, match="all-six discovery-axis"):
        validate_plan(replace(plan, discovery_axes=("surface",)), inventory)

    first_unit = plan.work_units[0]
    changed_unit_axes = replace(
        plan,
        work_units=tuple(
            replace(unit, discovery_axes=("surface",))
            if unit.work_unit_id == first_unit.work_unit_id else unit
            for unit in plan.work_units
        ),
    )
    with pytest.raises(ModelError, match="Work Unit discovery axes do not match"):
        validate_plan(changed_unit_axes, inventory)

    changed_languages = replace(
        plan,
        work_units=tuple(
            replace(unit, languages=("c",))
            if unit.work_unit_id == first_unit.work_unit_id else unit
            for unit in plan.work_units
        ),
    )
    with pytest.raises(ModelError, match="Work Unit languages do not match"):
        validate_plan(changed_languages, inventory)

    changed_categories = replace(
        plan,
        work_units=tuple(
            replace(unit, category_families=("INJECTION",))
            if unit.work_unit_id == first_unit.work_unit_id else unit
            for unit in plan.work_units
        ),
    )
    with pytest.raises(ModelError, match="Work Unit category families do not match"):
        validate_plan(changed_categories, inventory)


def test_validate_plan_checks_batch_source_file_count(tmp_path: Path) -> None:
    target = tmp_path / "batch-source-count"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:batch-source-count")
    plan = create_audit_plan(
        campaign_id="CMP-batch-source-count",
        inventory=inventory,
        category_families=["STATE"],
        max_source_files_per_work_unit=1,
        max_work_units_per_batch=1,
    )
    batch = plan.batches[0]
    incorrect_count = replace(
        plan,
        batches=(
            replace(batch, source_file_count=batch.source_file_count + 1),
            *plan.batches[1:],
        ),
    )

    with pytest.raises(ModelError, match="source_file_count does not match"):
        validate_plan(incorrect_count, inventory)

    incorrect_stages = replace(
        plan,
        batches=(replace(batch, required_stages=("R0", "R1")), *plan.batches[1:]),
    )
    with pytest.raises(ModelError, match="required_stages do not match"):
        validate_plan(incorrect_stages, inventory)


def test_worktree_footprint_excludes_symlinks_and_runtime_state(tmp_path: Path) -> None:
    (tmp_path / "payload.txt").write_text("abc", encoding="utf-8")
    (tmp_path / "shortcut").symlink_to("payload.txt")
    (tmp_path / "dangling").symlink_to("missing")
    (tmp_path / ".audit_vnext").mkdir()
    (tmp_path / ".audit_vnext" / "state").write_bytes(b"runtime data")
    assert build_inventory(tmp_path, "fixture:footprint").repository_size_bytes == 3


@pytest.mark.parametrize("axes", [("surface",), ("surface", "unknown")])
def test_planner_rejects_unsupported_axis_subsets(tmp_path: Path, axes: tuple[str, ...]) -> None:
    with pytest.raises(ModelError, match="all-six"):
        create_audit_plan(
            campaign_id="CMP-axes", inventory=build_inventory(tmp_path, "fixture:axes"),
            category_families=["STATE"], discovery_axes=axes,
        )


def test_manifest_only_component_has_a_unique_planned_owner(tmp_path: Path) -> None:
    target = tmp_path / "workspace"
    target.mkdir()
    _write(target / "empty" / "pyproject.toml", "[project]\nname='empty'\n")

    inventory = build_inventory(target, "fixture:manifest-only")
    plan = create_audit_plan(
        campaign_id="CMP-manifest-only",
        inventory=inventory,
        category_families=["STATE"],
    )

    assert len(inventory.components) == 1
    assert inventory.components[0].source_file_count == 0
    assert len(plan.work_units) == 1
    assert plan.work_units[0].component_id == inventory.components[0].component_id
    assert plan.work_units[0].source_files == ()
    assert plan.batches[0].work_unit_ids == (plan.work_units[0].work_unit_id,)


def test_plan_omits_only_empty_components_without_analysis_obligations(
    tmp_path: Path,
) -> None:
    target = tmp_path / "components"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:empty-components")
    empty = Component("COMP-empty", "unused", (), (), 0)
    inventory = replace(inventory, components=(*inventory.components, empty))

    plan = create_audit_plan(
        campaign_id="CMP-empty-component",
        inventory=inventory,
        category_families=["STATE"],
    )

    assert plan.omitted_empty_component_ids == ("COMP-empty",)
    assert "COMP-empty" not in {unit.component_id for unit in plan.work_units}
    assert {path for unit in plan.work_units for path in unit.source_files} == {
        source.path for source in inventory.source_files
    }

    target_component = next(
        item.component_id for item in inventory.components if item.root == "tools"
    )
    edge_plan = create_audit_plan(
        campaign_id="CMP-empty-component-edge",
        inventory=inventory,
        category_families=["STATE"],
        boundary_edges=[BoundaryEdge(
            "EDGE-empty-tools", "COMP-empty", target_component, "ipc",
            "empty component still owns a boundary obligation",
        )],
    )
    assert edge_plan.omitted_empty_component_ids == ()
    empty_owner = next(
        unit for unit in edge_plan.work_units if unit.component_id == "COMP-empty"
    )
    assert empty_owner.source_files == ()
    assert empty_owner.boundary_edge_ids == ("EDGE-empty-tools",)


def test_plan_retains_one_work_unit_when_all_components_are_empty(tmp_path: Path) -> None:
    target = tmp_path / "components"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:all-empty-components")
    empty = Component("COMP-empty", "unused", (), (), 0)
    inventory = replace(inventory, source_files=(), components=(empty,))

    plan = create_audit_plan(
        campaign_id="CMP-all-empty",
        inventory=inventory,
        category_families=["STATE"],
    )

    assert len(plan.work_units) == 1
    assert plan.work_units[0].component_id == "COMP-empty"
    assert plan.omitted_empty_component_ids == ()


def test_plan_has_exact_ownership_limits_and_cross_batch_handoff(tmp_path: Path) -> None:
    target = tmp_path / "monorepo"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:mono")
    components = {component.root: component.component_id for component in inventory.components}
    edge = BoundaryEdge(
        edge_id="EDGE-api-core",
        source_component_id=components["services/api"],
        target_component_id=components["libs/core"],
        kind="ffi",
        evidence="fixture boundary",
        source_path="services/api/main.py",
    )
    plan = create_audit_plan(
        campaign_id="CMP-plan",
        inventory=inventory,
        category_families=["memory-safety", "state"],
        boundary_edges=[edge],
        max_source_files_per_work_unit=1,
        max_source_files_per_batch=2,
        max_work_units_per_batch=1,
    )
    owned_paths = [path for unit in plan.work_units for path in unit.source_files]
    assert sorted(owned_paths) == sorted(source.path for source in inventory.source_files)
    assert len(owned_paths) == len(set(owned_paths))
    assert all(batch.source_file_count <= 2 for batch in plan.batches)
    assert all(
        batch.required_stages == ("R0", "R1", "R2", "R3", "R3.5", "R4", "R5", "R6")
        for batch in plan.batches
    )
    assert len(plan.handoffs) == 1
    assert plan.handoffs[0].from_batch != plan.handoffs[0].owner_batch
    assert plan.discovery_axes == (
        "surface", "mechanism", "state", "fix_variant", "boundary", "differential"
    )
    handoff = plan.handoffs[0]
    unrelated_batch = next(
        batch.batch_id for batch in plan.batches
        if batch.batch_id not in {handoff.from_batch, handoff.owner_batch}
    )
    wrong_route = replace(
        plan,
        handoffs=(replace(handoff, owner_batch=unrelated_batch),),
    )
    with pytest.raises(ModelError, match="Handoff route does not match"):
        validate_plan(wrong_route, inventory)
    missing_route = replace(plan, handoffs=())
    with pytest.raises(ModelError, match="Handoff coverage does not match"):
        validate_plan(missing_route, inventory)
    terminal_handoff = replace(
        plan,
        handoffs=(replace(handoff, status="RESOLVED"),),
    )
    with pytest.raises(ModelError, match="planned Handoff status must be OPEN"):
        validate_plan(terminal_handoff, inventory)
    forged_handoff_id = replace(
        plan,
        handoffs=(replace(handoff, handoff_id="HO-forged"),),
    )
    with pytest.raises(ModelError, match="Handoff ID does not match its Plan and edge"):
        validate_plan(forged_handoff_id, inventory)
    amended_plan, _ = amend_plan(
        plan,
        reason="repack batches while preserving endpoint ownership",
        max_source_files_per_batch=1,
        max_work_units_per_batch=1,
    )
    validate_plan(amended_plan, inventory)


@pytest.mark.parametrize(
    ("path_field", "invalid_path", "error"),
    (
        ("source_path", "tools/main.go", "source path is not owned by source component"),
        ("target_path", "services/api/main.py", "target path is not owned by target component"),
    ),
)
def test_plan_rejects_boundary_endpoint_path_owned_by_other_component(
    tmp_path: Path, path_field: str, invalid_path: str, error: str,
) -> None:
    target = tmp_path / "endpoint-paths"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:endpoint-paths")
    components = {component.root: component.component_id for component in inventory.components}
    edge = BoundaryEdge(
        edge_id="EDGE-api-core",
        source_component_id=components["services/api"],
        target_component_id=components["libs/core"],
        kind="ffi",
        evidence="fixture boundary",
        source_path="services/api/main.py",
        target_path="libs/core/src/lib.rs",
    )
    plan = create_audit_plan(
        campaign_id="CMP-endpoint-paths",
        inventory=inventory,
        category_families=["STATE"],
        boundary_edges=[edge],
    )

    with pytest.raises(ModelError, match=error):
        create_audit_plan(
            campaign_id="CMP-endpoint-paths",
            inventory=inventory,
            category_families=["STATE"],
            boundary_edges=[replace(edge, **{path_field: invalid_path})],
        )
    invalid_plan = replace(
        plan,
        boundary_edges=(replace(
            plan.boundary_edges[0], **{path_field: invalid_path},
        ),),
    )
    with pytest.raises(ModelError, match=error):
        validate_plan(invalid_plan, inventory)


def test_plan_splits_oversized_boundary_reviews_across_endpoint_work_units(
    tmp_path: Path,
) -> None:
    target = tmp_path / "boundary-split"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:boundary-split")
    source_component = Component("COMP-empty", "external", (), (), 0)
    inventory = replace(inventory, components=(*inventory.components, source_component))
    target_component = next(
        item.component_id for item in inventory.components if item.root == "tools"
    )
    edges = tuple(BoundaryEdge(
        edge_id=f"EDGE-{index:05d}-{'x' * 360}",
        source_component_id=source_component.component_id,
        target_component_id=target_component,
        kind="ipc",
        evidence="large fixture edge",
    ) for index in range(10_000))

    plan = create_audit_plan(
        campaign_id="CMP-boundary-split",
        inventory=inventory,
        category_families=["STATE"],
        boundary_edges=edges,
    )

    expected_edge_ids = {edge.edge_id for edge in edges}
    owner_by_edge = {edge.edge_id: edge.owner_work_unit_id for edge in plan.boundary_edges}
    batch_by_work_unit = {
        work_unit_id: batch.batch_id
        for batch in plan.batches
        for work_unit_id in batch.work_unit_ids
    }
    for component_id in (source_component.component_id, target_component):
        units = [unit for unit in plan.work_units if unit.component_id == component_id]
        reviewed_edge_ids = [edge_id for unit in units for edge_id in unit.boundary_edge_ids]
        assert len(units) > 1
        assert len(reviewed_edge_ids) == len(expected_edge_ids)
        assert set(reviewed_edge_ids) == expected_edge_ids
        assert all(
            discovery_output_floor_bytes(unit) <= TASK_OUTPUT_MAX_BYTES
            for unit in units
        )
    target_review_units = {
        unit.work_unit_id: set(unit.boundary_edge_ids)
        for unit in plan.work_units if unit.component_id == target_component
    }
    assert all(
        edge_id in target_review_units[owner_id]
        for edge_id, owner_id in owner_by_edge.items()
        if owner_id is not None
    )
    assert all(
        handoff.owner_batch == batch_by_work_unit[owner_by_edge[handoff.edge_id]]
        for handoff in plan.handoffs
    )

    review_unit = next(
        unit for unit in plan.work_units
        if unit.component_id == source_component.component_id
        and unit.boundary_edge_ids
    )
    broken_coverage = replace(
        plan,
        work_units=tuple(
            replace(unit, boundary_edge_ids=unit.boundary_edge_ids[1:])
            if unit.work_unit_id == review_unit.work_unit_id else unit
            for unit in plan.work_units
        ),
    )
    with pytest.raises(ModelError, match="exact per endpoint"):
        validate_plan(broken_coverage, inventory)

    first_edge = plan.boundary_edges[0]
    source_review_unit = next(
        unit for unit in plan.work_units
        if unit.component_id == first_edge.source_component_id
        and first_edge.edge_id in unit.boundary_edge_ids
    )
    broken_owner = replace(
        plan,
        boundary_edges=tuple(
            replace(edge, owner_work_unit_id=source_review_unit.work_unit_id)
            if edge.edge_id == first_edge.edge_id else edge
            for edge in plan.boundary_edges
        ),
    )
    with pytest.raises(ModelError, match="not its target review Work Unit"):
        validate_plan(broken_owner, inventory)

    target_units = [
        unit for unit in plan.work_units
        if unit.component_id == target_component and unit.boundary_edge_ids
    ]
    assert len(target_units) > 1
    other_target_unit = target_units[0]
    target_edge_id = target_units[1].boundary_edge_ids[0]
    same_component_wrong_owner = replace(
        plan,
        boundary_edges=tuple(
            replace(edge, owner_work_unit_id=other_target_unit.work_unit_id)
            if edge.edge_id == target_edge_id else edge
            for edge in plan.boundary_edges
        ),
    )
    with pytest.raises(ModelError, match="not its target review Work Unit"):
        validate_plan(same_component_wrong_owner, inventory)


@pytest.mark.parametrize(
    "scope_state", (PlanPathState.EXCLUDED, PlanPathState.DEFERRED),
)
def test_plan_retains_nonincluded_path_without_work_unit_assignment(
    tmp_path: Path, scope_state: PlanPathState,
) -> None:
    target = tmp_path / "scope"
    target.mkdir()
    _write(target / "included.py", "print('in')\n")
    _write(target / "excluded.py", "print('out')\n")
    inventory = build_inventory(target, "fixture:path-scope")
    plan = create_audit_plan(
        campaign_id="CMP-path-scope",
        inventory=inventory,
        category_families=["STATE"],
        path_dispositions=[PlanPathDisposition(
            path="excluded.py",
            state=scope_state,
            rationale="outside the approved audit boundary",
            approved_by="scope-owner",
            evidence_refs=("LOC-included.py:1",),
        )],
    )

    assert {item.path: item.state for item in plan.path_dispositions} == {
        "excluded.py": scope_state,
        "included.py": PlanPathState.INCLUDED,
    }
    assert [
        path for unit in plan.work_units for path in unit.source_files
    ] == ["included.py"]


@pytest.mark.parametrize("extra_fields", (
    {"rationale": "outside scope"},
    {"approved_by": "scope-owner", "evidence_refs": ["LOC-private.py:1"]},
))
def test_plan_path_exclusion_requires_reason_approver_and_evidence(
    extra_fields: dict[str, object],
) -> None:
    with pytest.raises(ModelError):
        PlanPathDisposition.from_dict({
            "path": "private.py",
            "state": "EXCLUDED",
            **extra_fields,
        })


def test_inventory_and_plan_are_persistent_and_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "monorepo"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:persist")
    with CampaignManager(target) as manager:
        manager.create_campaign(campaign_id="CMP-persist", snapshot_id="fixture:persist")
        first_inventory = manager.record_inventory(campaign_id="CMP-persist", inventory=inventory)
        second_inventory = manager.record_inventory(campaign_id="CMP-persist", inventory=inventory)
        plan = create_audit_plan(
            campaign_id="CMP-persist",
            inventory=inventory,
            category_families=["STATE"],
            max_source_files_per_work_unit=2,
            max_source_files_per_batch=2,
        )
        first_plan = manager.record_plan(campaign_id="CMP-persist", plan=plan, inventory=inventory)
        second_plan = manager.record_plan(campaign_id="CMP-persist", plan=plan, inventory=inventory)
        assert first_inventory == second_inventory
        assert first_plan == second_plan
        assert len(manager.store.list_batches("CMP-persist")) == len(plan.batches)
        event_types = [event.event_type for event in manager.store.list_events("CMP-persist")]
        assert event_types.count("INVENTORY_RECORDED") == 1
        assert event_types.count("PLAN_RECORDED") == 1
    campaign_dir = target / ".audit_vnext" / "campaigns" / "CMP-persist"
    assert (campaign_dir / "inventory.json").exists()
    assert (campaign_dir / "plans" / f"{plan.plan_id}.json").exists()


def test_record_plan_rejects_caller_inventory_different_from_campaign_artifact(
    tmp_path: Path,
) -> None:
    target = tmp_path / "durable-inventory"
    target.mkdir()
    _write(target / "app.py", "VALUE = 1\n")
    inventory = build_inventory(target, "fixture:durable-inventory")
    substituted_inventory = replace(
        inventory,
        source_files=(replace(inventory.source_files[0], language="rust"),),
        components=(replace(inventory.components[0], languages=("rust",)),),
    )
    plan = create_audit_plan(
        campaign_id="CMP-durable-inventory",
        inventory=substituted_inventory,
        category_families=["STATE"],
    )

    with CampaignManager(target) as manager:
        manager.create_campaign(
            campaign_id="CMP-durable-inventory",
            snapshot_id=inventory.snapshot_id,
        )
        manager.record_inventory(
            campaign_id="CMP-durable-inventory", inventory=inventory,
        )

        with pytest.raises(
            ValueError, match="does not match the durable Campaign inventory",
        ):
            manager.record_plan(
                campaign_id="CMP-durable-inventory",
                plan=plan,
                inventory=substituted_inventory,
            )
        assert not manager.store.list_events(
            "CMP-durable-inventory",
            entity_type="plan",
            event_type="PLAN_RECORDED",
        )


def test_campaign_inventory_is_write_once_after_initial_record(tmp_path: Path) -> None:
    target = tmp_path / "inventory-write-once"
    target.mkdir()
    _write(target / "app.py", "VALUE = 1\n")
    inventory = build_inventory(target, "fixture:inventory-write-once")
    component = inventory.components[0]
    source = inventory.source_files[0]
    changed_inventory = replace(
        inventory,
        components=(replace(component, languages=("rust",)),),
        source_files=(replace(source, language="rust"),),
    )

    with CampaignManager(target) as manager:
        manager.create_campaign(
            campaign_id="CMP-inventory-write-once",
            snapshot_id=inventory.snapshot_id,
        )
        original_ref = manager.record_inventory(
            campaign_id="CMP-inventory-write-once", inventory=inventory,
        )
        assert manager.record_inventory(
            campaign_id="CMP-inventory-write-once", inventory=inventory,
        ) == original_ref
        original_baseline = manager.load_snapshot_baseline(
            "CMP-inventory-write-once",
        )
        baseline_path = (
            manager.state_dir / "campaigns" / "CMP-inventory-write-once"
            / "snapshot-baseline.json"
        )
        forged_baseline = dict(original_baseline)
        forged_baseline["files"] = {"app.py": "sha256:forged"}
        baseline_path.write_text(json.dumps(forged_baseline), encoding="utf-8")
        assert manager.load_snapshot_baseline(
            "CMP-inventory-write-once",
        ) == original_baseline
        assert json.loads(baseline_path.read_text(encoding="utf-8")) == json.loads(
            json.dumps(original_baseline)
        )

        (target / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="snapshot baseline is write-once"):
            manager.record_inventory(
                campaign_id="CMP-inventory-write-once", inventory=inventory,
            )
        assert manager.load_snapshot_baseline("CMP-inventory-write-once") == original_baseline
        assert len(manager.store.list_events(
            "CMP-inventory-write-once", event_type="SNAPSHOT_BASELINE_RECORDED",
        )) == 1

        with pytest.raises(ValueError, match="inventory is write-once"):
            manager.record_inventory(
                campaign_id="CMP-inventory-write-once",
                inventory=changed_inventory,
            )
        assert manager.load_inventory("CMP-inventory-write-once") == inventory
        assert len(manager.store.list_events(
            "CMP-inventory-write-once", event_type="INVENTORY_RECORDED",
        )) == 1


def test_load_inventory_repairs_tampered_export_from_durable_artifact(
    tmp_path: Path,
) -> None:
    target = tmp_path / "inventory-export"
    target.mkdir()
    _write(target / "app.py", "VALUE = 1\n")
    inventory = build_inventory(target, "fixture:inventory-export")
    with CampaignManager(target) as manager:
        manager.create_campaign(
            campaign_id="CMP-inventory-export", snapshot_id=inventory.snapshot_id,
        )
        manager.record_inventory(campaign_id="CMP-inventory-export", inventory=inventory)
        export_path = (
            manager.state_dir / "campaigns" / "CMP-inventory-export" / "inventory.json"
        )
        tampered = asdict(inventory)
        tampered["source_files"][0]["language"] = "rust"
        export_path.write_text(json.dumps(tampered), encoding="utf-8")

        assert manager.load_inventory("CMP-inventory-export") == inventory
        assert json.loads(export_path.read_text(encoding="utf-8")) == json.loads(
            json.dumps(asdict(inventory))
        )


def test_load_component_graph_repairs_tampered_export_from_durable_artifact(
    tmp_path: Path,
) -> None:
    target = tmp_path / "graph-export"
    target.mkdir()
    _write(target / "app.py", "VALUE = 1\n")
    inventory = build_inventory(target, "fixture:graph-export")
    graph = ComponentGraph("1.0", inventory.snapshot_id, (), (), ())
    with CampaignManager(target) as manager:
        manager.create_campaign(
            campaign_id="CMP-graph-export", snapshot_id=inventory.snapshot_id,
        )
        manager.record_inventory(campaign_id="CMP-graph-export", inventory=inventory)
        manager.record_component_graph(campaign_id="CMP-graph-export", graph=graph)
        export_path = (
            manager.state_dir / "campaigns" / "CMP-graph-export" / "component_graph.json"
        )
        tampered = asdict(graph)
        tampered["diagnostics"] = [{
            "manifest_path": "forged.toml",
            "code": "FORGED",
            "detail": "caller-added build diagnostic",
        }]
        export_path.write_text(json.dumps(tampered), encoding="utf-8")

        assert manager.load_component_graph("CMP-graph-export") == graph
        assert json.loads(export_path.read_text(encoding="utf-8")) == json.loads(
            json.dumps(asdict(graph))
        )


def test_load_audit_plan_repairs_tampered_export_from_durable_artifact(
    tmp_path: Path,
) -> None:
    target = tmp_path / "plan-export"
    target.mkdir()
    _write(target / "app.py", "VALUE = 1\n")
    inventory = build_inventory(target, "fixture:plan-export")
    plan = create_audit_plan(
        campaign_id="CMP-plan-export",
        inventory=inventory,
        category_families=["STATE"],
    )
    with CampaignManager(target) as manager:
        manager.create_campaign(
            campaign_id="CMP-plan-export", snapshot_id=inventory.snapshot_id,
        )
        manager.record_inventory(campaign_id="CMP-plan-export", inventory=inventory)
        manager.record_plan(campaign_id="CMP-plan-export", plan=plan, inventory=inventory)
        export_path = (
            manager.state_dir / "campaigns" / "CMP-plan-export" / "plans" / f"{plan.plan_id}.json"
        )
        tampered = asdict(plan)
        tampered["category_families"] = ["FORGED"]
        export_path.write_text(json.dumps(tampered), encoding="utf-8")

        assert manager.load_audit_plan("CMP-plan-export", plan.plan_id) == plan
        assert json.loads(export_path.read_text(encoding="utf-8")) == json.loads(
            json.dumps(asdict(plan))
        )


def test_boundary_source_path_must_belong_to_source_component(tmp_path: Path) -> None:
    target = tmp_path / "monorepo"
    target.mkdir()
    _fixture_monorepo(target)
    inventory = build_inventory(target, "fixture:bad-edge")
    components = {component.root: component.component_id for component in inventory.components}

    try:
        create_audit_plan(
            campaign_id="CMP-bad-edge",
            inventory=inventory,
            category_families=["STATE"],
            boundary_edges=[BoundaryEdge(
                edge_id="EDGE-bad",
                source_component_id=components["services/api"],
                target_component_id=components["libs/core"],
                kind="call",
                evidence="invalid fixture",
                source_path="tools/main.go",
            )],
        )
    except ModelError as error:
        assert "not owned by source component" in str(error)
    else:
        raise AssertionError("invalid boundary source path was accepted")

def test_output_floor_grows_with_owned_edges_and_paths() -> None:
    from reachable_audit.plan_models import WorkUnit
    from reachable_audit.planning import discovery_output_floor_bytes

    def unit(paths: tuple[str, ...], edges: tuple[str, ...]) -> WorkUnit:
        return WorkUnit(
            work_unit_id="WU-x", component_id="C", source_files=paths, languages=(),
            category_families=(), discovery_axes=(), boundary_edge_ids=edges,
        )

    base = discovery_output_floor_bytes(unit(("a.py",), ()))
    with_edges = discovery_output_floor_bytes(
        unit(("a.py",), tuple(f"E-{i}" for i in range(1000)))
    )
    assert with_edges > base + 1000 * 100


def test_task_fanout_forecast_uses_explicit_assumptions_and_rates(tmp_path: Path) -> None:
    target = tmp_path / "forecast"
    target.mkdir()
    _write(target / "app.py", "print('ok')\n")
    inventory = build_inventory(target, "fixture:forecast")
    plan = create_audit_plan(
        campaign_id="CMP-forecast",
        inventory=inventory,
        category_families=["STATE"],
    )
    operations = (
        "discover_surfaces", "generate_hypotheses_compact", "run_category_audit",
        "verify_reachability", "refute_reachability", "adjudicate_refutations",
        "assess_experiment", "collect_batch_closure_evidence",
    )
    forecast = forecast_plan_cost(plan, {
        "profile_id": "fixture-cost-profile",
        "currency": "TEST",
        "assumptions": {
            "hypotheses_per_work_unit": {"low": 1, "expected": 2, "high": 3},
            "reachable_fraction": 0.5,
        },
        "cost_per_task": {operation: 1.0 for operation in operations},
    })

    assert forecast["fixed_task_counts"] == {
        "discover_surfaces": 1,
        "generate_hypotheses_compact": 1,
        "run_category_audit_plan_upper_bound": 1,
        "run_category_audit_task_upper_bound": 1,
        "collect_batch_closure_evidence": 1,
        "omitted_empty_components": 0,
    }
    assert forecast["scenarios"]["low"]["estimated_total_tasks"] == 9
    assert forecast["scenarios"]["expected"]["estimated_total_tasks"] == 11
    assert forecast["scenarios"]["high"]["estimated_total_tasks"] == 16
    assert forecast["scenarios"]["expected"]["estimated_cost"] == 11.0


def test_task_fanout_forecast_models_r4_bundling_as_an_explicit_scenario(
    tmp_path: Path,
) -> None:
    target = tmp_path / "forecast-bundle"
    target.mkdir()
    _write(target / "a.py", "print('a')\n")
    _write(target / "b.py", "print('b')\n")
    inventory = build_inventory(target, "fixture:forecast-bundle")
    plan = create_audit_plan(
        campaign_id="CMP-forecast-bundle",
        inventory=inventory,
        category_families=["STATE"],
        max_source_files_per_work_unit=1,
        max_source_files_per_batch=2,
        max_work_units_per_batch=2,
    )
    operations = (
        "discover_surfaces", "generate_hypotheses_compact", "run_category_audit_bundle",
        "verify_reachability", "refute_reachability", "adjudicate_refutations",
        "assess_experiment", "collect_batch_closure_evidence",
    )
    forecast = forecast_plan_cost(plan, {
        "profile_id": "fixture-bundle-profile",
        "currency": "TEST",
        "assumptions": {
            "hypotheses_per_work_unit": {"low": 0, "expected": 0, "high": 0},
            "reachable_fraction": 0,
            "r4_bundle_work_units_per_task": 2,
        },
        "cost_per_task": {operation: 1.0 for operation in operations},
    })

    assert forecast["fixed_task_counts"]["run_category_audit_plan_upper_bound"] == 2
    assert forecast["fixed_task_counts"]["run_category_audit_task_upper_bound"] == 1
    assert forecast["scenarios"]["expected"]["estimated_task_counts"][
        "run_category_audit_bundle"
    ] == 1


@pytest.mark.parametrize("rate", [1.0, 0.00013])
def test_multibatch_forecast_never_bundles_across_batches(tmp_path: Path, rate: float) -> None:
    _write(tmp_path / "a.py", "print('a')\n")
    _write(tmp_path / "b.py", "print('b')\n")
    plan = create_audit_plan(
        campaign_id="CMP-multibatch-cost", inventory=build_inventory(tmp_path, "fixture:cost"),
        category_families=["STATE"], max_source_files_per_work_unit=1,
        max_source_files_per_batch=1, max_work_units_per_batch=1,
    )
    operations = (
        "discover_surfaces", "generate_hypotheses_compact", "run_category_audit_bundle",
        "verify_reachability", "refute_reachability", "adjudicate_refutations",
        "assess_experiment", "collect_batch_closure_evidence",
    )
    forecast = forecast_plan_cost(plan, {
        "profile_id": "fixture-multibatch", "currency": "TEST",
        "assumptions": {
            "hypotheses_per_work_unit": {"low": 0, "expected": 0.5, "high": 1},
            "reachable_fraction": 0.5, "r4_bundle_work_units_per_task": 2,
        },
        "cost_per_task": {operation: rate for operation in operations},
    })
    assert forecast["fixed_task_counts"]["run_category_audit_task_upper_bound"] == 2
    assert forecast["scenarios"]["low"]["estimated_total_tasks"] == 8
    for scenario in forecast["scenarios"].values():
        batches = list(scenario["per_batch"].values())
        assert scenario["estimated_cost"] == sum(batch["estimated_cost"] for batch in batches)
        assert scenario["estimated_hypotheses"] == sum(batch["estimated_hypotheses"] for batch in batches)
        for operation, count in scenario["estimated_task_counts"].items():
            assert count == sum(batch["estimated_task_counts"][operation] for batch in batches)
