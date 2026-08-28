from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.query import query_products
from stech_agent.domain.fields import coerce_field
from stech_agent.domain.models import ActionType, FieldPatch, MutationMode, ProductRecord, TargetSpec
from stech_agent.domain.scopes import build_scoped_patch, resolve_field_path, resolve_section


_MUTATING_ACTIONS = {
    ActionType.UPDATE_FIELDS,
    ActionType.PREPARE_CHANGESET,
    ActionType.APPLY_CHANGESET,
    ActionType.GENERATE_SEO,
    ActionType.UPLOAD_SEO,
}


class ResolutionNeedsClarification(ValueError):
    def __init__(self, question: str, *, candidate_skus: Iterable[str] = ()):
        super().__init__(question)
        self.question = question
        self.candidate_skus = tuple(str(sku) for sku in candidate_skus)


@dataclass(frozen=True, slots=True)
class ResolvedPlan:
    decision: PlannerDecision
    target: TargetSpec
    skus: tuple[str, ...]
    query_explanation: str
    patch: FieldPatch | None = None


def _has_explicit_selector(decision: PlannerDecision) -> bool:
    target = decision.target
    return bool(
        target.skus
        or target.name
        or target.brand
        or target.category
        or target.subcategory
        or target.stock_lt is not None
        or target.stock_gt is not None
        or target.on_offer is not None
        or target.visible is not None
        or target.use_working_set
        or target.all_products
    )


def _coerce_values(decision: PlannerDecision, section: str) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for raw_field, raw_value in decision.values.items():
        field = resolve_field_path(raw_field, section=section)
        if field in normalized:
            raise ValueError(f"Campo repetido después de normalizar: {field}")
        normalized[field] = coerce_field(field, raw_value)
    return normalized


def resolve_decision(
    decision: PlannerDecision,
    products: Iterable[ProductRecord],
    *,
    working_set_skus: Iterable[str] = (),
) -> ResolvedPlan:
    product_list = list(products)
    working = tuple(str(sku).strip() for sku in working_set_skus if str(sku).strip())
    raw_target = decision.target

    if decision.action in _MUTATING_ACTIONS and not _has_explicit_selector(decision):
        raise ResolutionNeedsClarification(
            "No hay un objetivo suficientemente definido para la mutación. Indica SKU, nombre, filtro, conjunto anterior o confirma explícitamente todos los productos."
        )
    if raw_target.use_working_set and not working:
        raise ResolutionNeedsClarification(
            "La orden hace referencia al conjunto anterior, pero no hay productos guardados en el working set actual."
        )

    target = TargetSpec(
        skus=raw_target.skus,
        name=raw_target.name,
        brand=raw_target.brand,
        category=raw_target.category,
        subcategory=raw_target.subcategory,
        stock_lt=raw_target.stock_lt,
        stock_gt=raw_target.stock_gt,
        on_offer=raw_target.on_offer,
        visible=raw_target.visible,
        working_set_skus=working if raw_target.use_working_set else (),
    )
    result = query_products(product_list, target)

    if decision.action in _MUTATING_ACTIONS and raw_target.name is not None:
        if not result.skus:
            raise ResolutionNeedsClarification(
                f"No encontré un producto con nombre exacto {raw_target.name!r} en el catálogo actual."
            )
        if len(result.skus) > 1 and not raw_target.allow_multiple_name_matches:
            raise ResolutionNeedsClarification(
                "Encontré más de un producto con ese nombre. Confirma el SKU o indica explícitamente que quieres aplicar el cambio a todos los productos con ese nombre.",
                candidate_skus=result.skus,
            )

    patch: FieldPatch | None = None
    if decision.section is not None:
        section = resolve_section(decision.section)
        requested_fields = None
        if decision.fields:
            requested_fields = [resolve_field_path(field, section=section) for field in decision.fields]
        values = _coerce_values(decision, section)
        patch = build_scoped_patch(
            section=section,
            requested_fields=requested_fields,
            values=values,
            mode=decision.mode,
        )

        if decision.action is ActionType.UPDATE_FIELDS and decision.mode in {
            MutationMode.PATCH,
            MutationMode.REPLACE_SECTION,
        }:
            if not values:
                raise ResolutionNeedsClarification(
                    "Entendí qué campo quieres cambiar, pero falta el valor exacto que debe aplicarse."
                )
            if requested_fields is not None and set(values) != set(requested_fields):
                missing = sorted(set(requested_fields) - set(values))
                if missing:
                    raise ResolutionNeedsClarification(
                        "Falta el valor exacto para: " + ", ".join(missing)
                    )
    elif decision.values:
        raise ResolutionNeedsClarification(
            "La orden contiene valores para modificar, pero no identifica la sección del producto."
        )

    return ResolvedPlan(
        decision=decision,
        target=target,
        skus=tuple(result.skus),
        query_explanation=result.explanation,
        patch=patch,
    )
