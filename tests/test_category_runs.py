from dataclasses import asdict
import json
from pathlib import Path

import pytest

from reachable_audit.analysis_models import (
    Applicability,
    AxisRun,
    CategoryRun,
    CategoryRunStatus,
    DiscoveryAxis,
    EvaluationPartition,
    MechanismCard,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.execution import (
    DiscoveryCoordinator,
    ManualExecutionBackend,
    TaskResult,
)
from reachable_audit.inventory import build_inventory
from reachable_audit.knowledge import create_category_audit_plans
from reachable_audit.knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from reachable_audit.models import ModelError
from reachable_audit.planning import create_audit_plan
from conftest import axis_runs_from_evidence
from conftest import execution_configuration_fixture


def _ready_for_r4(tmp_path: Path):  # type: ignore[no-untyped-def]
    (tmp_path / "state.py").write_text("STATE = {}\n", encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:r4")
    plan = create_audit_plan(
        campaign_id="CMP-r4", inventory=inventory, category_families=["STATE"]
    )
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-r4", snapshot_id="fixture:r4")
    manager.record_inventory(campaign_id="CMP-r4", inventory=inventory)
    manager.record_plan(campaign_id="CMP-r4", plan=plan, inventory=inventory)
    workflow = BatchWorkflow(manager, "CMP-r4", plan.batches[0].batch_id)
    workflow.run_r0()
    workflow.record_r1([])
    axis_evidence = {
        "surface": ("EVID-surface",), "mechanism": ("EVID-mechanism",),
        "state": ("EVID-state",), "fix_variant": ("EVID-fix",),
        "boundary": ("EVID-boundary",), "differential": ("EVID-differential",),
    }
    workflow.record_r2(
        [], axis_evidence=axis_evidence,
        axis_runs=axis_runs_from_evidence(axis_evidence),
    )
    workflow.record_r3([])
    workflow.record_revival_selection(
        [], rationale="no unreachable hypotheses", evidence_refs=("EVID-r3",)
    )
    workflow.complete_r35()
    return manager, workflow, plan


def _card(partition: EvaluationPartition = EvaluationPartition.TRAINING) -> MechanismCard:
    return MechanismCard(
        mechanism_id="MECH-state-stale-owner",
        family="STATE",
        title="Stale owner after transition",
        preconditions=("owner can transition",),
        dangerous_transitions=("owner changes without generation update",),
        sink_semantics=("stale state use",),
        counterevidence=("generation token checked",),
        language_applicability=("python",),
        verification_recipe=("enumerate owner transitions",),
        provenance=("SRC-public-advisory",),
        evaluation_partition=partition,
    )


def test_r4_tracks_six_axis_coverage_with_zero_findings(tmp_path: Path) -> None:
    manager, workflow, plan = _ready_for_r4(tmp_path)
    try:
        category_plans = create_category_audit_plans(
            plan.work_units, [_card()], budget={"agent_runs": 2, "minutes": 30}
        )
        workflow.record_category_audit_plan(category_plans)
        category_plan = category_plans[0]
        axis_runs = tuple(AxisRun(
            axis=DiscoveryAxis(axis),
            applicability=Applicability.APPLICABLE,
            evidence_refs=(f"EVID-{axis}",),
            rationale=f"reviewed {axis} axis",
        ) for axis in category_plan.discovery_axes)
        workflow.record_r4([CategoryRun(
            category_run_id="CR-state",
            category_plan_id=category_plan.category_plan_id,
            work_unit_id=category_plan.work_unit_id,
            family="STATE",
            mechanism_variants_examined=category_plan.mechanism_variants,
            axis_runs=axis_runs,
            applicability=Applicability.APPLICABLE,
            status=CategoryRunStatus.COMPLETE,
            evidence_refs=("EVID-category-review",),
            rationale="all planned mechanisms and axes were reviewed",
            hypothesis_ids=(),
            finding_ids=(),
        )])
        r4_event = next(
            event for event in manager.store.list_events("CMP-r4")
            if event.event_type == "R4_COMPLETED"
        )
        assert r4_event.payload["finding_count"] == 0
    finally:
        manager.close()


def test_held_out_card_cannot_enter_runtime_category_plan(tmp_path: Path) -> None:
    manager, _, plan = _ready_for_r4(tmp_path)
    try:
        with pytest.raises(ModelError, match="held-out"):
            create_category_audit_plans(plan.work_units, [_card(EvaluationPartition.HELD_OUT)], budget={})
    finally:
        manager.close()


def test_r4_rejects_missing_discovery_axis(tmp_path: Path) -> None:
    manager, workflow, plan = _ready_for_r4(tmp_path)
    try:
        category_plan = create_category_audit_plans(plan.work_units, [_card()], budget={})[0]
        workflow.record_category_audit_plan([category_plan])
        with pytest.raises(ModelError, match="axis coverage mismatch"):
            workflow.record_r4([CategoryRun(
                "CR-incomplete", category_plan.category_plan_id,
                category_plan.work_unit_id, "STATE", category_plan.mechanism_variants,
                (), Applicability.APPLICABLE, CategoryRunStatus.COMPLETE,
                ("EVID-review",), "axes missing", (), (),
            )])
    finally:
        manager.close()


def test_r4_category_plan_runs_as_durable_task(tmp_path: Path) -> None:
    manager, workflow, plan = _ready_for_r4(tmp_path)
    try:
        catalog = KnowledgeCatalog.load(default_knowledge_root())
        state_card = next(
            card for card in catalog.cards.values()
            if card["family"] == "STATE"
            and "python" in card["language_applicability"]
        )
        category_plan = create_category_audit_plans(
            plan.work_units, [MechanismCard.from_dict(state_card)],
            budget={"agent_runs": 1},
        )[0]
        workflow.record_category_audit_plan([category_plan])
        run = CategoryRun(
            "CR-task", category_plan.category_plan_id,
            category_plan.work_unit_id, "STATE", category_plan.mechanism_variants,
            tuple(AxisRun(
                DiscoveryAxis(axis), Applicability.APPLICABLE,
                (f"EVID-{axis}",), f"reviewed {axis} axis",
            ) for axis in category_plan.discovery_axes),
            Applicability.APPLICABLE, CategoryRunStatus.COMPLETE,
            ("EVID-category-review",), "all planned checks completed", (), (),
        )
        backend = ManualExecutionBackend(manager, "CMP-r4")
        coordinator = DiscoveryCoordinator(workflow, backend)
        scheduled = coordinator.schedule_r4()
        assert len(scheduled) == 1
        task_input = json.loads(
            manager.artifacts.get_bytes(scheduled[0].task.input_refs[0])
        )
        assert task_input["mechanism_cards"][0]["mechanism_id"] == state_card["mechanism_id"]
        assert task_input["knowledge_context"]["issue_entries"]
        assert task_input["knowledge_context"]["knowledge_version"] == "portfolio-2026-09-v1"
        lease = backend.claim("category-auditor")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "category_run": asdict(run),
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, output_ref, "category complete", {"agent_runs": 1, "wall_seconds": 1},
            execution_configuration_fixture(),
        ))
        coordinator.commit_r4()
        events = manager.store.list_events("CMP-r4")
        assert sum(event.event_type == "R4_COMPLETED" for event in events) == 1
    finally:
        manager.close()