from stech_agent.seo.v72 import extract_json_object


def test_extract_json_accepts_raw_newline_inside_chatgpt_string():
    raw = '{"marca":"KINGSTON","observacion_seo":"línea uno\nlínea dos"}'

    payload = extract_json_object(raw)

    assert payload["marca"] == "KINGSTON"
    assert payload["observacion_seo"] == "línea uno\nlínea dos"


def test_extract_json_remains_strict_for_structurally_broken_json():
    raw = '{"marca":"KINGSTON","modelo":}'

    try:
        extract_json_object(raw)
    except ValueError as exc:
        assert "JSON inválido" in str(exc)
    else:
        raise AssertionError("Un JSON estructuralmente inválido no debe aceptarse")
