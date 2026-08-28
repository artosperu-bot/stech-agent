from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import json

from stech_agent.db.connection import AgentDatabase
from stech_agent.db.repositories import CatalogRepository
from stech_agent.seo.audit import SeoAuditRepository
from stech_agent.seo.batches import SeoBatchRepository
from stech_agent.seo.qa import validate_proposal
from stech_agent.seo.staging import export_batch_staging


class SeoBatchOrchestrator:
    """Durable compatibility-first pipeline: Edge research -> QA -> READY -> S-TECH."""

    def __init__(
        self,
        db: AgentDatabase,
        research_worker: Any,
        *,
        publisher: Any | None = None,
        work_dir: str | Path | None = None,
        log=None,
    ):
        self.db = db
        self.research = research_worker
        self.publisher = publisher
        self.work_dir = Path(work_dir or ".")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.log = log or (lambda _msg: None)
        self.batches = SeoBatchRepository(db)
        self.audits = SeoAuditRepository(db)
        self.catalogs = CatalogRepository(db)

    def preflight(self, skus: Iterable[str]) -> dict[str, Any]:
        ordered = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
        selection = self.audits.select_for_completion(ordered)
        safe: list[str] = []
        blocked: list[str] = []
        for sku in selection["process_skus"]:
            product = self.catalogs.get_by_sku(sku)
            if product is None or product.ambiguous:
                blocked.append(sku)
            else:
                safe.append(sku)
        return {
            "total_scope": len(ordered),
            "selected": len(safe),
            "selected_skus": safe,
            "already_complete": len(selection["complete_skus"]),
            "complete_skus": selection["complete_skus"],
            "empty": len(selection["empty_skus"]),
            "incomplete": len(selection["incomplete_skus"]),
            "unaudited": len(selection["unaudited_skus"]),
            "unaudited_skus": selection["unaudited_skus"],
            "blocked_ambiguous": len(blocked),
            "blocked_skus": blocked,
        }

    def create_batch(
        self,
        session_id: int | None,
        skus: Iterable[str],
        scope: dict[str, Any],
        publish: bool,
    ) -> dict[str, Any]:
        preflight = self.preflight(skus)
        if preflight["unaudited"]:
            preview = ", ".join(preflight["unaudited_skus"][:10])
            raise RuntimeError(
                f"Falta auditoría SEO real para {preflight['unaudited']} producto(s) ({preview}). "
                "Audítalos antes de crear el lote."
            )
        if not preflight["selected_skus"]:
            return {**preflight, "batch_id": None, "status": "NOTHING_TO_DO"}
        batch_id = self.batches.create(
            session_id=session_id,
            skus=preflight["selected_skus"],
            scope=scope or {},
            publish=publish,
        )
        return {**preflight, "batch_id": batch_id, "status": "CREATED"}

    @staticmethod
    def _product_payload(product) -> dict[str, Any]:
        return {
            "sku": product.sku,
            "name": product.name,
            "source_brand": product.brand,
            "brand": product.brand,
            "category": product.category,
            "subcategory": product.subcategory,
            "description": product.description,
            "specs_main": product.main_specs,
            "specs_tech": product.technical_specs,
            "url": str(product.extra.get("url") or product.source.get("URL") or "") if product else "",
        }

    def _save_research(self, item_id: int, result: Any) -> None:
        payload = dict(result.payload)
        sources = list(payload.get("fuentes_tecnicas") or [])
        with self.db.transaction(immediate=True) as con:
            con.execute(
                """
                INSERT INTO seo_research(
                    batch_item_id,status,facts_json,sources_json,raw_text,raw_path,
                    prompt_id,prompt_version,prompt_hash,provider_id,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(batch_item_id) DO UPDATE SET
                    status=excluded.status,facts_json=excluded.facts_json,
                    sources_json=excluded.sources_json,raw_text=excluded.raw_text,
                    raw_path=excluded.raw_path,prompt_id=excluded.prompt_id,
                    prompt_version=excluded.prompt_version,prompt_hash=excluded.prompt_hash,
                    provider_id=excluded.provider_id,updated_at=CURRENT_TIMESTAMP
                """,
                (
                    int(item_id), "RESEARCHED",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(sources, ensure_ascii=False),
                    str(result.raw_text), str(result.raw_path),
                    str(result.prompt_id), str(result.prompt_version), str(result.prompt_hash),
                    str(getattr(result, "provider_id", "edge-chatgpt")),
                ),
            )

    def _load_generated(self, item_id: int) -> dict[str, Any]:
        with self.db.connect() as con:
            row = con.execute("SELECT facts_json FROM seo_research WHERE batch_item_id=?", (int(item_id),)).fetchone()
        if row is None:
            raise RuntimeError("Research faltante")
        value = json.loads(row["facts_json"] or "{}")
        if not isinstance(value, dict):
            raise RuntimeError("Research inválido")
        return value

    def _save_proposal(self, item_id: int, current: dict[str, Any], qa) -> None:
        generated = dict(qa.generated or self._load_generated(item_id))
        with self.db.transaction(immediate=True) as con:
            con.execute(
                """
                INSERT INTO seo_proposals(
                    batch_item_id,current_seo_json,generated_json,proposed_patch_json,
                    qa_status,qa_notes_json,updated_at
                ) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(batch_item_id) DO UPDATE SET
                    current_seo_json=excluded.current_seo_json,
                    generated_json=excluded.generated_json,
                    proposed_patch_json=excluded.proposed_patch_json,
                    qa_status=excluded.qa_status,qa_notes_json=excluded.qa_notes_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    int(item_id),
                    json.dumps(current, ensure_ascii=False, sort_keys=True),
                    json.dumps(generated, ensure_ascii=False, sort_keys=True),
                    json.dumps(qa.patch, ensure_ascii=False, sort_keys=True),
                    qa.status,
                    json.dumps(list(qa.notes), ensure_ascii=False),
                ),
            )

    def _run_research_one(self, batch_id: int) -> bool:
        item = self.batches.claim(batch_id, {"RESEARCH_PENDING"}, "RESEARCHING", "research-edge-1", 1800)
        if item is None:
            return False
        product = self.catalogs.get_by_sku(item.sku)
        if product is None or product.ambiguous:
            self.batches.set_state(item.id, "BLOCKED_AMBIGUOUS", error="SKU ausente o ambiguo en catálogo")
            return True
        try:
            result = self.research.generate(self._product_payload(product))
            self._save_research(item.id, result)
            self.batches.transition(item.id, "RESEARCHING", "RESEARCHED")
            self.batches.set_state(item.id, "QA_PENDING")
            self.log(f"[SEO] {item.sku}: research listo")
        except Exception as exc:
            self.batches.set_state(item.id, "RESEARCH_ERROR", error=f"{type(exc).__name__}: {exc}")
            self.log(f"[SEO] {item.sku}: research error: {exc}")
        return True

    def _run_qa_one(self, batch_id: int) -> bool:
        item = self.batches.claim(batch_id, {"QA_PENDING"}, "QA_RUNNING", "qa-1", 300)
        if item is None:
            return False
        audit = self.audits.get(item.sku)
        if audit is None:
            self.batches.set_state(item.id, "QA_REVIEW", error="Auditoría SEO actual no disponible")
            return True
        try:
            generated = self._load_generated(item.id)
            qa = validate_proposal(current=dict(audit["values"]), generated=generated)
            self._save_proposal(item.id, dict(audit["values"]), qa)
            if qa.status == "READY":
                self.batches.set_state(item.id, "READY")
            elif qa.status == "NOOP":
                self.batches.set_state(item.id, "SEO_COMPLETE")
            else:
                self.batches.set_state(item.id, "QA_REVIEW", error="; ".join(qa.notes))
            self.log(f"[SEO] {item.sku}: QA {qa.status}")
        except Exception as exc:
            self.batches.set_state(item.id, "QA_REVIEW", error=f"{type(exc).__name__}: {exc}")
        return True

    def _run_publish_one(self, batch_id: int) -> bool:
        batch = self.batches.get(batch_id)
        if not batch or not batch["publish_enabled"] or self.publisher is None:
            return False
        item = self.batches.claim(batch_id, {"READY", "READY_REVERIFY"}, "PUBLISHING", "publisher-stech-1", 900)
        if item is None:
            return False
        try:
            result = self.publisher.publish(item.id)
            self.log(f"[SEO] {item.sku}: publish {result.status}")
        except Exception as exc:
            self.batches.set_state(item.id, "PUBLISH_ERROR", error=f"{type(exc).__name__}: {exc}")
        return True

    def _finish_if_idle(self, batch_id: int) -> None:
        batch = self.batches.get(batch_id)
        if not batch:
            return
        states = self.batches.status(batch_id)["states"]
        active = {"RESEARCH_PENDING", "RESEARCHING", "RESEARCHED", "QA_PENDING", "QA_RUNNING", "PUBLISHING", "READY_REVERIFY"}
        if any(state in active for state in states):
            return
        if batch["publish_enabled"] and "READY" in states:
            return
        review_states = {"RESEARCH_ERROR", "QA_REVIEW", "PUBLISH_ERROR", "VERIFY_ERROR", "BLOCKED_AMBIGUOUS", "BLOCKED_UNSUPPORTED"}
        status = "COMPLETED_WITH_REVIEW" if any(state in review_states for state in states) else ("COMPLETED" if batch["publish_enabled"] else "PREPARED")
        with self.db.transaction(immediate=True) as con:
            con.execute(
                "UPDATE seo_batches SET status=?, completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, int(batch_id)),
            )

    def run(self, batch_id: int) -> dict[str, Any]:
        self.batches.recover_expired(batch_id)
        batch = self.batches.get(batch_id)
        if batch is None:
            raise KeyError(f"Lote SEO inexistente: {batch_id}")
        if batch["status"] in {"PAUSED", "CANCELLED"}:
            return self.batches.status(batch_id)
        if batch["status"] in {"PREPARED", "COMPLETED", "COMPLETED_WITH_REVIEW"}:
            return self.batches.status(batch_id)

        while True:
            progressed = False
            if self._run_research_one(batch_id):
                progressed = True
            if self._run_qa_one(batch_id):
                progressed = True
            if self._run_publish_one(batch_id):
                progressed = True
            if not progressed:
                break

        export_batch_staging(self.db, batch_id, self.work_dir / f"seo_batch_{batch_id}.xlsx")
        self._finish_if_idle(batch_id)
        return self.batches.status(batch_id)

    def enable_publish(self, batch_id: int) -> None:
        with self.db.transaction(immediate=True) as con:
            cur = con.execute(
                "UPDATE seo_batches SET publish_enabled=1,status='RUNNING',completed_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(batch_id),),
            )
            if cur.rowcount != 1:
                raise KeyError(f"Lote SEO inexistente: {batch_id}")

    def pause(self, batch_id: int) -> None:
        self.batches.pause(batch_id)

    def resume(self, batch_id: int) -> None:
        self.batches.resume(batch_id)

    def status(self, batch_id: int) -> dict[str, Any]:
        return self.batches.status(batch_id)
