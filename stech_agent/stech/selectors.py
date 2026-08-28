from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class LocatorRecipe:
    role: str | None = None
    name: str | None = None
    description: str | None = None
    exact: bool | None = None
    css: str | None = None
    regex_name: bool = False


RECIPES: dict[str, LocatorRecipe] = {
    "sku_filter": LocatorRecipe("textbox", "Celda de filtro", "Columna SKU"),
    "name_filter": LocatorRecipe("textbox", "Celda de filtro", "Columna Nombre"),
    "brand_filter": LocatorRecipe("textbox", "Celda de filtro", "Columna Marca"),
    "category_filter": LocatorRecipe("textbox", "Celda de filtro", "Columna Categoría"),
    "edit_button": LocatorRecipe("button", description="Editar", exact=True),
    "tab_basic": LocatorRecipe("tab", "Información Básica", regex_name=True),
    "tab_pricing_stock": LocatorRecipe("tab", "Precios y Stock", regex_name=True),
    "tab_multimedia": LocatorRecipe("tab", "Multimedia", regex_name=True),
    "tab_characteristics": LocatorRecipe("tab", "Características", regex_name=True),
    "tab_seo": LocatorRecipe("tab", "SEO", regex_name=True),
    "seo_title": LocatorRecipe("textbox", "Ej: Zapatillas Deportivas"),
    "seo_description": LocatorRecipe("textbox", "Breve resumen del producto"),
    "seo_keywords": LocatorRecipe("textbox", "zapatillas, nike, deporte,"),
    "seo_question": LocatorRecipe("textbox", "Ej: ¿Cuál es el material de", regex_name=True),
    "seo_answer": LocatorRecipe("textbox", "Escribe la respuesta clara y", regex_name=True),
    "seo_add_faq": LocatorRecipe("button", "+ Añadir Pregunta"),
    "export_items": LocatorRecipe("button", "Exportar Items"),
    "import_data": LocatorRecipe("button", "Importar Datos"),
    "accept": LocatorRecipe("button", "Aceptar"),
    "close": LocatorRecipe("button", "Cerrar"),
}


def locate(page: Any, key: str):
    recipe = RECIPES[key]
    if recipe.css:
        return page.locator(recipe.css)
    kwargs: dict[str, Any] = {}
    if recipe.name is not None:
        kwargs["name"] = re.compile(re.escape(recipe.name), re.I) if recipe.regex_name else recipe.name
    if recipe.description is not None:
        kwargs["description"] = recipe.description
    if recipe.exact is not None:
        kwargs["exact"] = recipe.exact
    return page.get_by_role(recipe.role, **kwargs)
