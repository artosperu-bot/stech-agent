from __future__ import annotations

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import AuditRepository, CatalogRepository, SessionRepository
from stech_agent.domain.models import ProductRecord


class QueuePlanner:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    def plan(self, command, context):
        return self.decisions.pop(0)


class FakeLiveExecutor:
    def __init__(self):
        self.updates = []
        self.reads = []
        self.restores = []
        self.current = {
            "PROD-TEST": {
                "stock": 1,
                "seo_title": "Producto Test STECH",
                "seo_description": "Descripción SEO completa",
                "seo_keywords": "producto test, stech, prueba",
                "seo_faqs": [
                    {"question": "¿Pregunta 1?", "answer": "Respuesta 1"},
                    {"question": "¿Pregunta 2?", "answer": "Respuesta 2"},
                    {"question": "¿Pregunta 3?", "answer": "Respuesta 3"},
                ],
            }
        }

    def execute_update(self, *, sku, expected_name, patch):
        before = {field: self.current[sku].get(field) for field in patch.values}
        self.current[sku].update(patch.values)
        self.updates.append((sku, dict(patch.values)))
        return {
            "status": "VERIFIED",
            "sku": sku,
            "name": expected_name or "",
            "before": before,
            "after": {**before, **patch.values},
            "changed_fields": list(patch.values),
        }

    def read_fields(self, *, sku, fields, expected_name=None):
        self.reads.append((sku, tuple(fields)))
        return {field: self.current[sku].get(field) for field in fields}

    def restore_if_unchanged(self, *, sku, expected_name, expected_current, restore_values):
        self.restores.append((sku, dict(expected_current), dict(restore_values)))
        actual = {field: self.current[sku].get(field) for field in expected_current}
        if actual != expected_current:
            return {"status": "CONFLICT", "sku": sku, "before": actual, "after": actual, "changed_fields": []}
        before = dict(actual)
        self.current[sku].update(restore_values)
        return {"status": "VERIFIED", "sku": sku, "before": before, "after": dict(restore_values), "changed_fields": list(restore_values)}

    def close(self):
        pass


def _decision(action="UPDATE_FIELDS", *, use_working_set=False, section="pricing", fields=None, values=None, name="producto test"):
    return PlannerDecision.from_dict({
        "action": action,
        "target": {
            "skus": [],
            "name": name,
            "brand": None,
            "category": None,
            "subcategory": None,
            "stock_lt": None,
            "stock_gt": None,
            "on_offer": None,
            "visible": None,
            "use_working_set": use_working_set,
            "allow_multiple_name_matches": False,
            "all_products": False,
        },
        "section": section,
        "fields": fields or ["stock"],
        "values": values or {"stock": 2},
        "mode": "READ" if action == "READ" else "PATCH",
        "research_required": False,
        "clarification_required": False,
        "clarification_question": None,
        "explanation": "test",
    })


def _db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    CatalogRepository(db).save_snapshot(CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Stock"),
        canonical_headers=("sku", "name", "stock"),
        products=(ProductRecord(sku="PROD-TEST", name="producto test", stock=1, source_order=1),),
        source_path="fixture.xlsx",
        checksum="fixture",
    ))
    return db


def test_verified_live_change_is_recorded_in_session_history(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, QueuePlanner([_decision()]), live_executor=live)

    result = runtime.execute("cambia stock a 2", session_id=session_id)
    history = runtime.session_history(session_id)

    assert result["status"] == "VERIFIED"
    assert len(history["changes"]) == 1
    assert history["changes"][0]["sku"] == "PROD-TEST"
    assert history["changes"][0]["before"] == {"stock": 1}
    assert history["changes"][0]["after"] == {"stock": 2}


def test_rollback_restores_latest_verified_changes_in_reverse_order(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, QueuePlanner([_decision()]), live_executor=live)
    runtime.execute("cambia stock a 2", session_id=session_id)

    result = runtime.rollback_session(session_id)

    assert result["status"] == "ROLLED_BACK"
    assert live.current["PROD-TEST"]["stock"] == 1
    assert result["restored"] == 1
    assert runtime.session_history(session_id)["changes"][0]["reverted"] is True


def test_rollback_does_not_overwrite_manual_change_after_agent_change(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    live = FakeLiveExecutor()
    runtime = AgentBrainRuntime(db, QueuePlanner([_decision()]), live_executor=live)
    runtime.execute("cambia stock a 2", session_id=session_id)
    live.current["PROD-TEST"]["stock"] = 9

    result = runtime.rollback_session(session_id)

    assert result["status"] == "PARTIAL"
    assert result["conflicts"] == 1
    assert live.current["PROD-TEST"]["stock"] == 9


def test_read_seo_returns_human_completeness_summary(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    SessionRepository(db).replace_working_set(session_id, "current", ["PROD-TEST"])
    seo_decision = _decision(
        "READ",
        use_working_set=True,
        section="seo",
        fields=["seo_title", "seo_description", "seo_keywords", "seo_faq"],
        values={},
        name=None,
    )
    runtime = AgentBrainRuntime(db, QueuePlanner([seo_decision]), live_executor=FakeLiveExecutor())

    result = runtime.execute("verifica si el mismo producto tiene todo el seo", session_id=session_id)

    assert result["status"] == "SEO_COMPLETE"
    assert "SEO completo" in result["message"]
    assert "FAQ 3/3" in result["message"]
    assert result["resolved_skus"] == ["PROD-TEST"]


def test_read_seo_reports_missing_parts(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    SessionRepository(db).replace_working_set(session_id, "current", ["PROD-TEST"])
    live = FakeLiveExecutor()
    live.current["PROD-TEST"]["seo_keywords"] = ""
    live.current["PROD-TEST"]["seo_faqs"][2]["answer"] = ""
    seo_decision = _decision(
        "READ",
        use_working_set=True,
        section="seo",
        fields=["seo_title", "seo_description", "seo_keywords", "seo_faq"],
        values={},
        name=None,
    )
    runtime = AgentBrainRuntime(db, QueuePlanner([seo_decision]), live_executor=live)

    result = runtime.execute("verifica seo", session_id=session_id)

    assert result["status"] == "SEO_INCOMPLETE"
    assert "SEO incompleto" in result["message"]
    assert "Keywords" in result["message"]
    assert "FAQ 2/3" in result["message"]
