from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stech_agent.domain.models import ActionType, MutationMode


@dataclass(frozen=True, slots=True)
class PlannerTarget:
    skus: tuple[str, ...] = ()
    brand: str | None = None
    category: str | None = None
    subcategory: str | None = None
    stock_lt: int | None = None
    stock_gt: int | None = None
    on_offer: bool | None = None
    visible: bool | None = None
    use_working_set: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannerTarget":
        return cls(
            skus=tuple(str(item).strip() for item in payload.get("skus", []) if str(item).strip()),
            brand=_optional_text(payload.get("brand")),
            category=_optional_text(payload.get("category")),
            subcategory=_optional_text(payload.get("subcategory")),
            stock_lt=_optional_int(payload.get("stock_lt")),
            stock_gt=_optional_int(payload.get("stock_gt")),
            on_offer=_optional_bool(payload.get("on_offer")),
            visible=_optional_bool(payload.get("visible")),
            use_working_set=bool(payload.get("use_working_set", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skus": list(self.skus),
            "brand": self.brand,
            "category": self.category,
            "subcategory": self.subcategory,
            "stock_lt": self.stock_lt,
            "stock_gt": self.stock_gt,
            "on_offer": self.on_offer,
            "visible": self.visible,
            "use_working_set": self.use_working_set,
        }


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    action: ActionType
    target: PlannerTarget
    section: str | None
    fields: tuple[str, ...]
    mode: MutationMode
    research_required: bool
    clarification_required: bool
    clarification_question: str | None
    explanation: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannerDecision":
        return cls(
            action=ActionType(str(payload["action"])),
            target=PlannerTarget.from_dict(dict(payload["target"])),
            section=_optional_text(payload.get("section")),
            fields=tuple(str(item).strip() for item in payload.get("fields", []) if str(item).strip()),
            mode=MutationMode(str(payload["mode"])),
            research_required=bool(payload.get("research_required", False)),
            clarification_required=bool(payload.get("clarification_required", False)),
            clarification_question=_optional_text(payload.get("clarification_question")),
            explanation=str(payload.get("explanation") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "target": self.target.to_dict(),
            "section": self.section,
            "fields": list(self.fields),
            "mode": self.mode.value,
            "research_required": self.research_required,
            "clarification_required": self.clarification_required,
            "clarification_question": self.clarification_question,
            "explanation": self.explanation,
        }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise ValueError(f"Valor booleano inválido: {value!r}")


_TARGET_PROPERTIES: dict[str, Any] = {
    "skus": {"type": "array", "items": {"type": "string"}},
    "brand": {"type": ["string", "null"]},
    "category": {"type": ["string", "null"]},
    "subcategory": {"type": ["string", "null"]},
    "stock_lt": {"type": ["integer", "null"]},
    "stock_gt": {"type": ["integer", "null"]},
    "on_offer": {"type": ["boolean", "null"]},
    "visible": {"type": ["boolean", "null"]},
    "use_working_set": {"type": "boolean"},
}

PLANNER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": [item.value for item in ActionType]},
        "target": {
            "type": "object",
            "additionalProperties": False,
            "properties": _TARGET_PROPERTIES,
            "required": list(_TARGET_PROPERTIES),
        },
        "section": {
            "type": ["string", "null"],
            "enum": [None, "basic", "pricing", "features", "multimedia", "seo", "commercial"],
        },
        "fields": {"type": "array", "items": {"type": "string"}},
        "mode": {"type": "string", "enum": [item.value for item in MutationMode]},
        "research_required": {"type": "boolean"},
        "clarification_required": {"type": "boolean"},
        "clarification_question": {"type": ["string", "null"]},
        "explanation": {"type": "string"},
    },
    "required": [
        "action",
        "target",
        "section",
        "fields",
        "mode",
        "research_required",
        "clarification_required",
        "clarification_question",
        "explanation",
    ],
}
