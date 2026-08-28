from __future__ import annotations

from pathlib import Path

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord
from stech_agent.research.edge_chatgpt import ResearchSeoResult
from stech_agent.seo.audit import SeoAuditRepository
from stech_agent.seo.batches import SeoBatchRepository
from stech_agent.seo.progressive import SeoProgressivePreparer


def _generated(name: str):
    return {
        "marca": "JBL",
        "modelo": name,
        "categoria": "Audio",
        "caracteristicas_confirmadas": "Bluetooth",
        "informacion_falta_validar": "",
        "publico_objetivo": "Audio portátil",
        "titulo_seo": f"{name} Parlante Bluetooth Portátil para Perú",
        "descripcion_seo": f"Compra {name}, parlante Bluetooth portátil para música, viajes y uso diario. Revisa sus características confirmadas y disponibilidad para compra en Perú.",
        "keywords_seo": f"{name}, parlante Bluetooth, audio portátil, comprar parlante, Perú",
        "faqs": [
            {"pregunta": "¿Cómo se conecta?", "respuesta": "Mediante Bluetooth con equipos compatibles."},
            {"pregunta": "¿Para qué uso se recomienda?", "respuesta": "Para música portátil y uso cotidiano."},
            {"pregunta": "¿Dónde validar sus datos?", "respuesta": "En la ficha técnica oficial del fabricante."},
        ],
        "datos_faltantes_para_mejorar_seo": "",
        "recomendacion_final": "Lista",
        "fuentes_tecnicas": ["https://www.jbl.com/"],
        "observacion_seo": "",
    }


class FakeResearch:
    def __init__(self):
        self.calls: list[str] = []

    def generate(self, product):
        sku = product["sku"]
        self.calls.append(sku)
        return ResearchSeoResult(
            payload=_generated(product["name"]),
            raw_text="{}",
            raw_path=Path(f"{sku}.json"),
            prompt_id="SEO_PRODUCTO_STECH_V1",
            prompt_version="1",
            prompt_hash="abc",
        )


def _db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Marca"),
        canonical_headers=("sku", "name", "brand"),
        products=(
            ProductRecord(sku="A", name="Producto A", brand="JBL", source_order=1),
            ProductRecord(sku="B", name="Producto B", brand="JBL", source_order=2),
            ProductRecord(sku="C", name="Producto C", brand="JBL", source_order=3),
        ),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def _empty():
    return {"seo_title": "", "seo_description": "", "seo_keywords": "", "seo_faqs": []}


def test_complete_audit_is_cached_without_starting_research(tmp_path):
    db = _db(tmp_path)
    created = []
    preparer = SeoProgressivePreparer(
        db,
        research_worker_factory=lambda: created.append(True) or FakeResearch(),
        work_dir=tmp_path,
    )
    complete = {
        "seo_title": "T", "seo_description": "D", "seo_keywords": "K",
        "seo_faqs": [
            {"question": "Q1", "answer": "A1"},
            {"question": "Q2", "answer": "A2"},
            {"question": "Q3", "answer": "A3"},
        ],
    }

    result = preparer.accept_audit(
        sku="C", status="SEO_COMPLETE", values=complete,
        session_id=None, scope={"brand": "JBL"},
    )

    assert result["action"] == "SKIP_COMPLETE"
    assert created == []
    assert preparer.batch_id is None
    assert SeoAuditRepository(db).get("C")["status"] == "SEO_COMPLETE"


def test_first_missing_product_is_researched_immediately_and_left_ready(tmp_path):
    db = _db(tmp_path)
    research = FakeResearch()
    preparer = SeoProgressivePreparer(db, research_worker_factory=lambda: research, work_dir=tmp_path)

    result = preparer.accept_audit(
        sku="A", status="SEO_EMPTY", values=_empty(),
        session_id=None, scope={"brand": "JBL"},
    )

    assert research.calls == ["A"]
    assert result["action"] == "PREPARED"
    assert result["state"] == "READY"
    assert preparer.batch_id is not None
    assert SeoBatchRepository(db).list_items(preparer.batch_id)[0].state == "READY"
    assert (tmp_path / f"seo_batch_{preparer.batch_id}.xlsx").exists()


def test_next_missing_product_joins_same_batch_without_reprocessing_previous(tmp_path):
    db = _db(tmp_path)
    research = FakeResearch()
    preparer = SeoProgressivePreparer(db, research_worker_factory=lambda: research, work_dir=tmp_path)

    preparer.accept_audit(sku="A", status="SEO_EMPTY", values=_empty(), session_id=None, scope={"brand": "JBL"})
    first_batch = preparer.batch_id
    preparer.accept_audit(
        sku="B", status="SEO_INCOMPLETE",
        values={"seo_title": "Manual", "seo_description": "", "seo_keywords": "", "seo_faqs": []},
        session_id=None, scope={"brand": "JBL"},
    )

    assert preparer.batch_id == first_batch
    assert research.calls == ["A", "B"]
    items = SeoBatchRepository(db).list_items(first_batch)
    assert [(item.sku, item.state) for item in items] == [("A", "READY"), ("B", "READY")]


def test_runtime_bulk_audit_feeds_preparer_after_each_sku(tmp_path):
    db = _db(tmp_path)

    class Recorder:
        def __init__(self): self.calls = []
        def accept_audit(self, **kwargs):
            self.calls.append((kwargs["sku"], kwargs["status"]))
            action = "PREPARED" if kwargs["status"] in {"SEO_EMPTY", "SEO_INCOMPLETE"} else "SKIP_COMPLETE"
            return {"action": action}
        def finish(self): return {"batch_id": None}

    recorder = Recorder()
    runtime = AgentBrainRuntime(db, planner=object(), seo_preparer=recorder)
    results = {
        "A": {"status": "SEO_EMPTY", "message": "empty", "seo": _empty(), "seo_checks": {}},
        "B": {"status": "SEO_INCOMPLETE", "message": "partial", "seo": {"seo_title": "Manual"}, "seo_checks": {}},
        "C": {"status": "SEO_COMPLETE", "message": "complete", "seo": {"seo_title": "T"}, "seo_checks": {}},
    }
    runtime.verify_seo_sku = lambda sku: dict(results[sku], resolved_skus=[sku])

    output = runtime.verify_seo_skus(["A", "B", "C"], scope_label="JBL", session_id=77)

    assert recorder.calls == [
        ("A", "SEO_EMPTY"),
        ("B", "SEO_INCOMPLETE"),
        ("C", "SEO_COMPLETE"),
    ]
    assert output["prepared_during_audit"] == 2
