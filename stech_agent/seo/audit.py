from __future__ import annotations

import json
from typing import Any, Iterable

from stech_agent.db.connection import AgentDatabase


class SeoAuditRepository:
    def __init__(self, db: AgentDatabase):
        self.db = db

    def record(self, sku: str, status: str, values: dict[str, Any], *, source: str = "stech_live") -> None:
        sku = str(sku).strip()
        if not sku:
            raise ValueError("SKU vacío")
        with self.db.transaction(immediate=True) as con:
            con.execute(
                """
                INSERT INTO seo_audit_cache(sku,status,values_json,checked_at,source)
                VALUES (?,?,?,CURRENT_TIMESTAMP,?)
                ON CONFLICT(sku) DO UPDATE SET
                    status=excluded.status,
                    values_json=excluded.values_json,
                    checked_at=CURRENT_TIMESTAMP,
                    source=excluded.source
                """,
                (sku, str(status), json.dumps(values or {}, ensure_ascii=False, sort_keys=True), str(source)),
            )

    def get(self, sku: str) -> dict[str, Any] | None:
        with self.db.connect() as con:
            row = con.execute("SELECT * FROM seo_audit_cache WHERE sku=?", (str(sku).strip(),)).fetchone()
        if row is None:
            return None
        return {
            "sku": str(row["sku"]),
            "status": str(row["status"]),
            "values": json.loads(row["values_json"] or "{}"),
            "checked_at": row["checked_at"],
            "source": row["source"],
        }

    def select_for_completion(self, skus: Iterable[str]) -> dict[str, list[str]]:
        ordered = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
        process: list[str] = []
        complete: list[str] = []
        unaudited: list[str] = []
        empty: list[str] = []
        incomplete: list[str] = []
        for sku in ordered:
            row = self.get(sku)
            if row is None:
                unaudited.append(sku)
                continue
            status = row["status"]
            if status == "SEO_COMPLETE":
                complete.append(sku)
            elif status == "SEO_EMPTY":
                process.append(sku)
                empty.append(sku)
            elif status == "SEO_INCOMPLETE":
                process.append(sku)
                incomplete.append(sku)
            else:
                unaudited.append(sku)
        return {
            "process_skus": process,
            "complete_skus": complete,
            "empty_skus": empty,
            "incomplete_skus": incomplete,
            "unaudited_skus": unaudited,
        }
