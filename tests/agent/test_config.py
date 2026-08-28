from __future__ import annotations

import pytest

from stech_agent.agent.config import DEFAULT_OPENAI_MODEL, PlannerSettings


def test_planner_settings_uses_requested_default_model():
    settings = PlannerSettings.from_env({"OPENAI_API_KEY": "sk-test"})
    assert settings.api_key == "sk-test"
    assert settings.model == "gpt-5-mini-2025-08-07"
    assert DEFAULT_OPENAI_MODEL == "gpt-5-mini-2025-08-07"


def test_planner_settings_allows_model_override():
    settings = PlannerSettings.from_env(
        {"OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": "custom-model"}
    )
    assert settings.model == "custom-model"


def test_planner_settings_requires_api_key():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        PlannerSettings.from_env({})
