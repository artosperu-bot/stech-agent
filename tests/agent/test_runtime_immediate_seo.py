from __future__ import annotations

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate


class ImmediateRecorder:
    def __init__(self):
        self.calls = []
    def accept_audit(self, **kwargs):
        self.calls.append((kwargs["sku"], kwargs["status"]))
        if kwargs["status"] == "SEO_COMPLETE":
            return {"action": "SKIP_COMPLETE", "state": "SEO_COMPLETE", "batch_id": 9}
        return {"action": "COMPLETED", "state": "VERIFIED", "batch_id": 9}
    def finish(self):
        return {"batch_id": 9, "status": "COMPLETED", "states": {"VERIFIED": 2}}
    def close(self):
        pass


def test_bulk_audit_reports_immediate_completion_and_keeps_completed_skus_in_working_set(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    preparer = ImmediateRecorder()
    runtime = AgentBrainRuntime(db, planner=object(), seo_preparer=preparer)
    results = {
        "A": {"status": "SEO_EMPTY", "message": "A vacío", "seo": {"seo_title":"", "seo_description":"", "seo_keywords":"", "seo_faqs":[]}, "seo_checks": {}},
        "B": {"status": "SEO_INCOMPLETE", "message": "B parcial", "seo": {"seo_title":"Manual", "seo_description":"", "seo_keywords":"", "seo_faqs":[]}, "seo_checks": {}},
        "C": {"status": "SEO_COMPLETE", "message": "C completo", "seo": {"seo_title":"T"}, "seo_checks": {}},
    }
    runtime.verify_seo_sku = lambda sku: dict(results[sku], resolved_skus=[sku])

    output = runtime.verify_seo_skus(["A", "B", "C"], scope_label="JBL", session_id=None)

    assert output["completed_during_audit"] == 2
    assert output["completed_skus"] == ["A", "B"]
    assert output["preparation_batch_id"] == 9
    assert output["working_set_skus"] == ["C", "B", "A"] or set(output["working_set_skus"]) == {"A", "B", "C"}
    assert "Completé y verifiqué 2" in output["message"]
    assert "segundo plano" not in output["message"]


def test_single_empty_audit_returns_completed_status_when_immediate_flow_verified(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    preparer = ImmediateRecorder()
    runtime = AgentBrainRuntime(db, planner=object(), seo_preparer=preparer)

    result = {
        "status": "SEO_EMPTY",
        "executed": False,
        "message": "Producto A (A): SEO vacío.",
        "resolved_skus": ["A"],
        "seo": {"seo_title":"", "seo_description":"", "seo_keywords":"", "seo_faqs":[]},
        "seo_checks": {},
    }
    runtime._execute_seo_read = runtime._execute_seo_read
    # Exercise the shared per-SKU preparation hook through the public verifier path.
    runtime.verify_seo_sku = lambda sku: dict(result)
    output = runtime.verify_seo_skus(["A"], scope_label="Producto", session_id=None)

    assert output["completed_during_audit"] == 1
    assert output["working_set_skus"] == ["A"]
