from __future__ import annotations

from stech_agent.agent.live_executor import StechLiveExecutor


def test_restore_if_unchanged_normalizes_seo_faqs_read_alias(monkeypatch):
    executor = StechLiveExecutor()
    current_faqs = [
        {"question": "Q1", "answer": "A1"},
        {"question": "Q2", "answer": "A2"},
        {"question": "Q3", "answer": "A3"},
    ]
    calls = []

    monkeypatch.setattr(
        executor,
        "read_fields",
        lambda **kwargs: {"seo_faqs": current_faqs},
    )
    monkeypatch.setattr(
        executor,
        "execute_update",
        lambda **kwargs: calls.append(kwargs) or {"status": "VERIFIED", "changed_fields": ["seo_faq"]},
    )

    result = executor.restore_if_unchanged(
        sku="A",
        expected_name="Producto A",
        expected_current={"seo_faq": current_faqs},
        restore_values={"seo_faq": []},
    )

    assert result["status"] == "VERIFIED"
    assert len(calls) == 1
    assert calls[0]["patch"].values == {"seo_faq": []}
