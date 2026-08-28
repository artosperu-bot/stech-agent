from stech_agent.seo.publisher import _audit_field_value


def test_audit_field_value_drops_fully_blank_faq_rows():
    values = {
        "seo_faqs": [
            {"question": "", "answer": ""},
            {"question": "   ", "answer": ""},
        ]
    }
    assert _audit_field_value(values, "seo_faq") == []


def test_audit_field_value_keeps_partial_faq_row_for_safety_visibility():
    values = {"seo_faqs": [{"question": "Pregunta parcial", "answer": ""}]}
    assert _audit_field_value(values, "seo_faq") == [
        {"question": "Pregunta parcial", "answer": ""}
    ]
