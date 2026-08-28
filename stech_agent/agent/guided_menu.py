from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable, Any

from stech_agent.domain.models import ProductRecord


@dataclass(frozen=True, slots=True)
class GuidedField:
    key: str
    label: str
    enabled: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class GuidedScope:
    label: str
    skus: tuple[str, ...]
    blocked_skus: tuple[str, ...]
    total_matches: int


_SECTION_FIELDS: dict[str, tuple[GuidedField, ...]] = {
    "basic": (
        GuidedField("name", "Nombre del producto", True),
        GuidedField("description", "Descripción", True),
        GuidedField("category", "Categoría", False, "selector live pendiente de certificar"),
        GuidedField("subcategory", "Subcategoría", False, "selector live pendiente de certificar"),
        GuidedField("brand", "Marca", False, "selector live pendiente de certificar"),
    ),
    "pricing": (
        GuidedField("price", "Precio de Venta", True),
        GuidedField("stock", "Stock Disponible", True),
        GuidedField("discount", "Precio con Descuento", False, "pendiente de certificar en ejecución live"),
    ),
    "seo": (
        GuidedField("seo_title", "Título SEO", True),
        GuidedField("seo_description", "Descripción SEO", True),
        GuidedField("seo_keywords", "Keywords SEO", True),
        GuidedField("seo_faq", "Preguntas frecuentes", False, "lectura/verificación disponible; edición guiada pendiente"),
    ),
    "multimedia": (
        GuidedField("image", "Imagen principal", False, "subida de imágenes se conectará después"),
        GuidedField("gallery", "Galería", False, "subida de imágenes se conectará después"),
    ),
}


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return text


def section_fields(section: str) -> tuple[GuidedField, ...]:
    key = _norm(section)
    aliases = {
        "basic": "basic",
        "informacion basica": "basic",
        "pricing": "pricing",
        "precios": "pricing",
        "precios y stock": "pricing",
        "seo": "seo",
        "multimedia": "multimedia",
    }
    resolved = aliases.get(key)
    if resolved is None:
        raise KeyError(f"Sección guiada desconocida: {section}")
    return _SECTION_FIELDS[resolved]


def section_menu_text(section: str) -> str:
    fields = section_fields(section)
    lines = []
    for idx, item in enumerate(fields, start=1):
        suffix = "" if item.enabled else f"  [PENDIENTE: {item.note}]"
        lines.append(f"{idx}. {item.label}{suffix}")
    lines.append("0. Volver")
    return "\n".join(lines)


def scope_menu_text() -> str:
    return (
        "\n¿A QUÉ PRODUCTOS QUIERES APLICARLO?\n"
        "1. Un producto\n"
        "2. Todos los productos\n"
        "3. Por Marca\n"
        "4. Por Categoría\n"
        "5. Por Subcategoría\n"
        "6. Conjunto actual (\"de esos\")\n"
        "0. Volver\n"
    )


def scope_kind_from_choice(choice: str) -> str | None:
    return {
        "1": "single",
        "2": "all",
        "3": "brand",
        "4": "category",
        "5": "subcategory",
        "6": "working_set",
        "0": None,
    }.get(str(choice).strip())


def main_menu_text() -> str:
    return (
        "\nOPCIONES RÁPIDAS\n"
        "1. Chat libre (puedes seguir escribiendo órdenes naturales)\n"
        "2. Cambiar Información Básica\n"
        "3. Cambiar Precios y Stock\n"
        "4. SEO: editar campos o verificar si está completo\n"
        "5. Multimedia (consulta; subida de imágenes después)\n"
        "6. Historial de cambios de esta sesión\n"
        "7. Deshacer cambios de esta sesión\n"
        "0. Salir\n"
    )


def normalize_local_command(command: str) -> str | None:
    text = _norm(command)
    if text in {"menu", "opciones", "ayuda", "ver menu"}:
        return "menu"
    if text in {"2", "cambiar informacion basica", "editar informacion basica", "informacion basica"}:
        return "guided:basic"
    if text in {"3", "cambiar precios y stock", "editar precios y stock", "precios y stock"}:
        return "guided:pricing"
    if text in {"4", "menu seo", "editar seo", "cambiar seo"}:
        return "guided:seo"
    if text in {"5", "menu multimedia", "multimedia"}:
        return "guided:multimedia"
    if text in {"6", "historial", "ver historial", "ver historial de cambios", "historial de cambios", "cambios de esta sesion"}:
        return "history"
    if text in {"7", "deshacer", "deshacer cambios", "deshacer cambios de esta sesion", "revertir cambios de esta sesion"}:
        return "rollback"
    if text == "0":
        return "exit"
    return None


