from __future__ import annotations

import pytest

from stech_agent.agent.resolver import ResolutionNeedsClarification, resolve_decision
from stech_agent.agent.schema import PlannerDecision
from stech_agent.domain.models import ProductRecord


def payload(*, name="producto test", values=None, fields=None, allow_multiple=False, all_products=False):
    return {
        "action": "UPDATE_FIELDS",
        "target": {
            "skus": [],
            "name": name,
            "brand": None,
            "category": None,
            "subcategory": None,
            "stock_lt": None,
            "stock_gt": None,
            "on_offer": None,
            "visible": None,
            "use_working_set": False,
            "allow_multiple_name_matches": allow_multiple,
            "all_products": all_products,
        },
        "section": "pricing",
        "fields": fields if fields is not None else ["stock"],
        "values": values if values is not None else {"stock": 2},
        "mode": "PATCH",
        "research_required": False,
        "clarification_required": False,
        "clarification_question": None,
        "explanation": "Cambiar stock a 2.",
    }


def products():
    return [
        ProductRecord(sku="PROD-TEST", name="Producto Test", stock=1, source_order=1),
        ProductRecord(sku="OTRO", name="Otro Producto", stock=4, source_order=2),
    ]


def test_exact_normalized_name_resolves_unique_sku_and_explicit_value():
    decision = PlannerDecision.from_dict(payload(name="  PRODUCTO   TÉST ", values={"stock": "2"}))
    resolved = resolve_decision(decision, products())

    assert resolved.skus == ("PROD-TEST",)
    assert resolved.patch is not None
    assert resolved.patch.authorized_fields == frozenset({"stock"})
    assert resolved.patch.values == {"stock": 2}


def test_duplicate_exact_name_blocks_mutation_unless_user_explicitly_allows_multiple():
    duplicated = products() + [
        ProductRecord(sku="PROD-TEST-2", name="Producto Test", stock=5, source_order=3)
    ]
    decision = PlannerDecision.from_dict(payload())

    with pytest.raises(ResolutionNeedsClarification, match="más de un producto") as exc:
        resolve_decision(decision, duplicated)

    assert exc.value.candidate_skus == ("PROD-TEST", "PROD-TEST-2")


def test_explicit_multiple_name_authorization_allows_all_exact_matches():
    duplicated = products() + [
        ProductRecord(sku="PROD-TEST-2", name="Producto Test", stock=5, source_order=3)
    ]
    decision = PlannerDecision.from_dict(payload(allow_multiple=True))

    resolved = resolve_decision(decision, duplicated)

    assert resolved.skus == ("PROD-TEST", "PROD-TEST-2")


def test_missing_exact_name_blocks_mutation_instead_of_guessing():
    decision = PlannerDecision.from_dict(payload(name="producto inexistente"))
    with pytest.raises(ResolutionNeedsClarification, match="No encontré"):
        resolve_decision(decision, products())


def test_mutation_without_any_target_is_blocked_unless_all_products_is_explicit():
    no_target = payload(name=None)
    decision = PlannerDecision.from_dict(no_target)
    with pytest.raises(ResolutionNeedsClarification, match="objetivo"):
        resolve_decision(decision, products())

    all_target = payload(name=None, all_products=True)
    resolved = resolve_decision(PlannerDecision.from_dict(all_target), products())
    assert resolved.skus == ("PROD-TEST", "OTRO")


def test_patch_without_value_is_blocked_before_executor():
    decision = PlannerDecision.from_dict(payload(values={}))
    with pytest.raises(ResolutionNeedsClarification, match="valor"):
        resolve_decision(decision, products())


def test_value_for_unauthorized_field_is_rejected():
    decision = PlannerDecision.from_dict(payload(values={"price": 99}, fields=["stock"]))
    with pytest.raises(ValueError, match="Campos no autorizados"):
        resolve_decision(decision, products())


def test_schema_preserves_target_name_and_mutation_values():
    decision = PlannerDecision.from_dict(payload(values={"stock": 2}))
    data = decision.to_dict()
    assert data["target"]["name"] == "producto test"
    assert data["values"] == {"stock": 2}
