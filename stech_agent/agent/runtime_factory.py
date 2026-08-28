from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from stech_agent.agent.live_executor import StechLiveExecutor
from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.config import AgentPaths
from stech_agent.db.connection import AgentDatabase
from stech_agent.research.runtime_worker import RuntimeEdgeChatGPTWorker
from stech_agent.seo.progressive import SeoProgressivePreparer
from stech_agent.seo.publisher import SeoPublisher


def build_live_runtime(
    db: AgentDatabase,
    planner: Any,
    *,
    work_dir: str | Path | None = None,
    research_worker_factory: Callable[[], Any] | None = None,
    live_executor: Any | None = None,
    log=None,
) -> AgentBrainRuntime:
    """Build the real chat runtime for immediate SEO completion.

    Browser ownership stays lazy. Constructing the runtime opens neither Chrome
    nor Edge. The same S-TECH live executor is shared by audit and publication;
    Edge/ChatGPT is created only when the first EMPTY/INCOMPLETE SKU needs
    research. The runtime worker validates Selenium before touching Edge.
    """
    logger = log or print
    paths = AgentPaths.default()
    paths.ensure()
    staging_dir = Path(work_dir) if work_dir is not None else paths.exports / "SEO Staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = paths.logs / "seo_research"
    raw_dir.mkdir(parents=True, exist_ok=True)

    factory = research_worker_factory or (
        lambda: RuntimeEdgeChatGPTWorker(
            raw_dir=raw_dir,
            log_callback=logger,
        )
    )
    shared_live = live_executor or StechLiveExecutor(log=logger)
    publisher = SeoPublisher(db, shared_live)
    preparer = SeoProgressivePreparer(
        db,
        research_worker_factory=factory,
        publisher=publisher,
        work_dir=staging_dir,
        log=logger,
    )
    return AgentBrainRuntime(
        db,
        planner,
        live_executor=shared_live,
        work_dir=staging_dir,
        seo_preparer=preparer,
    )
