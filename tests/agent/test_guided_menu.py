from stech_agent.agent.guided_menu import (
    confirmation_text,
    main_menu_text,
    normalize_local_command,
    resolve_product_reference,
    section_fields,
)
from stech_agent.domain.models import ProductRecord


def test_main_menu_offers_chat_guided_history_and_rollback():
    text = main_menu_text()
    assert "Chat libre" in text
    assert "Información Básica" in text
    assert "Precios y Stock" in text
    assert "SEO" in text
    assert "Multimedia" in text
    assert "Historial" in text
    assert "Deshacer" in text


def test_common_local_phrases_route_without_using_model():
    assert normalize_local_command("menu") == "menu"
    assert normalize_local_command("cambiar información básica") == "guided:basic"
    assert normalize_local_command("cambiar precios y stock") == "guided:pricing"
    assert normalize_local_command("ver historial de cambios") == "history"
    assert normalize_local_command("deshacer cambios de esta sesión") == "rollback"
    assert normalize_local_command("buscame producto test y cambia stock a 2") is None


def test_guided_sections_expose_only_certified_writes_as_enabled():
    basic = {item.key: item for item in section_fields("basic")}
    pricing = {item.key: item for item in section_fields("pricing")}
    seo = {item.key: item for item in section_fields("seo")}
    multimedia = {item.key: item for item in section_fields("multimedia")}

    assert basic["name"].enabled is True
    assert basic["description"].enabled is True
    assert basic["category"].enabled is False
    assert pricing["stock"].enabled is True
    assert pricing["price"].enabled is True
    assert seo["seo_keywords"].enabled is True
    assert multimedia["image"].enabled is False


def test_guided_product_reference_accepts_exact_sku_or_normalized_exact_name():
    products = [
        ProductRecord(sku="PROD-TEST", name="Producto Test"),
        ProductRecord(sku="ABC-1", name="Cámara Acción Pro"),
    ]
    assert resolve_product_reference(products, "PROD-TEST").sku == "PROD-TEST"
    assert resolve_product_reference(products, "producto test").sku == "PROD-TEST"
    assert resolve_product_reference(products, "camara accion pro").sku == "ABC-1"


def test_guided_product_reference_refuses_ambiguous_name():
    products = [
        ProductRecord(sku="A", name="Producto Igual"),
        ProductRecord(sku="B", name="Producto Igual"),
    ]
    try:
        resolve_product_reference(products, "producto igual")
        assert False, "expected ambiguity error"
    except ValueError as exc:
        assert "más de un producto" in str(exc)


def test_confirmation_text_requires_explicit_accept_word():
    product = ProductRecord(sku="PROD-TEST", name="Producto Test")
    text = confirmation_text(product, {"stock": 3, "price": "1.50"})
    assert "Producto Test (PROD-TEST)" in text
    assert "stock = 3" in text
    assert "price = 1.50" in text
    assert "ACEPTAR" in text
    assert "CANCELAR" in text
