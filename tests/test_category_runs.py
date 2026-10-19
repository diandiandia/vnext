from dataclasses import asdict, replace
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
    EvidenceGrade,
    Hypothesis,
    HypothesisStatus,
    Mechanism,
    ReviewAltitude,
    Surface,
    VerdictKind,
    VerdictSubmission,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.cli import main
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
from reachable_audit.plan_models import PlanPathDisposition
from conftest import axis_runs_from_evidence
from conftest import execution_configuration_fixture


def _ready_for_r4(
    tmp_path: Path,
    *,
    static_hypothesis: bool = False,
    surface_without_hypothesis: bool = False,
    screening_work_unit: bool = False,
    path_dispositions: tuple[PlanPathDisposition, ...] = (),
    path_review_claims: tuple[dict[str, str], ...] = (),
    axis_review_altitudes: dict[str, str] | None = None,
):  # type: ignore[no-untyped-def]
    (tmp_path / "state.py").write_text("STATE = {}\n", encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:r4")
    plan = create_audit_plan(
        campaign_id="CMP-r4", inventory=inventory, category_families=["STATE"],
        path_dispositions=path_dispositions,
    )
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-r4", snapshot_id="fixture:r4")
    manager.record_inventory(campaign_id="CMP-r4", inventory=inventory)
    manager.record_plan(campaign_id="CMP-r4", plan=plan, inventory=inventory)
    workflow = BatchWorkflow(manager, "CMP-r4", plan.batches[0].batch_id)
    workflow.run_r0()
    work_unit = plan.work_units[0]
    surfaces = [Surface(
        "SURF-static", work_unit.work_unit_id, work_unit.component_id,
        "function_entry", "state.py", "run", "local", ("LOC-state.py:1",),
    )] if static_hypothesis or surface_without_hypothesis else []
    workflow.record_r1(surfaces, path_review_claims=path_review_claims)
    axis_evidence = {
        "surface": ("EVID-surface",), "mechanism": ("EVID-mechanism",),
        "state": ("EVID-state",), "fix_variant": ("EVID-fix",),
        "boundary": ("EVID-boundary",), "differential": ("EVID-differential",),
    }
    hypotheses = [Hypothesis(
        "HYP-static", work_unit.work_unit_id, "surface", ("SURF-static",),
        ("SURF-static",), Mechanism("STATE", "static-state-transition"),
        "static-only reachability needs further proof", HypothesisStatus.NEW,
    )] if static_hypothesis else []
    workflow.record_r2(
        hypotheses, axis_evidence=axis_evidence,
        axis_runs=axis_runs_from_evidence(
            axis_evidence,
            not_applicable=tuple(axis_evidence) if screening_work_unit else (),
            review_altitudes=axis_review_altitudes,
        ),
    )
    workflow.record_r3([
        VerdictSubmission(
            "HYP-static", VerdictKind.REACHABLE, EvidenceGrade.STATIC_ONLY,
            "remote", (), ("LOC-state.py:1",), ("LOC-state.py:1",), (), (),
            "static chain is plausible but not edge-proven",
        )
    ] if static_hypothesis else [])
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


def test_r4_tracks_six_axis_coverage_with_zero_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        category_run = CategoryRun(
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
        )
        original_append = manager.store._append_event_tx

        def fail_r4_append(**kwargs: object) -> object:
            if kwargs.get("event_type") == "R4_COMPLETED":
                raise RuntimeError("injected R4 event append failure")
            return original_append(**kwargs)

        monkeypatch.setattr(manager.store, "_append_event_tx", fail_r4_append)
        with pytest.raises(RuntimeError, match="injected R4 event append failure"):
            workflow.record_r4([category_run])
        assert workflow._stage_event("R4_COMPLETED") is None

        monkeypatch.setattr(manager.store, "_append_event_tx", original_append)
        artifact_id = workflow.record_r4([category_run])
        original_put_text = manager.artifacts.put_text
        writes = []

        def track_artifact_write(value: str) -> object:
            writes.append(value)
            return original_put_text(value)

        monkeypatch.setattr(manager.artifacts, "put_text", track_artifact_write)
        assert workflow.record_r4([category_run]) == artifact_id
        with pytest.raises(ModelError, match="R4_COMPLETED already committed"):
            workflow.record_r4([replace(
                category_run, rationale="conflicting category run",
            )])
        assert writes == []
        r4_event = next(
            event for event in manager.store.list_events("CMP-r4")
            if event.event_type == "R4_COMPLETED"
        )
        assert r4_event.payload["linked_finding_count"] == 0
        assert r4_event.payload_ref == artifact_id
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


def test_category_plan_cli_records_only_approved_catalog_cards(
    tmp_path: Path, capsys: object,
) -> None:
    manager, workflow, plan = _ready_for_r4(tmp_path)
    try:
        catalog = KnowledgeCatalog.load(default_knowledge_root())
        approved_card = next(
            card for card in catalog.cards.values()
            if card["family"] == "STATE"
            and "python" in card["language_applicability"]
        )
        input_path = tmp_path / "category-plan.json"
        input_path.write_text(json.dumps({
            "card_ids": [approved_card["mechanism_id"]],
            "budget": {"agent_runs": 2},
        }), encoding="utf-8")

        assert main([
            "category-plan", str(tmp_path), workflow.campaign_id,
            workflow.batch_id, "--input", str(input_path),
        ]) == 0
        result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        event = workflow._require_stage("CATEGORY_AUDIT_PLAN_RECORDED")
        artifact = json.loads(manager.artifacts.get_bytes(event.payload_ref))
        assert result["artifact_id"] == event.payload_ref
        assert len(artifact["category_plans"]) == 1
        category_plan = artifact["category_plans"][0]
        assert category_plan["work_unit_id"] == plan.work_units[0].work_unit_id
        assert category_plan["family"] == "STATE"
        assert category_plan["seed_card_ids"] == [approved_card["mechanism_id"]]
        assert category_plan["budget"] == {"agent_runs": 2}
    finally:
        manager.close()


@pytest.mark.parametrize("static_hypothesis", [False, True])
def test_r4_category_plan_runs_as_durable_task(
    tmp_path: Path, static_hypothesis: bool,
) -> None:
    manager, workflow, plan = _ready_for_r4(tmp_path, static_hypothesis=static_hypothesis)
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
                review_altitude=ReviewAltitude.INSPECTED,
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
        assert "Omit work_unit_id from each AxisRun" in task_input["analysis_contract"]
        assert task_input["mechanism_cards"][0]["mechanism_id"] == state_card["mechanism_id"]
        assert task_input["knowledge_context"]["issue_entries"]
        assert task_input["knowledge_context"]["knowledge_version"] == "portfolio-2026-09-v1"
        assert bool(task_input["allowed_hypothesis_ids"]) is static_hypothesis
        lease = backend.claim("category-auditor")
        assert lease is not None
        missing_altitude = asdict(run)
        missing_altitude["axis_runs"][0]["review_altitude"] = "NOT_RECORDED"
        missing_altitude_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "category_run": missing_altitude,
        })).artifact_id
        with pytest.raises(
            ModelError, match="applicable axis requires SCREENED or INSPECTED altitude",
        ):
            backend.collect(lease, TaskResult(
                True, missing_altitude_ref, "applicable R4 axis has no altitude",
                {"agent_runs": 1, "wall_seconds": 1},
            ))
        assert backend.poll(scheduled[0].task.task_id).status.value == "LEASED"
        unknown_hypothesis = asdict(run)
        unknown_hypothesis["hypothesis_ids"] = ["invented-slug"]
        unknown_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "category_run": unknown_hypothesis,
        })).artifact_id
        with pytest.raises(ModelError, match="allowed_hypothesis_ids"):
            backend.collect(lease, TaskResult(
                True, unknown_ref, "invalid hypothesis reference",
                {"agent_runs": 1, "wall_seconds": 1},
            ))
        assert category_plan.mechanism_variants
        missing_status = asdict(run)
        missing_status.pop("status")
        missing_status_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "category_run": missing_status,
        })).artifact_id
        with pytest.raises(ModelError, match="CategoryRun is missing fields.*status"):
            backend.collect(lease, TaskResult(
                True, missing_status_ref, "missing status",
                {"agent_runs": 1, "wall_seconds": 1},
            ))
        split_variant = asdict(run)
        split_variant["mechanism_variants_examined"] = [
            category_plan.mechanism_variants[0] + "-split"
        ]
        split_variant_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "category_run": split_variant,
        })).artifact_id
        with pytest.raises(ModelError, match="R4 mechanism coverage mismatch"):
            backend.collect(lease, TaskResult(
                True, split_variant_ref, "variant split from planned literal",
                {"agent_runs": 1, "wall_seconds": 1},
            ))
        assert backend.poll(scheduled[0].task.task_id).status.value == "LEASED"
        mismatched_axis_work_unit = asdict(run)
        mismatched_axis_work_unit["axis_runs"][0]["work_unit_id"] = "WU-unrelated"
        mismatched_axis_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "category_run": mismatched_axis_work_unit,
        })).artifact_id
        with pytest.raises(ModelError, match="AxisRun Work Unit mismatch"):
            backend.collect(lease, TaskResult(
                True, mismatched_axis_ref, "mismatched AxisRun Work Unit",
                {"agent_runs": 1, "wall_seconds": 1},
            ))
        assert backend.poll(scheduled[0].task.task_id).status.value == "LEASED"
        compact_run = asdict(run)
        for axis_run in compact_run["axis_runs"]:
            axis_run.pop("work_unit_id")
        compact_output_bytes = len(json.dumps({
            "schema_version": "1.0", "category_run": compact_run,
        }).encode("utf-8"))
        expanded_output_bytes = len(json.dumps({
            "schema_version": "1.0", "category_run": asdict(run),
        }).encode("utf-8"))
        assert compact_output_bytes < expanded_output_bytes
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "category_run": compact_run,
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, output_ref, "category complete", {"agent_runs": 1, "wall_seconds": 1},
            execution_configuration_fixture(),
        ))
        coordinator.commit_r4()
        events = manager.store.list_events("CMP-r4")
        assert sum(event.event_type == "R4_COMPLETED" for event in events) == 1
        event = next(item for item in events if item.event_type == "R4_COMPLETED")
        artifact = json.loads(manager.artifacts.get_bytes(event.payload_ref))
        assert event.payload["source_task_output_refs"] == {
            scheduled[0].task.task_id: output_ref,
        }
        assert event.payload["upstream_revision_ids"] == {
            "CATEGORY_AUDIT_PLAN_RECORDED": workflow._require_stage(
                "CATEGORY_AUDIT_PLAN_RECORDED"
            ).event_id,
            "R2_COMPLETED": workflow._require_stage("R2_COMPLETED").payload[
                "revision_id"
            ],
            "R3_COMPLETED": workflow._require_stage("R3_COMPLETED").payload[
                "revision_id"
            ],
        }
        assert all(
            axis_run["work_unit_id"] == category_plan.work_unit_id
            for axis_run in artifact["category_runs"][0]["axis_runs"]
        )
        assert all(
            axis_run["review_altitude"] == "INSPECTED"
            for axis_run in artifact["category_runs"][0]["axis_runs"]
        )
        previous_r5_tasks = coordinator.schedule_r5()
        prior_event = event
        amended_run = asdict(replace(
            run, rationale="corrected after the R4 projection was committed",
        ))
        for axis_run in amended_run["axis_runs"]:
            axis_run.pop("work_unit_id")
        replacement_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "category_run": amended_run,
        })).artifact_id
        backend.amend_completed_output(
            scheduled[0].task.task_id,
            replacement_ref,
            reason="corrected a committed category rationale",
            evidence_refs=(output_ref, replacement_ref),
        )
        assert workflow._stage_event("R4_COMPLETED") is None
        coordinator.commit_r4()
        replacement_event = workflow._require_stage("R4_COMPLETED")
        assert replacement_event.event_id != prior_event.event_id
        assert replacement_event.payload["source_task_output_refs"] == {
            scheduled[0].task.task_id: replacement_ref,
        }
        replacement_r5_tasks = coordinator.schedule_r5()
        assert len(replacement_r5_tasks) == len(previous_r5_tasks)
        assert {
            view.task.task_id for view in replacement_r5_tasks
        }.isdisjoint({view.task.task_id for view in previous_r5_tasks})
        assert coordinator._active_task_views(
            operation="assess_experiment",
        ) == replacement_r5_tasks
        assert sum(
            item.event_type == "R4_COMPLETED"
            for item in manager.store.list_batch_events(
                "CMP-r4", workflow.batch_id, event_type="R4_COMPLETED",
            )
        ) == 2
    finally:
        manager.close()


