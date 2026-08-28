from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from stech_agent.db.connection import AgentDatabase
from stech_agent.seo.audit import SeoAuditRepository
from stech_agent.seo.batches import SeoBatchRepository
from stech_agent.seo.orchestrator import SeoBatchOrchestrator


class SeoProgressivePreparer:
    """Turns SEO audit findings into immediate research/QA work without publishing."""

    def __init__(
        self,
        db: AgentDatabase,
        *,
        research_worker_factory: Callable[[], Any],
        work_dir: str | Path,
        log=None,
    ):
        self.db = db
        self.research_worker_factory = research_worker_factory
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.log = log or (lambda _msg: None)
        self.audits = SeoAuditRepository(db)
        self.batches = SeoBatchRepository(db)
        self._batch_id: int | None = None
        self._research = None
        self._orchestrator: SeoBatchOrchestrator | None = None

    @property
    def batch_id(self) -> int | None:
        return self._batch_id

    def _ensure_orchestrator(self) -> SeoBatchOrchestrator:
        if self._orchestrator is None:
            self._research = self.research_worker_factory()
            self._orchestrator = SeoBatchOrchestrator(
                self.db,
                self._research,
                work_dir=self.work_dir,
                log=self.log,
            )
        return self._orchestrator

    def accept_audit(
        self,
        *,
        sku: str,
        status: str,
        values: dict[str, Any],
        session_id: int | None,
        scope: dict[str, Any],
    ) -> dict[str, Any]:
        sku = str(sku).strip()
        self.audits.record(sku, status, dict(values or {}))

        if status == "SEO_COMPLETE":
            self.log(f"[SEO] {sku}: completo; no requiere Research.")
            return {"action": "SKIP_COMPLETE", "sku": sku, "state": "SEO_COMPLETE", "batch_id": self._batch_id}
        if status not in {"SEO_EMPTY", "SEO_INCOMPLETE"}:
            return {"action": "SKIP_UNSUPPORTED", "sku": sku, "state": status, "batch_id": self._batch_id}

        if self._batch_id is None:
            self._batch_id = self.batches.create(
                session_id=session_id,
                skus=[sku],
                scope=dict(scope or {}),
                publish=False,
            )
        else:
            self.batches.append_sku(self._batch_id, sku)

        orchestrator = self._ensure_orchestrator()
        orchestrator.run(self._batch_id)
        item = next(item for item in self.batches.list_items(self._batch_id) if item.sku == sku)
        action = "PREPARED" if item.state == "READY" else "REVIEW"
        self.log(f"[SEO] {sku}: auditoría {status} → preparación {item.state}")
        return {"action": action, "sku": sku, "state": item.state, "batch_id": self._batch_id}

    def finish(self) -> dict[str, Any]:
        batch_id = self._batch_id
        if batch_id is None:
            return {"batch_id": None, "status": "NOTHING_TO_PREPARE", "states": {}}
        status = self.batches.status(batch_id)
        self._batch_id = None
        return {"batch_id": batch_id, "status": status["status"], "states": status["states"]}

    def close(self) -> None:
        if self._research is not None and hasattr(self._research, "close"):
            self._research.close()
        self._research = None
        self._orchestrator = None
