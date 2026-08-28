from __future__ import annotations

from stech_agent.agent.resolver import resolve_decision
from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord


class GenerateSeoJblPlanner:
    def plan(self, command, context):
        return PlannerDecision.from_dict({
            "action": "GENERATE_SEO",
            "target": {
                "skus": [],
                "name": None,
                "brand": "JBL",
                "category": None,
                "subcategory": None,
                "stock_lt": None,
                "stock_gt": None,
                "on_offer": None,
                "visible": None,
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
            "explanation": "Revisar y completar el SEO de todos los JBL.",
        })


class FakeSeoLive:
    def __init__(self):
        self.read_calls = []

    def read_fields(self, *, sku, fields, expected_name=None):
        self.read_calls.append(sku)
        return {
            "seo_title": "",
            "seo_description": "",
            "seo_keywords": "",
            "seo_faqs": [],
        }

    def close(self):
        pass


class FakeImmediatePreparer:
    def __init__(self):
        self.calls = []

    def accept_audit(self, *, sku, status, values, session_id, scope):
        self.calls.append((sku, status, session_id, scope))
        return {
            "action": "COMPLETED",
            "batch_id": 77,
            "state": "VERIFIED",
            "sku": sku,
        }

    def finish(self):
        return {"batch_id": 77}

    def close(self):
        pass


def _decision():
    return GenerateSeoJblPlanner().plan("x", {})


def _products():
    return [
        ProductRecord(sku="JBL-SAFE", name="JBL Seguro", brand="JBL", source_order=1),
        ProductRecord(
            sku="JBL-CONFLICT",
            name="JBL Conflictivo",
            brand="JBL",
            source_order=2,
            conflict_fields=frozenset({"stock"}),
        ),
        ProductRecord(sku="EPSON-1", name="Epson", brand="EPSON", source_order=3),
    ]


def _db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Marca", "Stock"),
        canonical_headers=("sku", "name", "brand", "stock"),
        products=tuple(_products()),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def test_generate_seo_brand_scope_excludes_only_ambiguous_skus():
    resolved = resolve_decision(_decision(), _products())

    assert resolved.skus == ("JBL-SAFE",)
    assert resolved.blocked_skus == ("JBL-CONFLICT",)


def test_natural_generate_seo_runs_safe_jbl_and_reports_conflict(tmp_path):
    live = FakeSeoLive()
    preparer = FakeImmediatePreparer()
    runtime = AgentBrainRuntime(
        _db(tmp_path),
        GenerateSeoJblPlanner(),
        live_executor=live,
        seo_preparer=preparer,
    )

    result = runtime.execute(
        "Revisa el SEO de todos los productos de la marca JBL y completa lo que falte",
        session_id=None,
    )

    assert result["status"] == "SEO_AUDIT"
    assert live.read_calls == ["JBL-SAFE"]
    assert [call[0] for call in preparer.calls] == ["JBL-SAFE"]
    assert result["completed_during_audit"] == 1
    assert result["blocked_skus"] == ["JBL-CONFLICT"]
    assert result["blocked_ambiguous"] == 1
    assert "1" in result["message"]
    assert "conflict" in result["message"].casefold()
