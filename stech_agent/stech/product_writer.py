from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from stech_agent.domain.models import FieldPatch
from stech_agent.stech.product_reader import _control_near_label, _open_product_editor, _safe_input_value, ProductLiveState
from stech_agent.stech.selectors import locate
from stech_agent.stech.verifier import VerificationResult, compare_expected_fields


class UnsupportedLiveField(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WriteReceipt:
    sku: str
    requested_fields: frozenset[str]
    changed_fields: frozenset[str]
    status: str
    verification: VerificationResult | None = None


def _fill_control(control: Any, value: Any) -> None:
    control.fill(str(value))


def _default_control_for_field(page: Any, field: str):
    if field == "price": return _control_near_label(page, r"Precio de Venta")
    if field == "stock": return _control_near_label(page, r"Stock Disponible")
    if field == "name": return _control_near_label(page, r"^Nombre(?: del producto)?\s*\*?$")
    if field == "description": return _control_near_label(page, r"^Descripci[oó]n\s*\*?$")
    if field == "seo_title": return locate(page, "seo_title")
    if field == "seo_description": return locate(page, "seo_description")
    if field == "seo_keywords": return locate(page, "seo_keywords")
    return None


def _activate_field_tab(page: Any, field: str) -> None:
    if field in {"price", "stock"}: locate(page, "tab_pricing_stock").click()
    elif field in {"seo_title", "seo_description", "seo_keywords"}: locate(page, "tab_seo").click()
    elif field in {"name", "description"}: locate(page, "tab_basic").click()
    else: return
    try: page.wait_for_timeout(150)
    except Exception: pass


def _default_set_field(page: Any, field: str, value: Any) -> None:
    _activate_field_tab(page, field)
    control = _default_control_for_field(page, field)
    if control is None:
        raise UnsupportedLiveField(f"Campo sin control live certificado: {field}")
    _fill_control(control, value)


def _default_field_setters(page: Any) -> dict[str, Callable[[Any], None]]:
    supported = ("price", "stock", "name", "description", "seo_title", "seo_description", "seo_keywords")
    return {field: (lambda value, field=field: _default_set_field(page, field, value)) for field in supported}


def _default_read_fields(page: Any, sku: str, fields: frozenset[str]) -> ProductLiveState:
    values: dict[str, Any] = {}
    for field in fields:
        _activate_field_tab(page, field)
        control = _default_control_for_field(page, field)
        if control is None: continue
        values[field] = _safe_input_value(control)
    return ProductLiveState(sku=sku, sections=(), values=values, raw_sections={}, verified_at="live")


class ProductWriter:
    def __init__(self, page: Any, *, editor_opener: Callable[[str, str | None], Any] | None = None, live_reader: Callable[[str, frozenset[str]], ProductLiveState] | None = None, field_setters: dict[str, Callable[[Any], None]] | None = None, saver: Callable[[], None] | None = None, verifier: Callable[[str, dict[str, Any]], VerificationResult] | None = None):
        self.page = page
        self._editor_opener = editor_opener or (lambda sku, expected_name=None: _open_product_editor(page, sku, expected_name))
        self._live_reader = live_reader or (lambda sku, fields: _default_read_fields(page, sku, fields))
        self._field_setters = field_setters if field_setters is not None else _default_field_setters(page)
        self._saver = saver or self._save
        self._verifier = verifier or self._default_verifier

    def _save(self) -> None:
        locate(self.page, "accept").click()
        self.page.wait_for_timeout(700)

    def _default_verifier(self, sku: str, expected: dict[str, Any]) -> VerificationResult:
        _open_product_editor(self.page, sku)
        actual = _default_read_fields(self.page, sku, frozenset(expected.keys())).values
        return compare_expected_fields(actual, expected)

    def update_product_fields(self, sku: str, patch: FieldPatch, *, expected_name: str | None = None) -> WriteReceipt:
        unsupported = sorted(field for field in patch.fields if field not in self._field_setters)
        if unsupported:
            raise UnsupportedLiveField("Campos sin setter live certificado: " + ", ".join(unsupported))
        self._editor_opener(str(sku), expected_name)
        current = self._live_reader(str(sku), patch.fields)
        changed: dict[str, Any] = {}
        for field, value in patch.values.items():
            if not compare_expected_fields({field: current.values.get(field)}, {field: value}).ok:
                changed[field] = value
        if not changed:
            return WriteReceipt(sku=str(sku), requested_fields=patch.fields, changed_fields=frozenset(), status="NOOP")
        for field, value in changed.items(): self._field_setters[field](value)
        self._saver()
        verification = self._verifier(str(sku), changed)
        return WriteReceipt(sku=str(sku), requested_fields=patch.fields, changed_fields=frozenset(changed.keys()), status="VERIFIED" if verification.ok else "REVIEW", verification=verification)
