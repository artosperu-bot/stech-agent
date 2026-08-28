from __future__ import annotations

import pytest

from stech_agent.agent.resolver import resolve_decision
from stech_agent.agent.schema import PlannerDecision
from stech_agent.domain.models import ProductRecord


def _decision(brand: str) -> PlannerDecision:
    return PlannerDecision.from_dict({
        "action": "GENERATE_SEO",
        "target": {
            "skus": [],
            "name": None,
            "brand": brand,
            "category": None,
            "subcategory": None,
            "stock_lt": None,
            "stock_gt": None,
            "on_offer": None,
            "visible": None,
            "use_working_set": False,
            "allow_multiple_name_matches": False,
            "all_products": False,
        },
        "section": "seo",
        "fields": ["seo_title", "seo_description", "seo_keywords", "seo_faq"],
        "values": {},
        "mode": "FILL_MISSING",
        "research_required": True,
        "clarification_required": False,
        "clarification_question": None,
        "explanation": f"Revisar y completar SEO de {brand}.",
    })


def _products():
    return [
        ProductRecord(sku="JBL-1", name="JBL Uno", brand="JBL", source_order=1),
        ProductRecord(sku="JBL-2", name="JBL Dos", brand="JBL", source_order=2),
        ProductRecord(sku="EPSON-1", name="Epson Uno", brand="EPSON", source_order=3),
        ProductRecord(sku="LENOVO-1", name="Lenovo Uno", brand="Lenovo", source_order=4),
        ProductRecord(sku="LOGI-1", name="Logitech Uno", brand="Logitech", source_order=5),
    ]


@pytest.mark.parametrize(
    ("brand", "expected_skus"),
    [
        ("JBL", ("JBL-1", "JBL-2")),
        ("EPSON", ("EPSON-1",)),
        ("Lenovo", ("LENOVO-1",)),
        ("LOGITECH", ("LOGI-1",)),
    ],
)
def test_generate_seo_filters_any_brand_from_catalog(brand, expected_skus):
    resolved = resolve_decision(_decision(brand), _products())
    assert resolved.skus == expected_skus
    assert resolved.blocked_skus == ()


def test_generate_seo_brand_filter_is_case_insensitive():
    resolved = resolve_decision(_decision("lenovo"), _products())
    assert resolved.skus == ("LENOVO-1",)
