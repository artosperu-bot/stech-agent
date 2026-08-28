from __future__ import annotations

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository, SessionRepository
from stech_agent.domain.models import ProductRecord


class FakePlanner:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def plan(self, command, context):
        self.calls.append((command, context))
        return self.decision


def make_db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    snapshot = CatalogSnapshotData(
        raw_headers=("SKU", "Marca", "Stock"),
        canonical_headers=("sku", "brand", "stock"),
        products=(
            ProductRecord(sku="A", brand="JBL", stock=8, source_order=1),
            ProductRecord(sku="B", brand="JBL", stock=2, source_order=2),
            ProductRecord(sku="C", brand="EPSON", stock=9, source_order=3),
        ),
        source_path="fixture.xlsx",
        checksum="fixture",
    )
    CatalogRepository(db).save_snapshot(snapshot)
    return db


def read_decision():
    return PlannerDecision.from_dict({
        "action": "READ",
        "target": {
            "skus": [], "brand": "JBL", "category": None, "subcategory": None,
            "stock_lt": None, "stock_gt": 5, "on_offer": None, "visible": None,
            "use_working_set": False,
        },
        "section": None,
        "fields": [],
        "mode": "READ",
        "research_required": False,
        "clarification_required": False,
        "clarification_question": None,
        "explanation": "JBL con stock mayor a 5",
    })


def test_runtime_resolves_model_decision_against_latest_local_snapshot(tmp_path):
    db = make_db(tmp_path)
    planner = FakePlanner(read_decision())
    runtime = AgentBrainRuntime(db, planner)

    result = runtime.plan("dime los JBL con stock mayor a 5")

    assert result["dry_run"] is True
    assert result["resolved_skus"] == ["A"]
    assert result["count"] == 1
    assert planner.calls[0][1]["catalog_product_count"] == 3


def test_runtime_passes_working_set_context_and_resolves_de_esos(tmp_path):
    db = make_db(tmp_path)
    sessions = SessionRepository(db)
    session_id = sessions.create_session()
    sessions.replace_working_set(session_id, "current", ["A", "C"])
    payload = read_decision().to_dict()
    payload["target"]["brand"] = None
    payload["target"]["stock_gt"] = None
    payload["target"]["use_working_set"] = True
    planner = FakePlanner(PlannerDecision.from_dict(payload))

    result = AgentBrainRuntime(db, planner).plan("de esos muéstrame todos", session_id=session_id)

    assert result["resolved_skus"] == ["A", "C"]
    assert planner.calls[0][1]["working_set_available"] is True
    assert planner.calls[0][1]["working_set_count"] == 2
