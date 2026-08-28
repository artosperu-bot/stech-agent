from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import queue
import threading
import time

from stech_agent.db.connection import AgentDatabase
from stech_agent.seo.audit import SeoAuditRepository
from stech_agent.seo.batches import SeoBatchRepository
from stech_agent.seo.orchestrator import SeoBatchOrchestrator


_ACTIVE_STATES = {
    "RESEARCH_PENDING",
    "RESEARCHING",
    "RESEARCHED",
    "QA_PENDING",
    "QA_RUNNING",
    "PUBLISHING",
    "READY_REVERIFY",
}


class SeoProgressivePreparer:
    """Handle SEO findings as soon as each SKU is audited.

    When ``publisher`` is provided, EMPTY/INCOMPLETE products are completed
    synchronously: Edge research -> QA -> S-TECH publish/verify, and only then
    does ``accept_audit`` return so the caller can continue with the next SKU.

    Without a publisher the legacy preparation-only mode remains available and
    runs Research/QA in a background worker, leaving items READY.
    """

    def __init__(
        self,
        db: AgentDatabase,
        *,
        research_worker_factory: Callable[[], Any],
        work_dir: str | Path,
        publisher: Any | None = None,
        log=None,
    ):
        self.db = db
        self.research_worker_factory = research_worker_factory
        self.publisher = publisher
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.log = log or (lambda _msg: None)
        self.audits = SeoAuditRepository(db)
        self.batches = SeoBatchRepository(db)
        self._batch_id: int | None = None
        self._sealed = False
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._research = None
        self._orchestrator: SeoBatchOrchestrator | None = None
        self._closed = False

    @property
    def batch_id(self) -> int | None:
        return self._batch_id

    @property
    def immediate_publish(self) -> bool:
        return self.publisher is not None

    def _ensure_orchestrator(self) -> SeoBatchOrchestrator:
        if self._closed:
            raise RuntimeError("El preparador SEO ya está cerrado")
        if self._orchestrator is None:
            self._research = self.research_worker_factory()
            self._orchestrator = SeoBatchOrchestrator(
                self.db,
                self._research,
                publisher=self.publisher,
                work_dir=self.work_dir,
                log=self.log,
            )
        return self._orchestrator

    def _ensure_worker(self) -> None:
        if self._closed:
            raise RuntimeError("El preparador SEO ya está cerrado")
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="stech-seo-research-1",
                daemon=True,
            )
            self._worker.start()

    def _worker_loop(self) -> None:
        try:
            orchestrator = self._ensure_orchestrator()
            while True:
                batch_id = self._queue.get()
                try:
                    if batch_id is None:
                        return
                    orchestrator.run(int(batch_id))
                except Exception as exc:
                    self.log(f"[SEO] Error del worker Research/QA: {type(exc).__name__}: {exc}")
                finally:
                    self._queue.task_done()
        finally:
            if self._research is not None and hasattr(self._research, "close"):
                try:
                    self._research.close()
                except Exception:
                    pass
            self._research = None
            self._orchestrator = None

    def _open_batch(
        self,
        *,
        sku: str,
        session_id: int | None,
        scope: dict[str, Any],
    ) -> int:
        if self._batch_id is None or self._sealed:
            self._batch_id = self.batches.create(
                session_id=session_id,
                skus=[sku],
                scope=dict(scope or {}),
                publish=self.immediate_publish,
            )
            self._sealed = False
        else:
            self.batches.append_sku(self._batch_id, sku)
        return self._batch_id

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
            self.log(f"[SEO] {sku}: SEO completo; sigo con el siguiente producto.")
            return {
                "action": "SKIP_COMPLETE",
                "sku": sku,
                "state": "SEO_COMPLETE",
                "batch_id": self._batch_id,
            }
        if status not in {"SEO_EMPTY", "SEO_INCOMPLETE"}:
            return {
                "action": "SKIP_UNSUPPORTED",
                "sku": sku,
                "state": status,
                "batch_id": self._batch_id,
            }

        batch_id = self._open_batch(sku=sku, session_id=session_id, scope=scope)

        if self.immediate_publish:
            self.log(
                f"[SEO] {sku}: {status} → investigando ahora con Edge/ChatGPT antes de continuar."
            )
            orchestrator = self._ensure_orchestrator()
            orchestrator.run(batch_id)
            item = next(item for item in self.batches.list_items(batch_id) if item.sku == sku)
            if item.state in {"VERIFIED", "SEO_COMPLETE"}:
                action = "COMPLETED"
                self.log(f"[SEO] {sku}: {item.state}; ahora continúo con el siguiente producto.")
            else:
                action = "REVIEW"
                self.log(f"[SEO] {sku}: quedó en {item.state}; no inventé ni forcé el guardado.")
            return {
                "action": action,
                "sku": sku,
                "state": item.state,
                "batch_id": batch_id,
            }

        self._ensure_worker()
        self._queue.put(batch_id)
        self.log(f"[SEO] {sku}: {status} → enviado a Research/QA; la auditoría continúa.")
        return {
            "action": "ENQUEUED",
            "sku": sku,
            "state": "RESEARCH_PENDING",
            "batch_id": batch_id,
        }

    def wait_until_idle(self, timeout: float = 30.0) -> bool:
        if self.immediate_publish:
            return True
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() <= deadline:
            batch_id = self._batch_id
            if batch_id is None:
                return True
            status = self.batches.status(batch_id)
            active = any(state in _ACTIVE_STATES and count for state, count in status["states"].items())
            if not active and self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return False

    def finish(self) -> dict[str, Any]:
        batch_id = self._batch_id
        if batch_id is None:
            return {"batch_id": None, "status": "NOTHING_TO_PREPARE", "states": {}}
        self._sealed = True
        status = self.batches.status(batch_id)
        return {"batch_id": batch_id, "status": status["status"], "states": status["states"]}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        worker = self._worker
        if worker is not None and worker.is_alive():
            self._queue.put(None)
            worker.join(timeout=5.0)
        self._worker = None
        if self._research is not None and hasattr(self._research, "close"):
            try:
                self._research.close()
            except Exception:
                pass
        self._research = None
        self._orchestrator = None
