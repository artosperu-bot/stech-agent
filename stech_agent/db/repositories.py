from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
from typing import Any

from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.domain.models import ProductRecord


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    return json.loads(value)


def _product_to_json(product: ProductRecord) -> dict[str, Any]:
    data = asdict(product)
    data["price"] = None if product.price is None else str(product.price)
    data["discount"] = None if product.discount is None else str(product.discount)
    data["duplicate_sources"] = list(product.duplicate_sources)
    data["conflict_fields"] = sorted(product.conflict_fields)
    return data


def _product_from_json(payload: dict[str, Any]) -> ProductRecord:
    payload = dict(payload)
    if payload.get("price") is not None:
        payload["price"] = Decimal(str(payload["price"]))
    if payload.get("discount") is not None:
        payload["discount"] = Decimal(str(payload["discount"]))
    payload["duplicate_sources"] = tuple(payload.get("duplicate_sources") or ())
    payload["conflict_fields"] = frozenset(payload.get("conflict_fields") or ())
    return ProductRecord(**payload)


class CatalogRepository:
    def __init__(self, db: AgentDatabase):
        self.db = db

    def save_snapshot(self, snapshot: CatalogSnapshotData) -> int:
        with self.db.transaction(immediate=True) as con:
            cur = con.execute(
                "INSERT INTO catalog_snapshots(source_path, checksum, raw_headers_json) VALUES (?, ?, ?)",
                (snapshot.source_path, snapshot.checksum, _dumps(list(snapshot.raw_headers))),
            )
            snapshot_id = int(cur.lastrowid)
            for p in snapshot.products:
                con.execute(
                    """
                    INSERT INTO catalog_products(
                        snapshot_id, sku, source_order, name, brand, category, subcategory,
                        stock, on_offer, visible, price, ambiguous, conflict_fields_json, source_json, canonical_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        p.sku,
                        p.source_order,
                        p.name,
                        p.brand,
                        p.category,
                        p.subcategory,
                        p.stock,
                        None if p.on_offer is None else int(p.on_offer),
                        None if p.visible is None else int(p.visible),
                        None if p.price is None else str(p.price),
                        int(p.ambiguous),
                        _dumps(sorted(p.conflict_fields)),
                        _dumps(p.source),
                        _dumps(_product_to_json(p)),
                    ),
                )
            return snapshot_id

    def latest_snapshot_id(self) -> int | None:
        with self.db.connect() as con:
            row = con.execute("SELECT id FROM catalog_snapshots ORDER BY id DESC LIMIT 1").fetchone()
            return int(row[0]) if row else None

    def get_snapshot_meta(self, snapshot_id: int | None = None) -> dict[str, Any] | None:
        snapshot_id = snapshot_id or self.latest_snapshot_id()
        if snapshot_id is None:
            return None
        with self.db.connect() as con:
            row = con.execute("SELECT * FROM catalog_snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "source_path": row["source_path"],
                "checksum": row["checksum"],
                "raw_headers": _loads(row["raw_headers_json"], []),
                "created_at": row["created_at"],
            }

    def get_by_sku(self, sku: str, *, snapshot_id: int | None = None) -> ProductRecord | None:
        snapshot_id = snapshot_id or self.latest_snapshot_id()
        if snapshot_id is None:
            return None
        with self.db.connect() as con:
            row = con.execute(
                "SELECT canonical_json FROM catalog_products WHERE snapshot_id=? AND sku=?",
                (snapshot_id, str(sku)),
            ).fetchone()
            if not row:
                return None
            return _product_from_json(_loads(row[0], {}))

    def list_products(self, *, snapshot_id: int | None = None) -> list[ProductRecord]:
        snapshot_id = snapshot_id or self.latest_snapshot_id()
        if snapshot_id is None:
            return []
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT canonical_json FROM catalog_products WHERE snapshot_id=? ORDER BY source_order",
                (snapshot_id,),
            ).fetchall()
        return [_product_from_json(_loads(row[0], {})) for row in rows]

    def list_ambiguous_skus(self, *, snapshot_id: int | None = None) -> list[dict[str, Any]]:
        snapshot_id = snapshot_id or self.latest_snapshot_id()
        if snapshot_id is None:
            return []
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT sku, conflict_fields_json FROM catalog_products WHERE snapshot_id=? AND ambiguous=1 ORDER BY source_order",
                (snapshot_id,),
            ).fetchall()
        return [
            {"sku": row["sku"], "conflict_fields": _loads(row["conflict_fields_json"], [])}
            for row in rows
        ]


class SessionRepository:
    def __init__(self, db: AgentDatabase):
        self.db = db

    def create_session(self, metadata: dict[str, Any] | None = None) -> int:
        with self.db.transaction(immediate=True) as con:
            cur = con.execute("INSERT INTO chat_sessions(metadata_json) VALUES (?)", (_dumps(metadata or {}),))
            return int(cur.lastrowid)

    def replace_working_set(
        self,
        session_id: int,
        name: str,
        skus: list[str],
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_skus = list(dict.fromkeys(str(s).strip() for s in skus if str(s).strip()))
        with self.db.transaction(immediate=True) as con:
            row = con.execute(
                "SELECT id, version FROM working_sets WHERE session_id=? AND name=?",
                (session_id, name),
            ).fetchone()
            if row:
                version = int(row["version"]) + 1
                con.execute(
                    "UPDATE working_sets SET version=?, skus_json=?, query_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (version, _dumps(clean_skus), _dumps(query or {}), row["id"]),
                )
                working_set_id = int(row["id"])
            else:
                version = 1
                cur = con.execute(
                    "INSERT INTO working_sets(session_id,name,version,skus_json,query_json) VALUES (?,?,?,?,?)",
                    (session_id, name, version, _dumps(clean_skus), _dumps(query or {})),
                )
                working_set_id = int(cur.lastrowid)
        return {"id": working_set_id, "version": version, "skus": clean_skus, "query": query or {}}

    def get_working_set(self, session_id: int, name: str = "current") -> dict[str, Any] | None:
        with self.db.connect() as con:
            row = con.execute(
                "SELECT * FROM working_sets WHERE session_id=? AND name=?",
                (session_id, name),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "version": row["version"],
                "skus": _loads(row["skus_json"], []),
                "query": _loads(row["query_json"], {}),
            }


class TaskRepository:
    def __init__(self, db: AgentDatabase):
        self.db = db

    def create_task(
        self,
        action: str,
        skus: list[str],
        payload: dict[str, Any] | None = None,
        *,
        session_id: int | None = None,
    ) -> int:
        with self.db.transaction(immediate=True) as con:
            cur = con.execute(
                "INSERT INTO tasks(session_id, action, payload_json) VALUES (?, ?, ?)",
                (session_id, action, _dumps(payload or {})),
            )
            task_id = int(cur.lastrowid)
            for position, sku in enumerate(skus):
                con.execute(
                    "INSERT INTO task_items(task_id, position, sku) VALUES (?, ?, ?)",
                    (task_id, position, str(sku)),
                )
            return task_id

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self.db.connect() as con:
            row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            count = con.execute("SELECT COUNT(*) FROM task_items WHERE task_id=?", (task_id,)).fetchone()[0]
            return {
                "id": row["id"],
                "action": row["action"],
                "state": row["state"],
                "payload": _loads(row["payload_json"], {}),
                "item_count": count,
            }

    def list_items(self, task_id: int) -> list[dict[str, Any]]:
        with self.db.connect() as con:
            rows = con.execute("SELECT * FROM task_items WHERE task_id=? ORDER BY position", (task_id,)).fetchall()
        return [
            {
                "id": row["id"],
                "sku": row["sku"],
                "state": row["state"],
                "attempts": row["attempts"],
                "resume_required": bool(row["resume_required"]),
                "metadata": _loads(row["metadata_json"], {}),
            }
            for row in rows
        ]


class AuditRepository:
    def __init__(self, db: AgentDatabase):
        self.db = db

    def add(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        session_id: int | None = None,
        task_id: int | None = None,
        sku: str | None = None,
    ) -> int:
        with self.db.transaction(immediate=True) as con:
            cur = con.execute(
                "INSERT INTO audit_events(session_id, task_id, event_type, sku, payload_json) VALUES (?, ?, ?, ?, ?)",
                (session_id, task_id, event_type, sku, _dumps(payload)),
            )
            return int(cur.lastrowid)
