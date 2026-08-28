from __future__ import annotations

from decimal import Decimal

from stech_agent.agent.guided_menu import (
    create_confirmation_text,
    main_menu_text,
    normalize_local_command,
    product_create_reference_values,
)
from stech_agent.agent.product_creation import ProductCreateDraft
from stech_agent.domain.models import ProductRecord


def products():
    return [
        ProductRecord(sku="J1", name="JBL Uno", brand="JBL", category="Audio", subcategory="Parlantes Bluetooth", status="Activo", source_order=1),
        ProductRecord(sku="J2", name="JBL Dos", brand="JBL", category="Audio", subcategory="Audífonos Bluetooth", status="Activo", source_order=2),
        ProductRecord(sku="E1", name="Epson Uno", brand="EPSON", category="Impresión", subcategory="Impresoras", status="Activo", source_order=3),
    ]


def test_main_menu_exposes_create_product_option():
    assert "8. Agregar nuevo producto" in main_menu_text()


def test_natural_create_commands_open_same_guided_create_flow():
    for command in ("8", "agregar nuevo producto", "crear producto", "nuevo producto"):
        assert normalize_local_command(command) == "create_product"


def test_reference_values_come_from_current_catalog():
    refs = product_create_reference_values(products())
    assert refs["brands"] == ("JBL", "EPSON")
    assert refs["categories"] == ("Audio", "Impresión")
    assert refs["subcategories_by_category"]["Audio"] == ("Parlantes Bluetooth", "Audífonos Bluetooth")
    assert refs["statuses"] == ("Activo",)


def test_create_confirmation_is_human_readable_and_requires_crear():
    draft = ProductCreateDraft(
        sku="NEW-001",
        values={
            "sku": "NEW-001", "name": "Producto Nuevo", "brand": "JBL", "category": "Audio",
            "subcategory": "Parlantes Bluetooth", "price": Decimal("199.90"), "stock": 5,
            "visible": False, "on_offer": False, "recommended": False, "featured": False,
            "is_new": False, "discount": Decimal("0"), "description": "", "status": "",
            "main_specs": "", "technical_specs": "", "image": "", "gallery": "",
            "discount_rule": "", "promotions": "",
        },
    )
    text = create_confirmation_text(draft)
    assert "CREAR NUEVO PRODUCTO" in text
    assert "NEW-001" in text
    assert "Producto Nuevo" in text
    assert "Visible inicialmente: No" in text
    assert "Escribe CREAR" in text
    assert "CANCELAR" in text
