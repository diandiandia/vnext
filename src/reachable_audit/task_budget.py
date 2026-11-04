"""Opt-in, event-sourced Campaign admission budgets.

``budget.task_budget_policy`` contains positive integer ``totals`` and optional
``default_attempt_budget``, ``protected_reserve`` and ``downstream_operations``.
Task caps override defaults. Units are agent invocations (including delegates),
provider tokens, elapsed task seconds and integer micro-currency units; unlike
Campaign wall-clock deadlines, task seconds add across concurrent attempts.
Reservations are admission estimates, not provider or process hard limits.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from typing import Any, Iterator, Mapping, Sequence

from .models import ModelError
from .store import AuditStore, ConflictError


_UNITS = {
    "agent_runs": "agent invocations, including delegated agents; not model/tool requests",
    "delegated_agent_runs": "delegated agent invocations (a subset of agent_runs)",
    "tokens": "provider-reported total tokens",
    "input_tokens": "provider-reported input tokens",
    "output_tokens": "provider-reported output tokens",
    "wall_seconds": "summed elapsed task-attempt seconds, not Campaign wall time",
    "cost_microunits": "integer millionths of the Campaign's declared currency",
}
_CRITIC_OPERATIONS = ("coverage_critic:initial", "coverage_critic:final")


class BudgetInsufficient(ModelError):
    """Admission was deferred without changing the task or its coverage obligations."""


def _amounts(value: Any, label: str, *, positive: bool = True) -> dict[str, int]:
    if not isinstance(value, Mapping) or any(
        name not in _UNITS or type(amount) is not int
        or amount < (1 if positive else 0)
        for name, amount in value.items()
    ):
        raise ModelError(f"{label} requires known resource names and "
                         f"{'positive' if positive else 'nonnegative'} integers")
    return dict(value)


def _estimates(value: Any, label: str) -> dict[str, int]:
    result = _amounts(value, label, positive=False)
    if any(amount == 0 and name != "delegated_agent_runs" for name, amount in result.items()):
        raise ModelError(f"{label} must be positive except for explicitly unused delegated_agent_runs")
    return result


def validate_task_budget_policy(budget: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate opt-in configuration; unrelated legacy budget keys are unchanged."""
    if "task_budget_policy" not in budget:
        return None
    value = budget["task_budget_policy"]
    fields = {"totals", "protected_reserve", "default_attempt_budget", "downstream_operations"}
    if not isinstance(value, Mapping) or set(value) - fields:
        raise ModelError("task_budget_policy must be an object with known fields")
    totals = _amounts(value.get("totals"), "task budget totals")
    if not totals:
        raise ModelError("task budget totals cannot be empty")
    reserve = _amounts(value.get("protected_reserve", {}), "protected reserve", positive=False)
    defaults = _estimates(value.get("default_attempt_budget", {}), "default attempt budget")
    if (set(reserve) | set(defaults)) - set(totals):
        raise ModelError("reserve and default dimensions must belong to totals")
    if any(amount > totals[name] for name, amount in reserve.items()):
        raise ModelError("protected reserve cannot exceed totals")
    operations = value.get("downstream_operations", [])
    if (
        not isinstance(operations, (list, tuple))
        or any(not isinstance(item, str) or not item.strip() for item in operations)
        or len(operations) != len(set(operations))
    ):
        raise ModelError("protected reserve requires unique downstream operation names")
    operations = list(operations)
    operations.extend(item for item in _CRITIC_OPERATIONS if item not in operations)
    return {
        "totals": totals, "protected_reserve": reserve,
        "default_attempt_budget": defaults, "downstream_operations": list(operations),
    }


