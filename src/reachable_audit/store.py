"""SQLite fact store for Campaign, Batch, and append-only events."""

from __future__ import annotations

from contextlib import AbstractContextManager
import datetime as dt
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping
import uuid

from .models import (
    AppendResult,
    BatchRecord,
    BatchStatus,
    CampaignRecord,
    CampaignStatus,
    EventRecord,
    require_transition,
)


class StoreError(RuntimeError):
    """Base store error."""


class NotFoundError(StoreError):
    """Raised when a requested entity does not exist."""


class ConflictError(StoreError):
    """Raised when an idempotency key or entity ID is reused with different data."""


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AuditStore(AbstractContextManager["AuditStore"]):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                campaign_id TEXT PRIMARY KEY,
                target_root TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                status TEXT NOT NULL,
                budget_json TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS batches (
                campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                batch_id TEXT NOT NULL,
                status TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (campaign_id, batch_id)
            );

            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                batch_id TEXT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                actor TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_ref TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_campaign_sequence
                ON events(campaign_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_entity
                ON events(entity_type, entity_id, sequence);
            """
        )
        self._connection.commit()

    def create_campaign(
        self,
        *,
        campaign_id: str,
        target_root: str,
        snapshot_id: str,
        budget: Mapping[str, Any] | None = None,
        constraints: list[str] | tuple[str, ...] | None = None,
    ) -> CampaignRecord:
        now = _utc_now()
        budget_json = _json(dict(budget or {}))
        constraints_json = _json(list(constraints or ()))
        with self._connection:
            existing = self._connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            if existing is not None:
                record = self._campaign_from_row(existing)
                if (
                    record.target_root != target_root
                    or record.snapshot_id != snapshot_id
                    or _json(record.budget) != budget_json
                    or _json(record.constraints) != constraints_json
                ):
                    raise ConflictError(f"campaign ID reused with different data: {campaign_id}")
                return record
            self._connection.execute(
                """
                INSERT INTO campaigns (
                    campaign_id, target_root, snapshot_id, status, budget_json,
                    constraints_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    target_root,
                    snapshot_id,
                    CampaignStatus.PLANNING.value,
                    budget_json,
                    constraints_json,
                    now,
                    now,
                ),
            )
            self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=None,
                entity_type="campaign",
                entity_id=campaign_id,
                event_type="CAMPAIGN_CREATED",
                idempotency_key=f"campaign:create:{campaign_id}",
                actor="tool",
                payload={"snapshot_id": snapshot_id},
                payload_ref=None,
                created_at=now,
            )
        return self.get_campaign(campaign_id)

    def get_campaign(self, campaign_id: str) -> CampaignRecord:
        row = self._connection.execute(
            "SELECT * FROM campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"campaign not found: {campaign_id}")
        return self._campaign_from_row(row)

    def list_campaigns(self) -> list[CampaignRecord]:
        rows = self._connection.execute(
            "SELECT * FROM campaigns ORDER BY created_at, campaign_id"
        ).fetchall()
        return [self._campaign_from_row(row) for row in rows]

    def transition_campaign(
        self, campaign_id: str, target: CampaignStatus, *, actor: str = "tool"
    ) -> CampaignRecord:
        with self._connection:
            current = self.get_campaign(campaign_id)
            if current.status == target:
                return current
            require_transition(current.status, target)
            now = _utc_now()
            self._connection.execute(
                "UPDATE campaigns SET status = ?, updated_at = ? WHERE campaign_id = ?",
                (target.value, now, campaign_id),
            )
            self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=None,
                entity_type="campaign",
                entity_id=campaign_id,
                event_type="CAMPAIGN_STATUS_CHANGED",
                idempotency_key=(
                    f"campaign:transition:{campaign_id}:{current.status.value}:{target.value}"
                ),
                actor=actor,
                payload={"from": current.status.value, "to": target.value},
                payload_ref=None,
                created_at=now,
            )
        return self.get_campaign(campaign_id)

    def add_batch(
        self,
        *,
        campaign_id: str,
        batch_id: str,
        manifest: Mapping[str, Any],
    ) -> BatchRecord:
        self.get_campaign(campaign_id)
        manifest_json = _json(dict(manifest))
        now = _utc_now()
        with self._connection:
            existing = self._connection.execute(
                "SELECT * FROM batches WHERE campaign_id = ? AND batch_id = ?",
                (campaign_id, batch_id),
            ).fetchone()
            if existing is not None:
                record = self._batch_from_row(existing)
                if _json(record.manifest) != manifest_json:
                    raise ConflictError(f"batch ID reused with different manifest: {batch_id}")
                return record
            self._connection.execute(
                """
                INSERT INTO batches (
                    campaign_id, batch_id, status, manifest_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    batch_id,
                    BatchStatus.PLANNED.value,
                    manifest_json,
                    now,
                    now,
                ),
            )
            self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=batch_id,
                entity_type="batch",
                entity_id=batch_id,
                event_type="BATCH_CREATED",
                idempotency_key=f"batch:create:{campaign_id}:{batch_id}",
                actor="tool",
                payload={"manifest": dict(manifest)},
                payload_ref=None,
                created_at=now,
            )
        return self.get_batch(campaign_id, batch_id)

    def get_batch(self, campaign_id: str, batch_id: str) -> BatchRecord:
        row = self._connection.execute(
            "SELECT * FROM batches WHERE campaign_id = ? AND batch_id = ?",
            (campaign_id, batch_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"batch not found: {campaign_id}/{batch_id}")
        return self._batch_from_row(row)

    def list_batches(self, campaign_id: str) -> list[BatchRecord]:
        rows = self._connection.execute(
            "SELECT * FROM batches WHERE campaign_id = ? ORDER BY batch_id",
            (campaign_id,),
        ).fetchall()
        return [self._batch_from_row(row) for row in rows]

    def transition_batch(
        self,
        campaign_id: str,
        batch_id: str,
        target: BatchStatus,
        *,
        actor: str = "tool",
    ) -> BatchRecord:
        with self._connection:
            current = self.get_batch(campaign_id, batch_id)
            if current.status == target:
                return current
            require_transition(current.status, target)
            now = _utc_now()
            self._connection.execute(
                """
                UPDATE batches SET status = ?, updated_at = ?
                WHERE campaign_id = ? AND batch_id = ?
                """,
                (target.value, now, campaign_id, batch_id),
            )
            self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=batch_id,
                entity_type="batch",
                entity_id=batch_id,
                event_type="BATCH_STATUS_CHANGED",
                idempotency_key=(
                    f"batch:transition:{campaign_id}:{batch_id}:"
                    f"{current.status.value}:{target.value}"
                ),
                actor=actor,
                payload={"from": current.status.value, "to": target.value},
                payload_ref=None,
                created_at=now,
            )
        return self.get_batch(campaign_id, batch_id)

    def append_event(
        self,
        *,
        campaign_id: str,
        batch_id: str | None,
        entity_type: str,
        entity_id: str,
        event_type: str,
        idempotency_key: str,
        actor: str,
        payload: Mapping[str, Any] | None = None,
        payload_ref: str | None = None,
    ) -> AppendResult:
        self.get_campaign(campaign_id)
        with self._connection:
            return self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=batch_id,
                entity_type=entity_type,
                entity_id=entity_id,
                event_type=event_type,
                idempotency_key=idempotency_key,
                actor=actor,
                payload=dict(payload or {}),
                payload_ref=payload_ref,
                created_at=_utc_now(),
            )

    def list_events(self, campaign_id: str) -> list[EventRecord]:
        rows = self._connection.execute(
            "SELECT * FROM events WHERE campaign_id = ? ORDER BY sequence",
            (campaign_id,),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def claim_task(
        self,
        *,
        campaign_id: str,
        task_id: str,
        worker_id: str,
        lease_expires_at: str,
        now: str,
    ) -> EventRecord | None:
        self.get_campaign(campaign_id)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            rows = self._connection.execute(
                """
                SELECT * FROM events
                WHERE campaign_id = ? AND entity_type = 'execution_task'
                    AND entity_id = ?
                ORDER BY sequence
                """,
                (campaign_id, task_id),
            ).fetchall()
            if not rows:
                raise NotFoundError(f"execution task not found: {task_id}")
            events = [self._event_from_row(row) for row in rows]
            if any(
                event.event_type in {"TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED"}
                for event in events
            ):
                self._connection.rollback()
                return None
            claims = [event for event in events if event.event_type == "TASK_CLAIMED"]
            if claims and str(claims[-1].payload["lease_expires_at"]) > now:
                self._connection.rollback()
                return None
            attempt = len(claims) + 1
            result = self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=events[0].batch_id,
                entity_type="execution_task",
                entity_id=task_id,
                event_type="TASK_CLAIMED",
                idempotency_key=f"task:claim:{campaign_id}:{task_id}:{attempt}",
                actor=worker_id,
                payload={
                    "attempt": attempt,
                    "worker_id": worker_id,
                    "lease_expires_at": lease_expires_at,
                },
                payload_ref=None,
                created_at=now,
            )
            row = self._connection.execute(
                "SELECT * FROM events WHERE event_id = ?", (result.event_id,)
            ).fetchone()
            self._connection.commit()
            if row is None:
                raise StoreError(f"claimed task event missing: {result.event_id}")
            return self._event_from_row(row)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def finalize_task(
        self,
        *,
        campaign_id: str,
        task_id: str,
        worker_id: str,
        succeeded: bool,
        payload: Mapping[str, Any],
        payload_ref: str | None,
        now: str,
    ) -> AppendResult:
        self.get_campaign(campaign_id)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            rows = self._connection.execute(
                """
                SELECT * FROM events
                WHERE campaign_id = ? AND entity_type = 'execution_task'
                    AND entity_id = ?
                ORDER BY sequence
                """,
                (campaign_id, task_id),
            ).fetchall()
            if not rows:
                raise NotFoundError(f"execution task not found: {task_id}")
            events = [self._event_from_row(row) for row in rows]
            claims = [event for event in events if event.event_type == "TASK_CLAIMED"]
            if not claims:
                raise ConflictError(f"execution task has no active lease: {task_id}")
            claim = claims[-1]
            event_type = "TASK_COMPLETED" if succeeded else "TASK_FAILED"
            idempotency_key = f"task:finalize:{campaign_id}:{task_id}:{claim.event_id}"
            terminal = next((
                event
                for event in events
                if event.event_type in {"TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED"}
            ), None)
            if terminal is not None and terminal.idempotency_key != idempotency_key:
                raise ConflictError(f"execution task is already terminal: {task_id}")
            if claim.actor != worker_id:
                raise ConflictError(f"execution task lease belongs to another worker: {task_id}")
            if str(claim.payload["lease_expires_at"]) <= now and terminal is None:
                raise ConflictError(f"execution task lease expired: {task_id}")
            result = self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=events[0].batch_id,
                entity_type="execution_task",
                entity_id=task_id,
                event_type=event_type,
                idempotency_key=idempotency_key,
                actor=worker_id,
                payload=payload,
                payload_ref=payload_ref,
                created_at=now,
            )
            self._connection.commit()
            return result
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def cancel_task(
        self,
        *,
        campaign_id: str,
        task_id: str,
        reason: str,
        actor: str,
        now: str,
    ) -> AppendResult:
        self.get_campaign(campaign_id)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            rows = self._connection.execute(
                """
                SELECT * FROM events
                WHERE campaign_id = ? AND entity_type = 'execution_task'
                    AND entity_id = ?
                ORDER BY sequence
                """,
                (campaign_id, task_id),
            ).fetchall()
            if not rows:
                raise NotFoundError(f"execution task not found: {task_id}")
            events = [self._event_from_row(row) for row in rows]
            terminal = next((
                event
                for event in events
                if event.event_type in {"TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED"}
            ), None)
            idempotency_key = f"task:cancel:{campaign_id}:{task_id}"
            if terminal is not None and terminal.idempotency_key != idempotency_key:
                raise ConflictError(f"execution task is already terminal: {task_id}")
            result = self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=events[0].batch_id,
                entity_type="execution_task",
                entity_id=task_id,
                event_type="TASK_CANCELLED",
                idempotency_key=idempotency_key,
                actor=actor,
                payload={"reason": reason},
                payload_ref=None,
                created_at=now,
            )
            self._connection.commit()
            return result
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def _append_event_tx(
        self,
        *,
        campaign_id: str,
        batch_id: str | None,
        entity_type: str,
        entity_id: str,
        event_type: str,
        idempotency_key: str,
        actor: str,
        payload: Mapping[str, Any],
        payload_ref: str | None,
        created_at: str,
    ) -> AppendResult:
        payload_json = _json(dict(payload))
        existing = self._connection.execute(
            "SELECT * FROM events WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            comparable = (
                existing["campaign_id"],
                existing["batch_id"],
                existing["entity_type"],
                existing["entity_id"],
                existing["event_type"],
                existing["actor"],
                existing["payload_json"],
                existing["payload_ref"],
            )
            incoming = (
                campaign_id,
                batch_id,
                entity_type,
                entity_id,
                event_type,
                actor,
                payload_json,
                payload_ref,
            )
            if comparable != incoming:
                raise ConflictError(
                    f"idempotency key reused with different event: {idempotency_key}"
                )
            return AppendResult(event_id=existing["event_id"], inserted=False)
        event_id = f"EVT-{uuid.uuid4().hex}"
        self._connection.execute(
            """
            INSERT INTO events (
                event_id, campaign_id, batch_id, entity_type, entity_id, event_type,
                idempotency_key, actor, payload_json, payload_ref, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                campaign_id,
                batch_id,
                entity_type,
                entity_id,
                event_type,
                idempotency_key,
                actor,
                payload_json,
                payload_ref,
                created_at,
            ),
        )
        return AppendResult(event_id=event_id, inserted=True)

    @staticmethod
    def _campaign_from_row(row: sqlite3.Row) -> CampaignRecord:
        return CampaignRecord(
            campaign_id=row["campaign_id"],
            target_root=row["target_root"],
            snapshot_id=row["snapshot_id"],
            status=CampaignStatus(row["status"]),
            budget=json.loads(row["budget_json"]),
            constraints=tuple(json.loads(row["constraints_json"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _batch_from_row(row: sqlite3.Row) -> BatchRecord:
        return BatchRecord(
            campaign_id=row["campaign_id"],
            batch_id=row["batch_id"],
            status=BatchStatus(row["status"]),
            manifest=json.loads(row["manifest_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            sequence=row["sequence"],
            event_id=row["event_id"],
            campaign_id=row["campaign_id"],
            batch_id=row["batch_id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            event_type=row["event_type"],
            idempotency_key=row["idempotency_key"],
            actor=row["actor"],
            payload=json.loads(row["payload_json"]),
            payload_ref=row["payload_ref"],
            created_at=row["created_at"],
        )
