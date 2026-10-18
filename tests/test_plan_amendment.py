from pathlib import Path

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.inventory import build_inventory
from reachable_audit.models import BatchStatus
from reachable_audit.plan_models import PlanPathDisposition, PlanPathState
from reachable_audit.planning import amend_plan, create_audit_plan


def _inventory(root: Path):  # type: ignore[no-untyped-def]
    for index in range(4):
        (root / f"source_{index}.py").write_text("VALUE = 1\n", encoding="utf-8")
    return build_inventory(root, "fixture:amend")


def test_amendment_preserves_work_units_and_defers_replaced_batches(
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path)
    base_plan = create_audit_plan(
        campaign_id="CMP-amend",
        inventory=inventory,
        category_families=["STATE"],
        max_source_files_per_work_unit=1,
        max_source_files_per_batch=4,
        max_work_units_per_batch=4,
    )
    amended_plan, amendment = amend_plan(
        base_plan,
        reason="pilot batch exceeded budget",
        max_source_files_per_batch=1,
        max_work_units_per_batch=1,
    )

    assert {unit.work_unit_id for unit in amended_plan.work_units} == {
        unit.work_unit_id for unit in base_plan.work_units
    }
    assert len(base_plan.batches) == 1
    assert len(amended_plan.batches) == 4
    assert amendment.preserved_work_unit_ids == tuple(sorted(
        unit.work_unit_id for unit in base_plan.work_units
    ))

    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            campaign_id="CMP-amend", snapshot_id="fixture:amend"
        )
        manager.record_inventory(campaign_id="CMP-amend", inventory=inventory)
        manager.record_plan(
            campaign_id="CMP-amend", plan=base_plan, inventory=inventory
        )
        first = manager.record_plan_amendment(
            campaign_id="CMP-amend",
            base_plan=base_plan,
            amended_plan=amended_plan,
            amendment=amendment,
            inventory=inventory,
        )
        second = manager.record_plan_amendment(
            campaign_id="CMP-amend",
            base_plan=base_plan,
            amended_plan=amended_plan,
            amendment=amendment,
            inventory=inventory,
        )
        assert first == second
        assert manager.store.get_batch(
            "CMP-amend", base_plan.batches[0].batch_id
        ).status is BatchStatus.DEFERRED
        assert all(
            manager.store.get_batch("CMP-amend", batch.batch_id).status
            is BatchStatus.PLANNED
            for batch in amended_plan.batches
        )
        events = manager.store.list_events("CMP-amend")
        assert sum(event.event_type == "PLAN_AMENDED" for event in events) == 1


def test_amendment_rejects_a_plan_with_an_active_batch(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path)
    base_plan = create_audit_plan(
        campaign_id="CMP-active",
        inventory=inventory,
        category_families=["STATE"],
        max_source_files_per_work_unit=1,
        max_source_files_per_batch=4,
    )
    amended_plan, amendment = amend_plan(
        base_plan,
        reason="too large",
        max_source_files_per_batch=2,
        max_work_units_per_batch=2,
    )
    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            campaign_id="CMP-active", snapshot_id="fixture:amend"
        )
        manager.record_inventory(campaign_id="CMP-active", inventory=inventory)
        manager.record_plan(
            campaign_id="CMP-active", plan=base_plan, inventory=inventory
        )
        active_batch = base_plan.batches[0]
        manager.store.transition_batch(
            "CMP-active", active_batch.batch_id, BatchStatus.READY
        )
        manager.store.transition_batch(
            "CMP-active", active_batch.batch_id, BatchStatus.RUNNING
        )

        with pytest.raises(ValueError, match="scheduled or executed"):
            manager.record_plan_amendment(
                campaign_id="CMP-active",
                base_plan=base_plan,
                amended_plan=amended_plan,
                amendment=amendment,
                inventory=inventory,
            )


def test_amendment_preserves_path_scope_dispositions(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path)
    base_plan = create_audit_plan(
        campaign_id="CMP-amend-scope",
        inventory=inventory,
        category_families=["STATE"],
        path_dispositions=(PlanPathDisposition(
            path="source_0.py",
            state=PlanPathState.DEFERRED,
            rationale="awaiting generated-source ownership confirmation",
            approved_by="scope-owner",
            evidence_refs=("LOC-source_0.py:1",),
        ),),
        max_source_files_per_work_unit=1,
    )
    amended_plan, _amendment = amend_plan(
        base_plan,
        reason="reduce batch size",
        max_source_files_per_batch=1,
        max_work_units_per_batch=1,
    )

    assert amended_plan.path_dispositions == base_plan.path_dispositions
    assert "source_0.py" not in {
        path for unit in amended_plan.work_units for path in unit.source_files
    }