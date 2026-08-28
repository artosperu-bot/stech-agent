from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable

from stech_agent.domain.models import ProductRecord, TargetSpec


@dataclass(frozen=True, slots=True)
class QueryResult:
    skus: list[str]
    explanation: str


def _norm_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().strip()
    return re.sub(r"\s+", " ", text)


def query_products(products: Iterable[ProductRecord], target: TargetSpec) -> QueryResult:
    items = list(products)
    explanations: list[str] = []
    explicit = tuple(str(x) for x in target.skus)
    explicit_set = set(explicit)
    working_set = set(str(x) for x in target.working_set_skus)
    target_name = _norm_text(target.name) if target.name is not None else None

    def keep(p: ProductRecord) -> bool:
        if explicit and p.sku not in explicit_set:
            return False
        if working_set and p.sku not in working_set:
            return False
        if target_name is not None and _norm_text(p.name) != target_name:
            return False
        if target.brand is not None and p.brand.casefold() != target.brand.casefold():
            return False
        if target.category is not None and p.category.casefold() != target.category.casefold():
            return False
        if target.subcategory is not None and p.subcategory.casefold() != target.subcategory.casefold():
            return False
        if target.stock_lt is not None and (p.stock is None or p.stock >= target.stock_lt):
            return False
        if target.stock_gt is not None and (p.stock is None or p.stock <= target.stock_gt):
            return False
        if target.on_offer is not None and p.on_offer is not target.on_offer:
            return False
        if target.visible is not None and p.visible is not target.visible:
            return False
        return True

    matched = [p for p in items if keep(p)]
    if explicit:
        by_sku = {p.sku: p for p in matched}
        skus = [sku for sku in explicit if sku in by_sku]
        explanations.append(f"skus={','.join(explicit)}")
    else:
        skus = [p.sku for p in sorted(matched, key=lambda p: p.source_order)]

    if target.name is not None:
        explanations.append(f"name={target.name}")
    if target.brand is not None:
        explanations.append(f"brand={target.brand}")
    if target.category is not None:
        explanations.append(f"category={target.category}")
    if target.subcategory is not None:
        explanations.append(f"subcategory={target.subcategory}")
    if target.stock_lt is not None:
        explanations.append(f"stock<{target.stock_lt}")
    if target.stock_gt is not None:
        explanations.append(f"stock>{target.stock_gt}")
    if target.on_offer is not None:
        explanations.append(f"on_offer={target.on_offer}")
    if target.visible is not None:
        explanations.append(f"visible={target.visible}")
    if working_set:
        explanations.append(f"working_set={len(working_set)}")
    return QueryResult(skus=skus, explanation="; ".join(explanations) or "all")
