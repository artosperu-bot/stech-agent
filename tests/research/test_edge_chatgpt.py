from __future__ import annotations

import json

import pytest

from stech_agent.research.edge_chatgpt import (
    EdgeChatGPTWorker,
    choose_body_response_candidate,
    composer_prompt_text,
    looks_auth_gate,
    looks_conversation_limit,
    looks_like_complete_seo_response,
    looks_transient,
    prompt_delivery_matches,
)


def test_composer_flattens_newlines_so_selenium_does_not_submit_first_line():
    text = composer_prompt_text("uno\ndos\t tres")
    assert "\n" not in text and "\t" not in text
    assert text.split() == ["uno", "dos", "tres"]


def test_prompt_delivery_requires_head_tail_and_most_content():
    expected = "A" * 120 + " medio " + "Z" * 120
    assert prompt_delivery_matches(expected, expected)
    assert not prompt_delivery_matches(expected, expected[:120])


def test_error_classification_separates_conversation_limit_from_rate_limit():
    assert looks_conversation_limit("Esta conversación ha alcanzado el límite de longitud")
    assert not looks_transient("Esta conversación ha alcanzado el límite de longitud")
    assert looks_transient("You've reached your usage limit. Try again later")
    assert looks_auth_gate("Inicia sesión para continuar")


def test_complete_seo_response_detection_allows_json_needing_correction():
    text = '{"marca":"JBL","modelo":"X","categoria":"Audio","titulo_seo":"X","descripcion_seo":"X","keywords_seo":"X","faqs":[],"fuentes_tecnicas":[],"observacion_seo":"fin"}'
    assert looks_like_complete_seo_response(text)


def test_body_candidate_never_returns_prompt_json_template():
    prompt = 'Devuelve {"marca":"","modelo":"","categoria":"","titulo_seo":"","descripcion_seo":"","keywords_seo":"","faqs":[],"fuentes_tecnicas":[],"observacion_seo":""}'
    answer = {
        "marca": "JBL",
        "modelo": "Charge 6",
        "categoria": "Audio",
        "titulo_seo": "Titulo",
        "descripcion_seo": "Descripcion",
        "keywords_seo": "jbl, charge",
        "faqs": [],
        "fuentes_tecnicas": ["https://jbl.com"],
        "observacion_seo": "ok",
    }
    body = prompt + "\n" + json.dumps(answer, ensure_ascii=False)
    chosen = choose_body_response_candidate(body, prompt)
    assert json.loads(chosen)["modelo"] == "Charge 6"


def test_missing_selenium_is_detected_before_edge_is_launched(tmp_path, monkeypatch):
    worker = EdgeChatGPTWorker(raw_dir=tmp_path)
    launched: list[int] = []

    def missing_selenium():
        raise RuntimeError("Falta Selenium. Ejecuta pip install -e '.[dev]' nuevamente.")

    monkeypatch.setattr(worker, "_selenium", missing_selenium)
    monkeypatch.setattr(worker, "_launch_real_edge", lambda port: launched.append(port))

    with pytest.raises(RuntimeError, match="Falta Selenium"):
        worker.start()

    assert launched == []
