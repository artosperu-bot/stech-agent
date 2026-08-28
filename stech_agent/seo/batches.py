from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Iterable

from stech_agent.db.connection import AgentDatabase


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    return json.loads(value)


def _utc_sql(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True, slots=True)
class SeoBatchItem:
    id: int
    batch_id: int
    position: int
    sku: str
    state: str
    attempt_count: int
    lease_owner: str | None
    lease_until: str | None
    last_error: str | None
    updated_at: str


class SeoBatchRepository:
    def __init__(self, db: AgentDatabase):
        self.db = db

    @staticmethod
    def _item(row) -> SeoBatchItem:
        return SeoBatchItem(
            id=int(row["id"]),
            batch_id=int(row["batch_id"]),
            position=int(row["position"]),
            sku=str(row["sku"]),
            state=str(row["state"]),
            attempt_count=int(row["attempt_count"]),
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            last_error=row["last_error"],
            updated_at=str(row["updated_at"]),
        )

    def create(
        self,
        session_id: int | None,
        skus: Iterable[str],
        scope: dict,
        publish: bool,
    ) -> int:
        clean_skus = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
        if not clean_skus:
            raise ValueError("No se puede crear un lote SEO sin SKU")
        with self.db.transaction(immediate=True) as con:
            cur = con.execute(
                """
                INSERT INTO seo_batches(
                    session_id, scope_json, status, publish_enabled, total_items, started_at
                ) VALUES (?, ?, 'RUNNING', ?, ?, CURRENT_TIMESTAMP)
                """,
                (session_id, _dumps(scope or {}), int(bool(publish)), len(clean_skus)),
            )
            batch_id = int(cur.lastrowid)
            for position, sku in enumerate(clean_skus):
                con.execute(
                    """
                    INSERT INTO seo_batch_items(batch_id, position, sku, state)
                    VALUES (?, ?, ?, 'RESEARCH_PENDING')
                    """,
                    (batch_id, position, sku),
                )
            return batch_id

    def get(self, batch_id: int) -> dict | None:
        with self.db.connect() as con:
            row = con.execute("SELECT * FROM seo_batches WHERE id=?", (int(batch_id),)).fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "session_id": row["session_id"],
            "scope": _loads(row["scope_json"], {}),
            "status": str(row["status"]),
            "publish_enabled": bool(row["publish_enabled"]),
            "total_items": int(row["total_items"]),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }

    def list_items(self, batch_id: int) -> list[SeoBatchItem]:
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT * FROM seo_batch_items WHERE batch_id=? ORDER BY position, id",
                (int(batch_id),),
            ).fetchall()
        return [self._item(row) for row in rows]

    def get_item(self, item_id: int) -> SeoBatchItem | None:
        with self.db.connect() as con:
            row = con.execute("SELECT * FROM seo_batch_items WHERE id=?", (int(item_id),)).fetchone()
        return self._item(row) if row is not None else None

    def claim(
        self,
        batch_id: int,
        from_states: Iterable[str],
        to_state: str,
        worker_id: str,
        lease_seconds: int,
    ) -> SeoBatchItem | None:
        states = tuple(dict.fromkeys(str(state) for state in from_states if str(state)))
        if not states:
            raise ValueError("from_states no puede estar vacío")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds debe ser mayor que cero")
        now = datetime.now(timezone.utc)
        lease_until = _utc_sql(now + timedelta(seconds=int(lease_seconds)))
        placeholders = ",".join("?" for _ in states)

        with self.db.transaction(immediate=True) as con:
            batch = con.execute("SELECT status FROM seo_batches WHERE id=?", (int(batch_id),)).fetchone()
            if batch is None:
                raise KeyError(f"Lote SEO inexistente: {batch_id}")
            if batch["status"] != "RUNNING":
                return None

            row = con.execute(
                f"""
                SELECT * FROM seo_batch_items
                WHERE batch_id=?
                  AND state IN ({placeholders})
                  AND (lease_until IS NULL OR lease_until <= ?)
                ORDER BY position, id
                LIMIT 1
                """,
                (int(batch_id), *states, _utc_sql(now)),
            ).fetchone()
            if row is None:
                return None

            con.execute(
                """
                UPDATE seo_batch_items
                SET state=?, attempt_count=attempt_count+1,
                    lease_owner=?, lease_until=?, last_error=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (str(to_state), str(worker_id), lease_until, int(row["id"])),
            )
            claimed = con.execute("SELECT * FROM seo_batch_items WHERE id=?", (int(row["id"]),)).fetchone()
            return self._item(claimed)

    def transition(
        self,
        item_id: int,
        expected_state: str,
        new_state: str,
        *,
        error: str | None = None,
    ) -> SeoBatchItem:
        with self.db.transaction(immediate=True) as con:
            row = con.execute("SELECT state FROM seo_batch_items WHERE id=?", (int(item_id),)).fetchone()
            if row is None:
                raise KeyError(f"Item SEO inexistente: {item_id}")
            if row["state"] != expected_state:
                raise RuntimeError(
                    f"El item {item_id} está en estado {row['state']}, no en {expected_state}"
                )
            con.execute(
                """
                UPDATE seo_batch_items
                SET state=?, lease_owner=NULL, lease_until=NULL, last_error=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (str(new_state), error, int(item_id)),
            )
            updated = con.execute("SELECT * FROM seo_batch_items WHERE id=?", (int(item_id),)).fetchone()
            return self._item(updated)

    def set_state(self, item_id: int, new_state: str, *, error: str | None = None) -> SeoBatchItem:
        with self.db.transaction(immediate=True) as con:
            cur = con.execute(
                """
                UPDATE seo_batch_items
                SET state=?, lease_owner=NULL, lease_until=NULL, last_error=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (str(new_state), error, int(item_id)),
            )
            if cur.rowcount != 1:
                raise KeyError(f"Item SEO inexistente: {item_id}")
            row = con.execute("SELECT * FROM seo_batch_items WHERE id=?", (int(item_id),)).fetchone()
            return self._item(row)

    def recover_expired(self, batch_id: int) -> int:
        now = _utc_sql()
        with self.db.transaction(immediate=True) as con:
            rows = con.execute(
                """
                SELECT id, state FROM seo_batch_items
                WHERE batch_id=? AND lease_until IS NOT NULL AND lease_until <= ?
                """,
                (int(batch_id), now),
            ).fetchall()
            for row in rows:
                state = str(row["state"])
                if state == "PUBLISHING":
                    recovered_state = "READY_REVERIFY"
                elif state == "RESEARCHING":
                    recovered_state = "RESEARCH_PENDING"
                elif state == "QA_RUNNING":
                    recovered_state = "QA_PENDING"
                else:
                    recovered_state = "RESEARCH_PENDING"
                con.execute(
                    """
                    UPDATE seo_batch_items
                    SET state=?, lease_owner=NULL, lease_until=NULL,
                        last_error='Lease expirado; item recuperado', updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (recovered_state, int(row["id"])),
                )
            return len(rows)

    def status(self, batch_id: int) -> dict:
        batch = self.get(batch_id)
        if batch is None:
            raise KeyError(f"Lote SEO inexistente: {batch_id}")
        with self.db.connect() as con:
            rows = con.execute(
                """
                SELECT state, COUNT(*) AS n
                FROM seo_batch_items
                WHERE batch_id=?
                GROUP BY state
                ORDER BY state
                """,
                (int(batch_id),),
            ).fetchall()
        states = {str(row["state"]): int(row["n"]) for row in rows}
        return {**batch, "states": states}

    def pause(self, batch_id: int) -> None:
        self._set_batch_status(batch_id, "PAUSED")

    def resume(self, batch_id: int) -> None:
        self._set_batch_status(batch_id, "RUNNING")

    def cancel(self, batch_id: int) -> None:
        self._set_batch_status(batch_id, "CANCELLED")

    def _set_batch_status(self, batch_id: int, status: str) -> None:
        with self.db.transaction(immediate=True) as con:
            cur = con.execute(
                "UPDATE seo_batches SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(status), int(batch_id)),
            )
            if cur.rowcount != 1:
                raise KeyError(f"Lote SEO inexistente: {batch_id}")
