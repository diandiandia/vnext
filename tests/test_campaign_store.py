from pathlib import Path

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.models import BatchStatus, CampaignStatus, TransitionError
from reachable_audit.store import AuditStore, ConflictError


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