def test_r4_bundle_schedules_two_work_units_and_commits_each_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = {
        tmp_path / "services" / "api" / "pyproject.toml": "[project]\nname='api'\n",
        tmp_path / "services" / "api" / "api.py": "def handle(): pass\n",
        tmp_path / "services" / "worker" / "pyproject.toml": "[project]\nname='worker'\n",
        tmp_path / "services" / "worker" / "worker.py": "def run(): pass\n",
    }
    for path, contents in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:r4-bundle")
    plan = create_audit_plan(
        campaign_id="CMP-r4-bundle",
        inventory=inventory,
        category_families=["STATE"],
        max_source_files_per_work_unit=1,
        max_source_files_per_batch=2,
        max_work_units_per_batch=2,
    )
    assert len(plan.work_units) == 2
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-r4-bundle", snapshot_id="fixture:r4-bundle")
    manager.record_inventory(campaign_id="CMP-r4-bundle", inventory=inventory)
    manager.record_plan(campaign_id="CMP-r4-bundle", plan=plan, inventory=inventory)
    workflow = BatchWorkflow(manager, "CMP-r4-bundle", plan.batches[0].batch_id)
    try:
        workflow.run_r0()
        workflow.record_r1([])
        evidence = {
            axis.value: (f"EVID-{axis.value}",) for axis in DiscoveryAxis
        }
        workflow.record_r2(
            [],
            axis_evidence=evidence,
            axis_runs=tuple(
                AxisRun(
                    axis=DiscoveryAxis(axis),
                    applicability=Applicability.APPLICABLE,
                    evidence_refs=(f"EVID-{axis}-{unit.work_unit_id}",),
                    rationale=f"reviewed {axis} for {unit.work_unit_id}",
                    work_unit_id=unit.work_unit_id,
                )
                for unit in plan.work_units
                for axis in (item.value for item in DiscoveryAxis)
            ),
        )
        workflow.record_r3([])
        workflow.record_revival_selection(
            [], rationale="no unreachable hypotheses", evidence_refs=("EVID-r3",)
        )
        workflow.complete_r35()
        catalog = KnowledgeCatalog.load(default_knowledge_root())
        state_card = next(
            card for card in catalog.cards.values()
            if card["family"] == "STATE"
            and "python" in card["language_applicability"]
        )
        category_plans = create_category_audit_plans(
            plan.work_units, [MechanismCard.from_dict(state_card)], budget={},
        )
        assert all(item.seed_card_ids for item in category_plans)
        workflow.record_category_audit_plan(category_plans)
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend, catalog)
        with pytest.raises(ModelError, match="above bundle limit"):
            coordinator.schedule_r4_bundled(
                max_work_units_per_task=2, max_task_input_bytes=1,
            )
        tasks = coordinator.schedule_r4_bundled(max_work_units_per_task=2)
        assert len(tasks) == 1
        resumed_tasks = coordinator.schedule_r4_bundled(max_work_units_per_task=2)
        assert [view.task.task_id for view in resumed_tasks] == [tasks[0].task.task_id]
        with pytest.raises(ModelError, match="already has bundled tasks"):
            coordinator.schedule_r4()
        assert set(tasks[0].task.work_unit_ids) == {
            unit.work_unit_id for unit in plan.work_units
        }
        task_input = json.loads(manager.artifacts.get_bytes(tasks[0].task.input_refs[0]))
        assert len(task_input["category_items"]) == 2
        assert task_input["bundle_input_version"] == "2.0"
        assert task_input["family"] == "STATE"
        assert len(task_input["discovery_axis_sets"]) == 1
        assert all(
            item["seed_card_ids"] == [state_card["mechanism_id"]]
            for item in task_input["category_items"]
        )
        assert all("category_plan" not in item for item in task_input["category_items"])
        assert all(
            "category_families" not in item["work_unit"]
            and "discovery_axes" not in item["work_unit"]
            for item in task_input["category_items"]
        )
        assert {item["discovery_axis_set_id"] for item in task_input["category_items"]} == {0}
        assert task_input["mechanism_cards"] == [state_card]
        work_units_by_id = {
            str(item["work_unit_id"]): item
            for item in workflow.batch.manifest["work_units"]
        }
        legacy_task_input = coordinator._r4_bundle_input(
            "STATE",
            [asdict(item) for item in category_plans],
            work_units_by_id,
            {},
            wire_version="1.0",
        )
        compact_size = len(json.dumps(
            task_input, sort_keys=True, separators=(",", ":")
        ).encode("utf-8"))
        legacy_size = len(json.dumps(
            legacy_task_input, sort_keys=True, separators=(",", ":")
        ).encode("utf-8"))
        assert compact_size < legacy_size
        expanded_payload = {
            **task_input,
            "mechanism_cards": [state_card, state_card],
        }
        expanded_size = len(json.dumps(expanded_payload, separators=(",", ":")).encode("utf-8"))
        assert compact_size < expanded_size
        assert all(item["allowed_hypothesis_ids"] == [] for item in task_input["category_items"])
        lease = backend.claim("bundle-worker")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "category_runs": [asdict(CategoryRun(
                category_run_id=f"CR-{category_plan.category_plan_id}",
                category_plan_id=category_plan.category_plan_id,
                work_unit_id=category_plan.work_unit_id,
                family=category_plan.family,
                mechanism_variants_examined=category_plan.mechanism_variants,
                axis_runs=tuple(AxisRun(
                    axis=DiscoveryAxis(axis),
                    applicability=Applicability.APPLICABLE,
                    evidence_refs=(f"EVID-{axis}-{category_plan.work_unit_id}",),
                    rationale=f"reviewed {axis}",
                    work_unit_id=category_plan.work_unit_id,
                    review_altitude=ReviewAltitude.INSPECTED,
                ) for axis in category_plan.discovery_axes),
                applicability=Applicability.APPLICABLE,
                status=CategoryRunStatus.COMPLETE,
                evidence_refs=(f"EVID-r4-{category_plan.work_unit_id}",),
                rationale="all planned category checks were completed",
                hypothesis_ids=(),
                finding_ids=(),
            )) for category_plan in category_plans],
        })).artifact_id
        backend._validate_category_run_bundle(
            replace(tasks[0].task, input_refs=(manager.artifacts.put_text(
                json.dumps(legacy_task_input)
            ).artifact_id,)),
            json.loads(manager.artifacts.get_bytes(output_ref)),
        )
        original_get_bytes = manager.artifacts.get_bytes

        def corrupt_bundle_context(artifact_id: str) -> bytes:
            value = original_get_bytes(artifact_id)
            if artifact_id == tasks[0].task.input_refs[0]:
                malformed_input = json.loads(value)
                malformed_input["category_items"][0]["task_context_id"] = 999
                return json.dumps(malformed_input).encode("utf-8")
            return value

        with monkeypatch.context() as patch:
            patch.setattr(manager.artifacts, "get_bytes", corrupt_bundle_context)
            with pytest.raises(ModelError, match="invalid task context reference"):
                backend.collect(lease, TaskResult(
                    True, output_ref, "invalid v2 task context reference",
                    {"agent_runs": 1, "wall_seconds": 1},
                ))
        assert backend.poll(lease.task.task_id).status.value == "LEASED"

        def corrupt_bundle_axis_set(artifact_id: str) -> bytes:
            value = original_get_bytes(artifact_id)
            if artifact_id == tasks[0].task.input_refs[0]:
                malformed_input = json.loads(value)
                malformed_input["category_items"][0]["discovery_axis_set_id"] = 999
                return json.dumps(malformed_input).encode("utf-8")
            return value

        with monkeypatch.context() as patch:
            patch.setattr(manager.artifacts, "get_bytes", corrupt_bundle_axis_set)
            with pytest.raises(ModelError, match="invalid discovery axis set"):
                backend.collect(lease, TaskResult(
                    True, output_ref, "invalid v2 axis set reference",
                    {"agent_runs": 1, "wall_seconds": 1},
                ))
        assert backend.poll(lease.task.task_id).status.value == "LEASED"

        invalid_bundle = json.loads(manager.artifacts.get_bytes(output_ref))
        invalid_bundle["category_runs"][0]["hypothesis_ids"] = ["invented-slug"]
        invalid_ref = manager.artifacts.put_text(json.dumps(invalid_bundle)).artifact_id
        with pytest.raises(ModelError, match="allowed_hypothesis_ids"):
            backend.collect(lease, TaskResult(
                True, invalid_ref, "invalid bundled hypothesis reference",
                {"agent_runs": 1, "wall_seconds": 1},
            ))
        backend.collect(lease, TaskResult(
            True, output_ref, "bundled R4 review complete",
            {"agent_runs": 1, "wall_seconds": 2},
        ))
        coordinator.commit_r4()
        r4_event = workflow._require_stage("R4_COMPLETED")
        assert r4_event.payload_ref is not None
        r4 = json.loads(manager.artifacts.get_bytes(r4_event.payload_ref))
        assert r4_event.payload["source_task_output_refs"] == {
            tasks[0].task.task_id: output_ref,
        }
        assert r4_event.payload["upstream_revision_ids"] == {
            "CATEGORY_AUDIT_PLAN_RECORDED": workflow._require_stage(
                "CATEGORY_AUDIT_PLAN_RECORDED"
            ).event_id,
            "R2_COMPLETED": workflow._require_stage("R2_COMPLETED").payload[
                "revision_id"
            ],
            "R3_COMPLETED": workflow._require_stage("R3_COMPLETED").payload[
                "revision_id"
            ],
        }
        assert {run["category_plan_id"] for run in r4["category_runs"]} == {
            item.category_plan_id for item in category_plans
        }
        assert all(
            axis_run["review_altitude"] == "INSPECTED"
            for run in r4["category_runs"]
            for axis_run in run["axis_runs"]
        )
    finally:
        manager.close()


