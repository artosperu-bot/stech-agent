from __future__ import annotations

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord


class FakePlanner:
    def __init__(self, payload):
        self.decision = PlannerDecision.from_dict(payload)

    def plan(self, command, context):
        return self.decision


def make_db(tmp_path, products):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Stock"),
        canonical_headers=("sku", "name", "stock"),
        products=tuple(products),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def update_payload(*, name="Producto Test", stock_value=2):
    return {
        "action": "UPDATE_FIELDS",
        "target": {
            "skus": [], "name": name, "brand": None, "category": None,
            "subcategory": None, "stock_lt": None, "stock_gt": None,
            "on_offer": None, "visible": None, "use_working_set": False,
            "allow_multiple_name_matches": False, "all_products": False,
        },
        "section": "pricing",
        "fields": ["stock"],
        "values": {"stock": stock_value},
        "mode": "PATCH",
        "research_required": False,
        "clarification_required": False,
        "clarification_question": None,
        "explanation": "Cambiar stock.",
    }


def test_runtime_converts_invalid_field_value_into_safe_clarification(tmp_path):
    db = make_db(tmp_path, [ProductRecord(sku="PROD-TEST", name="Producto Test", stock=1)])
    runtime = AgentBrainRuntime(db, FakePlanner(update_payload(stock_value="dos")))

    result = runtime.plan("cambia stock a dos")

    assert result["dry_run"] is True
    assert result["decision"]["clarification_required"] is True
    assert result["resolved_skus"] == []


def test_mutation_with_no_catalog_matches_returns_clarification(tmp_path):
    db = make_db(tmp_path, [ProductRecord(sku="PROD-TEST", name="Producto Test", stock=1)])
    runtime = AgentBrainRuntime(db, FakePlanner(update_payload(name="No Existe")))

    result = runtime.plan("cambia No Existe")

    assert result["decision"]["clarification_required"] is True
    assert result["count"] == 0


def test_mutation_blocks_catalog_record_with_duplicate_conflicts(tmp_path):
    product = ProductRecord(
        sku="DUP-1",
        name="Producto Duplicado",
        stock=1,
        conflict_fields=frozenset({"stock"}),
    )
    db = make_db(tmp_path, [product])
    runtime = AgentBrainRuntime(db, FakePlanner(update_payload(name="Producto Duplicado")))

    result = runtime.plan("cambia el stock del producto duplicado a 2")

    assert result["decision"]["clarification_required"] is True
    assert result["candidate_skus"] == ["DUP-1"]
