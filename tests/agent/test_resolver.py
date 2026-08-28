from __future__ import annotations

from stech_agent.agent.resolver import resolve_decision
from stech_agent.agent.schema import PlannerDecision
from stech_agent.domain.models import ProductRecord


def decision_payload(**overrides):
    payload = {
        "action": "READ",
        "target": {
            "skus": [],
            "brand": "JBL",
            "category": None,
            "subcategory": None,
            "stock_lt": None,
            "stock_gt": 5,
            "on_offer": None,
            "visible": None,
            "use_working_set": False,
        },
        "section": None,
        "fields": [],
        "mode": "READ",
        "research_required": False,
        "clarification_required": False,
        "clarification_question": None,
        "explanation": "JBL con stock mayor a 5.",
    }
    payload.update(overrides)
    return PlannerDecision.from_dict(payload)


def products():
    return [
        ProductRecord(sku="001", brand="JBL", stock=8, source_order=1),
        ProductRecord(sku="002", brand="JBL", stock=3, source_order=2),
        ProductRecord(sku="003", brand="EPSON", stock=10, source_order=3),
    ]


def test_resolver_filters_catalog_locally():
    resolved = resolve_decision(decision_payload(), products())
    assert resolved.skus == ("001",)
    assert resolved.query_explanation == "brand=JBL; stock>5"


def test_resolver_uses_current_working_set_for_de_esos():
    payload = decision_payload().to_dict()
    payload["target"]["brand"] = None
    payload["target"]["stock_gt"] = None
    payload["target"]["use_working_set"] = True
    resolved = resolve_decision(
        PlannerDecision.from_dict(payload),
        products(),
        working_set_skus=("001", "003"),
    )
    assert resolved.skus == ("001", "003")


def test_resolver_authorizes_only_requested_seo_field():
    payload = decision_payload().to_dict()
    payload["action"] = "GENERATE_SEO"
    payload["target"]["brand"] = None
    payload["target"]["stock_gt"] = None
    payload["target"]["use_working_set"] = True
    payload["section"] = "seo"
    payload["fields"] = ["seo_keywords"]
    payload["mode"] = "FILL_MISSING"
    payload["research_required"] = True

    resolved = resolve_decision(
        PlannerDecision.from_dict(payload),
        products(),
        working_set_skus=("001", "003"),
    )

    assert resolved.patch is not None
    assert resolved.patch.authorized_fields == frozenset({"seo_keywords"})
    assert resolved.patch.values == {}
