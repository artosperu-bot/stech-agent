from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from stech_agent.domain.fields import FIELD_REGISTRY
from stech_agent.domain.models import FieldPatch, MutationMode


SECTION_FIELDS: dict[str, frozenset[str]] = {
    "basic": frozenset({"name", "description", "category", "subcategory", "brand"}),
    "pricing": frozenset({"price", "discount", "stock"}),
    "features": frozenset({"main_specs", "technical_specs"}),
    "multimedia": frozenset({"image", "gallery"}),
    "seo": frozenset({"seo_title", "seo_description", "seo_keywords", "seo_faq"}),
    "commercial": frozenset(
        {"is_new", "on_offer", "recommended", "featured", "visible", "status", "discount_rule", "promotions"}
    ),
}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


_SECTION_ALIASES = {
    "basic": "basic",
    "informacion basica": "basic",
    "datos basicos": "basic",
    "ficha basica": "basic",
    "pricing": "pricing",
    "precio": "pricing",
    "precios": "pricing",
    "stock": "pricing",
    "precios y stock": "pricing",
    "precio y stock": "pricing",
    "features": "features",
    "caracteristicas": "features",
    "especificaciones": "features",
    "caracteristicas y especificaciones": "features",
    "multimedia": "multimedia",
    "imagenes": "multimedia",
    "imagen y galeria": "multimedia",
    "seo": "seo",
    "optimizacion seo": "seo",
    "google": "seo",
    "commercial": "commercial",
    "comercial": "commercial",
    "visibilidad y oferta": "commercial",
}


_FIELD_ALIASES: dict[str, str] = {
    # Basic
    "name": "name",
    "nombre": "name",
    "nombre producto": "name",
    "nombre del producto": "name",
    "titulo producto": "name",
    "description": "description",
    "descripcion": "description",
    "descripcion producto": "description",
    "category": "category",
    "categoria": "category",
    "subcategory": "subcategory",
    "subcategoria": "subcategory",
    "brand": "brand",
    "marca": "brand",
    # Pricing / stock
    "price": "price",
    "precio": "price",
    "precio de venta": "price",
    "discount": "discount",
    "descuento": "discount",
    "stock": "stock",
    "existencias": "stock",
    "unidades": "stock",
    "unidades disponibles": "stock",
    # Features
    "main specs": "main_specs",
    "main_specs": "main_specs",
    "caracteristicas principales": "main_specs",
    "especificaciones principales": "main_specs",
    "technical specs": "technical_specs",
    "technical_specs": "technical_specs",
    "especificaciones tecnicas": "technical_specs",
    "detalles tecnicos": "technical_specs",
    # Multimedia
    "image": "image",
    "imagen": "image",
    "imagen principal": "image",
    "gallery": "gallery",
    "galeria": "gallery",
    "imagenes galeria": "gallery",
    # SEO
    "seo_title": "seo_title",
    "seo title": "seo_title",
    "titulo seo": "seo_title",
    "meta title": "seo_title",
    "titulo de google": "seo_title",
    "seo_description": "seo_description",
    "seo description": "seo_description",
    "descripcion seo": "seo_description",
    "meta descripcion": "seo_description",
    "meta description": "seo_description",
    "seo_keywords": "seo_keywords",
    "seo keywords": "seo_keywords",
    "keywords": "seo_keywords",
    "palabras clave": "seo_keywords",
    "seo_faq": "seo_faq",
    "seo faq": "seo_faq",
    "faq": "seo_faq",
    "preguntas frecuentes": "seo_faq",
    "preguntas y respuestas": "seo_faq",
    # Commercial
    "is_new": "is_new",
    "es nuevo": "is_new",
    "nuevo": "is_new",
    "on_offer": "on_offer",
    "en oferta": "on_offer",
    "oferta": "on_offer",
    "recommended": "recommended",
    "recomendado": "recommended",
    "featured": "featured",
    "destacado": "featured",
    "visible": "visible",
    "visibilidad": "visible",
    "status": "status",
    "estado": "status",
    "discount_rule": "discount_rule",
    "regla de descuento": "discount_rule",
    "promotions": "promotions",
    "promociones": "promotions",
}


