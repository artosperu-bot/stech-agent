from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
import unicodedata
from typing import Any

from openpyxl import Workbook

from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.domain.fields import coerce_field


@dataclass(frozen=True, slots=True)
class ProductCreateDraft:
    sku: str
    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CreateWorkbookReceipt:
    path: Path
    sku: str
    fields: frozenset[str]


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()


def _canonical_existing(values: list[str], requested: str, *, label: str) -> str:
    wanted = _norm(requested)
    matches = [value for value in values if _norm(value) == wanted]
    if not matches:
        raise ValueError(f"{label} {requested!r} no existe en el catálogo actual")
    return matches[0]


def prepare_new_product(snapshot: CatalogSnapshotData, raw_values: dict[str, Any]) -> ProductCreateDraft:
    values = dict(raw_values or {})
    required = ("sku", "name", "brand", "category", "subcategory", "price", "stock")
    missing = [field for field in required if values.get(field) in (None, "")]
    if missing:
        raise ValueError("Faltan campos obligatorios: " + ", ".join(missing))

    sku = str(values.get("sku") or "").strip()
    existing = {product.sku.casefold(): product for product in snapshot.products}
    if sku.casefold() in existing:
        product = existing[sku.casefold()]
        raise ValueError(f"El SKU {sku} ya existe como {product.name or product.sku}")

    brands = list(dict.fromkeys(product.brand for product in snapshot.products if product.brand))
    categories = list(dict.fromkeys(product.category for product in snapshot.products if product.category))
    brand = _canonical_existing(brands, str(values["brand"]), label="Marca")
    category = _canonical_existing(categories, str(values["category"]), label="Categoría")

    subcategories = list(dict.fromkeys(
        product.subcategory
        for product in snapshot.products
        if product.subcategory and _norm(product.category) == _norm(category)
    ))
    try:
        subcategory = _canonical_existing(subcategories, str(values["subcategory"]), label="Subcategoría")
    except ValueError as exc:
        raise ValueError(
            f"Subcategoría {values['subcategory']!r} no existe dentro de la categoría {category!r}"
        ) from exc

    normalized: dict[str, Any] = {
        "sku": sku,
        "name": coerce_field("name", values["name"]),
        "description": coerce_field("description", values.get("description")),
        "category": category,
        "subcategory": subcategory,
        "brand": brand,
        "price": coerce_field("price", values["price"]),
        "discount": coerce_field("discount", values.get("discount", 0)),
        "stock": coerce_field("stock", values["stock"]),
        "is_new": coerce_field("is_new", values.get("is_new", False)),
        "on_offer": coerce_field("on_offer", values.get("on_offer", False)),
        "recommended": coerce_field("recommended", values.get("recommended", False)),
        "featured": coerce_field("featured", values.get("featured", False)),
        "visible": coerce_field("visible", values.get("visible", False)),
        "status": coerce_field("status", values.get("status")),
        "main_specs": coerce_field("main_specs", values.get("main_specs")),
        "technical_specs": coerce_field("technical_specs", values.get("technical_specs")),
        "image": coerce_field("image", values.get("image")),
        "gallery": coerce_field("gallery", values.get("gallery")),
        "discount_rule": coerce_field("discount_rule", values.get("discount_rule")),
        "promotions": coerce_field("promotions", values.get("promotions")),
    }
    if normalized["price"] is None or normalized["price"] < 0:
        raise ValueError("Precio inválido; debe ser 0 o mayor")
    if normalized["discount"] is not None and normalized["discount"] < 0:
        raise ValueError("Descuento inválido; debe ser 0 o mayor")
    if normalized["stock"] is None or normalized["stock"] < 0:
        raise ValueError("Stock inválido; debe ser 0 o mayor")

    return ProductCreateDraft(sku=sku, values=normalized)


def _export_value(field: str, value: Any) -> Any:
    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, Decimal):
        return float(value)
    return value


def build_create_workbook(
    snapshot: CatalogSnapshotData,
    draft: ProductCreateDraft,
    output_path: str | Path,
) -> CreateWorkbookReceipt:
    header_for_field = {
        canonical: raw
        for raw, canonical in zip(snapshot.raw_headers, snapshot.canonical_headers)
        if not canonical.startswith("extra:")
    }
    required_headers = {"sku", "name", "category", "subcategory", "brand", "price", "stock"}
    missing_headers = sorted(required_headers - set(header_for_field))
    if missing_headers:
        raise ValueError("El export no contiene columnas obligatorias para crear: " + ", ".join(missing_headers))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Productos"
    ws.append(list(snapshot.raw_headers))

    row = [None] * len(snapshot.raw_headers)
    for field, value in draft.values.items():
        raw_header = header_for_field.get(field)
        if raw_header is None:
            continue
        index = snapshot.raw_headers.index(raw_header)
        row[index] = _export_value(field, value)
    ws.append(row)

    sku_col = snapshot.canonical_headers.index("sku") + 1
    sku_cell = ws.cell(2, sku_col)
    sku_cell.value = str(draft.sku)
    sku_cell.number_format = "@"
    wb.save(output_path)
    return CreateWorkbookReceipt(
        path=output_path,
        sku=draft.sku,
        fields=frozenset(field for field in draft.values if field in header_for_field),
    )
