from __future__ import annotations

from typing import Any

from stech_agent.agent.resolver import ResolutionNeedsClarification, resolve_decision
from stech_agent.agent.schema import PlannerDecision
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.repositories import CatalogRepository, SessionRepository
from stech_agent.domain.models import ActionType
from stech_agent.stech.product_writer import UnsupportedLiveField


_FIELD_LABELS = {
    "stock": "Stock",
    "price": "Precio",
    "name": "Nombre",
    "description": "Descripción",
    "seo_title": "Título SEO",
    "seo_description": "Descripción SEO",
    "seo_keywords": "Keywords SEO",
}


class AgentBrainRuntime:
    def __init__(self, db: AgentDatabase, planner: Any, *, live_executor: Any | None = None):
        self.db = db
        self.planner = planner
        self.live_executor = live_executor

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

    def _ensure_live_executor(self):
        if self.live_executor is None:
            from stech_agent.agent.live_executor import StechLiveExecutor

            self.live_executor = StechLiveExecutor()
        return self.live_executor

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
        if decision.action is not ActionType.UPDATE_FIELDS:
            count = planned.get("count", 0)
            if decision.action is ActionType.READ:
                return {
                    **planned,
                    "executed": False,
                    "status": "READ_ONLY",
                    "message": f"Encontré {count} producto(s) que cumplen la orden. No hice cambios.",
                }
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
        elif status == "NOOP":
            fields = sorted(resolved.patch.values)
            detail = ", ".join(
                f"{_FIELD_LABELS.get(field, field)} ya estaba en {outcome.get('before', {}).get(field)}"
                for field in fields
            )
            message = f"Encontré {expected_name or sku} ({sku}). {detail}. No fue necesario guardar cambios."
            executed = False
        else:
            message = f"Intenté actualizar {expected_name or sku} ({sku}), pero la verificación no confirmó el resultado. Lo dejé en revisión."
            executed = True

        return {
            **planned,
            "dry_run": False,
            "executed": executed,
            "status": status,
            "message": message,
            "before": outcome.get("before") or {},
            "after": outcome.get("after") or {},
        }

    def close(self) -> None:
        if self.live_executor is not None and hasattr(self.live_executor, "close"):
            self.live_executor.close()
