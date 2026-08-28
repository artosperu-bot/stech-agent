from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import SessionRepository
from stech_agent.seo.batches import SeoBatchRepository


def _db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    return db


def test_batch_create_deduplicates_skus_and_starts_research_pending(tmp_path):
    db = _db(tmp_path)
    session_id = SessionRepository(db).create_session()
    repo = SeoBatchRepository(db)

    batch_id = repo.create(
        session_id=session_id,
        skus=["A", "B", "A"],
        scope={"brand": "JBL"},
        publish=True,
    )

    batch = repo.get(batch_id)
    items = repo.list_items(batch_id)
    assert batch["total_items"] == 2
    assert batch["publish_enabled"] is True
    assert batch["scope"] == {"brand": "JBL"}
    assert [(item.sku, item.state) for item in items] == [
        ("A", "RESEARCH_PENDING"),
        ("B", "RESEARCH_PENDING"),
    ]


def test_claim_is_exclusive_and_moves_different_skus(tmp_path):
    db = _db(tmp_path)
    repo = SeoBatchRepository(db)
    batch_id = repo.create(session_id=None, skus=["A", "B"], scope={}, publish=False)

    first = repo.claim(batch_id, {"RESEARCH_PENDING"}, "RESEARCHING", "worker-1", 60)
    second = repo.claim(batch_id, {"RESEARCH_PENDING"}, "RESEARCHING", "worker-2", 60)
    third = repo.claim(batch_id, {"RESEARCH_PENDING"}, "RESEARCHING", "worker-3", 60)

    assert first is not None and first.sku == "A"
    assert second is not None and second.sku == "B"
    assert third is None
    assert first.lease_owner == "worker-1"
    assert second.lease_owner == "worker-2"


def test_transition_requires_expected_state(tmp_path):
    db = _db(tmp_path)
    repo = SeoBatchRepository(db)
    batch_id = repo.create(session_id=None, skus=["A"], scope={}, publish=True)
    item = repo.claim(batch_id, {"RESEARCH_PENDING"}, "RESEARCHING", "w", 60)
    assert item is not None

    repo.transition(item.id, "RESEARCHING", "RESEARCHED")
    assert repo.get_item(item.id).state == "RESEARCHED"

    with pytest.raises(RuntimeError, match="estado"):
        repo.transition(item.id, "RESEARCHING", "SEO_PENDING")


def test_recover_expired_claims_returns_safe_states(tmp_path):
    db = _db(tmp_path)
    repo = SeoBatchRepository(db)
    batch_id = repo.create(session_id=None, skus=["A", "B"], scope={}, publish=True)
    a = repo.claim(batch_id, {"RESEARCH_PENDING"}, "RESEARCHING", "research", 60)
    b = repo.claim(batch_id, {"RESEARCH_PENDING"}, "PUBLISHING", "publisher", 60)
    assert a is not None and b is not None

    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction(immediate=True) as con:
        con.execute("UPDATE seo_batch_items SET lease_until=? WHERE id IN (?,?)", (expired, a.id, b.id))

    recovered = repo.recover_expired(batch_id)

    assert recovered == 2
    assert repo.get_item(a.id).state == "RESEARCH_PENDING"
    assert repo.get_item(b.id).state == "READY_REVERIFY"


def test_status_pause_and_resume(tmp_path):
    db = _db(tmp_path)
    repo = SeoBatchRepository(db)
    batch_id = repo.create(session_id=None, skus=["A", "B"], scope={"all": True}, publish=True)

    repo.pause(batch_id)
    assert repo.get(batch_id)["status"] == "PAUSED"
    assert repo.claim(batch_id, {"RESEARCH_PENDING"}, "RESEARCHING", "w", 60) is None

    repo.resume(batch_id)
    assert repo.get(batch_id)["status"] == "RUNNING"
    assert repo.status(batch_id)["states"] == {"RESEARCH_PENDING": 2}
