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
        raise AssertionError("guided bulk mode must not call the model")


class FakeLiveExecutor:
    def __init__(self):
        self.current = {
            "A": {
                "stock": 1,
                "price": Decimal("10.00"),
                "seo_title": "A SEO",
                "seo_description": "Descripción A",
                "seo_keywords": "a, seo",
                "seo_faqs": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": "A3"},
                ],
            },
            "B": {
                "stock": 2,
                "price": Decimal("20.00"),
                "seo_title": "B SEO",
                "seo_description": "Descripción B",
                "seo_keywords": "",
                "seo_faqs": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": ""},
                ],
            },
            "C": {
                "stock": 3,
                "price": Decimal("30.00"),
                "seo_title": "C SEO",
                "seo_description": "Descripción C",
                "seo_keywords": "c, seo",
                "seo_faqs": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": "A3"},
                ],
            },
        }
        self.fail_update_for = set()
        self.fail_read_for = set()
        self.calls = []

    def execute_update(self, *, sku, expected_name, patch):
        if sku in self.fail_update_for:
            raise RuntimeError("fallo simulado")
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
        if sku in self.fail_read_for:
            raise RuntimeError("fallo de lectura simulado")
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
        raw_headers=("SKU", "Nombre del producto", "Marca", "Categoria", "Subcategoría", "Stock"),
        canonical_headers=("sku", "name", "brand", "category", "subcategory", "stock"),
        products=(
            ProductRecord(sku="A", name="Producto A", brand="JBL", category="Audio", subcategory="Parlantes", stock=1, source_order=1),
            ProductRecord(sku="B", name="Producto B", brand="JBL", category="Audio", subcategory="Audífonos", stock=2, source_order=2),
            ProductRecord(sku="C", name="Producto C", brand="EPSON", category="Impresión", subcategory="Impresoras", stock=3, source_order=3),
        ),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def test_bulk_guided_update_verifies_each_sku_and_records_each_change(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, NoPlanner(), live_executor=live)

    result = runtime.execute_guided_bulk_update(
        session_id=session_id,
        skus=("A", "B"),
        section="pricing",
        values={"stock": 7},
        scope_label="Marca: JBL",
    )

    assert result["status"] == "VERIFIED"
    assert result["success"] == 2
    assert result["failed"] == 0
    assert live.current["A"]["stock"] == 7
    assert live.current["B"]["stock"] == 7
    assert runtime.session_history(session_id)["count"] == 2


def test_bulk_guided_update_returns_partial_and_keeps_verified_successes(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    live = FakeLiveExecutor()
    live.fail_update_for.add("B")
    runtime = AgentBrainRuntime(db, NoPlanner(), live_executor=live)

    result = runtime.execute_guided_bulk_update(
        session_id=session_id,
        skus=("A", "B", "C"),
        section="pricing",
        values={"price": "99.90"},
        scope_label="Todos los productos",
    )

    assert result["status"] == "PARTIAL"
    assert result["success"] == 2
    assert result["failed"] == 1
    assert live.current["A"]["price"] == Decimal("99.90")
    assert live.current["B"]["price"] == Decimal("20.00")
    assert live.current["C"]["price"] == Decimal("99.90")
    assert runtime.session_history(session_id)["count"] == 2


def test_bulk_seo_verification_summarizes_complete_incomplete_and_errors(tmp_path):
    db = _db(tmp_path)
    live = FakeLiveExecutor()
    live.fail_read_for.add("C")
    runtime = AgentBrainRuntime(db, NoPlanner(), live_executor=live)

    result = runtime.verify_seo_skus(("A", "B", "C"), scope_label="Todos los productos")

    assert result["status"] == "PARTIAL"
    assert result["complete"] == 1
    assert result["incomplete"] == 1
    assert result["errors"] == 1
    assert "1 completo" in result["message"]
    assert "1 incompleto" in result["message"]
    assert "1 error" in result["message"]
    assert result["items"][0]["status"] == "SEO_COMPLETE"
    assert result["items"][1]["status"] == "SEO_INCOMPLETE"
    assert result["items"][2]["status"] == "ERROR"
