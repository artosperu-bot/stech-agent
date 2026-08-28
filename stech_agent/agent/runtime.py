from __future__ import annotations

from typing import Any

from stech_agent.agent.resolver import ResolutionNeedsClarification, resolve_decision
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.repositories import CatalogRepository, SessionRepository


class AgentBrainRuntime:
    def __init__(self, db: AgentDatabase, planner: Any):
        self.db = db
        self.planner = planner

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

    def plan(self, command: str, *, session_id: int | None = None) -> dict[str, Any]:
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
