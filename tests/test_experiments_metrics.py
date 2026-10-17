import json
from pathlib import Path
import sys

import pytest

from reachable_audit.analysis_models import (
    Applicability,
    Adjudication,
    AdjudicationActor,
    AttackAngle,
    AxisRun,
    CategoryAuditPlan,
    CategoryRun,
    CategoryRunStatus,
    DiscoveryAxis,
    Experiment,
    ExperimentFidelity,
    ExperimentResult,
    Refutation,
    R5Assessment,
    R5Disposition,
    VerdictKind,
)
from reachable_audit.execution import (
    DiscoveryCoordinator,
    ManualExecutionBackend,
    TaskResult,
)
from reachable_audit.experiments.harness_catalog import HarnessCatalog
from reachable_audit.models import ModelError
from reachable_audit.experiments.runner import run_harness
from test_category_runs import _card, _ready_for_r4
from test_refutation import _reachable_workflow
from reachable_audit.knowledge import create_category_audit_plans
from conftest import execution_configuration_fixture


def test_harness_catalog_scopes_optional_sanitizers_by_family() -> None:
    catalog = HarnessCatalog()
    for language in ("c", "cpp", "rust"):
        for family in ("INJECTION", "AUTHN", "MEMORY-SAFETY", "NUMERIC"):
            recipe = catalog.recipes((language,), family)[0]
            sanitizer_advised = any(
                "sanitizer" in prerequisite.lower() or "miri" in prerequisite.lower()
                for prerequisite in recipe.prerequisites
            )
            assert sanitizer_advised is (family in {"MEMORY-SAFETY", "NUMERIC"})
            if sanitizer_advised:
                assert any("optional" in item.lower() for item in recipe.prerequisites)


def _ready_for_r5(
    tmp_path: Path,
    *,
    static_hypothesis: bool = False,
    surface_without_hypothesis: bool = False,
    screening_work_unit: bool = False,
):  # type: ignore[no-untyped-def]
    manager, workflow, plan = _ready_for_r4(
        tmp_path, static_hypothesis=static_hypothesis,
        surface_without_hypothesis=surface_without_hypothesis,
        screening_work_unit=screening_work_unit,
    )
    category_plan = create_category_audit_plans(plan.work_units, [_card()], budget={})[0]
    workflow.record_category_audit_plan([category_plan])
    workflow.record_r4([CategoryRun(
        "CR-state", category_plan.category_plan_id, category_plan.work_unit_id,
        "STATE", category_plan.mechanism_variants,
        tuple(AxisRun(
            DiscoveryAxis(axis),
            Applicability.NOT_APPLICABLE if screening_work_unit else Applicability.APPLICABLE,
            (f"EVID-{axis}",),
            f"reviewed {axis}",
        ) for axis in category_plan.discovery_axes),
        Applicability.NOT_APPLICABLE if screening_work_unit else Applicability.APPLICABLE,
        CategoryRunStatus.COMPLETE,
        ("EVID-r4",), "all planned coverage executed", (), (),
    )])
    return manager, workflow


def test_r5_equivalent_confirmation_requires_equivalence_evidence(tmp_path: Path) -> None:
    with pytest.raises(ModelError, match="equivalence evidence"):
        Experiment.from_dict({
            "experiment_id": "EXP-1",
            "hypothesis_id": "HYP-1",
            "fidelity": "equivalent",
            "result": "confirmed",
            "target_ref": "HARNESS-1",
            "command_refs": ["CMD-1"],
            "observation_refs": ["OBS-1"],
            "rationale": "extracted target behavior",
        })


def test_mechanism_experiment_cannot_empirically_upgrade(tmp_path: Path) -> None:
    experiment = Experiment(
        "EXP-mechanism", "HYP-x", ExperimentFidelity.MECHANISM,
        ExperimentResult.CONFIRMED, "HARNESS-mechanism", ("CMD-1",),
        ("OBS-1",), (), (), "generic mechanism reproduced",
    )
    assert experiment.supports_empirical_upgrade is False