def resolve_product_reference(products: Iterable[ProductRecord], reference: str) -> ProductRecord:
    reference_text = str(reference).strip()
    if not reference_text:
        raise ValueError("Debes indicar un SKU o nombre de producto")
    items = list(products)

    for product in items:
        if product.sku.casefold() == reference_text.casefold():
            return product

    wanted = _norm(reference_text)
    matches = [product for product in items if _norm(product.name) == wanted]
    if not matches:
        raise ValueError(f"No encontré un producto con SKU o nombre exacto {reference_text!r}")
    if len(matches) > 1:
        skus = ", ".join(product.sku for product in matches[:10])
        raise ValueError(f"Encontré más de un producto con ese nombre ({skus}). Usa el SKU exacto.")
    return matches[0]


def _split_scope(matches: list[ProductRecord], label: str) -> GuidedScope:
    if not matches:
        raise ValueError(f"No encontré productos para {label}")
    allowed = tuple(product.sku for product in matches if not product.ambiguous)
    blocked = tuple(product.sku for product in matches if product.ambiguous)
    return GuidedScope(
        label=label,
        skus=allowed,
        blocked_skus=blocked,
        total_matches=len(matches),
    )


def resolve_guided_scope(
    products: Iterable[ProductRecord],
    kind: str,
    *,
    value: str | None = None,
    working_set_skus: Iterable[str] = (),
) -> GuidedScope:
    items = list(products)
    scope = _norm(kind)

    if scope in {"single", "uno", "un producto", "producto"}:
        if not str(value or "").strip():
            raise ValueError("Debes indicar un SKU o nombre de producto")
        product = resolve_product_reference(items, str(value))
        return _split_scope([product], f"Producto: {product.name or product.sku}")

    if scope in {"all", "todos", "todos los productos"}:
        return _split_scope(items, "Todos los productos")

    if scope in {"working set", "working_set", "conjunto actual", "de esos"}:
        wanted = {str(sku).strip() for sku in working_set_skus if str(sku).strip()}
        if not wanted:
            raise ValueError("No hay un conjunto actual. Primero selecciona o busca productos en el chat.")
        matches = [product for product in items if product.sku in wanted]
        return _split_scope(matches, 'Conjunto actual ("de esos")')

    field_by_scope = {
        "brand": ("brand", "Marca"),
        "marca": ("brand", "Marca"),
        "category": ("category", "Categoría"),
        "categoria": ("category", "Categoría"),
        "subcategory": ("subcategory", "Subcategoría"),
        "subcategoria": ("subcategory", "Subcategoría"),
    }
    resolved = field_by_scope.get(scope)
    if resolved is None:
        raise ValueError(f"Alcance desconocido: {kind}")
    field, label_name = resolved
    if not str(value or "").strip():
        raise ValueError(f"Debes indicar {label_name.lower()} para usar ese alcance")

    wanted = _norm(str(value))
    matches = [product for product in items if _norm(getattr(product, field, "")) == wanted]
    if not matches:
        raise ValueError(f"No encontré productos con {label_name.lower()} {value!r}")
    canonical = str(getattr(matches[0], field, "") or value).strip()
    return _split_scope(matches, f"{label_name}: {canonical}")


def confirmation_text(product: ProductRecord, values: dict[str, Any]) -> str:
    lines = [
        "\nCONFIRMAR CAMBIO",
        f"Producto: {product.name or product.sku} ({product.sku})",
        "Cambios solicitados:",
    ]
    for field, value in values.items():
        lines.append(f"  - {field} = {value}")
    lines.extend([
        "",
        "Escribe ACEPTAR para guardar en S-TECH.",
        "Escribe CANCELAR para no hacer ningún cambio.",
    ])
    return "\n".join(lines)


def bulk_confirmation_text(scope: GuidedScope, values: dict[str, Any]) -> str:
    lines = [
        "\nCONFIRMAR CAMBIO",
        f"Alcance: {scope.label}",
        f"Productos encontrados: {scope.total_matches}",
        f"Productos aplicables: {len(scope.skus)}",
        f"Bloqueados por ambigüedad: {len(scope.blocked_skus)}",
        "Cambios solicitados:",
    ]
    for field, value in values.items():
        lines.append(f"  - {field} = {value}")
    if scope.blocked_skus:
        preview = ", ".join(scope.blocked_skus[:10])
        suffix = " ..." if len(scope.blocked_skus) > 10 else ""
        lines.append(f"SKU bloqueados: {preview}{suffix}")
    lines.extend([
        "",
        "Escribe ACEPTAR para ejecutar y verificar cada producto en S-TECH.",
        "Escribe CANCELAR para no hacer ningún cambio.",
    ])
    return "\n".join(lines)
