import json
from pathlib import Path
import sqlite3

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.analysis_models import SkillIssue, SkillIssueKind, SkillIssueStatus
from reachable_audit.models import (
    BatchStatus,
    CampaignAuditMode,
    CampaignStatus,
    TransitionError,
)
from reachable_audit.store import AuditStore, ConflictError, NotFoundError


def test_campaign_and_batch_survive_reopen(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    with CampaignManager(target) as manager:
        campaign = manager.create_campaign(
            campaign_id="CMP-test",
            snapshot_id="fixture:snapshot-1",
            budget={"agent_runs": 10},
        )
        batch = manager.add_batch(
            campaign_id=campaign.campaign_id,
            batch_id="B-0001",
            manifest={"work_unit_ids": ["WU-parser"]},
        )
        assert batch.status is BatchStatus.PLANNED
        manager.store.transition_batch(campaign.campaign_id, batch.batch_id, BatchStatus.READY)
        manager.store.transition_batch(campaign.campaign_id, batch.batch_id, BatchStatus.RUNNING)
        manager.store.transition_batch(campaign.campaign_id, batch.batch_id, BatchStatus.COMPLETE)
        manager.store.transition_campaign(campaign.campaign_id, CampaignStatus.RUNNING)

    with AuditStore(target / ".audit_vnext" / "state.db") as reopened:
        assert reopened.get_campaign("CMP-test").status is CampaignStatus.RUNNING
        assert reopened.get_batch("CMP-test", "B-0001").status is BatchStatus.COMPLETE
        events = reopened.list_events("CMP-test")
        assert [event.sequence for event in events] == list(range(1, 8))
        assert sum(
            event.event_type == "SKILL_REGRESSION_BASELINE_RECORDED"
            for event in events
        ) == 1


def test_event_collection_is_idempotent_and_rejects_conflicts(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    with AuditStore(database) as store:
        store.create_campaign(
            campaign_id="CMP-idempotent",
            target_root="/runtime/target",
            snapshot_id="fixture:snapshot",
        )
        first = store.append_event(
            campaign_id="CMP-idempotent",
            batch_id=None,
            entity_type="work_unit",
            entity_id="WU-1",
            event_type="WORK_UNIT_OBSERVED",
            idempotency_key="observe:WU-1:input-a",
            actor="agent",
            payload={"surface_count": 4},
        )
        duplicate = store.append_event(
            campaign_id="CMP-idempotent",
            batch_id=None,
            entity_type="work_unit",
            entity_id="WU-1",
            event_type="WORK_UNIT_OBSERVED",
            idempotency_key="observe:WU-1:input-a",
            actor="agent",
            payload={"surface_count": 4},
        )
        assert first.inserted is True
        assert duplicate.inserted is False
        assert duplicate.event_id == first.event_id
        assert len(store.list_events("CMP-idempotent")) == 2

        with pytest.raises(ConflictError):
            store.append_event(
                campaign_id="CMP-idempotent",
                batch_id=None,
                entity_type="work_unit",
                entity_id="WU-1",
                event_type="WORK_UNIT_OBSERVED",
                idempotency_key="observe:WU-1:input-a",
                actor="agent",
                payload={"surface_count": 5},
            )


def test_event_queries_filter_by_entity_type_and_batch(tmp_path: Path) -> None:
    with AuditStore(tmp_path / "filtered.db") as store:
        store.create_campaign(
            campaign_id="CMP-filtered", target_root="/target",
            snapshot_id="fixture:filtered",
        )
        for batch_id, task_id in (("B-1", "TASK-1"), ("B-2", "TASK-2")):
            store.append_event(
                campaign_id="CMP-filtered", batch_id=batch_id,
                entity_type="execution_task", entity_id=task_id,
                event_type="TASK_SUBMITTED",
                idempotency_key=f"submit:{task_id}", actor="test",
                payload={},
            )
            store.append_event(
                campaign_id="CMP-filtered", batch_id=batch_id,
                entity_type="execution_task", entity_id=task_id,
                event_type="TASK_CLAIMED",
                idempotency_key=f"claim:{task_id}", actor="test",
                payload={},
            )

        assert [event.entity_id for event in store.list_events(
            "CMP-filtered", entity_type="execution_task", entity_id="TASK-2",
        )] == ["TASK-2", "TASK-2"]
        assert [event.event_type for event in store.list_batch_events(
            "CMP-filtered", "B-1", event_type="TASK_SUBMITTED",
        )] == ["TASK_SUBMITTED"]
        assert store.list_entity_ids(
            "CMP-filtered", entity_type="execution_task", event_type="TASK_SUBMITTED",
        ) == ("TASK-1", "TASK-2")


def test_filtered_task_ids_preserve_submission_order(tmp_path: Path) -> None:
    with AuditStore(tmp_path / "submission-order.db") as store:
        store.create_campaign(
            campaign_id="CMP-order", target_root="/target", snapshot_id="fixture:order",
        )
        for task_id in ("TASK-z-first", "TASK-a-second"):
            store.append_event(
                campaign_id="CMP-order", batch_id="B-1",
                entity_type="execution_task", entity_id=task_id,
                event_type="TASK_SUBMITTED", idempotency_key=f"submit:{task_id}",
                actor="test", payload={},
            )

        assert store.list_entity_ids(
            "CMP-order", entity_type="execution_task", event_type="TASK_SUBMITTED",
        ) == ("TASK-z-first", "TASK-a-second")


def test_illegal_terminal_transition_is_rejected(tmp_path: Path) -> None:
    with AuditStore(tmp_path / "state.db") as store:
        store.create_campaign(
            campaign_id="CMP-terminal",
            target_root="/runtime/target",
            snapshot_id="fixture:snapshot",
        )
        with pytest.raises(TransitionError):
            store.transition_campaign("CMP-terminal", CampaignStatus.COMPLETE)


def test_hundred_batches_can_be_recovered(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    with AuditStore(database) as store:
        store.create_campaign(
            campaign_id="CMP-large",
            target_root="/runtime/large",
            snapshot_id="fixture:large",
        )
        for index in range(100):
            batch_id = f"B-{index:04d}"
            store.add_batch(
                campaign_id="CMP-large",
                batch_id=batch_id,
                manifest={"work_unit_ids": [f"WU-{index:04d}"]},
            )
            store.transition_batch("CMP-large", batch_id, BatchStatus.READY)

    with AuditStore(database) as reopened:
        batches = reopened.list_batches("CMP-large")
        assert len(batches) == 100
        assert all(batch.status is BatchStatus.READY for batch in batches)
        assert len(reopened.list_events("CMP-large")) == 201


def test_fresh_campaign_does_not_import_prior_skill_regression_history(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    with CampaignManager(target) as manager:
        source = manager.create_campaign(
            campaign_id="CMP-source", snapshot_id="fixture:source"
        )
        manager.record_skill_review("CMP-source", (SkillIssue(
            issue_id="SKILL-old",
            kind=SkillIssueKind.DEFECT,
            stage="R3",
            summary="old target-specific workflow issue",
            evidence_refs=("EVT-old",),
            regression_expectation="exercise the old behavior",
            status=SkillIssueStatus.REGRESSION_PENDING,
        ),))
        fresh = manager.create_campaign(
            campaign_id="CMP-fresh", snapshot_id="fixture:fresh"
        )
        baseline = next(
            event for event in manager.store.list_events(fresh.campaign_id)
            if event.event_type == "SKILL_REGRESSION_BASELINE_RECORDED"
        )
        baseline_value = json.loads(manager.artifacts.get_bytes(baseline.payload_ref))

        assert source.audit_mode is CampaignAuditMode.FRESH
        assert fresh.audit_mode is CampaignAuditMode.FRESH
        assert baseline_value["issues"] == []


@pytest.mark.parametrize("invalid", (-0.1, 1.1, True, "0.5"))
def test_campaign_rejects_invalid_screening_ceiling(
    tmp_path: Path, invalid: object,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    with CampaignManager(target) as manager:
        with pytest.raises(ValueError, match="max_screening_fraction"):
            manager.create_campaign(
                campaign_id="CMP-bad-screening-limit",
                snapshot_id="fixture:bad-screening-limit",
                budget={"max_screening_fraction": invalid},
            )


def test_follow_up_requires_and_limits_history_sources(tmp_path: Path) -> None:
    first_target = tmp_path / "first"
    first_target.mkdir()
    second_target = tmp_path / "second"
    second_target.mkdir()
    with CampaignManager(first_target) as manager:
        source = manager.create_campaign(
            campaign_id="CMP-source", snapshot_id="fixture:source"
        )
        manager.record_skill_review("CMP-source", (SkillIssue(
            issue_id="SKILL-regression",
            kind=SkillIssueKind.DEFECT,
            stage="R3",
            summary="reusable workflow regression",
            evidence_refs=("EVT-regression",),
            regression_expectation="reproduce the regression",
            status=SkillIssueStatus.REGRESSION_PENDING,
        ),))
        with pytest.raises(ValueError, match="require explicit history sources"):
            manager.create_campaign(
                campaign_id="CMP-missing-source", snapshot_id="fixture:next",
                audit_mode=CampaignAuditMode.FOLLOW_UP,
            )
        with pytest.raises(ValueError, match="fresh Campaigns cannot declare"):
            manager.create_campaign(
                campaign_id="CMP-fresh-with-source", snapshot_id="fixture:next",
                history_source_campaign_ids=(source.campaign_id,),
            )
        follow_up = manager.create_campaign(
            campaign_id="CMP-follow-up", snapshot_id="fixture:next",
            audit_mode=CampaignAuditMode.FOLLOW_UP,
            history_source_campaign_ids=(source.campaign_id,),
        )
        baseline = next(
            event for event in manager.store.list_events(follow_up.campaign_id)
            if event.event_type == "SKILL_REGRESSION_BASELINE_RECORDED"
        )
        baseline_value = json.loads(manager.artifacts.get_bytes(baseline.payload_ref))
        assert follow_up.history_source_campaign_ids == (source.campaign_id,)
        assert [item["issue_id"] for item in baseline_value["issues"]] == [
            "SKILL-regression",
        ]

    with CampaignManager(second_target) as other_manager:
        with pytest.raises(NotFoundError, match="Campaign not found|campaign not found"):
            other_manager.create_campaign(
                campaign_id="CMP-cross-target", snapshot_id="fixture:bad",
                audit_mode=CampaignAuditMode.FOLLOW_UP,
                history_source_campaign_ids=("CMP-source",),
            )


def test_database_without_history_columns_migrates_as_legacy(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute("""
            CREATE TABLE campaigns (
                campaign_id TEXT PRIMARY KEY, target_root TEXT NOT NULL,
                snapshot_id TEXT NOT NULL, status TEXT NOT NULL,
                budget_json TEXT NOT NULL, constraints_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("CMP-old", "/target", "fixture:old", "PLANNING", "{}", "[]", "now", "now"),
        )

    with AuditStore(database) as store:
        old_campaign = store.get_campaign("CMP-old")
        assert old_campaign.audit_mode is CampaignAuditMode.LEGACY
        assert old_campaign.history_source_campaign_ids == ()
