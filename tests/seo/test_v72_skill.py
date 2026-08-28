from __future__ import annotations

import pytest

from stech_agent.seo.v72 import (
    REQUIRED_PAYLOAD_KEYS,
    build_research_prompt,
    validate_seo_payload,
)


def _valid_payload(**overrides):
    payload = {
        "marca": "JBL",
        "modelo": "Charge 6",
        "categoria": "Audio",
        "caracteristicas_confirmadas": "Bluetooth, IP68",
        "informacion_falta_validar": "",
        "publico_objetivo": "Usuarios que buscan audio portátil",
        "titulo_seo": "JBL Charge 6 Parlante Bluetooth Portátil Perú",
        "descripcion_seo": "Compra JBL Charge 6, parlante Bluetooth portátil con diseño resistente y gran autonomía. Ideal para música en casa, viajes y uso diario en Perú.",
        "keywords_seo": "JBL Charge 6, parlante Bluetooth, JBL Perú, parlante portátil, comprar JBL",
        "faqs": [
            {"pregunta": "¿Qué resistencia tiene?", "respuesta": "Cuenta con protección para uso portátil según la ficha técnica oficial."},
            {"pregunta": "¿Cómo se conecta?", "respuesta": "Se conecta de forma inalámbrica mediante Bluetooth con equipos compatibles."},
            {"pregunta": "¿Para quién se recomienda?", "respuesta": "Para quienes buscan un parlante portátil JBL para uso cotidiano y viajes."},
        ],
        "datos_faltantes_para_mejorar_seo": "",
        "recomendacion_final": "Ficha lista para SEO.",
        "fuentes_tecnicas": ["https://www.jbl.com/"],
        "observacion_seo": "",
    }
    payload.update(overrides)
    return payload


def test_v72_prompt_keeps_exact_research_contract():
    prompt = build_research_prompt(
        {
            "name": "Parlante JBL Charge 6",
            "sku": "JBLCHARGE6BLKAM",
            "source_brand": "JBL",
            "category": "Audio",
            "subcategory": "Parlantes Bluetooth",
            "description": "Descripción actual",
            "specs_main": "IP68, Bluetooth",
            "specs_tech": "Autonomía: 28 h",
            "url": "https://s-tech.com.pe/producto",
        }
    )

    assert "SKU / Part Number de autoridad interna: JBLCHARGE6BLKAM" in prompt
    assert "Prioriza fabricante, soporte oficial, manuales/fichas oficiales" in prompt
    assert "No inventes datos técnicos, stock, precio, garantía o contenido de caja" in prompt
    assert "Genera exactamente 3 FAQ" in prompt
    assert '"titulo_seo": ""' in prompt
    assert '"fuentes_tecnicas": ["https://..."]' in prompt
    assert "Devuelve SOLO el JSON" in prompt


def test_v72_payload_contract_and_cleaning():
    result = validate_seo_payload(_valid_payload())
    assert set(REQUIRED_PAYLOAD_KEYS) == set(result)
    assert len(result["faqs"]) == 3
    assert result["fuentes_tecnicas"] == ["https://www.jbl.com/"]


def test_v72_validator_requires_exactly_three_faq():
    with pytest.raises(ValueError, match="exactamente 3 FAQ"):
        validate_seo_payload(_valid_payload(faqs=[]))


def test_v72_validator_requires_technical_url():
    with pytest.raises(ValueError, match="URL técnica válida"):
        validate_seo_payload(_valid_payload(fuentes_tecnicas=["JBL"]))
