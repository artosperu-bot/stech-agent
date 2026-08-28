from __future__ import annotations

from typing import Any


class UnsafeFaqMerge(ValueError):
    pass


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _faq_pair(faq: Any) -> tuple[str, str]:
    if not isinstance(faq, dict):
        return "", ""
    question = str(faq.get("question") or faq.get("pregunta") or "").strip()
    answer = str(faq.get("answer") or faq.get("respuesta") or "").strip()
    return question, answer


def classify_current_seo(current: dict[str, Any]) -> str:
    title_ok = _nonempty(current.get("seo_title"))
    desc_ok = _nonempty(current.get("seo_description"))
    keywords_ok = _nonempty(current.get("seo_keywords"))
    faqs = current.get("seo_faqs") or []
    complete_faqs = 0
    any_faq = False
    for faq in faqs:
        q, a = _faq_pair(faq)
        if q or a:
            any_faq = True
        if q and a:
            complete_faqs += 1
    if title_ok and desc_ok and keywords_ok and complete_faqs >= 3:
        return "SEO_COMPLETE"
    if not (title_ok or desc_ok or keywords_ok or any_faq):
        return "SEO_EMPTY"
    return "SEO_INCOMPLETE"


def _merge_faqs(current_faqs: list[Any], generated_faqs: list[dict[str, Any]]) -> list[dict[str, str]] | None:
    if len(generated_faqs) != 3:
        raise UnsafeFaqMerge("La propuesta no contiene exactamente 3 FAQ")

    current_slots = list(current_faqs or [])
    if len(current_slots) > 3:
        extra_nonempty = any(any(_faq_pair(faq)) for faq in current_slots[3:])
        if extra_nonempty:
            raise UnsafeFaqMerge("FAQ existentes adicionales requieren revisión manual")
        current_slots = current_slots[:3]

    while len(current_slots) < 3:
        current_slots.append({})

    merged: list[dict[str, str]] = []
    changed = False
    for idx in range(3):
        cur_q, cur_a = _faq_pair(current_slots[idx])
        if bool(cur_q) != bool(cur_a):
            raise UnsafeFaqMerge(f"FAQ {idx + 1} está parcialmente llena y no se sobrescribirá")
        gen_q = str(generated_faqs[idx].get("pregunta") or generated_faqs[idx].get("question") or "").strip()
        gen_a = str(generated_faqs[idx].get("respuesta") or generated_faqs[idx].get("answer") or "").strip()
        if cur_q and cur_a:
            merged.append({"question": cur_q, "answer": cur_a})
        else:
            if not gen_q or not gen_a:
                raise UnsafeFaqMerge(f"FAQ generada {idx + 1} está incompleta")
            merged.append({"question": gen_q, "answer": gen_a})
            changed = True
    return merged if changed else None


def build_fill_missing_patch(current: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    mapping = {
        "seo_title": "titulo_seo",
        "seo_description": "descripcion_seo",
        "seo_keywords": "keywords_seo",
    }
    for field, generated_key in mapping.items():
        if not _nonempty(current.get(field)):
            value = generated.get(generated_key)
            if _nonempty(value):
                patch[field] = str(value).strip()

    merged_faqs = _merge_faqs(list(current.get("seo_faqs") or []), list(generated.get("faqs") or []))
    if merged_faqs is not None:
        patch["seo_faq"] = merged_faqs
    return patch
