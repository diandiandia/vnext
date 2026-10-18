from pathlib import Path
from dataclasses import replace

import pytest

from reachable_audit.analysis_models import (
    Adjudication,
    AdjudicationActor,
    Applicability,
    AttackAngle,
    AxisRun,
    BoundaryDataMapping,
    BoundaryDirection,
    BoundaryProof,
    BatchClosure,
    BoundaryDisposition,
    BoundaryReview,
    CategoryRun,
    CategoryRunStatus,
    DiscoveryAxis,
    EvidenceGrade,
    HandoffOutcome,
    HandoffResolution,
    Hypothesis,
    HypothesisStatus,
    Mechanism,
    Refutation,
    Surface,
    VerdictKind,
    VerdictSubmission,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.handoffs import HandoffResolver
from reachable_audit.inventory import build_inventory
from reachable_audit.knowledge import create_category_audit_plans
from reachable_audit.models import CampaignAuditMode, ModelError
from reachable_audit.plan_models import BoundaryEdge
from reachable_audit.planning import create_audit_plan
from conftest import axis_runs_from_evidence


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_resolve_many_reconciles_30k_handoffs(tmp_path: Path) -> None:
    _write(tmp_path / "entry" / "pyproject.toml", "[project]\nname='entry'\n")
    _write(tmp_path / "entry" / "entry.py", "def receive(): pass\n")
    _write(tmp_path / "parser" / "pyproject.toml", "[project]\nname='parser'\n")
    _write(tmp_path / "parser" / "parser.py", "def parse(): pass\n")
    inventory = build_inventory(tmp_path, "fixture:handoff-scale")
    components = {component.root: component.component_id for component in inventory.components}
    edge_count = 30_000
    plan = create_audit_plan(
        campaign_id="CMP-handoff-scale",
        inventory=inventory,
        category_families=["PARSING"],
        boundary_edges=tuple(BoundaryEdge(
            edge_id=f"EDGE-{index:05d}",
            source_component_id=components["entry"],
            target_component_id=components["parser"],
            kind="call",
            evidence="synthetic scale edge",
            source_path="entry/entry.py",
        ) for index in range(edge_count)),
        max_work_units_per_batch=1,
    )
    assert len(plan.handoffs) == edge_count

    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            campaign_id="CMP-handoff-scale", snapshot_id=inventory.snapshot_id,
        )
        manager.record_inventory(
            campaign_id="CMP-handoff-scale", inventory=inventory,
        )
        manager.record_plan(
            campaign_id="CMP-handoff-scale", plan=plan, inventory=inventory,
        )
        manager.store.append_events_batch("CMP-handoff-scale", [{
            "batch_id": batch.batch_id,
            "entity_type": "batch_stage",
            "entity_id": batch.batch_id,
            "event_type": "R3_COMPLETED",
            "idempotency_key": f"scale-r3:{batch.batch_id}",
            "actor": "test",
            "payload": {},
            "payload_ref": None,
        } for batch in plan.batches])

        resolutions = tuple(HandoffResolution(
            handoff_id=handoff.handoff_id,
            owner_batch_id=handoff.owner_batch,
            outcome=HandoffOutcome.NEEDS_REVIEW,
            chain_suffix=(),
            evidence_refs=(f"EVID-scale-{index}",),
            rationale="synthetic Handoff reconciliation scale fixture",
        ) for index, handoff in enumerate(plan.handoffs))
        artifact_ids = HandoffResolver(
            manager, "CMP-handoff-scale", plan,
        ).resolve_many(resolutions)

        resolved_events = manager.store.list_events(
            "CMP-handoff-scale", event_type="HANDOFF_RESOLVED",
        )
        assert len(artifact_ids) == edge_count
        assert len(resolved_events) == edge_count
        assert {event.entity_id for event in resolved_events} == {
            handoff.handoff_id for handoff in plan.handoffs
        }