class _NestedConnection:
    """Adapt legacy store methods' BEGIN/commit to one outer admission transaction."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.active = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)

    @property
    def in_transaction(self) -> bool:
        return self.active

    def execute(self, sql: str, *args: Any) -> Any:
        if sql == "BEGIN IMMEDIATE":
            self.active = True
            return self.connection.execute("SAVEPOINT budget_store_operation")
        return self.connection.execute(sql, *args)

    def commit(self) -> None:
        if self.active:
            self.connection.execute("RELEASE SAVEPOINT budget_store_operation")
            self.active = False

    def rollback(self) -> None:
        if self.active:
            self.connection.execute("ROLLBACK TO SAVEPOINT budget_store_operation")
            self.connection.execute("RELEASE SAVEPOINT budget_store_operation")
            self.active = False


class TaskBudget:
    """Budget projection and atomic hooks; all durable facts remain in events."""

    def __init__(self, store: AuditStore, campaign_id: str) -> None:
        self.store = store
        self.campaign_id = campaign_id
        self.policy = validate_task_budget_policy(store.get_campaign(campaign_id).budget)

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        connection = self.store._connection
        nested = connection.in_transaction
        if nested:
            connection.execute("SAVEPOINT task_budget")
        else:
            connection.execute("BEGIN IMMEDIATE")
        try:
            if nested:
                # Upgrade before reading, even inside atomic_events().
                connection.execute(
                    "UPDATE campaigns SET budget_json = budget_json WHERE campaign_id = ?",
                    (self.campaign_id,),
                )
            yield
        except BaseException:
            if nested:
                connection.execute("ROLLBACK TO SAVEPOINT task_budget")
                connection.execute("RELEASE SAVEPOINT task_budget")
            else:
                connection.rollback()
            raise
        else:
            if nested:
                connection.execute("RELEASE SAVEPOINT task_budget")
            else:
                connection.commit()

    def _call(self, name: str, **kwargs: Any) -> Any:
        connection = self.store._connection
        adapter = _NestedConnection(connection)
        self.store._connection = adapter
        try:
            return getattr(self.store, name)(**kwargs)
        finally:
            adapter.rollback()
            self.store._connection = connection

    def _events(self) -> list[Any]:
        return self.store.list_events(self.campaign_id, entity_type="task_budget")

    def _append(self, event_type: str, key: str, payload: Mapping[str, Any], actor: str) -> None:
        self.store.append_event(
            campaign_id=self.campaign_id, batch_id=None, entity_type="task_budget",
            entity_id=self.campaign_id, event_type=event_type,
            idempotency_key=f"task-budget:{self.campaign_id}:{key}",
            actor=actor, payload=payload,
        )

    def status(self) -> dict[str, Any]:
        """Return JSON-ready estimates, reservations, usage and enforcement limits."""
        with self.store.atomic_events():
            return self._status()

    def _status(self) -> dict[str, Any]:
        if self.policy is None:
            return {"enabled": False}
        totals = dict(self.policy["totals"])
        used = dict.fromkeys(totals, 0)
        reserved = dict(used)
        downstream = dict(used)
        reservations: dict[str, Any] = {}
        settlements: dict[str, Any] = {}
        observations: dict[str, dict[str, int]] = {}
        estimated: dict[str, int] = dict(used)
        for event in self._events():
            payload = event.payload
            if event.event_type == "TASK_BUDGET_TOTALS_AMENDED":
                totals = dict(payload["approved_totals"])
            elif event.event_type == "TASK_BUDGET_RESERVED":
                reservations[payload["claim_event_id"]] = payload
            elif event.event_type == "TASK_BUDGET_SETTLED":
                settlements[payload["claim_event_id"]] = payload
            elif event.event_type == "TASK_BUDGET_USAGE_OBSERVED":
                observed = observations.setdefault(payload["claim_event_id"], {})
                for name, amount in payload["measurements"].items():
                    observed[name] = max(observed.get(name, 0), amount)
        active = []
        for claim_id, payload in reservations.items():
            settlement = settlements.get(claim_id)
            observed = observations.get(claim_id, {})
            if settlement is None:
                active.append(payload)
            for name, amount in payload["reserved"].items():
                charged = max(
                    observed.get(name, 0),
                    settlement["charged"][name] if settlement is not None else 0,
                )
                held = max(0, amount - charged) if settlement is None else 0
                used[name] += charged
                reserved[name] += held
                if settlement is not None and name in settlement["estimated_dimensions"]:
                    estimated[name] += max(0, settlement["charged"][name] - observed.get(name, 0))
                if payload["downstream"]:
                    downstream[name] += charged + held
        protected = {
            name: max(0, self.policy["protected_reserve"].get(name, 0) - downstream[name])
            for name in totals
        }
        return {
            "enabled": True, "original_totals": self.policy["totals"], "totals": totals,
            "used": used, "reserved": reserved, "estimated_usage": estimated,
            "protected_remaining": protected,
            "available": {name: totals[name] - used[name] - reserved[name] for name in totals},
            "discovery_available": {
                name: totals[name] - used[name] - reserved[name] - protected[name]
                for name in totals
            },
            "active_reservations": active,
            "default_attempt_budget": self.policy["default_attempt_budget"],
            "downstream_operations": self.policy["downstream_operations"],
            "units": {name: _UNITS[name] for name in totals},
            "enforcement": "internal admission only; provider/process hard limits require host enforcement",
        }

    def validate_task(self, task: Any) -> dict[str, int]:
        if self.policy is None:
            return {}
        amounts = {**self.policy["default_attempt_budget"], **dict(task.budget)}
        missing = set(self.policy["totals"]) - set(amounts)
        if missing:
            raise ModelError(f"task budget is missing admission estimates: {sorted(missing)}")
        result = _estimates(
            {name: amounts[name] for name in self.policy["totals"]}, "attempt budget"
        )
        if result.get("delegated_agent_runs", 0) > result.get(
            "agent_runs", amounts.get("agent_runs", 1)
        ):
            raise ModelError("delegated_agent_runs reservation cannot exceed agent_runs")
        return result

    def _settle(self, reservation: Mapping[str, Any], measurements: Mapping[str, int],
                reason: str) -> None:
        _amounts({name: amount for name, amount in measurements.items()
                  if name in reservation["reserved"]}, "settlement usage", positive=False)
        missing = [name for name in reservation["reserved"] if name not in measurements]
        charged = {
            name: measurements.get(name, amount)
            for name, amount in reservation["reserved"].items()
        }
        if "agent_runs" in charged:
            floor = max(
                1, charged["agent_runs"], charged.get("delegated_agent_runs", 0)
            )
            if floor > charged["agent_runs"] and "agent_runs" not in missing:
                missing.append("agent_runs")
            charged["agent_runs"] = floor
        self._append("TASK_BUDGET_SETTLED", f"settle:{reservation['claim_event_id']}", {
            **dict(reservation), "charged": charged,
            "estimated_dimensions": missing, "reason": reason,
        }, "budget")

    def claim(self, task: Any, **kwargs: Any) -> Any:
        if self.policy is None:
            return self.store.claim_task(**kwargs)
        amounts = self.validate_task(task)
        insufficient = {}
        with self._atomic():
            state = self._status()
            for reservation in state["active_reservations"]:
                if reservation["lease_expires_at"] <= kwargs["now"]:
                    self._settle(reservation, {}, "expired attempt; usage unavailable")
            # Let the existing state machine reject unclaimable tasks before
            # reporting lack of funds, but roll its claim back if admission fails.
            connection = self.store._connection
            connection.execute("SAVEPOINT budget_admission")
            event = self._call("claim_task", **kwargs)
            if event is None:
                connection.execute("RELEASE SAVEPOINT budget_admission")
                return None
            state = self._status()
            downstream = task.operation in self.policy["downstream_operations"]
            available = state["available" if downstream else "discovery_available"]
            insufficient = {name: {"required": amount, "available": available[name]}
                            for name, amount in amounts.items() if amount > available[name]}
            if insufficient:
                connection.execute("ROLLBACK TO SAVEPOINT budget_admission")
            else:
                self._append("TASK_BUDGET_RESERVED", f"reserve:{event.event_id}", {
                    "claim_event_id": event.event_id, "task_id": task.task_id,
                    "attempt": event.payload["attempt"], "worker_id": kwargs["worker_id"],
                    "lease_expires_at": kwargs["lease_expires_at"],
                    "operation": task.operation, "downstream": downstream, "reserved": amounts,
                }, kwargs["worker_id"])
            connection.execute("RELEASE SAVEPOINT budget_admission")
        if insufficient:
            raise BudgetInsufficient(f"Campaign task budget insufficient; defer task: {insufficient}")
        return event

    def finish(self, method: str, *, measurements: Mapping[str, int] | None = None,
               **kwargs: Any) -> Any:
        if method not in {"finalize_task", "release_task"}:
            raise ModelError("unsupported budget settlement operation")
        if self.policy is None:
            return getattr(self.store, method)(**kwargs)
        with self._atomic():
            events = self._events()
            reservations = [
                event.payload for event in events
                if event.event_type == "TASK_BUDGET_RESERVED"
                and event.payload["task_id"] == kwargs["task_id"]
                and event.payload["attempt"] == kwargs["attempt"]
            ]
            if not reservations:
                raise ModelError("task attempt has no Campaign budget reservation")
            reservation = reservations[-1]
            settled = any(
                event.event_type == "TASK_BUDGET_SETTLED"
                and event.payload["claim_event_id"] == reservation["claim_event_id"]
                for event in events
            )
            if method == "release_task" and settled:
                if reservation["worker_id"] != kwargs["worker_id"]:
                    raise ConflictError("budget reservation belongs to another worker")
                releases = self.store.list_events(
                    self.campaign_id, entity_type="execution_task",
                    entity_id=kwargs["task_id"], event_type="TASK_LEASE_RELEASED",
                )
                if any(event.idempotency_key.endswith(
                    f":{reservation['claim_event_id']}"
                ) for event in releases):
                    return None
            result = self._call(method, **kwargs)
            if not settled:
                self._settle(reservation, measurements or {}, method)
            return result

    def observe_usage(self, *, task_id: str, attempt: int, worker_id: str,
                      measurements: Mapping[str, int]) -> None:
        """Retain reported cost even if output validation later rejects the result.

        Reports can only increase the charged/committed amount. They cannot release
        reservations, finalize a task, or refund an already estimated settlement.
        """
        if self.policy is None:
            return
        amounts = _amounts({
            name: amount for name, amount in measurements.items()
            if name in self.policy["totals"]
        }, "reported usage", positive=False)
        with self._atomic():
            reservations = [
                event.payload for event in self._events()
                if event.event_type == "TASK_BUDGET_RESERVED"
                and event.payload["task_id"] == task_id and event.payload["attempt"] == attempt
            ]
            if not reservations:
                raise ModelError("task attempt has no Campaign budget reservation")
            reservation = reservations[-1]
            if worker_id != reservation["worker_id"]:
                raise ConflictError("budget reservation belongs to another worker")
            digest = hashlib.sha256(json.dumps(amounts, sort_keys=True).encode()).hexdigest()
            self._append("TASK_BUDGET_USAGE_OBSERVED",
                         f"usage:{reservation['claim_event_id']}:{digest}", {
                             "claim_event_id": reservation["claim_event_id"],
                             "task_id": task_id, "attempt": attempt, "measurements": amounts,
                         }, worker_id)

    def amend_totals(self, approved_totals: Mapping[str, int], *, authorization_id: str,
                     actor: str, reason: str, evidence_refs: Sequence[str]) -> dict[str, Any]:
        """Explicit, replay-idempotent increase; never resets prior attempt usage."""
        approved = _amounts(approved_totals, "approved totals")
        if (
            self.policy is None or not isinstance(authorization_id, str)
            or not authorization_id.strip() or not isinstance(actor, str) or not actor.strip()
            or not isinstance(reason, str) or not reason.strip()
            or not isinstance(evidence_refs, (list, tuple)) or not evidence_refs
            or any(not isinstance(item, str) or not item.strip() for item in evidence_refs)
            or len(evidence_refs) != len(set(evidence_refs))
        ):
            raise ModelError("budget amendment requires enabled policy and authorization evidence")
        with self._atomic():
            payload = {"approved_totals": approved, "authorization_id": authorization_id,
                       "reason": reason, "evidence_refs": list(evidence_refs)}
            existing = [event for event in self._events()
                        if event.event_type == "TASK_BUDGET_TOTALS_AMENDED"
                        and event.payload["authorization_id"] == authorization_id]
            if existing:
                if existing[-1].payload != payload or existing[-1].actor != actor:
                    raise ConflictError("budget authorization reused with different data")
                return self._status()
            current = self._status()["totals"]
            if set(approved) != set(current) or any(
                approved[name] < current[name] for name in current
            ) or approved == current:
                raise ModelError("budget amendment must increase totals without changing dimensions")
            self._append("TASK_BUDGET_TOTALS_AMENDED", f"amend:{authorization_id}", payload, actor)
            return self._status()


def task_budget_status(store: AuditStore, campaign_id: str) -> dict[str, Any]:
    return TaskBudget(store, campaign_id).status()


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_task_budget_policy({"task_budget_policy": policy})
    assert result is not None
    return result


def budget_status(manager: Any, campaign_id: str) -> dict[str, Any]:
    return task_budget_status(manager.store, campaign_id)
