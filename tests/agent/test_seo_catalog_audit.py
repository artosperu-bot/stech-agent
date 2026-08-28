from __future__ import annotations

from stech_agent.agent.memory_policy import working_set_skus_for_result
from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord


class SeoAllPlanner:
    def plan(self, command, context):
        return PlannerDecision.from_dict({
            "action": "READ",
            "target": {
                "skus": [],
                "name": None,
                "brand": None,
                "category": None,
                "subcategory": None,
                "stock_lt": None,
                "stock_gt": None,
                "on_offer": None,
                "visible": None,
                "use_working_set": False,
                "allow_multiple_name_matches": False,
                "all_products": True,
            },
            "section": "seo",
            "fields": ["seo_title", "seo_description", "seo_keywords", "seo_faq"],
            "values": {},
            "mode": "READ",
            "research_required": False,
            "clarification_required": False,
            "clarification_question": None,
            "explanation": "Revisar qué productos tienen SEO.",
        })


class FakeSeoLiveExecutor:
    def __init__(self):
        self.values = {
            "A": {
                "seo_title": "Título A",
                "seo_description": "Descripción A",
                "seo_keywords": "a, producto",
                "seo_faqs": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": "A3"},
                ],
            },
            "B": {
                "seo_title": "Título B",
                "seo_description": "",
                "seo_keywords": "",
                "seo_faqs": [],
            },
            "C": {
                "seo_title": "",
                "seo_description": "",
                "seo_keywords": "",
                "seo_faqs": [],
            },
        }
        self.read_calls = []

    def read_fields(self, *, sku, fields, expected_name=None):
        self.read_calls.append(sku)
        return dict(self.values[sku])

    def close(self):
        pass


def make_db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto"),
        canonical_headers=("sku", "name"),
        products=(
            ProductRecord(sku="A", name="Producto A", source_order=1),
            ProductRecord(sku="B", name="Producto B", source_order=2),
            ProductRecord(sku="C", name="Producto C", source_order=3),
        ),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def test_seo_summary_distinguishes_empty_from_partial():
    status, message, checks = AgentBrainRuntime._seo_summary(
        "Producto vacío",
        "EMPTY",
        {"seo_title": "", "seo_description": "", "seo_keywords": "", "seo_faqs": []},
    )

    assert status == "SEO_EMPTY"
    assert "SEO vacío" in message
    assert checks["has_any_seo"] is False


def test_execute_bulk_seo_read_audits_all_products_instead_of_blocking(tmp_path):
    live = FakeSeoLiveExecutor()
    runtime = AgentBrainRuntime(make_db(tmp_path), SeoAllPlanner(), live_executor=live)

    result = runtime.execute("quiero que te fijes que productos tienen seo")

    assert live.read_calls == ["A", "B", "C"]
    assert result["status"] == "SEO_AUDIT"
    assert result["complete"] == 1
    assert result["incomplete"] == 1
    assert result["empty"] == 1
    assert result["errors"] == 0
    assert result["has_seo_skus"] == ["A", "B"]
    assert result["empty_skus"] == ["C"]
    assert result["working_set_skus"] == ["A", "B"]
    assert "1 completo" in result["message"]
    assert "1 parcial" in result["message"]
    assert "1 sin SEO" in result["message"]


def test_blocked_or_error_results_never_replace_working_set():
    assert working_set_skus_for_result({"status": "BLOCKED", "resolved_skus": ["A", "B"]}) is None
    assert working_set_skus_for_result({"status": "ERROR", "resolved_skus": ["A", "B"]}) is None
    assert working_set_skus_for_result({"status": "NEEDS_CLARIFICATION", "resolved_skus": ["A"]}) is None


def test_explicit_working_set_from_successful_result_has_priority():
    result = {
        "status": "SEO_AUDIT",
        "resolved_skus": ["A", "B", "C"],
        "working_set_skus": ["A", "B"],
    }
    assert working_set_skus_for_result(result) == ["A", "B"]
