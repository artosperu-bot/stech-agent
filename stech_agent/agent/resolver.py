from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from stech_agent.agent.schema import PlannerDecision
from stech_agent.catalog.query import query_products
from stech_agent.domain.models import FieldPatch, ProductRecord, TargetSpec
from stech_agent.domain.scopes import build_scoped_patch, resolve_field_path, resolve_section


@dataclass(frozen=True, slots=True)
class ResolvedPlan:
    decision: PlannerDecision
    target: TargetSpec
    skus: tuple[str, ...]
    query_explanation: str
    patch: FieldPatch | None = None


def resolve_decision(
    decision: PlannerDecision,
    products: Iterable[ProductRecord],
    *,
    working_set_skus: Iterable[str] = (),
) -> ResolvedPlan:
    working = tuple(str(sku).strip() for sku in working_set_skus if str(sku).strip())
    raw_target = decision.target
    target = TargetSpec(
        skus=raw_target.skus,
        brand=raw_target.brand,
        category=raw_target.category,
        subcategory=raw_target.subcategory,
        stock_lt=raw_target.stock_lt,
        stock_gt=raw_target.stock_gt,
        on_offer=raw_target.on_offer,
        visible=raw_target.visible,
        working_set_skus=working if raw_target.use_working_set else (),
    )
    result = query_products(products, target)

    patch: FieldPatch | None = None
    if decision.section is not None:
        section = resolve_section(decision.section)
        requested_fields = None
        if decision.fields:
            requested_fields = [resolve_field_path(field, section=section) for field in decision.fields]
        patch = build_scoped_patch(
            section=section,
            requested_fields=requested_fields,
            values={},
            mode=decision.mode,
        )

    return ResolvedPlan(
        decision=decision,
        target=target,
        skus=tuple(result.skus),
        query_explanation=result.explanation,
        patch=patch,
    )
