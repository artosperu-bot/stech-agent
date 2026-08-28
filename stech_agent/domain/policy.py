from __future__ import annotations

from dataclasses import dataclass

from stech_agent.domain.fields import FIELD_REGISTRY
from stech_agent.domain.models import ActionType, AgentPlan, RiskLevel


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    risk: RiskLevel
    requires_confirmation: bool
    reason: str = ""


class PolicyEngine:
    _READ_ACTIONS = {ActionType.READ, ActionType.EXPORT, ActionType.COMPARE}
    _R3_FIELDS = {"price", "discount", "stock", "discount_rule", "promotions"}
    _R2_FIELDS = {"is_new", "on_offer", "recommended", "featured", "visible", "status", "image", "gallery"}

    def evaluate(self, plan: AgentPlan, *, estimated_count: int = 0) -> PolicyDecision:
        if not isinstance(plan.action, ActionType):
            return PolicyDecision(False, RiskLevel.R3, True, "Acción no registrada")
        if plan.action in self._READ_ACTIONS:
            return PolicyDecision(True, RiskLevel.R0, False)
        if plan.action is ActionType.CREATE_PRODUCT:
            return PolicyDecision(True, RiskLevel.R3, True)
        if plan.action in {ActionType.GENERATE_SEO, ActionType.PREPARE_CHANGESET}:
            return PolicyDecision(True, RiskLevel.R1, False)
        if plan.action in {ActionType.APPLY_CHANGESET, ActionType.UPLOAD_SEO} and plan.patch is None:
            return PolicyDecision(True, RiskLevel.R2, True)
        if plan.patch is None:
            return PolicyDecision(False, RiskLevel.R3, True, "La acción requiere un patch explícito")

        unknown = [field for field in plan.patch.fields if field not in FIELD_REGISTRY]
        if unknown:
            return PolicyDecision(False, RiskLevel.R3, True, f"Campos desconocidos: {', '.join(sorted(unknown))}")
        immutable = [field for field in plan.patch.fields if not FIELD_REGISTRY[field].mutable]
        if immutable:
            return PolicyDecision(False, RiskLevel.R3, True, f"Campos inmutables: {', '.join(sorted(immutable))}")
        if plan.patch.fields & self._R3_FIELDS:
            return PolicyDecision(True, RiskLevel.R3, True)
        if plan.patch.fields & self._R2_FIELDS:
            return PolicyDecision(True, RiskLevel.R2, estimated_count > 0)
        return PolicyDecision(True, RiskLevel.R1, False)