# Context-specific short names. These are intentionally resolved only when the
# section is known, avoiding the classic ambiguity between product description
# and SEO description.
_CONTEXT_ALIASES: dict[str, dict[str, str]] = {
    "seo": {
        "titulo": "seo_title",
        "title": "seo_title",
        "descripcion": "seo_description",
        "description": "seo_description",
        "palabras": "seo_keywords",
        "preguntas": "seo_faq",
    },
    "basic": {
        "titulo": "name",
        "descripcion": "description",
    },
}


def resolve_section(section: str) -> str:
    normalized = _norm(section)
    resolved = _SECTION_ALIASES.get(normalized)
    if resolved is None:
        raise KeyError(f"Sección desconocida: {section}")
    return resolved


def resolve_field_path(field: str, *, section: str | None = None) -> str:
    normalized = _norm(field)
    section_key = resolve_section(section) if section is not None else None
    if section_key and normalized in _CONTEXT_ALIASES.get(section_key, {}):
        resolved = _CONTEXT_ALIASES[section_key][normalized]
    else:
        resolved = _FIELD_ALIASES.get(normalized)
    if resolved is None and field in FIELD_REGISTRY:
        resolved = field
    if resolved is None:
        raise KeyError(f"Campo desconocido: {field}")
    if section_key and resolved not in SECTION_FIELDS[section_key]:
        raise ValueError(f"El campo {field!r} no pertenece a la sección {section_key}")
    return resolved


def fields_for_section(section: str) -> frozenset[str]:
    return SECTION_FIELDS[resolve_section(section)]


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return len(value) == 0
    return False


def _normalize_value_keys(values: dict[str, Any], *, section: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_field, value in values.items():
        field = resolve_field_path(raw_field, section=section)
        if field in normalized:
            raise ValueError(f"Campo repetido después de normalizar: {field}")
        normalized[field] = value
    return normalized


def build_scoped_patch(
    *,
    section: str,
    requested_fields: Iterable[str] | None,
    values: dict[str, Any],
    mode: MutationMode = MutationMode.PATCH,
    current_values: dict[str, Any] | None = None,
) -> FieldPatch:
    """Build a hard field-authorized patch for one product editor section.

    ``requested_fields=None`` means the whole section was explicitly selected.
    Supplying field names means only those exact inputs are authorized.
    ``FILL_MISSING`` filters out fields that already contain a meaningful value.
    ``REPLACE_SECTION`` is accepted only for an explicit whole-section request.
    """

    section_key = resolve_section(section)
    whole_section = requested_fields is None
    if whole_section:
        authorized = SECTION_FIELDS[section_key]
    else:
        authorized = frozenset(resolve_field_path(item, section=section_key) for item in requested_fields)
        if not authorized:
            raise ValueError("Debe autorizarse al menos un campo")

    if mode is MutationMode.REPLACE_SECTION and not whole_section:
        raise ValueError("REPLACE_SECTION requiere autorización de la sección completa")

    normalized_values = _normalize_value_keys(values, section=section_key)
    unauthorized = frozenset(normalized_values) - authorized
    if unauthorized:
        raise ValueError("Campos no autorizados: " + ", ".join(sorted(unauthorized)))

    if mode is MutationMode.READ:
        if normalized_values:
            raise ValueError("READ no puede contener valores para modificar")
        return FieldPatch(
            values={},
            mode=mode,
            section=section_key,
            authorized_fields=authorized,
        )

    if mode is MutationMode.FILL_MISSING:
        current = _normalize_value_keys(current_values or {}, section=section_key)
        normalized_values = {
            field: value
            for field, value in normalized_values.items()
            if _is_missing(current.get(field))
        }

    return FieldPatch(
        values=normalized_values,
        mode=mode,
        section=section_key,
        authorized_fields=authorized,
    )
