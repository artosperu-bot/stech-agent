from __future__ import annotations

import json

from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import AuditRepository, CatalogRepository, SessionRepository
from stech_agent.domain.models import ProductRecord
from stech_agent.seo.audit import SeoAuditRepository
from stech_agent.seo.batches import SeoBatchRepository
from stech_agent.seo.publisher import SeoPublisher


def _generated():
    return {
        "marca":"JBL", "modelo":"Charge 6", "categoria":"Audio",
        "caracteristicas_confirmadas":"Bluetooth", "informacion_falta_validar":"",
        "publico_objetivo":"Audio portátil",
        "titulo_seo":"JBL Charge 6 Parlante Bluetooth Portátil Perú",
        "descripcion_seo":"Compra JBL Charge 6, parlante Bluetooth portátil con diseño resistente y gran autonomía. Ideal para música en casa, viajes y uso diario en Perú.",
        "keywords_seo":"JBL Charge 6, parlante Bluetooth, JBL Perú, parlante portátil, comprar JBL",
        "faqs":[
            {"pregunta":"¿Qué resistencia tiene?","respuesta":"Protección confirmada en ficha técnica."},
            {"pregunta":"¿Cómo se conecta?","respuesta":"Mediante Bluetooth con equipos compatibles."},
            {"pregunta":"¿Para quién se recomienda?","respuesta":"Para usuarios que buscan audio portátil."},
        ],
        "datos_faltantes_para_mejorar_seo":"", "recomendacion_final":"Lista",
        "fuentes_tecnicas":["https://www.jbl.com/"], "observacion_seo":"",
    }


class FakeLive:
    def __init__(self, current):
        self.current = dict(current)
        self.updates = []
        self.read_count = 0
        self.update_status = "VERIFIED"

    def read_fields(self, *, sku, fields, expected_name=None):
        self.read_count += 1
        return dict(self.current)

    def execute_update(self, *, sku, expected_name, patch):
        self.updates.append(dict(patch.values))
        for key, value in patch.values.items():
            if key == "seo_faq":
                self.current["seo_faqs"] = list(value)
            else:
                self.current[key] = value
        return {
            "status": self.update_status,
            "sku": sku,
            "name": expected_name or "",
            "before": {},
            "after": dict(patch.values),
            "changed_fields": list(patch.values),
        }


def _setup(tmp_path, *, with_session: bool = False):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU","Nombre del producto"), canonical_headers=("sku","name"),
        products=(ProductRecord(sku="A", name="Producto A", source_order=1),),
        source_path="fixture.xlsx", checksum="fixture",
    ))
    session_id = SessionRepository(db).create_session() if with_session else None
    repo = SeoBatchRepository(db)
    batch = repo.create(session_id, ["A"], {}, True)
    item = repo.list_items(batch)[0]
    with db.transaction(immediate=True) as con:
        con.execute(
            "INSERT INTO seo_proposals(batch_item_id,current_seo_json,generated_json,proposed_patch_json,qa_status,qa_notes_json) VALUES (?,?,?,?,?,?)",
            (item.id, json.dumps({}), json.dumps(_generated()), json.dumps({"seo_title":"stale"}), "READY", json.dumps([])),
        )
        con.execute("UPDATE seo_batch_items SET state='READY' WHERE id=?", (item.id,))
    return db, item, session_id


def test_publisher_re_reads_and_preserves_manual_title_added_after_staging(tmp_path):
    db, item, _ = _setup(tmp_path)
    live = FakeLive({"seo_title":"Título agregado manualmente", "seo_description":"", "seo_keywords":"", "seo_faqs":[]})

    result = SeoPublisher(db, live).publish(item.id)

    assert result.status == "VERIFIED"
    assert live.read_count >= 2
    assert live.updates
    assert "seo_title" not in live.updates[0]
    assert live.updates[0]["seo_description"] == _generated()["descripcion_seo"]
    assert live.current["seo_title"] == "Título agregado manualmente"
    cached = SeoAuditRepository(db).get("A")
    assert cached is not None
    assert cached["status"] == "SEO_COMPLETE"
    assert cached["values"] == live.current


def test_publisher_noops_if_product_became_complete_before_publish(tmp_path):
    db, item, _ = _setup(tmp_path)
    live = FakeLive({
        "seo_title":"Manual", "seo_description":"Manual desc", "seo_keywords":"manual",
        "seo_faqs":[{"question":"Q1","answer":"A1"},{"question":"Q2","answer":"A2"},{"question":"Q3","answer":"A3"}],
    })

    result = SeoPublisher(db, live).publish(item.id)

    assert result.status == "NOOP"
    assert live.updates == []
    assert SeoBatchRepository(db).get_item(item.id).state == "SEO_COMPLETE"
    cached = SeoAuditRepository(db).get("A")
    assert cached is not None
    assert cached["status"] == "SEO_COMPLETE"


def test_publisher_marks_verify_error_when_live_writer_does_not_verify(tmp_path):
    db, item, _ = _setup(tmp_path)
    live = FakeLive({"seo_title":"", "seo_description":"", "seo_keywords":"", "seo_faqs":[]})
    live.update_status = "REVIEW"

    result = SeoPublisher(db, live).publish(item.id)

    assert result.status == "VERIFY_ERROR"
    assert SeoBatchRepository(db).get_item(item.id).state == "VERIFY_ERROR"
    with db.connect() as con:
        attempt = con.execute("SELECT status FROM seo_publish_attempts WHERE batch_item_id=? ORDER BY id DESC", (item.id,)).fetchone()
    assert attempt["status"] == "VERIFY_ERROR"


def test_verified_publish_records_session_change_with_rollback_compatible_faq_keys(tmp_path):
    db, item, session_id = _setup(tmp_path, with_session=True)
    live = FakeLive({"seo_title":"Manual", "seo_description":"", "seo_keywords":"", "seo_faqs":[]})

    result = SeoPublisher(db, live).publish(item.id)

    assert result.status == "VERIFIED"
    events = AuditRepository(db).list_session(session_id, event_types=("LIVE_UPDATE_VERIFIED",))
    assert len(events) == 1
    event = events[0]
    assert event["sku"] == "A"
    payload = event["payload"]
    assert payload["command"] == "AUTO_SEO_FILL_MISSING"
    assert payload["name"] == "Producto A"
    assert "seo_title" not in payload["fields"]
    assert set(payload["fields"]) == {"seo_description", "seo_keywords", "seo_faq"}
    assert payload["before"]["seo_faq"] == []
    assert payload["after"]["seo_faq"] == live.current["seo_faqs"]


def test_noop_publish_does_not_create_session_change_event(tmp_path):
    db, item, session_id = _setup(tmp_path, with_session=True)
    live = FakeLive({
        "seo_title":"Manual", "seo_description":"Manual desc", "seo_keywords":"manual",
        "seo_faqs":[{"question":"Q1","answer":"A1"},{"question":"Q2","answer":"A2"},{"question":"Q3","answer":"A3"}],
    })

    assert SeoPublisher(db, live).publish(item.id).status == "NOOP"
    assert AuditRepository(db).list_session(session_id, event_types=("LIVE_UPDATE_VERIFIED",)) == []
