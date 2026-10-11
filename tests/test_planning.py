from pathlib import Path

from reachable_audit.campaign import CampaignManager
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from reachable_audit.plan_models import BoundaryEdge
from reachable_audit.planning import create_audit_plan


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
