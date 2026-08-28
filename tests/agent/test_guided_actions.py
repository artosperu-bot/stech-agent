from __future__ import annotations

from decimal import Decimal

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository, SessionRepository
from stech_agent.domain.models import ProductRecord


class NoPlanner:
    def plan(self, command, context):
        raise AssertionError("guided mode must not call the model")


class FakeLiveExecutor:
    def __init__(self):
        self.current = {
            "PROD-TEST": {
                "stock": 2,
                "price": "1.00",
                "name": "producto test",
                "description": "",
                "seo_title": "Producto Test SEO",
                "seo_description": "Descripción SEO",
                "seo_keywords": "producto test, prueba",
                "seo_faqs": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": "A3"},
                ],
            }
        }
        self.calls = []

    def execute_update(self, *, sku, expected_name, patch):
        before = {field: self.current[sku].get(field) for field in patch.values}
        self.current[sku].update(patch.values)
        self.calls.append((sku, dict(patch.values)))
        return {
            "status": "VERIFIED",
            "sku": sku,
            "name": expected_name or "",
            "before": before,
            "after": {**before, **patch.values},
            "changed_fields": list(patch.values),
        }

    def read_fields(self, *, sku, fields, expected_name=None):
        result = {}
        for field in fields:
            if field == "seo_faq":
                result["seo_faqs"] = self.current[sku]["seo_faqs"]
            else:
                result[field] = self.current[sku].get(field)
        return result

    def close(self):
        pass


def _db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Stock", "Precio"),
        canonical_headers=("sku", "name", "stock", "price"),
        products=(ProductRecord(sku="PROD-TEST", name="producto test", stock=2, source_order=1),),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def test_guided_update_bypasses_model_and_saves_one_validated_patch(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, NoPlanner(), live_executor=live)

    result = runtime.execute_guided_update(
        session_id=session_id,
        sku="PROD-TEST",
        section="pricing",
        values={"stock": 3, "price": "1.50"},
    )

    assert result["status"] == "VERIFIED"
    assert live.calls == [("PROD-TEST", {"stock": 3, "price": Decimal("1.50")})]
    assert "Cambios guardados y verificados" in result["message"]
    assert runtime.session_history(session_id)["count"] == 1


def test_guided_update_rejects_field_outside_selected_section_before_live_call(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, NoPlanner(), live_executor=live)

    result = runtime.execute_guided_update(
        session_id=session_id,
        sku="PROD-TEST",
        section="pricing",
        values={"name": "otro nombre"},
    )

    assert result["status"] == "BLOCKED"
    assert live.calls == []


def test_guided_seo_verification_bypasses_model(tmp_path):
    db = _db(tmp_path)
    runtime = AgentBrainRuntime(db, NoPlanner(), live_executor=FakeLiveExecutor())

    result = runtime.verify_seo_sku("PROD-TEST")

    assert result["status"] == "SEO_COMPLETE"
    assert "SEO completo" in result["message"]
