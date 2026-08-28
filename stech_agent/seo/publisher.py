from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Any

from stech_agent.db.connection import AgentDatabase
from stech_agent.db.repositories import AuditRepository, CatalogRepository
from stech_agent.domain.models import FieldPatch, MutationMode
from stech_agent.seo.audit import SeoAuditRepository
from stech_agent.seo.batches import SeoBatchRepository
from stech_agent.seo.qa import validate_proposal
from stech_agent.stech.verifier import compare_expected_fields


_PUBLISH_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class PublishResult:
    item_id: int
    sku: str
    status: str
    message: str
    patch: dict[str, Any]


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _audit_field_value(values: dict[str, Any], field: str) -> Any:
    if field == "seo_faq":
        return values.get("seo_faqs", [])
    return values.get(field)


class SeoPublisher:
    """Single-writer publisher. Re-reads S-TECH before and after every mutation."""

    def __init__(self, db: AgentDatabase, live_executor: Any):
        self.db = db
        self.live = live_executor
        self.batches = SeoBatchRepository(db)
        self.catalogs = CatalogRepository(db)
        self.audits = SeoAuditRepository(db)

    def _proposal(self, item_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        with self.db.connect() as con:
            row = con.execute(
                "SELECT generated_json, proposed_patch_json FROM seo_proposals WHERE batch_item_id=?",
                (int(item_id),),
            ).fetchone()
        if row is None:
            raise RuntimeError("El item no tiene propuesta SEO validada")
        return _loads(row["generated_json"]), _loads(row["proposed_patch_json"])

    def _record_attempt(
        self,
        item_id: int,
        *,
        before: dict[str, Any],
        patch: dict[str, Any],
        after: dict[str, Any],
        status: str,
        error: str | None = None,
    ) -> None:
        with self.db.transaction(immediate=True) as con:
            con.execute(
                """
                INSERT INTO seo_publish_attempts(
                    batch_item_id,before_json,intended_patch_json,after_json,status,error
                ) VALUES (?,?,?,?,?,?)
                """,
                (int(item_id), _json(before), _json(patch), _json(after), status, error),
            )

    def _record_session_update(
        self,
        *,
        item,
        name: str,
        patch: dict[str, Any],
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        batch = self.batches.get(item.batch_id)
        session_id = None if batch is None else batch.get("session_id")
        if session_id is None or not patch:
            return
        fields = list(patch)
        AuditRepository(self.db).add(
            "LIVE_UPDATE_VERIFIED",
            {
                "command": "AUTO_SEO_FILL_MISSING",
                "name": name,
                "fields": fields,
                "before": {field: _audit_field_value(before, field) for field in fields},
                "after": {field: _audit_field_value(after, field) for field in fields},
            },
            session_id=int(session_id),
            sku=item.sku,
        )

    @staticmethod
    def _verification_actual(after: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        actual: dict[str, Any] = {}
        expected: dict[str, Any] = {}
        for field, value in patch.items():
            if field == "seo_faq":
                actual[field] = after.get("seo_faqs", [])
                expected[field] = value
            else:
                actual[field] = after.get(field)
                expected[field] = value
        return actual, expected

    def publish(self, item_id: int) -> PublishResult:
        with _PUBLISH_LOCK:
            item = self.batches.get_item(int(item_id))
            if item is None:
                raise KeyError(f"Item SEO inexistente: {item_id}")
            if item.state not in {"READY", "READY_REVERIFY", "PUBLISHING"}:
                return PublishResult(item.id, item.sku, "BLOCKED", f"El item está en estado {item.state}", {})

            if item.state != "PUBLISHING":
                self.batches.transition(item.id, item.state, "PUBLISHING")

            product = self.catalogs.get_by_sku(item.sku)
            expected_name = product.name if product is not None else None
            generated, _staged_patch = self._proposal(item.id)
            fields = ("seo_title", "seo_description", "seo_keywords", "seo_faq")

            try:
                before = self.live.read_fields(sku=item.sku, fields=fields, expected_name=expected_name)
            except Exception as exc:
                error = f"Lectura previa falló: {type(exc).__name__}: {exc}"
                self.batches.set_state(item.id, "PUBLISH_ERROR", error=error)
                self._record_attempt(item.id, before={}, patch={}, after={}, status="PUBLISH_ERROR", error=error)
                return PublishResult(item.id, item.sku, "PUBLISH_ERROR", error, {})

            qa = validate_proposal(current=before, generated=generated)
            if qa.status == "QA_REVIEW":
                message = "; ".join(qa.notes)
                self.batches.set_state(item.id, "QA_REVIEW", error=message)
                self._record_attempt(item.id, before=before, patch={}, after=before, status="QA_REVIEW", error=message)
                return PublishResult(item.id, item.sku, "QA_REVIEW", message, {})
            if qa.status == "NOOP" or not qa.patch:
                self.batches.set_state(item.id, "SEO_COMPLETE")
                self.audits.record(item.sku, "SEO_COMPLETE", before, source="stech_live_after_publish")
                self._record_attempt(item.id, before=before, patch={}, after=before, status="NOOP")
                return PublishResult(item.id, item.sku, "NOOP", "El SEO ya estaba completo; no pulsé Aceptar.", {})

            patch = dict(qa.patch)
            try:
                outcome = self.live.execute_update(
                    sku=item.sku,
                    expected_name=expected_name,
                    patch=FieldPatch(
                        patch,
                        mode=MutationMode.FILL_MISSING,
                        section="seo",
                        authorized_fields=frozenset(patch),
                    ),
                )
            except Exception as exc:
                error = f"Publicación falló: {type(exc).__name__}: {exc}"
                self.batches.set_state(item.id, "PUBLISH_ERROR", error=error)
                self._record_attempt(item.id, before=before, patch=patch, after={}, status="PUBLISH_ERROR", error=error)
                return PublishResult(item.id, item.sku, "PUBLISH_ERROR", error, patch)

            if outcome.get("status") not in {"VERIFIED", "NOOP"}:
                error = "S-TECH no confirmó el guardado"
                self.batches.set_state(item.id, "VERIFY_ERROR", error=error)
                self._record_attempt(item.id, before=before, patch=patch, after=outcome.get("after") or {}, status="VERIFY_ERROR", error=error)
                return PublishResult(item.id, item.sku, "VERIFY_ERROR", error, patch)

            try:
                after = self.live.read_fields(sku=item.sku, fields=fields, expected_name=expected_name)
            except Exception as exc:
                error = f"Relectura posterior falló: {type(exc).__name__}: {exc}"
                self.batches.set_state(item.id, "VERIFY_ERROR", error=error)
                self._record_attempt(item.id, before=before, patch=patch, after={}, status="VERIFY_ERROR", error=error)
                return PublishResult(item.id, item.sku, "VERIFY_ERROR", error, patch)

            actual, expected = self._verification_actual(after, patch)
            verification = compare_expected_fields(actual, expected)
            if not verification.ok:
                error = "La relectura de S-TECH no coincide exactamente con el patch publicado"
                self.batches.set_state(item.id, "VERIFY_ERROR", error=error)
                self._record_attempt(item.id, before=before, patch=patch, after=after, status="VERIFY_ERROR", error=error)
                return PublishResult(item.id, item.sku, "VERIFY_ERROR", error, patch)

            self.batches.set_state(item.id, "VERIFIED")
            self.audits.record(item.sku, "SEO_COMPLETE", after, source="stech_live_after_publish")
            self._record_attempt(item.id, before=before, patch=patch, after=after, status="VERIFIED")
            self._record_session_update(
                item=item,
                name=expected_name or item.sku,
                patch=patch,
                before=before,
                after=after,
            )
            return PublishResult(
                item.id,
                item.sku,
                "VERIFIED",
                f"{item.sku}: SEO guardado con Aceptar y verificado por relectura.",
                patch,
            )
