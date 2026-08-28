from __future__ import annotations

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.stech.import_certification import mark_prod_test_certified


class DummyPlanner:
    pass


class FakeLiveExecutor:
    def __init__(self):
        self.calls = []

    def create_product(self, **kwargs):
        self.calls.append(kwargs)
        values = kwargs["values"]
        return {
            "status": "VERIFIED",
            "created": True,
            "sku": values["sku"],
            "name": values["name"],
            "message": f"Creé {values['name']} ({values['sku']}) y verifiqué el alta en S-TECH.",
        }


def test_runtime_blocks_create_before_opening_live_executor_when_import_not_certified(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, DummyPlanner(), live_executor=live, work_dir=tmp_path)

    result = runtime.create_product({"sku": "NEW-1", "name": "Nuevo"}, session_id=1)

    assert result["status"] == "IMPORT_NOT_CERTIFIED"
    assert result["created"] is False
    assert live.calls == []
    assert "certific" in result["message"].lower()


def test_runtime_delegates_certified_create_to_live_executor(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    mark_prod_test_certified(
        db, sku="PROD-TEST", unrelated_changes=0, restored=True, operator_confirmed=True,
    )
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, DummyPlanner(), live_executor=live, work_dir=tmp_path)
    values = {"sku": "NEW-1", "name": "Nuevo"}

    result = runtime.create_product(values, session_id=7)

    assert result["status"] == "VERIFIED"
    assert result["sku"] == "NEW-1"
    assert live.calls[0]["values"] == values
    assert live.calls[0]["session_id"] == 7
