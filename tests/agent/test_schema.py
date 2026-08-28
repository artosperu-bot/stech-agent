from __future__ import annotations

import pytest

from stech_agent.agent.schema import PLANNER_JSON_SCHEMA, PlannerDecision
from stech_agent.domain.models import ActionType, MutationMode


def payload(**overrides):
    data = {
        "action": "GENERATE_SEO",
        "target": {
            "skus": [],
            "brand": "JBL",
            "category": None,
            "subcategory": None,
            "stock_lt": None,
            "stock_gt": None,
            "on_offer": None,
            "visible": None,
            "use_working_set": False,
        },
        "section": "seo",
        "fields": ["seo_keywords"],
        "mode": "FILL_MISSING",
        "research_required": True,
        "clarification_required": False,
        "clarification_question": None,
        "explanation": "Completar keywords faltantes de JBL.",
    }
    data.update(overrides)
    return data


def test_planner_decision_parses_canonical_values():
    decision = PlannerDecision.from_dict(payload())
    assert decision.action is ActionType.GENERATE_SEO
    assert decision.mode is MutationMode.FILL_MISSING
    assert decision.target.brand == "JBL"
    assert decision.fields == ("seo_keywords",)
    assert decision.research_required is True


def test_planner_decision_rejects_unknown_action():
    with pytest.raises(ValueError):
        PlannerDecision.from_dict(payload(action="DELETE_PRODUCT"))


def test_planner_json_schema_is_strict_and_has_no_tool_definition():
    assert PLANNER_JSON_SCHEMA["type"] == "object"
    assert PLANNER_JSON_SCHEMA["additionalProperties"] is False
    assert "tools" not in PLANNER_JSON_SCHEMA["properties"]
