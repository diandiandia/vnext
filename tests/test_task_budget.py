import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.execution import ManualExecutionBackend, TaskResult, TaskSpec, TaskStatus
from reachable_audit.models import ModelError
from reachable_audit.store import ConflictError
from reachable_audit.task_budget import (
    BudgetInsufficient,
    TaskBudget,
    budget_status,
    task_budget_status,
    validate_policy,
    validate_task_budget_policy,
)


def _setup(tmp_path: Path, policy: dict | None = None):
    target = tmp_path / "target"
    target.mkdir()
    manager = CampaignManager(target)
    manager.create_campaign(
        campaign_id="CMP-budget", snapshot_id="fixture:budget",
        budget={} if policy is None else {"task_budget_policy": policy},
    )
    manager.add_batch(campaign_id="CMP-budget", batch_id="B-1", manifest={})
    artifact = manager.artifacts.put_text("{}").artifact_id
    task = TaskSpec(
        task_id="TASK-1", campaign_id="CMP-budget", batch_id="B-1", work_unit_id="WU-1",
        operation="discover", input_refs=(artifact,), required_output="opaque/v1",
        budget={"agent_runs": 1},
    )
    return target, manager, task


def _policy(total=3, **kwargs):
    return {"totals": {"agent_runs": total}, **kwargs}


def _result(manager, **measurements):
    return TaskResult(
        True, manager.artifacts.put_text("{}").artifact_id, "finished",
        {"agent_runs": 1, "wall_seconds": 1, **measurements},
    )


@pytest.mark.parametrize("policy", [
    None, True, [], {}, {"totals": {}}, {"totals": {"agent_runs": True}},
    {"totals": {"agent_runs": 1.5}}, {"totals": {"agent_runs": 0}},
    {"totals": {"unknown": 1}}, {"totals": {"agent_runs": 1}, "typo": 1},
    _policy(protected_reserve={"agent_runs": 2}, downstream_operations=["verify"], total=1),
    _policy(default_attempt_budget={"tokens": 1}),
    _policy(downstream_operations="verify"),
    _policy(downstream_operations=["verify", "verify"]),
    _policy(protected_reserve={"agent_runs": False}),
])
def test_policy_is_strict(policy):
    with pytest.raises(ModelError):
        validate_task_budget_policy({"task_budget_policy": policy})


def test_cli_policy_and_status_api_and_builtin_critic_protection(tmp_path):
    policy = validate_policy(_policy(1, protected_reserve={"agent_runs": 1}))
    assert set(policy["downstream_operations"]) == {
        "coverage_critic:initial", "coverage_critic:final",
    }
    _, manager, task = _setup(tmp_path, policy)
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        backend.submit(task)
        backend.submit(replace(task, task_id="CRITIC", operation="coverage_critic:initial"))
        lease = backend.claim("worker")
        assert lease.task.task_id == "CRITIC"
        assert backend.poll(task.task_id).attempt == 0
        assert budget_status(manager, task.campaign_id)["protected_remaining"]["agent_runs"] == 0
    finally:
        manager.close()


def test_legacy_task_behavior_has_no_budget_events(tmp_path):
    _, manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        backend.submit(task)
        lease = backend.claim("worker")
        backend.release(lease)
        assert backend.claim("retry") is not None
        assert task_budget_status(manager.store, task.campaign_id) == {"enabled": False}
        assert manager.store.list_events(task.campaign_id, entity_type="task_budget") == []
    finally:
        manager.close()


def test_missing_estimates_block_submit_and_task_caps_override_defaults(tmp_path):
    _, manager, task = _setup(tmp_path, {
        "totals": {"agent_runs": 4, "tokens": 100},
        "default_attempt_budget": {"agent_runs": 2},
    })
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        with pytest.raises(ModelError, match="missing admission estimates"):
            backend.submit(task)
        task = replace(task, budget={"agent_runs": 1, "tokens": 20})
        backend.submit(task)
        backend.claim("worker")
        status = task_budget_status(manager.store, task.campaign_id)
        assert status["reserved"] == {"agent_runs": 1, "tokens": 20}
    finally:
        manager.close()


def test_defaults_missing_usage_idempotent_settlement_and_restart(tmp_path):
    target, manager, task = _setup(tmp_path, {
        "totals": {"agent_runs": 5, "tokens": 200, "wall_seconds": 100},
        "default_attempt_budget": {"tokens": 40, "wall_seconds": 10},
    })
    backend = ManualExecutionBackend(manager, task.campaign_id)
    backend.submit(task)
    lease = backend.claim("worker")
    result = _result(manager)
    backend.collect(lease, result)
    backend.collect(lease, result)
    manager.close()
    manager = CampaignManager(target)
    try:
        status = task_budget_status(manager.store, task.campaign_id)
        assert status["used"] == {"agent_runs": 1, "tokens": 40, "wall_seconds": 1}
        assert status["estimated_usage"] == {"agent_runs": 0, "tokens": 40, "wall_seconds": 0}
        assert status["reserved"] == {"agent_runs": 0, "tokens": 0, "wall_seconds": 0}
        settlements = manager.store.list_events(
            task.campaign_id, event_type="TASK_BUDGET_SETTLED"
        )
        assert len(settlements) == 1
        assert settlements[0].payload["task_id"] == task.task_id
        assert settlements[0].payload["attempt"] == 1
    finally:
        manager.close()


