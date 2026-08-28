from __future__ import annotations

from stech_agent.agent.runtime_factory import build_live_runtime
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate


class DummyPlanner:
    pass


def test_live_runtime_wires_progressive_seo_without_creating_research_worker(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    created = []

    runtime = build_live_runtime(
        db,
        DummyPlanner(),
        work_dir=tmp_path / "work",
        research_worker_factory=lambda: created.append("edge") or object(),
        log=lambda _msg: None,
    )

    assert runtime.seo_preparer is not None
    assert runtime.seo_preparer.batch_id is None
    assert created == []
    runtime.close()
    assert created == []
