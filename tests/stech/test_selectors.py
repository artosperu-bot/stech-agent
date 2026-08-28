from stech_agent.stech.selectors import RECIPES


def test_primary_selector_recipes_are_accessible_and_not_positional():
    required = {"sku_filter", "name_filter", "brand_filter", "category_filter", "edit_button", "tab_basic", "tab_pricing_stock", "tab_multimedia", "tab_characteristics", "tab_seo", "seo_title", "seo_description", "seo_keywords", "seo_add_faq", "export_items", "import_data", "accept", "close"}
    assert required <= set(RECIPES)
    for key in required:
        recipe = RECIPES[key]
        rendered = f"{recipe.role}|{recipe.name}|{recipe.description}|{recipe.css or ''}".lower()
        assert "nth-child" not in rendered, key
        assert recipe.role or recipe.css


def test_sku_filter_uses_recorded_accessible_description():
    recipe = RECIPES["sku_filter"]
    assert recipe.role == "textbox"
    assert recipe.name == "Celda de filtro"
    assert recipe.description == "Columna SKU"