def test_empirical_experiment_requires_registered_harness_artifacts(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        fake = Experiment(
            "EXP-fake", "HYP-bound", ExperimentFidelity.REAL_TARGET,
            ExperimentResult.CONFIRMED, "target", ("CMD-1",), ("OBS-1",),
            (), (), "claimed confirmation",
        )
        with pytest.raises(ModelError, match="registered harness execution"):
            workflow._validate_empirical_harness_evidence(fake)

        result = run_harness(
            manager,
            workflow.campaign_id,
            command=[sys.executable, "-c", "print('observed')"],
            hypothesis_id="HYP-bound",
        )
        experiment = Experiment(
            "EXP-real", "HYP-bound", ExperimentFidelity.REAL_TARGET,
            ExperimentResult.CONFIRMED, "target",
            (str(result["execution_artifact_id"]),),
            (str(result["stdout_artifact_id"]), str(result["stderr_artifact_id"])),
            (), (), "managed target behavior observed",
        )
        workflow._validate_empirical_harness_evidence(experiment)

        mismatched = Experiment(
            "EXP-mismatch", "HYP-other", ExperimentFidelity.REAL_TARGET,
            ExperimentResult.CONFIRMED, "target",
            experiment.command_refs, experiment.observation_refs,
            (), (), "reused another hypothesis's run",
        )
        with pytest.raises(ModelError, match="registered harness execution"):
            workflow._validate_empirical_harness_evidence(mismatched)
    finally:
        manager.close()


def test_clean_r5_and_transmission_metrics_are_non_gating(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        workflow.record_r5([], [])
        coordinator = DiscoveryCoordinator(
            workflow, ManualExecutionBackend(manager, workflow.campaign_id),
        )
        closure_task = coordinator.schedule_r6()
        closure_input = json.loads(manager.artifacts.get_bytes(closure_task.task.input_refs[0]))
        assert closure_input["evidence_contract"] == {
            "source": "canonical_stage_artifacts", "source_inventory_required": False,
        }
        metrics = workflow.build_transmission_metrics()
        assert metrics["axis_runs"] == {
            axis.value: 1 for axis in DiscoveryAxis
        }
        assert metrics["hypothesis_count"] == 0
        assert metrics["finding_count"] == 0
        assert metrics["r4_linked_finding_count"] == 0
        assert metrics["gate_effect"] == "NONE"
        manager.store.append_event(
            campaign_id=workflow.campaign_id,
            batch_id=workflow.batch_id,
            entity_type="finding",
            entity_id="FND-canonical",
            event_type="FINDING_RECORDED",
            idempotency_key="finding:CMP-r4:FND-canonical",
            actor="test",
            payload={"status": "CONFIRMED"},
        )
        metrics = workflow.build_transmission_metrics()
        assert metrics["finding_count"] == 1
        assert metrics["r4_linked_finding_count"] == 0
    finally:
        manager.close()


@pytest.mark.parametrize("invalid_experiment_id", ["", " ", "EXP-other"])
@pytest.mark.parametrize("legacy_collected", [False, True])
def test_r5_assessment_runs_as_durable_task(
    tmp_path: Path, invalid_experiment_id: str, legacy_collected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow = _reachable_workflow(tmp_path)
    try:
        workflow.record_refutation(Refutation(
            "REF-r5-call", "HYP-state", "refuter-a", VerdictKind.REACHABLE,
            AttackAngle.CALL_CHAIN, ("EVID-call",), "call chain holds",
        ))
        workflow.record_refutation(Refutation(
            "REF-r5-principal", "HYP-state", "refuter-b", VerdictKind.REACHABLE,
            AttackAngle.PRINCIPAL, ("EVID-principal",), "principal can invoke",
        ))
        workflow.record_adjudication(Adjudication(
            "ADJ-r5", "HYP-state", ("REF-r5-call", "REF-r5-principal"),
            VerdictKind.REACHABLE, AdjudicationActor.AUTO, (),
            "both reviews confirm reachability",
        ))
        workflow.record_revival_selection(
            [], rationale="no initial unreachable verdicts", evidence_refs=("EVID-r3",)
        )
        workflow.complete_r35()
        work_unit = workflow.batch.manifest["work_units"][0]
        category_plan = CategoryAuditPlan(
            "CAP-r5-task", str(work_unit["work_unit_id"]), "STATE",
            ("stale-owner",), ("MECH-state",),
            tuple(str(axis) for axis in work_unit["discovery_axes"]), {},
        )
        workflow.record_category_audit_plan([category_plan])
        workflow.record_r4([CategoryRun(
            "CR-r5-task", category_plan.category_plan_id,
            category_plan.work_unit_id, "STATE", category_plan.mechanism_variants,
            tuple(AxisRun(
                DiscoveryAxis(axis), Applicability.APPLICABLE,
                (f"EVID-{axis}",), f"reviewed {axis}",
            ) for axis in category_plan.discovery_axes),
            Applicability.APPLICABLE, CategoryRunStatus.COMPLETE,
            ("EVID-r4",), "all planned coverage executed", ("HYP-state",), (),
        )])
        backend = ManualExecutionBackend(manager, "CMP-refute")
        coordinator = DiscoveryCoordinator(workflow, backend)
        scheduled = coordinator.schedule_r5()
        assert len(scheduled) == 1
        task_input = json.loads(
            manager.artifacts.get_bytes(scheduled[0].task.input_refs[0])
        )
        assert task_input["harness_recipes"]
        assert all(recipe["family"] == "STATE" for recipe in task_input["harness_recipes"])
        assert task_input["language_adapters"]
        assert task_input["registered_harness_executions"] == []
        assert "host-registered harness-run" in task_input["analysis_contract"]
        assert "NOT_FEASIBLE only when an experiment is required" in task_input["analysis_contract"]
        assert "not evidence of safety, confirmation, or refutation" in task_input["analysis_contract"]
        assert "JSON null" in task_input["analysis_contract"]
        lease = backend.claim("experiment-reviewer")
        assert lease is not None
        output = {
            "schema_version": "1.0",
            "experiments": [],
            "assessment": {
                "hypothesis_id": "HYP-state",
                "experiment_required": False,
                "experiment_id": invalid_experiment_id,
                "disposition": "STATIC_VERDICT_RETAINED",
                "evidence_refs": ["EVID-r3"],
                "rationale": "static edge evidence is sufficient for this stage",
            },
        }
        invalid_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
        with pytest.raises(ModelError, match="experiment"):
            backend.collect(lease, TaskResult(
                True, invalid_ref, "invalid experiment reference",
                {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture(),
            ))
        assert backend.poll(lease.task.task_id).status.value == "LEASED"
        output["assessment"]["experiment_id"] = None
        output_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
        if legacy_collected:
            with monkeypatch.context() as legacy:
                legacy.setattr(backend, "_validate_task_output", lambda *_args: None)
                backend.collect(lease, TaskResult(
                    True, invalid_ref, "legacy successful collection",
                    {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture(),
                ))
            with pytest.raises(ModelError, match="experiment"):
                coordinator.commit_r5()
            backend.amend_completed_output(
                lease.task.task_id, output_ref, reason="correct legacy experiment reference",
                evidence_refs=(invalid_ref,),
            )
            assert json.loads(manager.artifacts.get_bytes(invalid_ref))["assessment"]["experiment_id"] == invalid_experiment_id
        else:
            backend.collect(lease, TaskResult(
                True, output_ref, "assessed", {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture()
            ))
        coordinator.commit_r5()
        events = manager.store.list_events("CMP-refute")
        assert sum(event.event_type == "R5_COMPLETED" for event in events) == 1
    finally:
        manager.close()