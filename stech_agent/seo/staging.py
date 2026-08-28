from __future__ import annotations

from pathlib import Path
import json
import os

from openpyxl import Workbook

from stech_agent.db.connection import AgentDatabase


HEADERS = [
    "Batch ID",
    "SKU",
    "Producto",
    "Marca",
    "Categoría",
    "Subcategoría",
    "Estado",
    "Intentos",
    "Research Status",
    "Research Sources",
    "Research Facts",
    "SEO Actual",
    "SEO Generado",
    "Patch Propuesto",
    "QA Status",
    "QA Notes",
    "Último Error",
    "Actualizado",
]


def _loads(raw, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _compact(value) -> str:
    if value in (None, "", {}, []):
        return ""
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return " | ".join(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def export_batch_staging(db: AgentDatabase, batch_id: int, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".tmp" + target.suffix)

    with db.connect() as con:
        batch = con.execute("SELECT id FROM seo_batches WHERE id=?", (int(batch_id),)).fetchone()
        if batch is None:
            raise KeyError(f"Lote SEO inexistente: {batch_id}")
        rows = con.execute(
            """
            WITH latest AS (SELECT MAX(id) AS snapshot_id FROM catalog_snapshots)
            SELECT
                i.id AS item_id, i.batch_id, i.sku, i.state, i.attempt_count,
                i.last_error, i.updated_at,
                p.name, p.brand, p.category, p.subcategory,
                r.status AS research_status, r.sources_json, r.facts_json,
                q.current_seo_json, q.generated_json, q.proposed_patch_json,
                q.qa_status, q.qa_notes_json
            FROM seo_batch_items i
            LEFT JOIN latest ON 1=1
            LEFT JOIN catalog_products p
              ON p.snapshot_id=latest.snapshot_id AND p.sku=i.sku
            LEFT JOIN seo_research r ON r.batch_item_id=i.id
            LEFT JOIN seo_proposals q ON q.batch_item_id=i.id
            WHERE i.batch_id=?
            ORDER BY i.position, i.id
            """,
            (int(batch_id),),
        ).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "SEO Batch"
    ws.append(HEADERS)
    for row in rows:
        sources = _loads(row["sources_json"], [])
        ws.append([
            int(row["batch_id"]),
            str(row["sku"]),
            row["name"] or "",
            row["brand"] or "",
            row["category"] or "",
            row["subcategory"] or "",
            str(row["state"]),
            int(row["attempt_count"]),
            row["research_status"] or "",
            _compact(sources),
            _compact(_loads(row["facts_json"], {})),
            _compact(_loads(row["current_seo_json"], {})),
            _compact(_loads(row["generated_json"], {})),
            _compact(_loads(row["proposed_patch_json"], {})),
            row["qa_status"] or "",
            _compact(_loads(row["qa_notes_json"], [])),
            row["last_error"] or "",
            row["updated_at"] or "",
        ])

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(tmp)
    os.replace(tmp, target)
    return target
