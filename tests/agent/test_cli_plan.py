from __future__ import annotations

import json

from stech_agent import cli
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord


class FakePlanner:
    def plan(self, command, context):
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


def test_cli_plan_prints_resolved_dry_run_without_browser(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "agent.sqlite3"
    db = AgentDatabase(db_path)
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Marca", "Stock"),
        canonical_headers=("sku", "brand", "stock"),
        products=(
            ProductRecord(sku="A", brand="JBL", stock=8, source_order=1),
            ProductRecord(sku="B", brand="JBL", stock=2, source_order=2),
        ),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    monkeypatch.setattr(cli, "build_default_planner", lambda: FakePlanner())

    code = cli.main([
        "--db", str(db_path),
        "plan", "dime los JBL con stock mayor a 5",
    ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["resolved_skus"] == ["A"]
    assert payload["count"] == 1
