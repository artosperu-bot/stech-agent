from __future__ import annotations

from stech_agent.seo.proposals import build_fill_missing_patch, classify_current_seo
from stech_agent.seo.qa import validate_proposal


def _generated():
    return {
        "marca": "JBL",
        "modelo": "Charge 6",
        "categoria": "Audio",
        "caracteristicas_confirmadas": "Bluetooth, IP68",
        "informacion_falta_validar": "",
        "publico_objetivo": "Audio portátil",
        "titulo_seo": "JBL Charge 6 Parlante Bluetooth Portátil Perú",
        "descripcion_seo": "Compra JBL Charge 6, parlante Bluetooth portátil con diseño resistente y gran autonomía. Ideal para música en casa, viajes y uso diario en Perú.",
        "keywords_seo": "JBL Charge 6, parlante Bluetooth, JBL Perú, parlante portátil, comprar JBL",
        "faqs": [
            {"pregunta": "¿Qué resistencia tiene?", "respuesta": "Cuenta con protección confirmada por la ficha técnica oficial."},
            {"pregunta": "¿Cómo se conecta?", "respuesta": "Se conecta mediante Bluetooth con equipos compatibles."},
            {"pregunta": "¿Para quién se recomienda?", "respuesta": "Para quienes buscan audio portátil JBL para uso diario."},
        ],
        "datos_faltantes_para_mejorar_seo": "",
        "recomendacion_final": "Lista",
        "fuentes_tecnicas": ["https://www.jbl.com/"],
        "observacion_seo": "",
    }


def test_classifies_empty_partial_and_complete():
    assert classify_current_seo({"seo_title":"", "seo_description":"", "seo_keywords":"", "seo_faqs":[]}) == "SEO_EMPTY"
    assert classify_current_seo({"seo_title":"Manual", "seo_description":"", "seo_keywords":"", "seo_faqs":[]}) == "SEO_INCOMPLETE"
    assert classify_current_seo({
        "seo_title":"T", "seo_description":"D", "seo_keywords":"K",
        "seo_faqs":[{"question":"Q1","answer":"A1"},{"question":"Q2","answer":"A2"},{"question":"Q3","answer":"A3"}],
    }) == "SEO_COMPLETE"


def test_fill_missing_never_overwrites_existing_text_fields():
    current = {"seo_title":"Título manual", "seo_description":"", "seo_keywords":"manual, keywords", "seo_faqs":[]}
    patch = build_fill_missing_patch(current, _generated())
    assert "seo_title" not in patch
    assert "seo_keywords" not in patch
    assert patch["seo_description"] == _generated()["descripcion_seo"]
    assert len(patch["seo_faq"]) == 3


def test_fill_missing_preserves_existing_faq_slots_and_fills_only_empty_slots():
    current = {
        "seo_title":"", "seo_description":"", "seo_keywords":"",
        "seo_faqs":[
            {"question":"Pregunta manual", "answer":"Respuesta manual"},
            {"question":"", "answer":""},
            {"question":"", "answer":""},
        ],
    }
    patch = build_fill_missing_patch(current, _generated())
    assert patch["seo_faq"][0] == {"question":"Pregunta manual", "answer":"Respuesta manual"}
    assert patch["seo_faq"][1]["question"] == _generated()["faqs"][1]["pregunta"]
    assert patch["seo_faq"][2]["question"] == _generated()["faqs"][2]["pregunta"]


def test_unsafe_partial_faq_slot_requires_review_instead_of_overwrite():
    current = {
        "seo_title":"", "seo_description":"", "seo_keywords":"",
        "seo_faqs":[{"question":"Pregunta manual", "answer":""}],
    }
    result = validate_proposal(current=current, generated=_generated())
    assert result.status == "QA_REVIEW"
    assert any("FAQ" in note for note in result.notes)
    assert result.patch == {}


def test_valid_empty_product_is_ready_and_patch_is_authorized_only_for_seo():
    current = {"seo_title":"", "seo_description":"", "seo_keywords":"", "seo_faqs":[]}
    result = validate_proposal(current=current, generated=_generated())
    assert result.status == "READY"
    assert set(result.patch) == {"seo_title", "seo_description", "seo_keywords", "seo_faq"}
