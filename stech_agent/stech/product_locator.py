from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from stech_agent.stech.selectors import locate


class NeedsReview(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LocatedProduct:
    sku: str
    name: str
    row: Any


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def _extract_name(row: Any, sku: str) -> str:
    try:
        cell = row.get_by_role("gridcell", description="Columna Nombre")
        if cell.count() == 1:
            return _clean(cell.first.inner_text(timeout=800))
    except Exception:
        pass
    try:
        text = _clean(row.inner_text(timeout=1000))
    except Exception:
        return ""
    return _clean(text.replace(sku, ""))


def locate_exact_sku(page: Any, sku: str, *, expected_name: str | None = None, settle_ms: int = 900) -> LocatedProduct:
    sku = _clean(sku)
    if not sku:
        raise ValueError("SKU vacío")
    for key in ("name_filter", "brand_filter", "category_filter"):
        try:
            locate(page, key).fill("")
        except Exception:
            pass
    sku_filter = locate(page, "sku_filter")
    sku_filter.fill("")
    sku_filter.fill(sku)
    sku_filter.press("Enter")
    page.wait_for_timeout(settle_ms)
    exact = page.get_by_role("gridcell", name=sku, exact=True)
    count = exact.count()
    if count == 0:
        raise NeedsReview(f"No se encontró una fila con SKU exacto {sku}")
    if count > 1:
        raise NeedsReview(f"Se encontraron múltiples celdas con el SKU exacto {sku}; no se modificará")
    row = exact.first.locator("xpath=ancestor::tr[1]")
    name = _extract_name(row, sku)
    if expected_name is not None and _clean(name).casefold() != _clean(expected_name).casefold():
        raise NeedsReview(
            f"El SKU {sku} existe pero el nombre esperado no coincide: esperado '{_clean(expected_name)}', visible '{name}'"
        )
    return LocatedProduct(sku=sku, name=name, row=row)
