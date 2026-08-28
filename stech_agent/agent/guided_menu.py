from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True, slots=True)
class GuidedField:
    key: str
    label: str
    enabled: bool
    note: str = ""


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
