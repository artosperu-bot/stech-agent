from __future__ import annotations

from pathlib import Path

from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord
from stech_agent.research.edge_chatgpt import ResearchSeoResult
from stech_agent.seo.audit import SeoAuditRepository
from stech_agent.seo.batches import SeoBatchRepository
from stech_agent.seo.orchestrator import SeoBatchOrchestrator


def _generated(name):
    return {
        "marca":"JBL", "modelo":name, "categoria":"Audio",
        "caracteristicas_confirmadas":"Bluetooth", "informacion_falta_validar":"",
        "publico_objetivo":"Audio portátil",
        "titulo_seo":f"{name} Parlante Bluetooth Portátil para Perú",
        "descripcion_seo":f"Compra {name}, parlante Bluetooth portátil con diseño práctico para música, viajes y uso diario. Revisa sus características confirmadas y disponibilidad en Perú.",
        "keywords_seo":f"{name}, parlante Bluetooth, audio portátil, comprar parlante, Perú",
        "faqs":[
            {"pregunta":"¿Cómo se conecta?","respuesta":"Mediante Bluetooth con equipos compatibles."},
            {"pregunta":"¿Para qué uso se recomienda?","respuesta":"Para música portátil y uso cotidiano."},
            {"pregunta":"¿Dónde revisar sus datos?","respuesta":"En la ficha técnica oficial del fabricante."},
        ],
        "datos_faltantes_para_mejorar_seo":"", "recomendacion_final":"Lista",
        "fuentes_tecnicas":["https://www.jbl.com/"], "observacion_seo":"",
    }


class FakeResearch:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.calls = []
    def generate(self, product):
        sku = product["sku"]
        self.calls.append(sku)
        if sku in self.fail:
            raise RuntimeError("fallo research")
        return ResearchSeoResult(
            payload=_generated(product["name"]), raw_text="{}",
            raw_path=Path(f"{sku}.json"), prompt_id="SEO_PRODUCTO_STECH_V1",
            prompt_version="1", prompt_hash="abc",
        )


class FakePublisher:
    def __init__(self, db):
        self.repo = SeoBatchRepository(db)
        self.calls = []
    def publish(self, item_id):
        item = self.repo.get_item(item_id)
        self.calls.append(item.sku)
        self.repo.set_state(item_id, "VERIFIED")
        return type("R", (), {"status":"VERIFIED", "message":"ok"})()


def _setup(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU","Nombre del producto","Marca"), canonical_headers=("sku","name","brand"),
        products=(
            ProductRecord(sku="A", name="Producto A", brand="JBL", source_order=1),
            ProductRecord(sku="B", name="Producto B", brand="JBL", source_order=2),
            ProductRecord(sku="C", name="Producto C", brand="JBL", source_order=3),
        ), source_path="fixture.xlsx", checksum="fixture",
    ))
    audits = SeoAuditRepository(db)
    audits.record("A", "SEO_EMPTY", {"seo_title":"", "seo_description":"", "seo_keywords":"", "seo_faqs":[]})
    audits.record("B", "SEO_INCOMPLETE", {"seo_title":"Manual", "seo_description":"", "seo_keywords":"", "seo_faqs":[]})
    audits.record("C", "SEO_COMPLETE", {"seo_title":"T", "seo_description":"D", "seo_keywords":"K", "seo_faqs":[{"question":"Q1","answer":"A1"},{"question":"Q2","answer":"A2"},{"question":"Q3","answer":"A3"}]})
    return db


def test_create_batch_uses_only_empty_and_incomplete_from_latest_audit(tmp_path):
    db = _setup(tmp_path)
    orch = SeoBatchOrchestrator(db, FakeResearch(), work_dir=tmp_path)
    created = orch.create_batch(session_id=None, skus=["A","B","C"], scope={"brand":"JBL"}, publish=False)
    assert created["selected"] == 2
    assert created["already_complete"] == 1
    assert [x.sku for x in SeoBatchRepository(db).list_items(created["batch_id"])] == ["A","B"]


def test_generate_only_runs_research_and_qa_to_ready_without_publisher(tmp_path):
    db = _setup(tmp_path)
    research = FakeResearch()
    publisher = FakePublisher(db)
    orch = SeoBatchOrchestrator(db, research, publisher=publisher, work_dir=tmp_path)
    batch_id = orch.create_batch(None, ["A","B","C"], {"brand":"JBL"}, publish=False)["batch_id"]

    result = orch.run(batch_id)

    assert research.calls == ["A", "B"]
    assert publisher.calls == []
    assert result["states"] == {"READY": 2}
    assert (tmp_path / f"seo_batch_{batch_id}.xlsx").exists()


def test_one_research_failure_does_not_stop_other_items(tmp_path):
    db = _setup(tmp_path)
    research = FakeResearch(fail={"B"})
    orch = SeoBatchOrchestrator(db, research, work_dir=tmp_path)
    batch_id = orch.create_batch(None, ["A","B"], {}, publish=False)["batch_id"]

    result = orch.run(batch_id)

    assert result["states"]["READY"] == 1
    assert result["states"]["RESEARCH_ERROR"] == 1


def test_publish_mode_uses_single_publisher_and_verified_items_are_not_reprocessed(tmp_path):
    db = _setup(tmp_path)
    research = FakeResearch()
    publisher = FakePublisher(db)
    orch = SeoBatchOrchestrator(db, research, publisher=publisher, work_dir=tmp_path)
    batch_id = orch.create_batch(None, ["A","B"], {}, publish=True)["batch_id"]

    first = orch.run(batch_id)
    second = orch.run(batch_id)

    assert first["states"] == {"VERIFIED": 2}
    assert second["states"] == {"VERIFIED": 2}
    assert publisher.calls == ["A", "B"]
    assert research.calls == ["A", "B"]
