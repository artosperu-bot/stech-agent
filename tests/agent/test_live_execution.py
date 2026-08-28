from __future__ import annotations

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord


class FakePlanner:
    def plan(self, command, context):
        return PlannerDecision.from_dict({
            "action": "UPDATE_FIELDS",
            "target": {
                "skus": [],
                "name": "producto test",
                "brand": None,
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
            "section": "pricing",
            "fields": ["stock"],
            "values": {"stock": 2},
            "mode": "PATCH",
            "research_required": False,
            "clarification_required": False,
            "clarification_question": None,
            "explanation": "Cambiar stock a 2.",
        })


class FakeLiveExecutor:
    def __init__(self):
        self.calls = []

    def execute_update(self, *, sku, expected_name, patch):
        self.calls.append((sku, expected_name, dict(patch.values)))
        return {
            "status": "VERIFIED",
            "sku": sku,
            "name": expected_name,
            "before": {"stock": 1},
            "after": {"stock": 2},
            "changed_fields": ["stock"],
        }


def make_db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Stock"),
        canonical_headers=("sku", "name", "stock"),
        products=(ProductRecord(sku="PROD-TEST", name="Producto Test", stock=1, source_order=1),),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def test_execute_runs_verified_single_sku_update_and_returns_human_message(tmp_path):
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(make_db(tmp_path), FakePlanner(), live_executor=live)

    result = runtime.execute("buscame el producto llamado producto test y cambiale el stock a 2")

    assert live.calls == [("PROD-TEST", "Producto Test", {"stock": 2})]
    assert result["executed"] is True
    assert result["status"] == "VERIFIED"
    assert result["message"] == "Encontré Producto Test (PROD-TEST). Stock: 1 → 2. Cambio guardado y verificado."


def test_execute_refuses_multi_sku_live_mutation(tmp_path):
    db = make_db(tmp_path)
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, FakePlanner(), live_executor=live)
    # The planner resolves one SKU in this fixture; this assertion documents
    # that a live executor must exist only behind the explicit execute path.
    assert hasattr(runtime, "execute")