def test_independent_connections_cannot_oversell_concurrent_claims(tmp_path):
    target, manager, task = _setup(tmp_path, _policy(1))
    backend = ManualExecutionBackend(manager, task.campaign_id)
    for task_id in ("TASK-1", "TASK-2"):
        backend.submit(replace(task, task_id=task_id))
    manager.close()

    def claim(task_id):
        connection = CampaignManager(target)
        try:
            return ManualExecutionBackend(connection, task.campaign_id).claim(
                task_id, task_id_filter=task_id
            )
        except BudgetInsufficient:
            return None
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        leases = list(workers.map(claim, ("TASK-1", "TASK-2")))
    assert sum(lease is not None for lease in leases) == 1
    manager = CampaignManager(target)
    try:
        assert task_budget_status(manager.store, task.campaign_id)["reserved"] == {"agent_runs": 1}
        assert len(manager.store.list_events(task.campaign_id, event_type="TASK_CLAIMED")) == 1
    finally:
        manager.close()


def test_protected_reserve_survives_candidate_explosion_and_funds_downstream(tmp_path):
    _, manager, task = _setup(tmp_path, _policy(
        4, protected_reserve={"agent_runs": 2}, downstream_operations=["verify"],
    ))
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        for index in range(20):
            backend.submit(replace(task, task_id=f"TASK-{index}"))
        backend.submit(replace(task, task_id="VERIFY", operation="verify"))
        for index in range(2):
            lease = backend.claim("worker", task_id_filter=f"TASK-{index}")
            backend.collect(lease, _result(manager))
        with pytest.raises(BudgetInsufficient, match="insufficient"):
            backend.claim("blocked", task_id_filter="TASK-2")
        assert backend.poll("TASK-2").attempt == 0
        assert backend.poll("TASK-2").status is TaskStatus.PENDING
        lease = backend.claim("verifier", task_id_filter="VERIFY")
        backend.collect(lease, _result(manager))
        state = task_budget_status(manager.store, task.campaign_id)
        assert state["used"]["agent_runs"] == 3
        assert state["protected_remaining"]["agent_runs"] == 1
        assert state["discovery_available"]["agent_runs"] == 0
    finally:
        manager.close()


def test_failures_release_and_retry_are_not_free(tmp_path):
    _, manager, task = _setup(tmp_path, _policy(3))
    try:
        task = replace(task, max_attempts=1)
        backend = ManualExecutionBackend(manager, task.campaign_id)
        backend.submit(task)
        first = backend.claim("worker")
        failed = TaskResult(False, None, "failed before measuring", {
            "agent_runs": 0, "wall_seconds": 0,
        })
        backend.collect(first, failed)
        backend.collect(first, failed)
        backend.retry(task.task_id, reason="approved retry")
        second = backend.claim("worker")
        assert second.attempt == 2
        backend.release(second)
        backend.release(second)
        status = task_budget_status(manager.store, task.campaign_id)
        assert status["used"]["agent_runs"] == 2
        assert status["reserved"]["agent_runs"] == 0
        backend.retry(task.task_id, reason="last retry")
        third = backend.claim("worker")
        backend.collect(third, _result(manager))
        assert task_budget_status(manager.store, task.campaign_id)["used"]["agent_runs"] == 3
    finally:
        manager.close()


def test_expiry_counts_unknown_usage_even_when_next_claim_is_denied(tmp_path):
    target, manager, task = _setup(tmp_path, _policy(1))
    now = [dt.datetime(2026, 11, 1, tzinfo=dt.UTC)]
    backend = ManualExecutionBackend(manager, task.campaign_id, clock=lambda: now[0])
    backend.submit(task)
    backend.claim("worker", lease_seconds=1)
    manager.close()
    now[0] += dt.timedelta(seconds=2)
    manager = CampaignManager(target)
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id, clock=lambda: now[0])
        for _ in range(2):
            with pytest.raises(BudgetInsufficient):
                backend.claim("retry")
        state = task_budget_status(manager.store, task.campaign_id)
        assert state["used"]["agent_runs"] == 1
        assert state["reserved"]["agent_runs"] == 0
        assert len(manager.store.list_events(task.campaign_id, event_type="TASK_CLAIMED")) == 1
    finally:
        manager.close()


