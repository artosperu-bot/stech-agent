from stech_agent.agent.guided_menu import main_menu_text, normalize_local_command, section_fields


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
