"""SQLite fact store for Campaign, Batch, and append-only events."""

from __future__ import annotations

from contextlib import AbstractContextManager
import datetime as dt
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence
import uuid

from .models import (
    AppendResult,
    BatchRecord,
    BatchStatus,
    CampaignAuditMode,
    CampaignRecord,
    CampaignStatus,
    EventRecord,
    require_transition,
)


_MAX_TASK_RETRY_AUTHORIZATIONS = 3


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
                audit_mode TEXT NOT NULL DEFAULT 'legacy',
                history_sources_json TEXT NOT NULL DEFAULT '[]',
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

            CREATE TABLE IF NOT EXISTS campaign_evidence_paths (
                campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                path TEXT NOT NULL,
                role TEXT NOT NULL,
                component_id TEXT NOT NULL,
                PRIMARY KEY (campaign_id, path, role)
            );

            CREATE TABLE IF NOT EXISTS campaign_evidence_path_indexes (
                campaign_id TEXT PRIMARY KEY REFERENCES campaigns(campaign_id),
                snapshot_id TEXT NOT NULL,
                created_at TEXT NOT NULL
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
            CREATE INDEX IF NOT EXISTS idx_events_campaign_entity
                ON events(campaign_id, entity_type, entity_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_campaign_entity_event
                ON events(campaign_id, entity_type, event_type, batch_id, entity_id);
            CREATE INDEX IF NOT EXISTS idx_events_campaign_event_type
                ON events(campaign_id, event_type, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_campaign_batch_type
                ON events(campaign_id, batch_id, event_type, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_campaign_batch_type_entity
                ON events(campaign_id, batch_id, event_type, entity_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_events_payload_ref
                ON events(payload_ref);
            CREATE INDEX IF NOT EXISTS idx_evidence_paths_campaign_role_path
                ON campaign_evidence_paths(campaign_id, role, path);
            """
        )
        campaign_columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(campaigns)")
        }
        if "audit_mode" not in campaign_columns:
            self._connection.execute(
                "ALTER TABLE campaigns ADD COLUMN audit_mode TEXT NOT NULL DEFAULT 'legacy'"
            )
        if "history_sources_json" not in campaign_columns:
            self._connection.execute(
                "ALTER TABLE campaigns ADD COLUMN history_sources_json TEXT NOT NULL DEFAULT '[]'"
            )
        self._connection.commit()

    def create_campaign(
        self,
        *,
        campaign_id: str,
        target_root: str,
        snapshot_id: str,
        audit_mode: CampaignAuditMode = CampaignAuditMode.FRESH,
        history_source_campaign_ids: tuple[str, ...] = (),
        budget: Mapping[str, Any] | None = None,
        constraints: list[str] | tuple[str, ...] | None = None,
    ) -> CampaignRecord:
        if audit_mode is CampaignAuditMode.LEGACY:
            raise ValueError("legacy is reserved for migrated Campaign records")
        if len(history_source_campaign_ids) != len(set(history_source_campaign_ids)):
            raise ValueError("history source Campaign IDs must be unique")
        if audit_mode is CampaignAuditMode.FRESH and history_source_campaign_ids:
            raise ValueError("fresh Campaigns cannot declare historical Campaign sources")
        if audit_mode is CampaignAuditMode.FOLLOW_UP and not history_source_campaign_ids:
            raise ValueError("follow-up Campaigns require explicit history sources")
        screening_fraction = (budget or {}).get("max_screening_fraction")
        if screening_fraction is not None and (
            isinstance(screening_fraction, bool)
            or not isinstance(screening_fraction, (int, float))
            or not 0 <= screening_fraction <= 1
        ):
            raise ValueError("max_screening_fraction must be a number between 0 and 1")
        if "require_host_worker_attestation" in (budget or {}) and type(
            (budget or {})["require_host_worker_attestation"]
        ) is not bool:
            raise ValueError("require_host_worker_attestation must be boolean")
        delegated_cap = (budget or {}).get("max_delegated_agent_runs")
        if delegated_cap is not None and (
            type(delegated_cap) is not int or delegated_cap < 0
        ):
            raise ValueError("max_delegated_agent_runs must be a non-negative integer")
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
                    or record.audit_mode != audit_mode
                    or record.history_source_campaign_ids != history_source_campaign_ids
                    or _json(record.budget) != budget_json
                    or _json(record.constraints) != constraints_json
                ):
                    raise ConflictError(f"campaign ID reused with different data: {campaign_id}")
                return record
            self._connection.execute(
                """
                INSERT INTO campaigns (
                    campaign_id, target_root, snapshot_id, audit_mode,
                    history_sources_json, status, budget_json, constraints_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    target_root,
                    snapshot_id,
                    audit_mode.value,
                    _json(list(history_source_campaign_ids)),
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
                payload={
                    "snapshot_id": snapshot_id,
                    "audit_mode": audit_mode.value,
                    "history_source_campaign_ids": list(history_source_campaign_ids),
                },
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

    def effective_wall_limit_seconds(self, campaign_id: str) -> int | None:
        campaign = self.get_campaign(campaign_id)
        original_limit = campaign.budget.get("max_wall_seconds")
        if original_limit is None:
            return None
        if type(original_limit) is not int or original_limit <= 0:
            raise StoreError("Campaign max_wall_seconds budget must be a positive integer")
        effective_limit = original_limit
        amendments = self.list_events(
            campaign_id,
            entity_type="campaign_wall_budget",
            entity_id=campaign_id,
            event_type="CAMPAIGN_WALL_BUDGET_AMENDED",
        )
        for event in amendments:
            payload = event.payload
            if (
                payload.get("original_max_wall_seconds") != original_limit
                or payload.get("previous_approved_max_wall_seconds") != effective_limit
                or type(payload.get("approved_max_wall_seconds")) is not int
                or payload["approved_max_wall_seconds"] <= effective_limit
            ):
                raise StoreError("Campaign wall-budget amendment history is invalid")
            effective_limit = payload["approved_max_wall_seconds"]
        return effective_limit

    def amend_campaign_wall_budget(
        self,
        *,
        campaign_id: str,
        approved_max_wall_seconds: int,
        actor: str,
        reason: str,
        evidence_refs: Sequence[str],
        now: str,
    ) -> AppendResult:
        if type(approved_max_wall_seconds) is not int or approved_max_wall_seconds <= 0:
            raise ValueError("approved wall limit must be a positive integer")
        if not actor.strip() or not reason.strip():
            raise ValueError("wall-budget amendment requires actor and reason")
        if isinstance(evidence_refs, (str, bytes)):
            raise ValueError("wall-budget amendment requires evidence references")
        normalized_evidence = tuple(evidence_refs)
        if (
            not normalized_evidence
            or any(not isinstance(item, str) or not item.strip() for item in normalized_evidence)
            or len(set(normalized_evidence)) != len(normalized_evidence)
        ):
            raise ValueError("wall-budget amendment requires unique evidence references")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            campaign_row = self._connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            if campaign_row is None:
                raise NotFoundError(f"campaign not found: {campaign_id}")
            campaign = self._campaign_from_row(campaign_row)
            if campaign.status is CampaignStatus.COMPLETE:
                raise ConflictError("completed Campaign wall budget cannot be amended")
            original_limit = campaign.budget.get("max_wall_seconds")
            if type(original_limit) is not int or original_limit <= 0:
                raise ConflictError("Campaign has no amendable max_wall_seconds budget")
            amendment_rows = self._connection.execute(
                """
                SELECT * FROM events
                WHERE campaign_id = ? AND entity_type = 'campaign_wall_budget'
                    AND entity_id = ? AND event_type = 'CAMPAIGN_WALL_BUDGET_AMENDED'
                ORDER BY sequence
                """,
                (campaign_id, campaign_id),
            ).fetchall()
            amendments = [self._event_from_row(row) for row in amendment_rows]
            effective_limit = original_limit
            for event in amendments:
                payload = event.payload
                if (
                    payload.get("original_max_wall_seconds") != original_limit
                    or payload.get("previous_approved_max_wall_seconds") != effective_limit
                    or type(payload.get("approved_max_wall_seconds")) is not int
                    or payload["approved_max_wall_seconds"] <= effective_limit
                ):
                    raise StoreError("Campaign wall-budget amendment history is invalid")
                effective_limit = payload["approved_max_wall_seconds"]

            if approved_max_wall_seconds == effective_limit and amendments:
                previous = amendments[-1]
                if (
                    previous.actor == actor
                    and previous.payload.get("reason") == reason
                    and previous.payload.get("evidence_refs") == list(normalized_evidence)
                ):
                    self._connection.commit()
                    return AppendResult(event_id=previous.event_id, inserted=False)
            if approved_max_wall_seconds <= effective_limit:
                raise ConflictError(
                    "approved wall limit must monotonically exceed the current limit"
                )

            created_at = dt.datetime.fromisoformat(campaign.created_at)
            approval_at = dt.datetime.fromisoformat(now)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=dt.UTC)
            if approval_at.tzinfo is None:
                approval_at = approval_at.replace(tzinfo=dt.UTC)
            elapsed_seconds = max(
                0.0,
                (
                    approval_at.astimezone(dt.UTC) - created_at.astimezone(dt.UTC)
                ).total_seconds(),
            )
            payload = {
                "original_max_wall_seconds": original_limit,
                "previous_approved_max_wall_seconds": effective_limit,
                "approved_max_wall_seconds": approved_max_wall_seconds,
                "extension_seconds": approved_max_wall_seconds - effective_limit,
                "elapsed_at_approval_seconds": round(elapsed_seconds, 1),
                "original_limit_breached": elapsed_seconds > original_limit,
                "reason": reason,
                "evidence_refs": list(normalized_evidence),
            }
            result = self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=None,
                entity_type="campaign_wall_budget",
                entity_id=campaign_id,
                event_type="CAMPAIGN_WALL_BUDGET_AMENDED",
                idempotency_key=(
                    f"campaign:wall-budget-amend:{campaign_id}:"
                    f"{effective_limit}:{approved_max_wall_seconds}"
                ),
                actor=actor,
                payload=payload,
                payload_ref=None,
                created_at=now,
            )
            self._connection.commit()
            return result
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

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

    def append_events_batch(
        self,
        campaign_id: str,
        events: Sequence[Mapping[str, Any]],
    ) -> list[AppendResult]:
        self.get_campaign(campaign_id)
        created_at = _utc_now()
        results = []
        with self._connection:
            for item in events:
                results.append(self._append_event_tx(
                    campaign_id=campaign_id,
                    batch_id=(str(item["batch_id"]) if item.get("batch_id") is not None else None),
                    entity_type=str(item["entity_type"]),
                    entity_id=str(item["entity_id"]),
                    event_type=str(item["event_type"]),
                    idempotency_key=str(item["idempotency_key"]),
                    actor=str(item.get("actor", "tool")),
                    payload=dict(item.get("payload", {})),
                    payload_ref=(
                        str(item["payload_ref"])
                        if item.get("payload_ref") is not None else None
                    ),
                    created_at=created_at,
                ))
        return results

    def list_events(
        self,
        campaign_id: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
        event_types: set[str] | frozenset[str] | None = None,
    ) -> list[EventRecord]:
        clauses = ["campaign_id = ?"]
        parameters: list[Any] = [campaign_id]
        for column, value in (
            ("entity_type", entity_type),
            ("entity_id", entity_id),
            ("event_type", event_type),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if event_types is not None:
            values = sorted(event_types)
            if not values:
                return []
            clauses.append(f"event_type IN ({','.join('?' for _ in values)})")
            parameters.extend(values)
        rows = self._connection.execute(
            f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY sequence",
            parameters,
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_batch_events(
        self,
        campaign_id: str,
        batch_id: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
        event_types: set[str] | frozenset[str] | None = None,
    ) -> list[EventRecord]:
        clauses = ["campaign_id = ?", "batch_id = ?"]
        parameters: list[Any] = [campaign_id, batch_id]
        for column, value in (
            ("entity_type", entity_type),
            ("entity_id", entity_id),
            ("event_type", event_type),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if event_types is not None:
            values = sorted(event_types)
            if not values:
                return []
            clauses.append(f"event_type IN ({','.join('?' for _ in values)})")
            parameters.extend(values)
        rows = self._connection.execute(
            f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY sequence",
            parameters,
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_entity_ids(
        self,
        campaign_id: str,
        *,
        entity_type: str,
        event_type: str,
        batch_id: str | None = None,
    ) -> tuple[str, ...]:
        clauses = ["campaign_id = ?", "entity_type = ?", "event_type = ?"]
        parameters: list[Any] = [campaign_id, entity_type, event_type]
        if batch_id is not None:
            clauses.append("batch_id = ?")
            parameters.append(batch_id)
        rows = self._connection.execute(
            "SELECT entity_id FROM events WHERE "
            f"{' AND '.join(clauses)} "
            "GROUP BY entity_id ORDER BY MIN(sequence)",
            parameters,
        ).fetchall()
        return tuple(str(row["entity_id"]) for row in rows)

    def record_evidence_paths(
        self,
        campaign_id: str,
        paths: list[tuple[str, str, str]] | tuple[tuple[str, str, str], ...],
    ) -> None:
        self.get_campaign(campaign_id)
        values = sorted(set(paths))
        owner_by_role: dict[tuple[str, str], str] = {}
        for path, role, component_id in values:
            key = (path, role)
            previous = owner_by_role.setdefault(key, component_id)
            if previous != component_id:
                raise ConflictError(
                    f"evidence path has multiple owners within Campaign: {path}"
                )
        with self._connection:
            campaign = self.get_campaign(campaign_id)
            self._connection.execute(
                "INSERT OR IGNORE INTO campaign_evidence_path_indexes "
                "(campaign_id, snapshot_id, created_at) VALUES (?, ?, ?)",
                (campaign_id, campaign.snapshot_id, _utc_now()),
            )
            index = self._connection.execute(
                "SELECT snapshot_id FROM campaign_evidence_path_indexes "
                "WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if index is None or index["snapshot_id"] != campaign.snapshot_id:
                raise ConflictError("evidence path index snapshot mismatch")
            self._connection.execute(
                "CREATE TEMP TABLE IF NOT EXISTS incoming_evidence_paths ("
                "path TEXT NOT NULL, role TEXT NOT NULL, component_id TEXT NOT NULL, "
                "PRIMARY KEY(path, role))"
            )
            self._connection.execute("DELETE FROM incoming_evidence_paths")
            self._connection.executemany(
                "INSERT INTO incoming_evidence_paths (path, role, component_id) "
                "VALUES (?, ?, ?)",
                values,
            )
            conflict = self._connection.execute(
                "SELECT incoming.path FROM incoming_evidence_paths AS incoming "
                "JOIN campaign_evidence_paths AS existing "
                "ON existing.campaign_id = ? AND existing.path = incoming.path "
                "AND existing.role = incoming.role "
                "WHERE existing.component_id != incoming.component_id LIMIT 1",
                (campaign_id,),
            ).fetchone()
            if conflict is not None:
                raise ConflictError(
                    "evidence path ownership changed within Campaign: "
                    f"{conflict['path']}"
                )
            self._connection.execute(
                "INSERT OR IGNORE INTO campaign_evidence_paths "
                "(campaign_id, path, role, component_id) "
                "SELECT ?, path, role, component_id FROM incoming_evidence_paths",
                (campaign_id,),
            )
            self._connection.execute("DELETE FROM incoming_evidence_paths")

    def has_evidence_path_index(self, campaign_id: str) -> bool:
        row = self._connection.execute(
            "SELECT snapshot_id FROM campaign_evidence_path_indexes "
            "WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return False
        return row["snapshot_id"] == self.get_campaign(campaign_id).snapshot_id

    def has_evidence_path(
        self, campaign_id: str, path: str, *, roles: tuple[str, ...] | None = None
    ) -> bool:
        if roles is None:
            row = self._connection.execute(
                "SELECT 1 FROM campaign_evidence_paths "
                "WHERE campaign_id = ? AND path = ? LIMIT 1",
                (campaign_id, path),
            ).fetchone()
        elif not roles:
            return False
        else:
            placeholders = ",".join("?" for _ in roles)
            row = self._connection.execute(
                "SELECT 1 FROM campaign_evidence_paths "
                f"WHERE campaign_id = ? AND path = ? AND role IN ({placeholders}) LIMIT 1",
                (campaign_id, path, *roles),
            ).fetchone()
        return row is not None

    def artifact_campaign_owners(
        self, artifact_ids: set[str] | tuple[str, ...]
    ) -> dict[str, set[str]]:
        references = sorted(set(artifact_ids))
        owners: dict[str, set[str]] = {}
        for offset in range(0, len(references), 400):
            chunk = references[offset:offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = self._connection.execute(
                f"SELECT payload_ref, campaign_id FROM events "
                f"WHERE payload_ref IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                owners.setdefault(row["payload_ref"], set()).add(row["campaign_id"])
        return owners

    def _task_inputs_invalidated(self, submission: EventRecord) -> bool:
        revisions = submission.payload.get("stage_revision_ids", {})
        if not isinstance(revisions, dict) or not revisions or submission.batch_id is None:
            return False
        rows = self._connection.execute(
            """
            SELECT payload_json FROM events
            WHERE campaign_id = ? AND batch_id = ?
                AND event_type = 'STAGE_PROJECTION_INVALIDATED'
            """,
            (submission.campaign_id, submission.batch_id),
        ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            target_stage = str(payload.get("target_stage", ""))
            target_revision_id = str(payload.get("target_revision_id", ""))
            if revisions.get(target_stage) == target_revision_id:
                return True
        return False

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
            if self._task_inputs_invalidated(events[0]):
                self._connection.rollback()
                return None
            claims = [event for event in events if event.event_type == "TASK_CLAIMED"]
            state_events = [event for event in events if event.event_type in {
                "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
                "TASK_FAILED", "TASK_RETRY_AUTHORIZED", "TASK_CANCELLED",
            }]
            latest_state = state_events[-1] if state_events else None
            if latest_state is not None and latest_state.event_type in {
                "TASK_COMPLETED", "TASK_CANCELLED",
            }:
                self._connection.rollback()
                return None
            attempt = len(claims) + 1
            max_attempts = int(events[0].payload.get("max_attempts", 3))
            retry_authorizations = sum(
                event.event_type == "TASK_RETRY_AUTHORIZED" for event in events
            )
            if attempt > max_attempts + retry_authorizations:
                self._connection.rollback()
                return None
            if (
                latest_state is not None
                and latest_state.event_type == "TASK_CLAIMED"
                and str(latest_state.payload["lease_expires_at"]) > now
            ):
                self._connection.rollback()
                return None
            campaign_row = self._connection.execute(
                "SELECT budget_json FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if campaign_row is None:
                raise NotFoundError(f"campaign not found: {campaign_id}")
            campaign_budget = json.loads(campaign_row["budget_json"])
            delegated_cap = campaign_budget.get("max_delegated_agent_runs")
            if delegated_cap is not None:
                campaign_task_rows = self._connection.execute(
                    """
                    SELECT * FROM events
                    WHERE campaign_id = ? AND entity_type = 'execution_task'
                    ORDER BY sequence
                    """,
                    (campaign_id,),
                ).fetchall()
                events_by_task: dict[str, list[EventRecord]] = {}
                for row in campaign_task_rows:
                    event = self._event_from_row(row)
                    events_by_task.setdefault(event.entity_id, []).append(event)
                used = 0
                reserved = 0
                for existing_task_id, task_events in events_by_task.items():
                    submission = next(
                        (event for event in task_events if event.event_type == "TASK_SUBMITTED"),
                        None,
                    )
                    if submission is None:
                        continue
                    task_budget = submission.payload.get("budget", {})
                    if not isinstance(task_budget, dict):
                        task_budget = {}
                    task_cap = task_budget.get("delegated_agent_runs", 0)
                    if type(task_cap) is not int or task_cap < 0:
                        raise StoreError(
                            f"execution task has invalid delegated reservation: {existing_task_id}"
                        )
                    used += sum(
                        int(event.payload.get("measurements", {}).get(
                            "delegated_agent_runs", 0
                        ))
                        for event in task_events
                        if event.event_type in {"TASK_COMPLETED", "TASK_FAILED"}
                    )
                    task_state_events = [
                        event for event in task_events
                        if event.event_type in {
                            "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
                            "TASK_FAILED", "TASK_RETRY_AUTHORIZED", "TASK_CANCELLED",
                        }
                    ]
                    current_state = task_state_events[-1] if task_state_events else None
                    if (
                        existing_task_id != task_id
                        and current_state is not None
                        and current_state.event_type == "TASK_CLAIMED"
                        and str(current_state.payload.get("lease_expires_at", "")) > now
                        and not self._task_inputs_invalidated(submission)
                    ):
                        reserved += task_cap
                candidate_budget = events[0].payload.get("budget", {})
                candidate_reservation = (
                    candidate_budget.get("delegated_agent_runs", 0)
                    if isinstance(candidate_budget, dict) else 0
                )
                if (
                    type(candidate_reservation) is not int
                    or candidate_reservation < 0
                    or used + reserved + candidate_reservation > delegated_cap
                ):
                    self._connection.rollback()
                    return None
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

    def authorize_expired_task_recovery(
        self,
        *,
        campaign_id: str,
        task_id: str,
        worker_id: str,
        attempt: int,
        output_ref: str,
        lease_expires_at: str,
        actor: str,
        reason: str,
        evidence_refs: Sequence[str],
        now: str,
    ) -> AppendResult:
        if not actor.strip() or not reason.strip():
            raise ValueError("expired-lease recovery requires operator actor and reason")
        if (
            not evidence_refs or isinstance(evidence_refs, (str, bytes))
            or any(not isinstance(item, str) or not item.strip() for item in evidence_refs)
            or len(set(evidence_refs)) != len(evidence_refs)
        ):
            raise ValueError("expired-lease recovery requires unique evidence references")
        if not output_ref:
            raise ValueError("expired-lease recovery requires the original output artifact")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            campaign = self.get_campaign(campaign_id)
            if campaign.status is CampaignStatus.COMPLETE:
                raise ConflictError("completed Campaign cannot recover task output")
            events = self.list_events(
                campaign_id, entity_type="execution_task", entity_id=task_id,
            )
            if not events:
                raise NotFoundError(f"execution task not found: {task_id}")
            if self._task_inputs_invalidated(events[0]):
                raise ConflictError("execution task inputs refer to an invalidated stage revision")
            state_events = [
                event for event in events if event.event_type in {
                    "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
                    "TASK_FAILED", "TASK_RETRY_AUTHORIZED", "TASK_CANCELLED",
                }
            ]
            if not state_events or state_events[-1].event_type != "TASK_CLAIMED":
                raise ConflictError("only a currently leased task can recover expired output")
            claim = state_events[-1]
            if claim.payload["attempt"] != attempt:
                raise ConflictError("execution task lease attempt is stale")
            if claim.actor != worker_id:
                raise ConflictError("execution task lease belongs to another worker")
            if claim.payload["lease_expires_at"] != lease_expires_at:
                raise ConflictError("execution task lease expiration binding is stale")
            if dt.datetime.fromisoformat(lease_expires_at) > dt.datetime.fromisoformat(now):
                raise ConflictError("execution task lease has not expired")
            result = self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=events[0].batch_id,
                entity_type="execution_task_recovery",
                entity_id=task_id,
                event_type="TASK_EXPIRED_RECOVERY_AUTHORIZED",
                idempotency_key=(
                    f"task:expired-recovery:{campaign_id}:{task_id}:"
                    f"{claim.event_id}:{output_ref}"
                ),
                actor=actor,
                payload={
                    "claim_event_id": claim.event_id,
                    "attempt": attempt,
                    "worker_id": worker_id,
                    "lease_expires_at": lease_expires_at,
                    "output_ref": output_ref,
                    "reason": reason,
                    "evidence_refs": list(evidence_refs),
                },
                payload_ref=output_ref,
                created_at=now,
            )
            self._connection.commit()
            return result
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
        attempt: int,
        succeeded: bool,
        payload: Mapping[str, Any],
        payload_ref: str | None,
        now: str,
        recovery_authorization_id: str | None = None,
    ) -> AppendResult:
        self.get_campaign(campaign_id)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            if (
                recovery_authorization_id is not None
                and self.get_campaign(campaign_id).status is CampaignStatus.COMPLETE
            ):
                raise ConflictError("completed Campaign cannot recover task output")
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
            if self._task_inputs_invalidated(events[0]):
                raise ConflictError(
                    f"execution task inputs refer to an invalidated stage revision: {task_id}"
                )
            claims = [event for event in events if event.event_type == "TASK_CLAIMED"]
            if not claims:
                raise ConflictError(f"execution task has no active lease: {task_id}")
            claim = claims[-1]
            if int(claim.payload["attempt"]) != attempt:
                raise ConflictError(f"execution task lease attempt is stale: {task_id}")
            event_type = "TASK_COMPLETED" if succeeded else "TASK_FAILED"
            idempotency_key = f"task:finalize:{campaign_id}:{task_id}:{claim.event_id}"
            state_events = [event for event in events if event.event_type in {
                "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
                "TASK_FAILED", "TASK_RETRY_AUTHORIZED", "TASK_CANCELLED",
            }]
            latest_state = state_events[-1] if state_events else None
            if recovery_authorization_id is not None:
                if latest_state is None or latest_state.event_id != claim.event_id:
                    raise ConflictError("only a currently leased task can recover expired output")
                authorization = self._connection.execute(
                    """
                    SELECT * FROM events WHERE event_id = ? AND campaign_id = ?
                        AND entity_type = 'execution_task_recovery' AND entity_id = ?
                        AND event_type = 'TASK_EXPIRED_RECOVERY_AUTHORIZED'
                    """,
                    (recovery_authorization_id, campaign_id, task_id),
                ).fetchone()
                if authorization is None:
                    raise ConflictError("expired-lease recovery authorization not found")
                authorized = self._event_from_row(authorization)
                binding = authorized.payload
                if (
                    not succeeded or payload_ref is None
                    or binding.get("claim_event_id") != claim.event_id
                    or binding.get("attempt") != attempt
                    or binding.get("worker_id") != worker_id
                    or binding.get("lease_expires_at") != claim.payload["lease_expires_at"]
                    or binding.get("output_ref") != payload_ref
                    or dt.datetime.fromisoformat(claim.payload["lease_expires_at"])
                    > dt.datetime.fromisoformat(now)
                ):
                    raise ConflictError("expired-lease recovery does not match original lease/output")
                consumed = self._connection.execute(
                    "SELECT 1 FROM events WHERE idempotency_key = ?",
                    (f"task:expired-recovery-consumed:{recovery_authorization_id}",),
                ).fetchone()
                if consumed:
                    raise ConflictError("expired-lease recovery authorization already consumed")
            if latest_state is not None and latest_state.event_type in {
                "TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED",
            }:
                if latest_state.idempotency_key != idempotency_key:
                    raise ConflictError(f"execution task attempt is already terminal: {task_id}")
            elif latest_state is None or latest_state.event_id != claim.event_id:
                raise ConflictError(f"execution task lease is no longer active: {task_id}")
            if claim.actor != worker_id:
                raise ConflictError(f"execution task lease belongs to another worker: {task_id}")
            if (
                str(claim.payload["lease_expires_at"]) <= now
                and latest_state is not None
                and latest_state.event_type == "TASK_CLAIMED"
            ):
                if recovery_authorization_id is None:
                    raise ConflictError(f"execution task lease expired: {task_id}")
            if recovery_authorization_id is not None:
                self._append_event_tx(
                    campaign_id=campaign_id,
                    batch_id=events[0].batch_id,
                    entity_type="execution_task_recovery",
                    entity_id=task_id,
                    event_type="TASK_EXPIRED_RECOVERY_CONSUMED",
                    idempotency_key=(
                        f"task:expired-recovery-consumed:{recovery_authorization_id}"
                    ),
                    actor=worker_id,
                    payload={
                        "authorization_event_id": recovery_authorization_id,
                        "claim_event_id": claim.event_id,
                        "attempt": attempt,
                        "output_ref": payload_ref,
                    },
                    payload_ref=payload_ref,
                    created_at=now,
                )
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

    def authorize_task_retry(
        self,
        *,
        campaign_id: str,
        task_id: str,
        actor: str,
        reason: str,
        now: str,
    ) -> AppendResult:
        self.get_campaign(campaign_id)
        if not actor.strip() or not reason.strip():
            raise ValueError("task retry authorization requires actor and reason")
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
            retries = [event for event in events if event.event_type == "TASK_RETRY_AUTHORIZED"]
            state_events = [event for event in events if event.event_type in {
                "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
                "TASK_FAILED", "TASK_RETRY_AUTHORIZED", "TASK_CANCELLED",
            }]
            latest_state = state_events[-1] if state_events else None
            released_claim = (
                len(state_events) >= 2
                and latest_state is not None
                and latest_state.event_type == "TASK_LEASE_RELEASED"
                and state_events[-2].event_type == "TASK_CLAIMED"
                and claims[-1].event_id == state_events[-2].event_id
            )
            retryable_state = (
                latest_state is not None
                and latest_state.event_type == "TASK_FAILED"
            ) or released_claim
            if not retryable_state:
                raise ConflictError(
                    "only an exhausted failed task or released claim can be retried"
                )
            max_attempts = int(events[0].payload.get("max_attempts", 3))
            if len(claims) < max_attempts + len(retries):
                raise ConflictError("task still has configured attempts remaining")
            if len(retries) >= _MAX_TASK_RETRY_AUTHORIZATIONS:
                raise ConflictError("task retry authorization limit exceeded")
            result = self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=events[0].batch_id,
                entity_type="execution_task",
                entity_id=task_id,
                event_type="TASK_RETRY_AUTHORIZED",
                idempotency_key=(
                    f"task:retry:{campaign_id}:{task_id}:{latest_state.event_id}:"
                    f"{len(retries) + 1}"
                ),
                actor=actor,
                payload={"reason": reason, "additional_attempts": 1},
                payload_ref=None,
                created_at=now,
            )
            self._connection.commit()
            return result
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def release_task(
        self,
        *,
        campaign_id: str,
        task_id: str,
        worker_id: str,
        attempt: int,
        reason: str,
        now: str,
    ) -> AppendResult:
        self.get_campaign(campaign_id)
        if not reason.strip():
            raise ValueError("task lease release requires a reason")
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
            state_events = [event for event in events if event.event_type in {
                "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
                "TASK_FAILED", "TASK_CANCELLED",
            }]
            latest_state = state_events[-1] if state_events else None
            if latest_state is None or latest_state.event_type != "TASK_CLAIMED":
                raise ConflictError(f"execution task has no active lease: {task_id}")
            if latest_state.actor != worker_id:
                raise ConflictError(f"execution task lease belongs to another worker: {task_id}")
            if int(latest_state.payload["attempt"]) != attempt:
                raise ConflictError(f"execution task lease attempt is stale: {task_id}")
            if str(latest_state.payload["lease_expires_at"]) <= now:
                raise ConflictError(f"execution task lease expired: {task_id}")
            result = self._append_event_tx(
                campaign_id=campaign_id,
                batch_id=events[0].batch_id,
                entity_type="execution_task",
                entity_id=task_id,
                event_type="TASK_LEASE_RELEASED",
                idempotency_key=f"task:release:{campaign_id}:{task_id}:{latest_state.event_id}",
                actor=worker_id,
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
            state_events = [event for event in events if event.event_type in {
                "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
                "TASK_FAILED", "TASK_CANCELLED",
            }]
            terminal = state_events[-1] if state_events and state_events[-1].event_type in {
                "TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED",
            } else None
            idempotency_key = f"task:cancel:{campaign_id}:{task_id}"
            if terminal is not None and terminal.event_type in {"TASK_COMPLETED", "TASK_CANCELLED"} and terminal.idempotency_key != idempotency_key:
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
            audit_mode=CampaignAuditMode(row["audit_mode"]),
            history_source_campaign_ids=tuple(json.loads(row["history_sources_json"])),
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
