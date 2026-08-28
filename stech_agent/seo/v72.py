from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from stech_agent.prompts.registry import PromptRegistry


REQUIRED_PAYLOAD_KEYS = [
    "marca",
    "modelo",
    "categoria",
    "caracteristicas_confirmadas",
    "informacion_falta_validar",
    "publico_objetivo",
    "titulo_seo",
    "descripcion_seo",
    "keywords_seo",
    "faqs",
    "datos_faltantes_para_mejorar_seo",
    "recomendacion_final",
    "fuentes_tecnicas",
    "observacion_seo",
]


def normalize_header(value: object) -> str:
    text = "" if value is None else str(value).strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", text.upper()).strip("_")


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.I | re.S)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        if start < 0:
            raise ValueError("La respuesta no contiene un objeto JSON")
        depth = 0
        in_string = False
        escape = False
        end = None
        for idx, ch in enumerate(text[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx + 1
                        break
        if end is None:
            raise ValueError("JSON incompleto")
        text = text[start:end]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("La respuesta JSON debe ser un objeto")
    return data


def validate_seo_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_PAYLOAD_KEYS if key not in payload]
    if missing:
        raise ValueError("Faltan campos JSON: " + ", ".join(missing))

    cleaned: dict[str, Any] = {}
    for key in REQUIRED_PAYLOAD_KEYS:
        if key in {"faqs", "fuentes_tecnicas"}:
            continue
        cleaned[key] = clean_text(payload.get(key))

    faqs = payload.get("faqs")
    if not isinstance(faqs, list) or len(faqs) != 3:
        raise ValueError("Se requieren exactamente 3 FAQ")
    out_faqs = []
    for i, faq in enumerate(faqs, 1):
        if not isinstance(faq, dict):
            raise ValueError(f"FAQ {i} no es un objeto")
        q = clean_text(faq.get("pregunta"))
        a = clean_text(faq.get("respuesta"))
        if not q or not a:
            raise ValueError(f"FAQ {i} debe tener pregunta y respuesta")
        out_faqs.append({"pregunta": q, "respuesta": a})
    cleaned["faqs"] = out_faqs

    sources = payload.get("fuentes_tecnicas")
    if isinstance(sources, str):
        sources = [x.strip() for x in re.split(r"[|\n]", sources) if x.strip()]
    if not isinstance(sources, list):
        raise ValueError("fuentes_tecnicas debe ser una lista")
    cleaned["fuentes_tecnicas"] = [clean_text(x) for x in sources if clean_text(x)]
    if not cleaned["fuentes_tecnicas"]:
        raise ValueError("Debe incluir al menos una fuente técnica")
    if not any(src.startswith(("http://", "https://")) for src in cleaned["fuentes_tecnicas"]):
        raise ValueError("Debe incluir al menos una URL técnica válida")

    if not cleaned["titulo_seo"] or not cleaned["descripcion_seo"] or not cleaned["keywords_seo"]:
        raise ValueError("Título, descripción y keywords SEO no pueden estar vacíos")
    if not (35 <= len(cleaned["titulo_seo"]) <= 70):
        raise ValueError(f"Título SEO fuera de rango operativo (35-70): {len(cleaned['titulo_seo'])}")
    if not (120 <= len(cleaned["descripcion_seo"]) <= 170):
        raise ValueError(f"Descripción SEO fuera de rango operativo (120-170): {len(cleaned['descripcion_seo'])}")
    return cleaned


def build_research_prompt(product, product_url: str | None = None) -> str:
    """Build the proven V7.2 research prompt from an ERP catalog row."""
    if isinstance(product, dict):
        values = {
            "__NAME__": clean_text(product.get("name")) or "No disponible",
            "__URL__": clean_text(product.get("url")) or "No disponible",
            "__SKU__": clean_text(product.get("sku")) or "No disponible",
            "__DESCRIPTION__": clean_text(product.get("description")) or "No disponible",
            "__CATEGORY__": clean_text(product.get("category")) or "No disponible",
            "__SUBCATEGORY__": clean_text(product.get("subcategory")) or "No disponible",
            "__SOURCE_BRAND__": clean_text(product.get("source_brand") or product.get("brand")) or "No disponible",
            "__SPECS_MAIN__": clean_text(product.get("specs_main") or product.get("main_specs")) or "No disponible",
            "__SPECS_TECH__": clean_text(product.get("specs_tech") or product.get("technical_specs")) or "No disponible",
        }
    else:
        values = {
            "__NAME__": clean_text(product) or "No disponible",
            "__URL__": clean_text(product_url) or "No disponible",
            "__SKU__": "No disponible",
            "__DESCRIPTION__": "No disponible",
            "__CATEGORY__": "No disponible",
            "__SUBCATEGORY__": "No disponible",
            "__SOURCE_BRAND__": "No disponible",
            "__SPECS_MAIN__": "No disponible",
            "__SPECS_TECH__": "No disponible",
        }

    prompt = PromptRegistry.get("SEO_PRODUCTO_STECH_V1").text
    for token, value in values.items():
        prompt = prompt.replace(token, value)
    return prompt
