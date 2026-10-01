from pathlib import Path

import pytest

from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.drift import resolve_snapshot_drift
from reachable_audit.graph import build_component_graph
from reachable_audit.inventory import build_inventory
from reachable_audit.models import BatchStatus, ModelError
from reachable_audit.planning import create_audit_plan


def test_r0_drift_invalidates_reverse_dependencies_only(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='app'\ndependencies=['lib @ file:./lib']\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("from lib import value\n", encoding="utf-8")
    for directory, name in (("lib", "lib"), ("isolated", "isolated")):
        root = tmp_path / directory
        root.mkdir()
        (root / "pyproject.toml").write_text(
            f"[project]\nname='{name}'\n", encoding="utf-8"
        )
        (root / f"{name}.py").write_text("value = 1\n", encoding="utf-8")

    inventory = build_inventory(tmp_path, "fixture:drift")
    graph = build_component_graph(tmp_path, inventory)
    plan = create_audit_plan(
        campaign_id="CMP-drift",
        inventory=inventory,
        category_families=["STATE"],
        boundary_edges=graph.edges,
        max_work_units_per_batch=1,
    )
    manager = CampaignManager(tmp_path)
    try:
        manager.create_campaign(campaign_id="CMP-drift", snapshot_id="fixture:drift")
        manager.record_inventory(campaign_id="CMP-drift", inventory=inventory)
        manager.record_component_graph(campaign_id="CMP-drift", graph=graph)
        manager.record_plan(campaign_id="CMP-drift", plan=plan, inventory=inventory)
        lib_unit = next(
            unit for unit in plan.work_units if "lib/lib.py" in unit.source_files
        )
        app_unit = next(
            unit for unit in plan.work_units if "app.py" in unit.source_files
        )
        isolated_unit = next(
            unit for unit in plan.work_units if "isolated/isolated.py" in unit.source_files
        )
        lib_batch = next(
            batch for batch in plan.batches if lib_unit.work_unit_id in batch.work_unit_ids
        )
        (tmp_path / "lib" / "lib.py").write_text("value = 2\n", encoding="utf-8")

        with pytest.raises(ModelError, match="snapshot drift detected"):
            BatchWorkflow(manager, "CMP-drift", lib_batch.batch_id).run_r0()

        events = manager.store.list_events("CMP-drift")
        invalidated = {
            event.entity_id
            for event in events
            if event.event_type == "WORK_UNIT_INVALIDATED"
        }
        assert {lib_unit.work_unit_id, app_unit.work_unit_id}.issubset(invalidated)
        assert isolated_unit.work_unit_id not in invalidated
        assert manager.store.get_batch(
            "CMP-drift", lib_batch.batch_id
        ).status is BatchStatus.BLOCKED
        assert any(event.event_type == "HANDOFF_INVALIDATED" for event in events)

        drift_event = next(
            event for event in events if event.event_type == "SNAPSHOT_DRIFT"
        )
        with pytest.raises(ModelError, match="remains unresolved"):
            resolve_snapshot_drift(
                manager,
                campaign_id="CMP-drift",
                drift_event_id=drift_event.event_id,
                evidence_refs=("EVID-recheck",),
            )
        (tmp_path / "lib" / "lib.py").write_text("value = 1\n", encoding="utf-8")
        resolve_snapshot_drift(
            manager,
            campaign_id="CMP-drift",
            drift_event_id=drift_event.event_id,
            evidence_refs=("EVID-source-restored",),
        )
        assert manager.store.get_batch(
            "CMP-drift", lib_batch.batch_id
        ).status is BatchStatus.PLANNED
        assert BatchWorkflow(manager, "CMP-drift", lib_batch.batch_id).run_r0()
        resolved_events = manager.store.list_events("CMP-drift")
        assert any(
            event.event_type == "SNAPSHOT_DRIFT_RESOLVED"
            for event in resolved_events
        )
        assert len([
            event for event in resolved_events
            if event.event_type == "WORK_UNIT_REVALIDATED"
        ]) == len(invalidated)
    finally:
        manager.close()