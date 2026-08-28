from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    key: str
    headers: tuple[str, ...]
    mutable: bool
    risk: str
    coercer: Callable[[Any], Any]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _identity(value: Any) -> Any:
    return value


def _sku(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace("S/", "").replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Valor monetario inválido: {value!r}") from exc


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return int(str(value).strip())


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def _bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _normalize(str(value))
    if text in {"si", "yes", "true", "1", "activo", "visible"}:
        return True
    if text in {"no", "false", "0", "inactivo", "oculto"}:
        return False
    raise ValueError(f"Booleano inválido: {value!r}")


FIELD_REGISTRY: dict[str, FieldDefinition] = {
    "sku": FieldDefinition("sku", ("SKU",), False, "R3", _sku),
    "name": FieldDefinition("name", ("Nombre del producto", "Nombre"), True, "R1", _text),
    "description": FieldDefinition("description", ("Descripcion", "Descripción"), True, "R1", _text),
    "category": FieldDefinition("category", ("Categoria", "Categoría"), True, "R1", _text),
    "subcategory": FieldDefinition("subcategory", ("Subcategoría", "Subcategoria"), True, "R1", _text),
    "brand": FieldDefinition("brand", ("Marca",), True, "R1", _text),
    "price": FieldDefinition("price", ("Precio",), True, "R3", _decimal),
    "discount": FieldDefinition("discount", ("Descuento",), True, "R3", _decimal),
    "stock": FieldDefinition("stock", ("Stock",), True, "R3", _int),
    "is_new": FieldDefinition("is_new", ("Es nuevo",), True, "R2", _bool),
    "on_offer": FieldDefinition("on_offer", ("En oferta",), True, "R2", _bool),
    "recommended": FieldDefinition("recommended", ("Recomendado",), True, "R2", _bool),
    "featured": FieldDefinition("featured", ("Destacado",), True, "R2", _bool),
    "visible": FieldDefinition("visible", ("Visible",), True, "R2", _bool),
    "status": FieldDefinition("status", ("Estado",), True, "R2", _text),
    "main_specs": FieldDefinition("main_specs", ("Especificaciones principales (separadas por coma)", "Características principales"), True, "R1", _text),
    "technical_specs": FieldDefinition("technical_specs", ("Especificaciones técnicas (separadas por slash y dos puntos)",), True, "R1", _text),
    "image": FieldDefinition("image", ("Imagen",), True, "R2", _text),
    "gallery": FieldDefinition("gallery", ("Galería", "Galeria"), True, "R2", _text),
    "discount_rule": FieldDefinition("discount_rule", ("Regla de descuento",), True, "R3", _text),
    "promotions": FieldDefinition("promotions", ("Promociones",), True, "R3", _text),
    # Live-only SEO fields. They are intentionally not bound to Excel headers;
    # they are read/written from the S-TECH SEO tab and persisted separately.
    "seo_title": FieldDefinition("seo_title", (), True, "R1", _text),
    "seo_description": FieldDefinition("seo_description", (), True, "R1", _text),
    "seo_keywords": FieldDefinition("seo_keywords", (), True, "R1", _text),
    "seo_faq": FieldDefinition("seo_faq", (), True, "R1", _identity),
}

_HEADER_TO_KEY: dict[str, str] = {}
for key, definition in FIELD_REGISTRY.items():
    for header in definition.headers:
        _HEADER_TO_KEY[_normalize(header)] = key


def resolve_header(header: str) -> str:
    normalized = _normalize(str(header))
    return _HEADER_TO_KEY.get(normalized, f"extra:{normalized}")


def coerce_field(field: str, value: Any) -> Any:
    if field.startswith("extra:"):
        return value
    definition = FIELD_REGISTRY.get(field)
    if definition is None:
        raise KeyError(field)
    return definition.coercer(value)
