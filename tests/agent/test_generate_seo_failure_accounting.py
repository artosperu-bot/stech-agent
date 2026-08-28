from __future__ import annotations

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord


class Planner:
    def plan(self, command, context):
        return PlannerDecision.from_dict({
            "action": "GENERATE_SEO",
            "target": {
                "skus": [], "name": None, "brand": "KINGSTON",
                "category": None, "subcategory": None,
                "stock_lt": None, "stock_gt": None,
                "on_offer": None, "visible": None,
                "use_working_set": False,
                "allow_multiple_name_matches": False,
                "all_products": False,
            },
            "section": "seo",
            "fields": ["seo_title", "seo_description", "seo_keywords", "seo_faq"],
            "values": {},
            "mode": "FILL_MISSING",
            "research_required": True,
            "clarification_required": False,
            "clarification_question": None,
            "explanation": "Completar SEO Kingston",
        })


class Live:
    def read_fields(self, *, sku, fields, expected_name=None):
        if sku == "K-COMPLETE":
            return {
                "seo_title": "T", "seo_description": "D", "seo_keywords": "K",
                "seo_faqs": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": "A3"},
                ],
            }
        return {"seo_title": "", "seo_description": "", "seo_keywords": "", "seo_faqs": []}

    def close(self):
        pass


class Preparer:
    def __init__(self):
        self.states = {
            "K-RESEARCH": "RESEARCH_ERROR",
            "K-QA": "QA_REVIEW",
        }

    def accept_audit(self, *, sku, status, values, session_id, scope):
        if status == "SEO_COMPLETE":
            return {"action": "SKIP_COMPLETE", "sku": sku, "state": "SEO_COMPLETE", "batch_id": 9}
        state = self.states[sku]
        return {"action": "REVIEW", "sku": sku, "state": state, "batch_id": 9}

    def finish(self):
        return {"batch_id": 9, "states": {"RESEARCH_ERROR": 1, "QA_REVIEW": 1}}

    def close(self):
        pass


def _db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Marca"),
        canonical_headers=("sku", "name", "brand"),
        products=(
            ProductRecord(sku="K-COMPLETE", name="Completo", brand="KINGSTON", source_order=1),
            ProductRecord(sku="K-RESEARCH", name="Research falla", brand="KINGSTON", source_order=2),
            ProductRecord(sku="K-QA", name="QA review", brand="KINGSTON", source_order=3),
        ),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def test_generate_seo_counts_research_and_qa_failures_separately(tmp_path):
    runtime = AgentBrainRuntime(_db(tmp_path), Planner(), live_executor=Live(), seo_preparer=Preparer())

    result = runtime.execute("Revisa y completa SEO Kingston", session_id=None)

    assert result["errors"] == 0
    assert result["workflow_errors"] == 2
    assert result["workflow_error_states"] == {"RESEARCH_ERROR": 1, "QA_REVIEW": 1}
    assert "2" in result["message"]
    assert "Research/QA/publicación" in result["message"]


def test_generate_seo_keeps_full_safe_brand_scope_in_working_set(tmp_path):
    runtime = AgentBrainRuntime(_db(tmp_path), Planner(), live_executor=Live(), seo_preparer=Preparer())

    result = runtime.execute("Revisa y completa SEO Kingston", session_id=None)

    assert result["working_set_skus"] == ["K-COMPLETE", "K-RESEARCH", "K-QA"]
    assert result["resolved_skus"] == ["K-COMPLETE", "K-RESEARCH", "K-QA"]
