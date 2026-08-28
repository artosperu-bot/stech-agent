from __future__ import annotations

from pathlib import Path
from typing import Any

from stech_agent.agent.resolver import ResolutionNeedsClarification, resolve_decision
from stech_agent.agent.schema import PlannerDecision
from stech_agent.config import AgentPaths
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.repositories import AuditRepository, CatalogRepository, SessionRepository
from stech_agent.domain.fields import coerce_field
from stech_agent.domain.models import ActionType, MutationMode
from stech_agent.domain.scopes import build_scoped_patch, resolve_field_path, resolve_section
from stech_agent.stech.import_certification import require_mass_import_certified
from stech_agent.stech.product_writer import UnsupportedLiveField


_FIELD_LABELS = {
    "stock": "Stock",
    "price": "Precio",
    "name": "Nombre",
    "description": "Descripción",
    "seo_title": "Título SEO",
    "seo_description": "Descripción SEO",
    "seo_keywords": "Keywords SEO",
    "seo_faq": "FAQ SEO",
}

_LIVE_UPDATE_EVENT = "LIVE_UPDATE_VERIFIED"
_LIVE_ROLLBACK_EVENT = "LIVE_ROLLBACK_VERIFIED"


class AgentBrainRuntime:
    def __init__(
        self,
        db: AgentDatabase,
        planner: Any,
        *,
        live_executor: Any | None = None,
        work_dir: str | Path | None = None,
    ):
        self.db = db
        self.planner = planner
        self.live_executor = live_executor
        self.work_dir = Path(work_dir) if work_dir is not None else AgentPaths.default().app_data / "work"

    @staticmethod
    def _clarification_result(decision, question: str, *, candidate_skus=()) -> dict[str, Any]:
        decision_data = decision.to_dict()
        decision_data["clarification_required"] = True
        decision_data["clarification_question"] = question
        return {
            "dry_run": True,
            "decision": decision_data,
            "resolved_skus": [],
            "count": 0,
            "query_explanation": "clarification_required",
            "authorized_fields": [],
            "candidate_skus": list(candidate_skus),
        }

    def _catalog_context(self, session_id: int | None):
        catalogs = CatalogRepository(self.db)
        products = catalogs.list_products()
        meta = catalogs.get_snapshot_meta()
        if not products or meta is None:
            raise RuntimeError("No existe un snapshot de catálogo. Ejecuta primero ingest sobre el export de S-TECH.")

        working_set = None
        if session_id is not None:
            working_set = SessionRepository(self.db).get_working_set(session_id, "current")
        working_skus = tuple((working_set or {}).get("skus") or ())
        context = {
            "catalog_product_count": len(products),
            "catalog_snapshot_at": meta.get("created_at"),
            "catalog_headers": list(meta.get("raw_headers") or ()),
            "working_set_available": bool(working_skus),
            "working_set_count": len(working_skus),
        }
        return catalogs, products, working_skus, context

    def plan(self, command: str, *, session_id: int | None = None) -> dict[str, Any]:
        _catalogs, products, working_skus, context = self._catalog_context(session_id)
        decision = self.planner.plan(command, context)

        if decision.clarification_required:
            return self._clarification_result(
                decision,
                decision.clarification_question or "Necesito una aclaración antes de continuar.",
            )

        try:
            resolved = resolve_decision(decision, products, working_set_skus=working_skus)
        except ResolutionNeedsClarification as exc:
            return self._clarification_result(
                decision,
                exc.question,
                candidate_skus=exc.candidate_skus,
            )
        except (ValueError, KeyError) as exc:
            return self._clarification_result(
                decision,
                f"El plan contiene un campo o valor que no puedo validar con seguridad: {exc}",
            )

        authorized_fields = []
        if resolved.patch is not None:
            authorized_fields = sorted(resolved.patch.authorized_fields or ())

        return {
            "dry_run": True,
            "decision": decision.to_dict(),
            "resolved_skus": list(resolved.skus),
            "count": len(resolved.skus),
            "query_explanation": resolved.query_explanation,
            "authorized_fields": authorized_fields,
            "candidate_skus": [],
        }

    @staticmethod
    def _format_verified(name: str, sku: str, before: dict[str, Any], after: dict[str, Any], changed_fields: list[str]) -> str:
        display_name = name or sku
        if len(changed_fields) == 1:
            field = changed_fields[0]
            label = _FIELD_LABELS.get(field, field)
            return f"Encontré {display_name} ({sku}). {label}: {before.get(field)} → {after.get(field)}. Cambio guardado y verificado."
        details = ", ".join(
            f"{_FIELD_LABELS.get(field, field)}: {before.get(field)} → {after.get(field)}"
            for field in changed_fields
        )
        return f"Encontré {display_name} ({sku}). Actualicé {details}. Cambios guardados y verificados."

    @staticmethod
    def _nonempty(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    @classmethod
    def _seo_summary(cls, name: str, sku: str, values: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        title_ok = cls._nonempty(values.get("seo_title"))
        description_ok = cls._nonempty(values.get("seo_description"))
        keywords_ok = cls._nonempty(values.get("seo_keywords"))
        faqs = values.get("seo_faqs") or []
        complete_faqs = sum(
            1
            for faq in faqs
            if isinstance(faq, dict)
            and cls._nonempty(faq.get("question"))
            and cls._nonempty(faq.get("answer"))
        )
        faq_target = 3
        faq_ok = complete_faqs >= faq_target
        complete = title_ok and description_ok and keywords_ok and faq_ok

        checks = [
            f"Título {'✓' if title_ok else '✗'}",
            f"Descripción {'✓' if description_ok else '✗'}",
            f"Keywords {'✓' if keywords_ok else '✗'}",
            f"FAQ {min(complete_faqs, faq_target)}/{faq_target} {'✓' if faq_ok else '✗'}",
        ]
        display_name = name or sku
        if complete:
            message = f"{display_name} ({sku}): SEO completo. " + " · ".join(checks)
            status = "SEO_COMPLETE"
        else:
            missing: list[str] = []
            if not title_ok:
                missing.append("título")
            if not description_ok:
                missing.append("descripción")
            if not keywords_ok:
                missing.append("keywords")
            if not faq_ok:
                missing.append(f"FAQ ({complete_faqs}/{faq_target} completas)")
            message = f"{display_name} ({sku}): SEO incompleto. Falta: {', '.join(missing)}. " + " · ".join(checks)
            status = "SEO_INCOMPLETE"
        return status, message, {
            "title_ok": title_ok,
            "description_ok": description_ok,
            "keywords_ok": keywords_ok,
            "complete_faqs": complete_faqs,
            "faq_target": faq_target,
            "complete": complete,
        }

    def _ensure_live_executor(self):
        if self.live_executor is None:
            from stech_agent.agent.live_executor import StechLiveExecutor

            self.live_executor = StechLiveExecutor()
        return self.live_executor

    def create_product(self, values: dict[str, Any], *, session_id: int | None = None) -> dict[str, Any]:
        try:
            require_mass_import_certified(self.db)
        except RuntimeError as exc:
            return {
                "status": "IMPORT_NOT_CERTIFIED",
                "created": False,
                "sku": str(values.get("sku") or "").strip(),
                "message": (
                    "No abrí S-TECH ni importé nada. El importador Agregar / Actualizar todavía no está "
                    f"certificado en esta PC: {exc}"
                ),
            }
        try:
            return self._ensure_live_executor().create_product(
                db=self.db,
                catalog_repository=CatalogRepository(self.db),
                values=dict(values),
                work_dir=self.work_dir,
                session_id=session_id,
            )
        except Exception as exc:
            return {
                "status": "ERROR",
                "created": False,
                "sku": str(values.get("sku") or "").strip(),
                "message": f"No pude crear el producto: {type(exc).__name__}: {exc}",
            }

    def _record_verified_update(
        self,
        *,
        session_id: int | None,
        command: str,
        sku: str,
        name: str,
        before: dict[str, Any],
        after: dict[str, Any],
        changed_fields: list[str],
    ) -> int | None:
        if session_id is None or not changed_fields:
            return None
        fields = list(dict.fromkeys(changed_fields))
        before_changed = {field: before.get(field) for field in fields}
        after_changed = {field: after.get(field) for field in fields}
        return AuditRepository(self.db).add(
            _LIVE_UPDATE_EVENT,
            {
                "command": command,
                "name": name,
                "fields": fields,
                "before": before_changed,
                "after": after_changed,
            },
            session_id=session_id,
            sku=sku,
        )

    def session_history(self, session_id: int) -> dict[str, Any]:
        events = AuditRepository(self.db).list_session(
            session_id,
            event_types=(_LIVE_UPDATE_EVENT, _LIVE_ROLLBACK_EVENT),
        )
        reverted_ids = {
            int(event["payload"].get("source_event_id"))
            for event in events
            if event["event_type"] == _LIVE_ROLLBACK_EVENT and event["payload"].get("source_event_id") is not None
        }
        changes = []
        for event in events:
            if event["event_type"] != _LIVE_UPDATE_EVENT:
                continue
            payload = event["payload"]
            changes.append({
                "event_id": event["id"],
                "sku": event.get("sku"),
                "name": payload.get("name") or "",
                "fields": list(payload.get("fields") or []),
                "before": dict(payload.get("before") or {}),
                "after": dict(payload.get("after") or {}),
                "command": payload.get("command") or "",
                "created_at": event.get("created_at"),
                "reverted": event["id"] in reverted_ids,
            })
        return {
            "session_id": int(session_id),
            "changes": changes,
            "count": len(changes),
            "pending_rollback": sum(1 for change in changes if not change["reverted"]),
        }

    def rollback_session(self, session_id: int) -> dict[str, Any]:
        history = self.session_history(session_id)
        pending = [change for change in history["changes"] if not change["reverted"]]
        if not pending:
            return {
                "status": "NOTHING_TO_ROLLBACK",
                "restored": 0,
                "conflicts": 0,
                "failed": 0,
                "message": "No hay cambios verificados pendientes de deshacer en esta sesión.",
                "items": [],
            }

        catalogs = CatalogRepository(self.db)
        audit = AuditRepository(self.db)
        executor = self._ensure_live_executor()
        restored = 0
        conflicts = 0
        failed = 0
        items: list[dict[str, Any]] = []

        for change in reversed(pending):
            sku = str(change["sku"])
            product = catalogs.get_by_sku(sku)
            name = change.get("name") or (product.name if product is not None else "")
            try:
                outcome = executor.restore_if_unchanged(
                    sku=sku,
                    expected_name=name or None,
                    expected_current=dict(change["after"]),
                    restore_values=dict(change["before"]),
                )
            except Exception as exc:
                failed += 1
                items.append({"sku": sku, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
                continue

            if outcome.get("status") in {"VERIFIED", "NOOP"}:
                restored += 1
                audit.add(
                    _LIVE_ROLLBACK_EVENT,
                    {
                        "source_event_id": change["event_id"],
                        "name": name,
                        "fields": list(change["fields"]),
                        "before": dict(change["after"]),
                        "after": dict(change["before"]),
                    },
                    session_id=session_id,
                    sku=sku,
                )
                items.append({"sku": sku, "status": "RESTORED", "fields": list(change["fields"])})
            elif outcome.get("status") == "CONFLICT":
                conflicts += 1
                items.append({
                    "sku": sku,
                    "status": "CONFLICT",
                    "fields": list(change["fields"]),
                    "current": outcome.get("before") or {},
                    "expected": dict(change["after"]),
                })
            else:
                failed += 1
                items.append({"sku": sku, "status": outcome.get("status") or "ERROR"})

        if restored and not conflicts and not failed:
            status = "ROLLED_BACK"
            message = f"Deshice {restored} cambio(s) de esta sesión y verifiqué la restauración."
        elif restored:
            status = "PARTIAL"
            message = f"Deshice {restored} cambio(s). {conflicts} no se tocaron porque el valor actual cambió después; {failed} fallaron."
        elif conflicts:
            status = "PARTIAL"
            message = f"No revertí cambios porque {conflicts} valor(es) ya no coinciden con lo que había dejado el agente. No pisé esos cambios posteriores."
        else:
            status = "ERROR"
            message = f"No pude deshacer los cambios. Fallaron {failed} operación(es)."

        return {
            "status": status,
            "restored": restored,
            "conflicts": conflicts,
            "failed": failed,
            "message": message,
            "items": items,
        }

    def verify_seo_sku(self, sku: str) -> dict[str, Any]:
        product = CatalogRepository(self.db).get_by_sku(str(sku))
        if product is None:
            return {
                "status": "BLOCKED",
                "executed": False,
                "message": f"No encontré el SKU {sku} en el catálogo actual.",
                "resolved_skus": [],
            }
        if product.ambiguous:
            return {
                "status": "BLOCKED",
                "executed": False,
                "message": f"El SKU {sku} tiene filas duplicadas/conflictivas en el export. No abrí S-TECH.",
                "resolved_skus": [str(sku)],
            }
        try:
            values = self._ensure_live_executor().read_fields(
                sku=str(sku),
                fields=("seo_title", "seo_description", "seo_keywords", "seo_faq"),
                expected_name=product.name,
            )
        except Exception as exc:
            return {
                "status": "ERROR",
                "executed": False,
                "message": f"No pude verificar el SEO en S-TECH: {type(exc).__name__}: {exc}",
                "resolved_skus": [str(sku)],
            }
        status, message, checks = self._seo_summary(product.name, str(sku), values)
        return {
            "status": status,
            "executed": False,
            "message": message,
            "resolved_skus": [str(sku)],
            "seo": values,
            "seo_checks": checks,
        }

    def verify_seo_skus(self, skus, *, scope_label: str = "Selección") -> dict[str, Any]:
        clean_skus = tuple(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
        if not clean_skus:
            return {
                "status": "BLOCKED",
                "complete": 0,
                "incomplete": 0,
                "errors": 0,
                "message": "No hay productos para verificar.",
                "items": [],
            }

        items = []
        complete = 0
        incomplete = 0
        errors = 0
        for sku in clean_skus:
            result = self.verify_seo_sku(sku)
            status = result.get("status")
            if status == "SEO_COMPLETE":
                complete += 1
            elif status == "SEO_INCOMPLETE":
                incomplete += 1
            else:
                errors += 1
            items.append({
                "sku": sku,
                "status": status,
                "message": result.get("message") or "",
                "seo_checks": result.get("seo_checks") or {},
            })

        if errors:
            overall = "PARTIAL"
        elif incomplete:
            overall = "SEO_INCOMPLETE"
        else:
            overall = "SEO_COMPLETE"
        message = (
            f"{scope_label}: {complete} completo(s), {incomplete} incompleto(s), "
            f"{errors} error(es)."
        )
        return {
            "status": overall,
            "complete": complete,
            "incomplete": incomplete,
            "errors": errors,
            "message": message,
            "items": items,
        }

    def _execute_seo_read(self, planned: dict[str, Any], decision: PlannerDecision) -> dict[str, Any]:
        if planned.get("count") != 1:
            return {
                **planned,
                "executed": False,
                "status": "BLOCKED",
                "message": "Para verificar SEO necesito resolver exactamente un producto.",
            }
        sku = planned["resolved_skus"][0]
        product = CatalogRepository(self.db).get_by_sku(sku)
        expected_name = product.name if product is not None else None
        fields = tuple(decision.fields or ("seo_title", "seo_description", "seo_keywords", "seo_faq"))
        try:
            values = self._ensure_live_executor().read_fields(
                sku=sku,
                fields=fields,
                expected_name=expected_name,
            )
        except Exception as exc:
            return {
                **planned,
                "executed": False,
                "status": "ERROR",
                "message": f"No pude verificar el SEO en S-TECH: {type(exc).__name__}: {exc}",
            }
        status, message, checks = self._seo_summary(expected_name or "", sku, values)
        return {
            **planned,
            "dry_run": False,
            "executed": False,
            "status": status,
            "message": message,
            "seo": values,
            "seo_checks": checks,
        }

    def execute_guided_update(
        self,
        *,
        session_id: int | None,
        sku: str,
        section: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        catalogs = CatalogRepository(self.db)
        product = catalogs.get_by_sku(str(sku))
        if product is None:
            return {
                "status": "BLOCKED",
                "executed": False,
                "message": f"No encontré el SKU {sku} en el catálogo actual.",
                "resolved_skus": [],
            }
        if product.ambiguous:
            return {
                "status": "BLOCKED",
                "executed": False,
                "message": f"El SKU {sku} tiene filas duplicadas/conflictivas en el export. No hice cambios.",
                "resolved_skus": [str(sku)],
            }
        if not values:
            return {
                "status": "BLOCKED",
                "executed": False,
                "message": "No seleccionaste ningún valor para cambiar.",
                "resolved_skus": [str(sku)],
            }

        try:
            section_key = resolve_section(section)
            normalized: dict[str, Any] = {}
            for raw_field, raw_value in values.items():
                field = resolve_field_path(raw_field, section=section_key)
                normalized[field] = coerce_field(field, raw_value)
            patch = build_scoped_patch(
                section=section_key,
                requested_fields=tuple(normalized),
                values=normalized,
                mode=MutationMode.PATCH,
            )
        except (ValueError, KeyError) as exc:
            return {
                "status": "BLOCKED",
                "executed": False,
                "message": f"No puedo aplicar ese cambio de forma segura: {exc}",
                "resolved_skus": [str(sku)],
            }

        try:
            outcome = self._ensure_live_executor().execute_update(
                sku=str(sku),
                expected_name=product.name,
                patch=patch,
            )
        except UnsupportedLiveField as exc:
            return {
                "status": "UNSUPPORTED_LIVE_FIELD",
                "executed": False,
                "message": str(exc),
                "resolved_skus": [str(sku)],
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "executed": False,
                "message": f"No pude completar el cambio en S-TECH: {type(exc).__name__}: {exc}",
                "resolved_skus": [str(sku)],
            }

        status = outcome.get("status")
        if status == "VERIFIED":
            changed_fields = outcome.get("changed_fields") or []
            message = self._format_verified(
                outcome.get("name") or product.name,
                str(sku),
                outcome.get("before") or {},
                outcome.get("after") or {},
                changed_fields,
            )
            audit_event_id = self._record_verified_update(
                session_id=session_id,
                command=f"modo guiado: {section_key}",
                sku=str(sku),
                name=product.name,
                before=outcome.get("before") or {},
                after=outcome.get("after") or {},
                changed_fields=changed_fields,
            )
            executed = True
        elif status == "NOOP":
            message = f"{product.name} ({sku}) ya tenía esos valores. No fue necesario pulsar Aceptar."
            audit_event_id = None
            executed = False
        else:
            message = f"Intenté actualizar {product.name} ({sku}), pero la verificación no confirmó el resultado."
            audit_event_id = None
            executed = True

        return {
            "status": status,
            "executed": executed,
            "message": message,
            "resolved_skus": [str(sku)],
            "before": outcome.get("before") or {},
            "after": outcome.get("after") or {},
            "audit_event_id": audit_event_id,
        }

    def execute_guided_bulk_update(
        self,
        *,
        session_id: int | None,
        skus,
        section: str,
        values: dict[str, Any],
        scope_label: str = "Selección",
    ) -> dict[str, Any]:
        clean_skus = tuple(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
        if not clean_skus:
            return {
                "status": "BLOCKED",
                "success": 0,
                "unchanged": 0,
                "failed": 0,
                "message": "No hay productos para modificar.",
                "items": [],
            }

        success = 0
        unchanged = 0
        failed = 0
        items = []
        for sku in clean_skus:
            result = self.execute_guided_update(
                session_id=session_id,
                sku=sku,
                section=section,
                values=values,
            )
            status = result.get("status")
            if status == "VERIFIED":
                success += 1
            elif status == "NOOP":
                unchanged += 1
            else:
                failed += 1
            items.append({
                "sku": sku,
                "status": status,
                "message": result.get("message") or "",
                "audit_event_id": result.get("audit_event_id"),
            })

        if failed and (success or unchanged):
            overall = "PARTIAL"
        elif failed:
            overall = "ERROR"
        else:
            overall = "VERIFIED"
        message = (
            f"{scope_label}: {success} actualizado(s), {unchanged} sin cambios, "
            f"{failed} error(es). Cada resultado fue verificado individualmente."
        )
        return {
            "status": overall,
            "success": success,
            "unchanged": unchanged,
            "failed": failed,
            "message": message,
            "items": items,
            "resolved_skus": list(clean_skus),
        }

    def execute(self, command: str, *, session_id: int | None = None) -> dict[str, Any]:
        planned = self.plan(command, session_id=session_id)
        decision_data = planned["decision"]

        if decision_data.get("clarification_required"):
            question = decision_data.get("clarification_question") or "Necesito una aclaración antes de continuar."
            return {
                **planned,
                "executed": False,
                "status": "NEEDS_CLARIFICATION",
                "message": question,
            }

        decision = PlannerDecision.from_dict(decision_data)
        if decision.action is ActionType.READ:
            if decision.section == "seo":
                return self._execute_seo_read(planned, decision)
            count = planned.get("count", 0)
            return {
                **planned,
                "executed": False,
                "status": "READ_ONLY",
                "message": f"Encontré {count} producto(s) que cumplen la orden. No hice cambios.",
            }

        if decision.action is not ActionType.UPDATE_FIELDS:
            return {
                **planned,
                "executed": False,
                "status": "NOT_CONNECTED",
                "message": f"Entendí la acción {decision.action.value}, pero esa ejecución todavía no está conectada al navegador.",
            }

        if decision.research_required:
            return {
                **planned,
                "executed": False,
                "status": "RESEARCH_NOT_CONNECTED",
                "message": "Esta orden necesita investigación. El flujo de Research Edge todavía no está conectado, así que no hice cambios.",
            }

        if planned.get("count") != 1:
            return {
                **planned,
                "executed": False,
                "status": "BLOCKED",
                "message": "Para cambios directos por navegador necesito resolver exactamente un producto. No hice cambios.",
            }

        catalogs, products, working_skus, _context = self._catalog_context(session_id)
        try:
            resolved = resolve_decision(decision, products, working_set_skus=working_skus)
        except (ResolutionNeedsClarification, ValueError, KeyError) as exc:
            return {
                **planned,
                "executed": False,
                "status": "BLOCKED",
                "message": str(exc),
            }

        if resolved.patch is None or not resolved.patch.values:
            return {
                **planned,
                "executed": False,
                "status": "BLOCKED",
                "message": "No hay un cambio concreto y validado para ejecutar.",
            }

        sku = resolved.skus[0]
        product = catalogs.get_by_sku(sku)
        expected_name = product.name if product is not None else None

        try:
            outcome = self._ensure_live_executor().execute_update(
                sku=sku,
                expected_name=expected_name,
                patch=resolved.patch,
            )
        except UnsupportedLiveField as exc:
            return {
                **planned,
                "executed": False,
                "status": "UNSUPPORTED_LIVE_FIELD",
                "message": str(exc),
            }
        except Exception as exc:
            return {
                **planned,
                "executed": False,
                "status": "ERROR",
                "message": f"No pude completar el cambio en S-TECH: {type(exc).__name__}: {exc}",
            }

        status = outcome["status"]
        if status == "VERIFIED":
            message = self._format_verified(
                outcome.get("name") or expected_name or "",
                sku,
                outcome.get("before") or {},
                outcome.get("after") or {},
                outcome.get("changed_fields") or [],
            )
            executed = True
            audit_event_id = self._record_verified_update(
                session_id=session_id,
                command=command,
                sku=sku,
                name=outcome.get("name") or expected_name or "",
                before=outcome.get("before") or {},
                after=outcome.get("after") or {},
                changed_fields=outcome.get("changed_fields") or [],
            )
        elif status == "NOOP":
            fields = sorted(resolved.patch.values)
            detail = ", ".join(
                f"{_FIELD_LABELS.get(field, field)} ya estaba en {outcome.get('before', {}).get(field)}"
                for field in fields
            )
            message = f"Encontré {expected_name or sku} ({sku}). {detail}. No fue necesario guardar cambios."
            executed = False
            audit_event_id = None
        else:
            message = f"Intenté actualizar {expected_name or sku} ({sku}), pero la verificación no confirmó el resultado. Lo dejé en revisión."
            executed = True
            audit_event_id = None

        return {
            **planned,
            "dry_run": False,
            "executed": executed,
            "status": status,
            "message": message,
            "before": outcome.get("before") or {},
            "after": outcome.get("after") or {},
            "audit_event_id": audit_event_id,
        }

    def close(self) -> None:
        if self.live_executor is not None and hasattr(self.live_executor, "close"):
            self.live_executor.close()
