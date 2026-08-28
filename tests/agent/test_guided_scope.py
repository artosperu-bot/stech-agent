from __future__ import annotations

from stech_agent.agent.guided_menu import resolve_guided_scope, scope_menu_text
from stech_agent.domain.models import ProductRecord


def _products():
    return [
        ProductRecord(sku="J1", name="JBL Uno", brand="JBL", category="Audio", subcategory="Parlantes", source_order=1),
        ProductRecord(sku="J2", name="JBL Dos", brand="JBL", category="Audio", subcategory="Audífonos", source_order=2),
        ProductRecord(sku="E1", name="Epson Uno", brand="EPSON", category="Impresión", subcategory="Impresoras", source_order=3),
        ProductRecord(sku="AMB", name="JBL Ambiguo", brand="JBL", category="Audio", subcategory="Parlantes", ambiguous=True, source_order=4),
    ]


def test_scope_menu_exposes_single_all_brand_category_subcategory_and_working_set():
    text = scope_menu_text()
    assert "Un producto" in text
    assert "Todos los productos" in text
    assert "Por Marca" in text
    assert "Por Categoría" in text
    assert "Por Subcategoría" in text
    assert 'Conjunto actual ("de esos")' in text


def test_scope_by_brand_is_case_and_accent_insensitive_and_separates_ambiguous():
    result = resolve_guided_scope(_products(), "brand", value="jbl")
    assert result.label == "Marca: JBL"
    assert result.skus == ("J1", "J2")
    assert result.blocked_skus == ("AMB",)
    assert result.total_matches == 3


def test_scope_by_category_and_subcategory_use_exact_normalized_values():
    category = resolve_guided_scope(_products(), "category", value="audio")
    subcategory = resolve_guided_scope(_products(), "subcategory", value="parlantes")
    assert category.skus == ("J1", "J2")
    assert category.blocked_skus == ("AMB",)
    assert subcategory.skus == ("J1",)
    assert subcategory.blocked_skus == ("AMB",)


def test_scope_all_returns_every_nonambiguous_product_and_blocks_ambiguous_rows():
    result = resolve_guided_scope(_products(), "all")
    assert result.skus == ("J1", "J2", "E1")
    assert result.blocked_skus == ("AMB",)
    assert result.total_matches == 4


def test_scope_working_set_preserves_catalog_order_and_ignores_unknown_skus():
    result = resolve_guided_scope(
        _products(),
        "working_set",
        working_set_skus=("E1", "J1", "NO-EXISTE"),
    )
    assert result.skus == ("J1", "E1")
    assert result.blocked_skus == ()
    assert result.total_matches == 2


def test_scope_requires_value_for_brand_category_and_subcategory():
    for kind in ("brand", "category", "subcategory"):
        try:
            resolve_guided_scope(_products(), kind)
        except ValueError as exc:
            assert "indicar" in str(exc).lower()
        else:
            raise AssertionError(f"{kind} debió exigir un valor")
