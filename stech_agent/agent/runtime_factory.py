from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.config import AgentPaths
from stech_agent.db.connection import AgentDatabase
from stech_agent.research.edge_chatgpt import EdgeChatGPTWorker
from stech_agent.seo.progressive import SeoProgressivePreparer


def build_live_runtime(
    db: AgentDatabase,
    planner: Any,
    *,
    work_dir: str | Path | None = None,
    research_worker_factory: Callable[[], Any] | None = None,
    log=None,
) -> AgentBrainRuntime:
    """Build the real chat runtime with lazy progressive SEO preparation.

    Merely constructing the runtime never opens Edge. The Research worker is
    created only when the SEO audit finds the first EMPTY/INCOMPLETE SKU.
    """
    logger = log or print
    paths = AgentPaths.default()
    paths.ensure()
    staging_dir = Path(work_dir) if work_dir is not None else paths.exports / "SEO Staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = paths.logs / "seo_research"
    raw_dir.mkdir(parents=True, exist_ok=True)

    factory = research_worker_factory or (
        lambda: EdgeChatGPTWorker(
            raw_dir=raw_dir,
            log_callback=logger,
        )
    )
    preparer = SeoProgressivePreparer(
        db,
        research_worker_factory=factory,
        work_dir=staging_dir,
        log=logger,
    )
    return AgentBrainRuntime(
        db,
        planner,
        work_dir=staging_dir,
        seo_preparer=preparer,
    )
