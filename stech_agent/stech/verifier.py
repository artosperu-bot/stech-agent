from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class VerificationMismatch:
    actual: Any
    expected: Any


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    mismatches: dict[str, VerificationMismatch]


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def _boolish(value: Any):
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    if text in {"si", "sí", "true", "1", "yes", "activo", "visible"}:
        return True
    if text in {"no", "false", "0", "inactivo", "oculto"}:
        return False
    return None


def _decimalish(value: Any):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    text = _text(value).replace("S/", "").replace(",", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return _boolish(actual) is expected
    if isinstance(expected, (Decimal, int, float)) and not isinstance(expected, bool):
        a, e = _decimalish(actual), _decimalish(expected)
        if a is not None and e is not None:
            return a == e
    if isinstance(actual, Decimal):
        a, e = _decimalish(actual), _decimalish(expected)
        if a is not None and e is not None:
            return a == e
    return _text(actual).casefold() == _text(expected).casefold()


def compare_expected_fields(actual: dict[str, Any], expected: dict[str, Any]) -> VerificationResult:
    mismatches: dict[str, VerificationMismatch] = {}
    for field, wanted in expected.items():
        got = actual.get(field)
        if not _equal(got, wanted):
            mismatches[field] = VerificationMismatch(actual=got, expected=wanted)
    return VerificationResult(ok=not mismatches, mismatches=mismatches)


_FIELD_SECTION = {
    "name": "basic",
    "description": "basic",
    "category": "basic",
    "subcategory": "basic",
    "brand": "basic",
    "sku": "basic",
    "price": "pricing_stock",
    "stock": "pricing_stock",
    "seo_title": "seo",
    "seo_description": "seo",
    "seo_keywords": "seo",
    "seo_faqs": "seo",
}


def verify_fields(reader, sku: str, expected: dict[str, Any], *, expected_name: str | None = None) -> VerificationResult:
    sections: list[str] = []
    for field in expected:
        section = _FIELD_SECTION.get(field)
        if section is None:
            raise ValueError(f"No hay lector live certificado para campo {field}")
        if section not in sections:
            sections.append(section)
    state = reader.read_product(str(sku), sections=tuple(sections), expected_name=expected_name)
    return compare_expected_fields(state.values, expected)
