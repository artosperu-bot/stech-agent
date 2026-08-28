from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stech_agent.seo.proposals import UnsafeFaqMerge, build_fill_missing_patch
from stech_agent.seo.v72 import validate_seo_payload


@dataclass(frozen=True, slots=True)
class QaResult:
    status: str
    patch: dict[str, Any]
    notes: tuple[str, ...]
    generated: dict[str, Any] | None = None


def validate_proposal(*, current: dict[str, Any], generated: dict[str, Any]) -> QaResult:
    notes: list[str] = []
    try:
        cleaned = validate_seo_payload(dict(generated))
    except Exception as exc:
        return QaResult(status="QA_REVIEW", patch={}, notes=(f"Payload SEO inválido: {exc}",), generated=None)

    try:
        patch = build_fill_missing_patch(current, cleaned)
    except UnsafeFaqMerge as exc:
        return QaResult(status="QA_REVIEW", patch={}, notes=(f"FAQ: {exc}",), generated=cleaned)

    allowed = {"seo_title", "seo_description", "seo_keywords", "seo_faq"}
    unexpected = set(patch) - allowed
    if unexpected:
        return QaResult(
            status="QA_REVIEW",
            patch={},
            notes=("Campos SEO no autorizados: " + ", ".join(sorted(unexpected)),),
            generated=cleaned,
        )

    if not patch:
        notes.append("No hay campos SEO faltantes para completar")
        return QaResult(status="NOOP", patch={}, notes=tuple(notes), generated=cleaned)

    if not cleaned.get("fuentes_tecnicas"):
        return QaResult(status="QA_REVIEW", patch={}, notes=("Faltan fuentes técnicas",), generated=cleaned)

    notes.append("FILL_MISSING validado; no se sobrescriben campos no vacíos")
    return QaResult(status="READY", patch=patch, notes=tuple(notes), generated=cleaned)
