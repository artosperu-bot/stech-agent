from __future__ import annotations

import pytest

from stech_agent.domain.models import FieldPatch, MutationMode
from stech_agent.domain.scopes import (
    build_scoped_patch,
    fields_for_section,
    resolve_field_path,
    resolve_section,
)


def test_seo_section_expands_to_all_seo_inputs():
    assert fields_for_section("seo") == frozenset(
        {"seo_title", "seo_description", "seo_keywords", "seo_faq"}
    )


def test_specific_seo_field_resolves_without_authorizing_other_inputs():
    assert resolve_field_path("título SEO") == "seo_title"
    patch = build_scoped_patch(
        section="seo",
        requested_fields=["título SEO"],
        values={"seo_title": "Nuevo título"},
        mode=MutationMode.PATCH,
    )
    assert patch.fields == frozenset({"seo_title"})
    assert patch.authorized_fields == frozenset({"seo_title"})


def test_fill_missing_only_keeps_empty_authorized_fields():
    patch = build_scoped_patch(
        section="seo",
        requested_fields=None,
        values={
            "seo_title": "Título nuevo",
            "seo_description": "Descripción nueva",
            "seo_keywords": "jbl, parlante",
            "seo_faq": [{"q": "¿Es resistente?", "a": "Sí"}],
        },
        current_values={
            "seo_title": "Título existente",
            "seo_description": "",
            "seo_keywords": None,
            "seo_faq": [],
        },
        mode=MutationMode.FILL_MISSING,
    )
    assert patch.fields == frozenset({"seo_description", "seo_keywords", "seo_faq"})
    assert "seo_title" not in patch.values


def test_patch_rejects_value_outside_explicit_authorization():
    with pytest.raises(ValueError, match="no autorizados"):
        build_scoped_patch(
            section="seo",
            requested_fields=["keywords"],
            values={"seo_keywords": "epson, impresora", "seo_title": "NO TOCAR"},
            mode=MutationMode.PATCH,
        )


def test_field_patch_enforces_authorized_fields_at_domain_boundary():
    with pytest.raises(ValueError, match="no autorizados"):
        FieldPatch(
            values={"price": 100, "stock": 9},
            authorized_fields=frozenset({"stock"}),
        )


def test_replace_section_requires_explicit_section_scope():
    with pytest.raises(ValueError, match="sección completa"):
        build_scoped_patch(
            section="seo",
            requested_fields=["título SEO"],
            values={"seo_title": "X"},
            mode=MutationMode.REPLACE_SECTION,
        )


def test_sections_cover_product_editor_groups():
    assert fields_for_section("información básica") == frozenset(
        {"name", "description", "category", "subcategory", "brand"}
    )
    assert fields_for_section("precios y stock") == frozenset({"price", "discount", "stock"})
    assert fields_for_section("características") == frozenset({"main_specs", "technical_specs"})
    assert fields_for_section("multimedia") == frozenset({"image", "gallery"})
    assert fields_for_section("comercial") == frozenset(
        {"is_new", "on_offer", "recommended", "featured", "visible", "status", "discount_rule", "promotions"}
    )


def test_natural_aliases_resolve_to_canonical_fields_and_sections():
    assert resolve_section("precios y stock") == "pricing"
    assert resolve_section("informacion basica") == "basic"
    assert resolve_field_path("meta descripción") == "seo_description"
    assert resolve_field_path("palabras clave") == "seo_keywords"
    assert resolve_field_path("preguntas frecuentes") == "seo_faq"
    assert resolve_field_path("existencias") == "stock"
    assert resolve_field_path("características principales") == "main_specs"
    assert resolve_field_path("especificaciones técnicas") == "technical_specs"
