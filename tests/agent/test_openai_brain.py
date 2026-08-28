from __future__ import annotations

import json

from stech_agent.agent.config import PlannerSettings
from stech_agent.agent.openai_brain import OpenAIPlanner


class FakeResponse:
    def __init__(self, payload):
        self.output_text = json.dumps(payload, ensure_ascii=False)


class FakeResponses:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.payload)


class FakeClient:
    def __init__(self, payload):
        self.responses = FakeResponses(payload)


def test_openai_planner_sends_no_openai_tools_and_uses_json_schema():
    payload = {
        "action": "READ",
        "target": {
            "skus": [],
            "brand": "EPSON",
            "category": None,
            "subcategory": None,
            "stock_lt": 3,
            "stock_gt": None,
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
        "explanation": "Leer Epson con stock menor a 3.",
    }
    client = FakeClient(payload)
    planner = OpenAIPlanner(
        PlannerSettings(api_key="sk-test", model="gpt-5-mini-2025-08-07"),
        client=client,
    )

    decision = planner.plan("dime los Epson con stock menor a 3", {"working_set_count": 0})

    call = client.responses.calls[0]
    assert call["model"] == "gpt-5-mini-2025-08-07"
    assert "tools" not in call
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True
    assert decision.target.brand == "EPSON"
    assert decision.target.stock_lt == 3