def test_r4_screening_work_unit_needs_no_agent_category_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, plan = _ready_for_r4(
        tmp_path, screening_work_unit=True
    )
    try:
        category_plan = create_category_audit_plans(
            plan.work_units, [_card()], budget={}
        )[0]
        workflow.record_category_audit_plan([category_plan])
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)

        original_append = manager.store._append_event_tx

        def fail_screening_append(**kwargs: object) -> object:
            if kwargs.get("event_type") == "R4_SCREENING_COVERAGE_RECORDED":
                raise RuntimeError("injected R4 screening event append failure")
            return original_append(**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(manager.store, "_append_event_tx", fail_screening_append)
            with pytest.raises(
                RuntimeError, match="injected R4 screening event append failure",
            ):
                coordinator.schedule_r4()
        assert workflow._stage_event("R4_SCREENING_COVERAGE_RECORDED") is None

        assert coordinator.schedule_r4() == ()
        screening_event = next(
            event for event in manager.store.list_batch_events(
                workflow.campaign_id, workflow.batch_id,
                event_type="R4_SCREENING_COVERAGE_RECORDED",
            )
        )
        assert screening_event.payload["category_plan_ids"] == [
            category_plan.category_plan_id,
        ]
        assert screening_event.payload["source_task_output_refs"] == {}
        assert screening_event.payload["upstream_revision_ids"] == {
            "CATEGORY_AUDIT_PLAN_RECORDED": workflow._require_stage(
                "CATEGORY_AUDIT_PLAN_RECORDED"
            ).event_id,
            "R2_COMPLETED": workflow._require_stage("R2_COMPLETED").payload[
                "revision_id"
            ],
        }
        screening_runs = [
            CategoryRun.from_dict(item)
            for item in json.loads(
                manager.artifacts.get_bytes(screening_event.payload_ref)
            )["category_runs"]
        ]
        assert workflow.record_r4_screening_runs(screening_runs) == screening_event.payload_ref
        with pytest.raises(ModelError, match="conflicts with its prior projection"):
            workflow.record_r4_screening_runs((replace(
                screening_runs[0], rationale="conflicting replay",
            ),))
        assert len(manager.store.list_batch_events(
            workflow.campaign_id, workflow.batch_id,
            event_type="R4_SCREENING_COVERAGE_RECORDED",
        )) == 1

        coordinator.commit_r4()
        r4_event = next(
            event for event in manager.store.list_batch_events(
                workflow.campaign_id, workflow.batch_id,
                event_type="R4_COMPLETED",
            )
        )
        runs = json.loads(manager.artifacts.get_bytes(r4_event.payload_ref))["category_runs"]
        assert len(runs) == 1
        assert runs[0]["applicability"] == Applicability.NOT_APPLICABLE.value
        assert runs[0]["status"] == CategoryRunStatus.COMPLETE.value
        assert runs[0]["hypothesis_ids"] == []
    finally:
        manager.close()