def test_nested_transactions_roll_back_claim_and_settlement_together(tmp_path):
    _, manager, task = _setup(tmp_path, _policy(2))
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        backend.submit(task)
        with pytest.raises(RuntimeError):
            with manager.store.atomic_events():
                backend.claim("worker")
                raise RuntimeError("abort")
        assert backend.poll(task.task_id).attempt == 0
        assert task_budget_status(manager.store, task.campaign_id)["reserved"]["agent_runs"] == 0
        lease = backend.claim("worker")
        with pytest.raises(RuntimeError):
            with manager.store.atomic_events():
                backend.collect(lease, _result(manager))
                raise RuntimeError("abort")
        assert backend.poll(task.task_id).status is TaskStatus.LEASED
        assert task_budget_status(manager.store, task.campaign_id)["used"]["agent_runs"] == 0
        backend.collect(lease, _result(manager))
    finally:
        manager.close()


def test_authorized_increase_is_durable_monotonic_and_idempotent(tmp_path):
    target, manager, task = _setup(tmp_path, _policy(1))
    backend = ManualExecutionBackend(manager, task.campaign_id)
    backend.submit(task)
    lease = backend.claim("worker")
    backend.release(lease)
    budget = TaskBudget(manager.store, task.campaign_id)
    auth = dict(authorization_id="AUTH-1", actor="operator", reason="fund retries",
                evidence_refs=["approval:1"])
    budget.amend_totals({"agent_runs": 3}, **auth)
    budget.amend_totals({"agent_runs": 3}, **auth)
    with pytest.raises(ConflictError):
        budget.amend_totals({"agent_runs": 4}, **auth)
    with pytest.raises(ModelError):
        budget.amend_totals({"agent_runs": 2}, **{**auth, "authorization_id": "AUTH-2"})
    manager.close()
    manager = CampaignManager(target)
    try:
        state = task_budget_status(manager.store, task.campaign_id)
        assert state["original_totals"] == {"agent_runs": 1}
        assert state["totals"] == {"agent_runs": 3}
        assert state["used"] == {"agent_runs": 1}
        assert ManualExecutionBackend(manager, task.campaign_id).claim("retry") is not None
    finally:
        manager.close()


def test_overrun_is_reported_not_misrepresented_as_provider_hard_enforcement(tmp_path):
    _, manager, task = _setup(tmp_path, {
        "totals": {"agent_runs": 2, "tokens": 50},
        "default_attempt_budget": {"tokens": 20},
    })
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        backend.submit(task)
        lease = backend.claim("worker")
        backend.collect(lease, _result(manager, tokens=60))
        state = task_budget_status(manager.store, task.campaign_id)
        assert state["available"]["tokens"] == -10
        assert "internal admission only" in state["enforcement"]
        backend.submit(replace(task, task_id="TASK-2"))
        with pytest.raises(BudgetInsufficient):
            backend.claim("blocked", task_id_filter="TASK-2")
    finally:
        manager.close()


def test_per_task_caps_and_worker_binding_still_apply(tmp_path):
    _, manager, task = _setup(tmp_path, _policy(3))
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        backend.submit(task)
        lease = backend.claim("worker")
        with pytest.raises(ModelError, match="exceeded budget"):
            backend.collect(lease, _result(manager, agent_runs=2))
        with pytest.raises(ConflictError):
            backend.release(replace(lease, worker_id="other"))
        assert backend.poll(task.task_id).status is TaskStatus.LEASED
        state = task_budget_status(manager.store, task.campaign_id)
        assert state["used"]["agent_runs"] == 2
        assert state["reserved"]["agent_runs"] == 0
        backend.collect(lease, _result(manager))
        assert task_budget_status(manager.store, task.campaign_id)["used"]["agent_runs"] == 2
    finally:
        manager.close()


def test_zero_delegation_is_valid_and_missing_agent_cost_is_conservative(tmp_path):
    _, manager, task = _setup(tmp_path, {
        "totals": {"agent_runs": 3, "delegated_agent_runs": 1},
        "default_attempt_budget": {"delegated_agent_runs": 0},
    })
    try:
        backend = ManualExecutionBackend(manager, task.campaign_id)
        backend.submit(task)
        lease = backend.claim("worker")
        backend.collect(lease, TaskResult(
            False, None, "failed attempt", {"agent_runs": 0, "wall_seconds": 0}
        ))
        state = budget_status(manager, task.campaign_id)
        assert state["used"] == {"agent_runs": 1, "delegated_agent_runs": 0}
        assert state["estimated_usage"]["agent_runs"] == 1
    finally:
        manager.close()


def test_independent_connections_settle_same_attempt_once(tmp_path):
    target, manager, task = _setup(tmp_path, _policy(2))
    backend = ManualExecutionBackend(manager, task.campaign_id)
    backend.submit(task)
    lease = backend.claim("worker")
    result = _result(manager)
    manager.close()

    def collect(_):
        connection = CampaignManager(target)
        try:
            return ManualExecutionBackend(connection, task.campaign_id).collect(lease, result).status
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(collect, range(2))) == [TaskStatus.SUCCEEDED] * 2
    manager = CampaignManager(target)
    try:
        assert budget_status(manager, task.campaign_id)["used"]["agent_runs"] == 1
        assert len(manager.store.list_events(
            task.campaign_id, event_type="TASK_BUDGET_SETTLED"
        )) == 1
    finally:
        manager.close()
