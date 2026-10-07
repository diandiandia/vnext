from pathlib import Path

import pytest

from reachable_audit.analysis_models import (
    BoundaryDisposition,
    BoundaryReview,
    HandoffOutcome,
    HandoffResolution,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.handoffs import HandoffResolver
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from reachable_audit.plan_models import BoundaryEdge
from reachable_audit.planning import create_audit_plan
from conftest import axis_runs_from_evidence


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_resolved_handoff_merges_a_cross_batch_call_chain(tmp_path: Path) -> None:
    _write(tmp_path / "entry" / "pyproject.toml", "[project]\nname='entry'\n")
    _write(tmp_path / "entry" / "entry.py", "def receive(): pass\n")
    _write(tmp_path / "parser" / "pyproject.toml", "[project]\nname='parser'\n")
    _write(tmp_path / "parser" / "parser.py", "def parse(): pass\n")
    _write(tmp_path / "decoder" / "pyproject.toml", "[project]\nname='decoder'\n")
    _write(tmp_path / "decoder" / "decoder.py", "def decode(): pass\n")
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
    handoffs = plan.handoffs

    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            campaign_id="CMP-handoff", snapshot_id="fixture:handoff"
        )
        manager.record_inventory(campaign_id="CMP-handoff", inventory=inventory)
        manager.record_plan(
            campaign_id="CMP-handoff", plan=plan, inventory=inventory
        )
        work_units = {unit.work_unit_id: unit for unit in plan.work_units}
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
        resolutions = tuple(HandoffResolution(
            handoff_id=handoff.handoff_id,
            owner_batch_id=handoff.owner_batch,
            outcome=HandoffOutcome.EDGE_PROVEN,
            chain_suffix=("LOC-boundary", f"LOC-{handoff.edge_id}.py:1"),
            evidence_refs=(f"EVID-owner-{handoff.edge_id}",),
            rationale="owner verified the cross-batch entry edge",
        ) for handoff in handoffs)
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
        artifact_ids = resolver.resolve_many(resolutions)
        assert len(artifact_ids) == 2
        assert len([
            event for event in manager.store.list_events("CMP-handoff")
            if event.event_type == "HANDOFF_RESOLVED"
        ]) == 2

        handoff = handoffs[0]
        integrated = resolver.integrate(
            handoff.handoff_id,
            known_chain_prefix=("LOC-entry.py:1", "LOC-boundary"),
            evidence_refs=("EVID-source-edge",),
        )

        assert integrated["call_chain"] == [
            "LOC-entry.py:1", "LOC-boundary", resolutions[0].chain_suffix[1]
        ]
        assert integrated["evidence_refs"] == [
            "EVID-source-edge", *resolutions[0].evidence_refs
        ]
        event_types = [
            event.event_type for event in manager.store.list_events("CMP-handoff")
        ]
        assert event_types.count("HANDOFF_RESOLVED") == 2
        assert event_types.count("HANDOFF_INTEGRATED") == 1


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