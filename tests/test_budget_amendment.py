import datetime as dt
import json
from pathlib import Path

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.cli import main
from reachable_audit.execution import ManualExecutionBackend, TaskSpec
from reachable_audit.models import ModelError
from reachable_audit.models import CampaignStatus
from reachable_audit.store import ConflictError


def _manager(tmp_path: Path, *, wall_limit: int | None = 100) -> CampaignManager:
    target = tmp_path / "target"
    target.mkdir()
    manager = CampaignManager(target)
    manager.create_campaign(
        campaign_id="CMP-wall-budget",
        snapshot_id="fixture:wall-budget",
        budget=(
            {"max_wall_seconds": wall_limit}
            if wall_limit is not None
            else None
        ),
    )
    return manager


def test_wall_amendment_is_audited_monotone_and_preserves_original_limit(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    try:
        original = manager.store.get_campaign("CMP-wall-budget")
        created_at = dt.datetime.fromisoformat(original.created_at)
        evidence = manager.artifacts.put_text("operator-reviewed extension evidence")
        approval_time = (created_at + dt.timedelta(seconds=125)).isoformat()

        amendment = manager.amend_wall_budget(
            "CMP-wall-budget",
            180,
            reason="Allow completion of already-started evidence review",
            evidence_refs=(evidence.artifact_id,),
            actor="operator-17",
            now=approval_time,
        )

        assert amendment.inserted is True
        assert manager.effective_wall_limit_seconds("CMP-wall-budget") == 180
        campaign = manager.store.get_campaign("CMP-wall-budget")
        assert campaign.budget["max_wall_seconds"] == 100
        assert campaign.created_at == original.created_at

        event = next(
            event
            for event in manager.store.list_events("CMP-wall-budget")
            if event.event_id == amendment.event_id
        )
        assert event.event_type == "CAMPAIGN_WALL_BUDGET_AMENDED"
        assert event.actor == "operator-17"
        assert event.payload == {
            "original_max_wall_seconds": 100,
            "previous_approved_max_wall_seconds": 100,
            "approved_max_wall_seconds": 180,
            "extension_seconds": 80,
            "elapsed_at_approval_seconds": 125.0,
            "original_limit_breached": True,
            "reason": "Allow completion of already-started evidence review",
            "evidence_refs": [evidence.artifact_id],
        }

        repeated = manager.amend_wall_budget(
            "CMP-wall-budget",
            180,
            reason="Allow completion of already-started evidence review",
            evidence_refs=(evidence.artifact_id,),
            actor="operator-17",
            now=approval_time,
        )
        assert repeated.event_id == amendment.event_id
        assert repeated.inserted is False

        next_evidence = manager.artifacts.put_text("second approval evidence")
        manager.amend_wall_budget(
            "CMP-wall-budget",
            240,
            reason="Further bounded extension",
            evidence_refs=(next_evidence.artifact_id,),
            now=approval_time,
        )
        assert manager.effective_wall_limit_seconds("CMP-wall-budget") == 240
        history = manager.store.list_events(
            "CMP-wall-budget",
            entity_type="campaign_wall_budget",
            event_type="CAMPAIGN_WALL_BUDGET_AMENDED",
        )
        assert [item.payload["original_max_wall_seconds"] for item in history] == [100, 100]
        assert [item.payload["approved_max_wall_seconds"] for item in history] == [180, 240]
        assert history[1].payload["previous_approved_max_wall_seconds"] == 180
    finally:
        manager.close()


def test_wall_amendment_requires_real_evidence_and_increasing_limit(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    try:
        evidence = manager.artifacts.put_text("valid evidence")
        with pytest.raises(ValueError, match="evidence references"):
            manager.amend_wall_budget(
                "CMP-wall-budget",
                150,
                reason="documented reason",
                evidence_refs=(),
            )
        with pytest.raises((FileNotFoundError, ValueError)):
            manager.amend_wall_budget(
                "CMP-wall-budget",
                150,
                reason="documented reason",
                evidence_refs=("sha256:" + "0" * 64,),
            )
        for limit in (100, 99):
            with pytest.raises(ConflictError, match="monotonically"):
                manager.amend_wall_budget(
                    "CMP-wall-budget",
                    limit,
                    reason="documented reason",
                    evidence_refs=(evidence.artifact_id,),
                )
        with pytest.raises(ValueError, match="positive integer"):
            manager.amend_wall_budget(
                "CMP-wall-budget",
                True,
                reason="documented reason",
                evidence_refs=(evidence.artifact_id,),
            )
        with pytest.raises(ValueError, match="actor and reason"):
            manager.amend_wall_budget(
                "CMP-wall-budget",
                150,
                reason="   ",
                evidence_refs=(evidence.artifact_id,),
            )
        assert manager.effective_wall_limit_seconds("CMP-wall-budget") == 100
        assert not manager.store.list_events(
            "CMP-wall-budget",
            event_type="CAMPAIGN_WALL_BUDGET_AMENDED",
        )
    finally:
        manager.close()


def test_wall_amendment_requires_existing_limit_and_open_campaign(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path, wall_limit=None)
    try:
        evidence = manager.artifacts.put_text("valid evidence")
        assert manager.effective_wall_limit_seconds("CMP-wall-budget") is None
        with pytest.raises(ConflictError, match="no amendable"):
            manager.amend_wall_budget(
                "CMP-wall-budget",
                100,
                reason="Add a wall budget",
                evidence_refs=(evidence.artifact_id,),
            )
        assert not manager.store.list_events(
            "CMP-wall-budget",
            event_type="CAMPAIGN_WALL_BUDGET_AMENDED",
        )

        for status in (
            CampaignStatus.RUNNING,
            CampaignStatus.INTEGRATING,
            CampaignStatus.COMPLETE,
        ):
            manager.store.transition_campaign("CMP-wall-budget", status)
        with pytest.raises(ConflictError, match="completed Campaign"):
            manager.amend_wall_budget(
                "CMP-wall-budget",
                100,
                reason="Attempt amendment after closure",
                evidence_refs=(evidence.artifact_id,),
            )
    finally:
        manager.close()


def test_effective_wall_budget_resumes_claims_without_resetting_clock(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    try:
        campaign_id = "CMP-wall-budget"
        campaign = manager.store.get_campaign(campaign_id)
        manager.add_batch(campaign_id=campaign_id, batch_id="B-1", manifest={})
        input_ref = manager.artifacts.put_text("{}").artifact_id
        task = TaskSpec(
            "TASK-wall", campaign_id, "B-1", "WU-1", "fixture",
            (input_ref,), "fixture/v1", {"agent_runs": 1},
        )
        now = dt.datetime.fromisoformat(campaign.created_at) + dt.timedelta(seconds=125)
        backend = ManualExecutionBackend(manager, campaign_id, clock=lambda: now)
        backend.submit(task)
        with pytest.raises(ModelError, match="deadline reached"):
            backend.claim("worker")
        evidence = manager.artifacts.put_text("extension evidence").artifact_id
        manager.amend_wall_budget(
            campaign_id, 180, reason="bounded approved continuation",
            evidence_refs=(evidence,), now=now.isoformat(),
        )
        lease = backend.claim("worker")
        assert lease is not None
        clock = backend.describe_lease(lease)["campaign_wall_clock"]
        assert clock["created_at"] == campaign.created_at
        assert clock["elapsed_seconds"] == 125
        assert clock["max_wall_seconds"] == 180
        assert dt.datetime.fromisoformat(clock["deadline_at"]) == (
            dt.datetime.fromisoformat(campaign.created_at) + dt.timedelta(seconds=180)
        )
    finally:
        manager.close()


def test_budget_amendment_cli_and_init_constraints(tmp_path: Path, capsys) -> None:
    target = tmp_path / "cli-target"
    target.mkdir()
    state_dir = tmp_path / "cli-state"
    assert main([
        "init", str(target), "--snapshot-id", "fixture:budget-cli",
        "--campaign-id", "CMP-cli", "--state-dir", str(state_dir),
        "--max-wall-seconds", "100", "--static-challenges",
        "--experimental-java-hotspots",
    ]) == 0
    capsys.readouterr()
    with CampaignManager(target, state_dir) as manager:
        campaign = manager.store.get_campaign("CMP-cli")
        assert set(campaign.constraints) == {"static_challenges", "experimental_java_hotspots"}
        evidence = manager.artifacts.put_text("CLI extension evidence").artifact_id
    assert main([
        "campaign-wall-budget-amend", str(target), "CMP-cli",
        "--state-dir", str(state_dir), "--approved-max-wall-seconds", "150",
        "--reason", "approved extension", "--evidence-ref", evidence,
    ]) == 0
    assert json.loads(capsys.readouterr().out)["effective_max_wall_seconds"] == 150
