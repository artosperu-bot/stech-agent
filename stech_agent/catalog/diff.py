from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from stech_agent.domain.models import FieldPatch, ProductRecord


@dataclass(frozen=True, slots=True)
class FieldChange:
    before: Any
    after: Any


@dataclass(frozen=True, slots=True)
class ProductDiff:
    sku: str
    changes: dict[str, FieldChange]


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.normalize())
    return value


def build_diff(before: ProductRecord, patch: FieldPatch) -> ProductDiff:
    changes: dict[str, FieldChange] = {}
    for field in patch.fields:
        if not hasattr(before, field):
            raise KeyError(field)
        old = getattr(before, field)
        new = patch.values[field]
        if _normalize(old) != _normalize(new):
            changes[field] = FieldChange(before=old, after=new)
    return ProductDiff(sku=before.sku, changes=changes)
