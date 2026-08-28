from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.seo.audit import SeoAuditRepository


def test_audit_cache_persists_current_seo_and_selects_missing(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    repo = SeoAuditRepository(db)
    repo.record("A", "SEO_EMPTY", {"seo_title":"", "seo_description":"", "seo_keywords":"", "seo_faqs":[]})
    repo.record("B", "SEO_INCOMPLETE", {"seo_title":"Manual", "seo_description":"", "seo_keywords":"", "seo_faqs":[]})
    repo.record("C", "SEO_COMPLETE", {"seo_title":"T", "seo_description":"D", "seo_keywords":"K", "seo_faqs":[{"question":"Q1","answer":"A1"},{"question":"Q2","answer":"A2"},{"question":"Q3","answer":"A3"}]})

    assert repo.get("B")["values"]["seo_title"] == "Manual"
    selected = repo.select_for_completion(["C", "A", "B", "D"])
    assert selected["process_skus"] == ["A", "B"]
    assert selected["complete_skus"] == ["C"]
    assert selected["unaudited_skus"] == ["D"]