def test_resolved_handoff_merges_a_cross_batch_call_chain(tmp_path: Path) -> None:
    _write(tmp_path / "entry" / "pyproject.toml", "[project]\nname='entry'\n")
    _write(tmp_path / "entry" / "entry.py", "def receive(): pass\n")
    _write(tmp_path / "parser" / "pyproject.toml", "[project]\nname='parser'\n")
    _write(tmp_path / "parser" / "parser.py", "def parse(): pass\n")
    _write(tmp_path / "decoder" / "CMakeLists.txt", "add_library(decoder decoder.c)\n")
    _write(tmp_path / "decoder" / "decoder.c", "int decode(void) { return 0; }\n")
    inventory = build_inventory(tmp_path, "fixture:handoff")
    components = {component.root: component.component_id for component in inventory.components}
    plan = create_audit_plan(
        campaign_id="CMP-handoff",
        inventory=inventory,
        category_families=["PARSING"],
        boundary_edges=[
            BoundaryEdge(
                edge_id="EDGE-entry-parser",
                source_component_id=components["entry"],
                target_component_id=components["parser"],
                kind="call",
                evidence="EVID-build-edge-parser",
                source_path="entry/entry.py",
            ),
            BoundaryEdge(
                edge_id="EDGE-entry-decoder",
                source_component_id=components["entry"],
                target_component_id=components["decoder"],
                kind="call",
                evidence="EVID-build-edge-decoder",
                source_path="entry/entry.py",
            ),
        ],
        max_source_files_per_work_unit=1,
        max_source_files_per_batch=1,
        max_work_units_per_batch=1,
    )
    handoffs = tuple(sorted(plan.handoffs, key=lambda item: item.edge_id))
    assert {source.language for source in inventory.source_files} == {"python", "c"}

    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            campaign_id="CMP-handoff", snapshot_id="fixture:handoff"
        )
        manager.record_inventory(campaign_id="CMP-handoff", inventory=inventory)
        manager.record_plan(
            campaign_id="CMP-handoff", plan=plan, inventory=inventory
        )
        work_units = {unit.work_unit_id: unit for unit in plan.work_units}
        units_by_batch = {
            batch.batch_id: work_units[batch.work_unit_ids[0]] for batch in plan.batches
        }
        for batch in plan.batches:
            workflow = BatchWorkflow(manager, "CMP-handoff", batch.batch_id)
            workflow.run_r0()
            reviews = [
                BoundaryReview(
                    edge_id=edge_id,
                    work_unit_id=work_unit_id,
                    disposition=BoundaryDisposition.CONFIRMED,
                    evidence_refs=(f"LOC-{work_units[work_unit_id].source_files[0]}:1",),
                    rationale="source and owner components expose this declared call edge",
                )
                for work_unit_id in batch.work_unit_ids
                for edge_id in work_units[work_unit_id].boundary_edge_ids
            ]
            workflow.record_r1([], reviews)
            axis_evidence = {
                    "surface": (f"EVID-{batch.batch_id}-surface",),
                    "mechanism": (f"EVID-{batch.batch_id}-mechanism",),
                    "state": (f"EVID-{batch.batch_id}-state",),
                    "fix_variant": (f"EVID-{batch.batch_id}-fix",),
                    "boundary": (f"EVID-{batch.batch_id}-boundary",),
                    "differential": (f"EVID-{batch.batch_id}-differential",),
                }
            workflow.record_r2(
                [],
                axis_evidence=axis_evidence,
                axis_runs=axis_runs_from_evidence(axis_evidence),
            )
            workflow.record_r3([])

        resolver = HandoffResolver(manager, "CMP-handoff", plan)
        edges_by_id = {edge.edge_id: edge for edge in plan.boundary_edges}
        resolutions = tuple(
            HandoffResolution(
                handoff_id=handoff.handoff_id,
                owner_batch_id=handoff.owner_batch,
                outcome=HandoffOutcome.EDGE_PROVEN,
                chain_suffix=(
                    "LOC-entry/entry.py:1",
                    f"LOC-{units_by_batch[handoff.owner_batch].source_files[0]}:1",
                ),
                evidence_refs=(f"EVID-owner-{handoff.edge_id}",),
                rationale="owner verified the cross-batch entry edge",
                boundary_proof=BoundaryProof(
                    edge_id=handoff.edge_id,
                    source_component_id=edges_by_id[handoff.edge_id].source_component_id,
                    target_component_id=edges_by_id[handoff.edge_id].target_component_id,
                    interface_kind=edges_by_id[handoff.edge_id].kind,
                    direction=BoundaryDirection.SOURCE_TO_TARGET,
                    principal="remote client",
                    premises=("the client can reach the entry function",),
                    source_evidence_refs=("LOC-entry/entry.py:1",),
                    target_evidence_refs=(
                        f"LOC-{units_by_batch[handoff.owner_batch].source_files[0]}:1",
                    ),
                    data_mappings=(BoundaryDataMapping(
                        source_value="request bytes",
                        target_value="parser input",
                        meaning="untrusted request bytes reach the target parser",
                        evidence_refs=(
                            "LOC-entry/entry.py:1",
                            f"LOC-{units_by_batch[handoff.owner_batch].source_files[0]}:1",
                        ),
                    ),),
                ),
            )
            for handoff in handoffs
        )
        with pytest.raises(ModelError, match="duplicate handoff IDs"):
            resolver.resolve_many((resolutions[0], resolutions[0]))
        with pytest.raises(ModelError, match="non-owner Batch"):
            resolver.resolve_many((
                resolutions[0],
                HandoffResolution(
                    **{
                        **resolutions[1].__dict__,
                        "owner_batch_id": "B-not-owner",
                    }
                ),
            ))
        assert not [
            event for event in manager.store.list_events("CMP-handoff")
            if event.event_type == "HANDOFF_RESOLVED"
        ]
        first_proof = resolutions[0].boundary_proof
        assert first_proof is not None
        with pytest.raises(ModelError, match="requires a boundary proof"):
            resolver.resolve_many((replace(
                resolutions[0], boundary_proof=None,
            ),))
        with pytest.raises(ModelError, match="valid only for EDGE_PROVEN"):
            resolver.resolve_many((replace(
                resolutions[0], outcome=HandoffOutcome.BLOCKED,
            ),))
        with pytest.raises(ModelError, match="each Boundary data mapping"):
            resolver.resolve_many((replace(
                resolutions[0],
                boundary_proof=replace(
                    first_proof,
                    data_mappings=(replace(
                        first_proof.data_mappings[0],
                        evidence_refs=(first_proof.source_evidence_refs[0],),
                    ),),
                ),
            ),))
        with pytest.raises(ModelError, match="does not match planned edge endpoints"):
            resolver.resolve_many((replace(
                resolutions[0],
                boundary_proof=replace(
                    first_proof, target_component_id="COMP-forged",
                ),
            ),))
        with pytest.raises(ModelError, match="source proof evidence"):
            resolver.resolve_many((replace(
                resolutions[0],
                boundary_proof=replace(
                    first_proof,
                    source_evidence_refs=(
                        *first_proof.source_evidence_refs,
                        "LOC-missing.py:1",
                    ),
                ),
            ),))
        with pytest.raises(ModelError, match="not owned by the planned endpoint component"):
            resolver.resolve_many((replace(
                resolutions[0],
                boundary_proof=replace(
                    first_proof,
                    source_evidence_refs=(
                        *first_proof.source_evidence_refs,
                        "LOC-parser/parser.py:1",
                    ),
                ),
            ),))
        assert not manager.store.list_events(
            "CMP-handoff", event_type="HANDOFF_RESOLVED"
        )
        artifact_ids = resolver.resolve_many(resolutions)
        assert len(artifact_ids) == 2
        assert len([
            event for event in manager.store.list_events("CMP-handoff")
            if event.event_type == "HANDOFF_RESOLVED"
        ]) == 2

        handoff = handoffs[0]
        with pytest.raises(ModelError, match="must join"):
            resolver.integrate(
                handoff.handoff_id,
                known_chain_prefix=("LOC-unrelated.py:99",),
                evidence_refs=("EVID-unrelated",),
            )
        assert not manager.store.list_events(
            "CMP-handoff", event_type="HANDOFF_INTEGRATED"
        )
        integrated = resolver.integrate(
            handoff.handoff_id,
            known_chain_prefix=("LOC-entry/entry.py:1",),
            evidence_refs=("EVID-source-edge",),
        )

        assert integrated["call_chain"] == [
            "LOC-entry/entry.py:1", resolutions[0].chain_suffix[1]
        ]
        assert integrated["evidence_refs"] == [
            "EVID-source-edge", *resolutions[0].evidence_refs,
            "LOC-entry/entry.py:1", resolutions[0].boundary_proof.target_evidence_refs[0],
        ]
        assert integrated["boundary_proof"]["edge_id"] == handoff.edge_id
        event_types = [
            event.event_type for event in manager.store.list_events("CMP-handoff")
        ]
        assert event_types.count("HANDOFF_RESOLVED") == 2
        assert event_types.count("HANDOFF_INTEGRATED") == 1

        source_unit = units_by_batch[handoff.from_batch]
        original = BatchWorkflow(manager, "CMP-handoff", handoff.from_batch)
        original.record_revival_selection(
            [], rationale="initial R3 had no hypotheses", evidence_refs=(integrated["artifact_id"],),
        )
        original.complete_r35()
        category_plan = create_category_audit_plans((source_unit,), (), budget={})[0]
        original.record_category_audit_plan((category_plan,))
        late_risk = "Late R4 boundary candidate requires follow-up verification; not a confirmed finding."
        original.record_r4((CategoryRun(
            category_run_id="CR-late-candidate", category_plan_id=category_plan.category_plan_id,
            work_unit_id=source_unit.work_unit_id, family=category_plan.family,
            mechanism_variants_examined=category_plan.mechanism_variants,
            axis_runs=tuple(AxisRun(
                axis=DiscoveryAxis(axis), applicability=Applicability.APPLICABLE,
                evidence_refs=("LOC-entry/entry.py:1",), rationale="synthetic category review",
                work_unit_id=source_unit.work_unit_id,
            ) for axis in category_plan.discovery_axes),
            applicability=Applicability.APPLICABLE, status=CategoryRunStatus.COMPLETE,
            evidence_refs=(integrated["artifact_id"],), rationale=late_risk,
            hypothesis_ids=(), finding_ids=(),
        ),))
        original.record_r5((), ())
        original.build_transmission_metrics()
        original.close_r6(BatchClosure(
            budget_used={"agent_runs": 0}, constraints_observed=(), unreviewed_scope=(),
            residual_risks=(late_risk,), lessons=("route late candidates through a new Campaign",),
        ))
        old_verdict_ref = original._require_stage("R3_COMPLETED").payload_ref
        follow_up = manager.create_campaign(
            campaign_id="CMP-late-follow-up", snapshot_id=inventory.snapshot_id,
            audit_mode=CampaignAuditMode.FOLLOW_UP, history_source_campaign_ids=("CMP-handoff",),
        )
        manager.record_inventory(campaign_id=follow_up.campaign_id, inventory=inventory)
        follow_plan = create_audit_plan(
            campaign_id=follow_up.campaign_id, inventory=inventory, category_families=["PARSING"],
            max_work_units_per_batch=1,
        )
        manager.record_plan(campaign_id=follow_up.campaign_id, plan=follow_plan, inventory=inventory)
        entry_unit = next(unit for unit in follow_plan.work_units if "entry/entry.py" in unit.source_files)
        entry_batch = next(batch for batch in follow_plan.batches if entry_unit.work_unit_id in batch.work_unit_ids)
        review = BatchWorkflow(manager, follow_up.campaign_id, entry_batch.batch_id)
        review.run_r0()
        review.record_r1((Surface(
            "SURF-late", entry_unit.work_unit_id, entry_unit.component_id, "entry",
            "entry/entry.py", "receive", "remote", ("LOC-entry/entry.py:1",),
        ),))
        review.record_r2((Hypothesis(
            "HYP-late", entry_unit.work_unit_id, "boundary", ("SURF-late",), ("SURF-late",),
            Mechanism("PARSING", "cross-boundary-candidate"), late_risk, HypothesisStatus.NEW,
        ),), axis_evidence=axis_evidence, axis_runs=axis_runs_from_evidence(axis_evidence))
        review.record_r3((VerdictSubmission(
            "HYP-late", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN, "remote", (),
            tuple(integrated["call_chain"]), (integrated["artifact_id"],), (), (),
            "synthetic source chain reviewed in explicitly declared follow-up",
        ),))
        for refuter, angle in (("call-reviewer", AttackAngle.CALL_CHAIN), ("premise-reviewer", AttackAngle.PRINCIPAL)):
            review.record_refutation(Refutation(
                f"REF-{refuter}", "HYP-late", refuter, VerdictKind.REACHABLE, angle,
                (integrated["artifact_id"],), "synthetic independent review record",
            ))
        review.record_adjudication(Adjudication(
            "ADJ-late", "HYP-late", ("REF-call-reviewer", "REF-premise-reviewer"),
            VerdictKind.REACHABLE, AdjudicationActor.AUTO, (), "both required perspectives recorded",
        ))
        review.record_revival_selection([], rationale="no rejected candidates", evidence_refs=(integrated["artifact_id"],))
        review.complete_r35()
        assert original._require_stage("R3_COMPLETED").payload_ref == old_verdict_ref
        assert not manager.store.list_events("CMP-handoff", event_type="FINDING_RECORDED")
        assert review._require_stage("R3_5_COMPLETED") is not None
        assert follow_up.history_source_campaign_ids == ("CMP-handoff",)


def test_handoff_can_record_evidenced_non_security_boundary() -> None:
    resolution = HandoffResolution.from_dict({
        "handoff_id": "HO-build-import",
        "owner_batch_id": "B-owner",
        "outcome": HandoffOutcome.NOT_SECURITY_BOUNDARY.value,
        "evidence_refs": ["LOC-tools/helper.py:1"],
        "rationale": "The import resolves to a development-time standard-library helper, not a runtime trust edge.",
    })

    assert resolution.outcome is HandoffOutcome.NOT_SECURITY_BOUNDARY
    assert resolution.chain_suffix == ()


def test_edge_proven_handoff_requires_interface_and_data_mapping_proof() -> None:
    with pytest.raises(ModelError, match="requires a boundary proof"):
        HandoffResolution.from_dict({
            "handoff_id": "HO-edge-proof",
            "owner_batch_id": "B-owner",
            "outcome": HandoffOutcome.EDGE_PROVEN.value,
            "chain_suffix": ["LOC-source.py:1", "LOC-target.py:1"],
            "evidence_refs": ["EVID-edge"],
            "rationale": "the chain is structurally joined",
        })