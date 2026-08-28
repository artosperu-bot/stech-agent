from __future__ import annotations

from pathlib import Path

from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord
from stech_agent.research.edge_chatgpt import ResearchSeoResult
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
    def __init__(self, events):
        self.events = events
        self.calls = []
    def generate(self, product):
        sku = product["sku"]
        self.calls.append(sku)
        self.events.append((sku, "research"))
        return ResearchSeoResult(
            payload=_generated(product["name"]), raw_text="{}", raw_path=Path(f"{sku}.json"),
            prompt_id="SEO_PRODUCTO_STECH_V1", prompt_version="1", prompt_hash="abc",
        )
    def close(self):
        pass


class FakePublisher:
    def __init__(self, db, events):
        self.repo = SeoBatchRepository(db)
        self.events = events
        self.calls = []
    def publish(self, item_id):
        item = self.repo.get_item(item_id)
        self.calls.append(item.sku)
        self.events.append((item.sku, "publish"))
        self.repo.set_state(item_id, "VERIFIED")
        return type("Result", (), {"status": "VERIFIED", "message": "ok"})()


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
        source_path="fixture.xlsx", checksum="fixture",
    ))
    return db


def _empty():
    return {"seo_title": "", "seo_description": "", "seo_keywords": "", "seo_faqs": []}


def test_missing_sku_is_researched_and_published_before_accept_audit_returns(tmp_path):
    db = _db(tmp_path)
    events = []
    research = FakeResearch(events)
    publisher = FakePublisher(db, events)
    preparer = SeoProgressivePreparer(
        db,
        research_worker_factory=lambda: research,
        publisher=publisher,
        work_dir=tmp_path,
    )

    result = preparer.accept_audit(
        sku="A", status="SEO_EMPTY", values=_empty(),
        session_id=None, scope={"brand": "JBL"},
    )

    assert result["action"] == "COMPLETED"
    assert result["state"] == "VERIFIED"
    assert events == [("A", "research"), ("A", "publish")]
    assert SeoBatchRepository(db).list_items(result["batch_id"])[0].state == "VERIFIED"


def test_each_missing_sku_finishes_before_next_one_and_previous_is_not_reprocessed(tmp_path):
    db = _db(tmp_path)
    events = []
    research = FakeResearch(events)
    publisher = FakePublisher(db, events)
    preparer = SeoProgressivePreparer(
        db,
        research_worker_factory=lambda: research,
        publisher=publisher,
        work_dir=tmp_path,
    )

    first = preparer.accept_audit(sku="A", status="SEO_EMPTY", values=_empty(), session_id=None, scope={})
    second = preparer.accept_audit(
        sku="B", status="SEO_INCOMPLETE",
        values={"seo_title": "Manual", "seo_description": "", "seo_keywords": "", "seo_faqs": []},
        session_id=None, scope={},
    )

    assert first["state"] == second["state"] == "VERIFIED"
    assert first["batch_id"] == second["batch_id"]
    assert events == [
        ("A", "research"), ("A", "publish"),
        ("B", "research"), ("B", "publish"),
    ]
    assert research.calls == ["A", "B"]
    assert publisher.calls == ["A", "B"]


def test_complete_sku_is_skipped_without_edge_or_publisher(tmp_path):
    db = _db(tmp_path)
    events = []
    preparer = SeoProgressivePreparer(
        db,
        research_worker_factory=lambda: FakeResearch(events),
        publisher=FakePublisher(db, events),
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
        session_id=None, scope={},
    )

    assert result["action"] == "SKIP_COMPLETE"
    assert events == []
    assert preparer.batch_id is None
