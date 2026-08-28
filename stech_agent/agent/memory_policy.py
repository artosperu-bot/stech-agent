from __future__ import annotations

from typing import Any, Mapping


_UNSAFE_STATUSES = frozenset({
    "BLOCKED",
    "ERROR",
    "NEEDS_CLARIFICATION",
    "NOT_CONNECTED",
    "RESEARCH_NOT_CONNECTED",
    "UNSUPPORTED_LIVE_FIELD",
    "IMPORT_NOT_CERTIFIED",
})


def _clean_skus(values) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in (values or ()) if str(value).strip()))


def working_set_skus_for_result(result: Mapping[str, Any]) -> list[str] | None:
    """Return the only SKU set that is safe to persist as conversational context.

    Failed/blocked operations never replace memory. A successful operation may
    publish an explicit ``working_set_skus`` subset (for example, products that
    actually contain SEO after a catalog audit); otherwise its resolved SKUs are
    used.
    """
    status = str(result.get("status") or "").strip().upper()
    if status in _UNSAFE_STATUSES:
        return None
    if "working_set_skus" in result:
        return _clean_skus(result.get("working_set_skus"))
    return _clean_skus(result.get("resolved_skus"))
