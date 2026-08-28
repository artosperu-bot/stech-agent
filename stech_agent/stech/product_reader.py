from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Iterable

from stech_agent.stech.product_open import open_product_editor
from stech_agent.stech.selectors import locate


SUPPORTED_SECTIONS = ("basic", "pricing_stock", "multimedia_read", "characteristics", "seo")


@dataclass(frozen=True, slots=True)
class ProductLiveState:
    sku: str
    sections: tuple[str, ...]
    values: dict[str, Any]
    raw_sections: dict[str, Any]
    verified_at: str


def _open_product_editor(page: Any, sku: str, expected_name: str | None = None):
    located, _method = open_product_editor(page, sku, expected_name)
    return located


def _safe_input_value(locator: Any) -> str:
    try:
        return locator.input_value()
    except Exception:
        try:
            return locator.inner_text(timeout=700)
        except Exception:
            return ""


def _read_generic_controls(page: Any) -> list[dict[str, Any]]:
    controls = page.locator("input, textarea, select")
    result: list[dict[str, Any]] = []
    try:
        count = controls.count()
    except Exception:
        count = 0
    for idx in range(count):
        item = controls.nth(idx)
        try:
            if hasattr(item, "is_visible") and not item.is_visible(timeout=150):
                continue
        except Exception:
            pass
        attrs = {}
        for attr in ("name", "id", "placeholder", "aria-label", "type"):
            try:
                value = item.get_attribute(attr)
            except Exception:
                value = None
            if value:
                attrs[attr] = value
        result.append({"attributes": attrs, "value": _safe_input_value(item)})
    return result


def _control_near_label(page: Any, label_pattern: str):
    label = page.get_by_text(re.compile(label_pattern, re.I)).first
    try:
        if not label.count():
            return None
    except Exception:
        return None
    candidates = [
        label.locator("xpath=following::input[1]"),
        label.locator("xpath=following::textarea[1]"),
        label.locator("xpath=ancestor::*[contains(@class,'form-group') or contains(@class,'mb-')][1]//input[1]"),
        label.locator("xpath=ancestor::*[contains(@class,'form-group') or contains(@class,'mb-')][1]//textarea[1]"),
    ]
    for candidate in candidates:
        try:
            if candidate.count():
                return candidate.first
        except Exception:
            continue
    return None


class ProductReader:
    def __init__(self, page: Any, *, editor_opener: Callable[[str, str | None], Any] | None = None):
        self.page = page
        self._editor_opener = editor_opener or (lambda sku, expected_name=None: _open_product_editor(page, sku, expected_name))

    def _open_tab(self, selector_key: str) -> None:
        tab = locate(self.page, selector_key)
        tab.click()
        self.page.wait_for_timeout(250)

    def _read_basic(self) -> tuple[dict[str, Any], Any]:
        self._open_tab("tab_basic")
        raw = _read_generic_controls(self.page)
        values: dict[str, Any] = {}
        candidates = {
            "name": r"^Nombre(?: del producto)?\s*\*?$",
            "description": r"^Descripci[oó]n\s*\*?$",
            "category": r"^Categor[ií]a\s*\*?$",
            "subcategory": r"^Sub\s*Categor[ií]a\s*\*?$|^Subcategor[ií]a\s*\*?$",
            "brand": r"^Marca\s*\*?$",
            "sku": r"^SKU\s*\*?$",
        }
        for field, pattern in candidates.items():
            control = _control_near_label(self.page, pattern)
            if control is not None:
                values[field] = _safe_input_value(control)
        return values, raw

    def _read_pricing_stock(self) -> tuple[dict[str, Any], Any]:
        self._open_tab("tab_pricing_stock")
        raw = _read_generic_controls(self.page)
        values: dict[str, Any] = {}
        price = _control_near_label(self.page, r"Precio de Venta")
        stock = _control_near_label(self.page, r"Stock Disponible")
        if price is not None:
            values["price"] = _safe_input_value(price)
        if stock is not None:
            values["stock"] = _safe_input_value(stock)
        return values, raw

    def _read_multimedia(self) -> tuple[dict[str, Any], Any]:
        self._open_tab("tab_multimedia")
        images = self.page.locator("img")
        raw: list[dict[str, str]] = []
        try:
            count = images.count()
        except Exception:
            count = 0
        for idx in range(count):
            img = images.nth(idx)
            entry: dict[str, str] = {}
            for attr in ("src", "alt", "title"):
                try:
                    value = img.get_attribute(attr)
                except Exception:
                    value = None
                if value:
                    entry[attr] = value
            if entry:
                raw.append(entry)
        return {"multimedia": raw}, raw

    def _read_characteristics(self) -> tuple[dict[str, Any], Any]:
        self._open_tab("tab_characteristics")
        raw = _read_generic_controls(self.page)
        return {"characteristics_controls": raw}, raw

    def _read_seo(self) -> tuple[dict[str, Any], Any]:
        self._open_tab("tab_seo")
        title = locate(self.page, "seo_title").input_value()
        description = locate(self.page, "seo_description").input_value()
        keywords = locate(self.page, "seo_keywords").input_value()
        questions = locate(self.page, "seo_question")
        answers = locate(self.page, "seo_answer")
        faq_count = min(questions.count(), answers.count())
        faqs: list[dict[str, str]] = []
        for i in range(faq_count):
            question = questions.nth(i).input_value()
            answer = answers.nth(i).input_value()
            if question or answer:
                faqs.append({"question": question, "answer": answer})
        values = {"seo_title": title, "seo_description": description, "seo_keywords": keywords, "seo_faqs": faqs}
        return values, dict(values)

    def read_product(self, sku: str, sections: Iterable[str] = SUPPORTED_SECTIONS, *, expected_name: str | None = None) -> ProductLiveState:
        requested = tuple(sections)
        unknown = [section for section in requested if section not in SUPPORTED_SECTIONS]
        if unknown:
            raise ValueError(f"Sección S-TECH no soportada: {', '.join(unknown)}")
        self._editor_opener(str(sku), expected_name)
        values: dict[str, Any] = {}
        raw: dict[str, Any] = {}
        readers = {"basic": self._read_basic, "pricing_stock": self._read_pricing_stock, "multimedia_read": self._read_multimedia, "characteristics": self._read_characteristics, "seo": self._read_seo}
        for section in requested:
            section_values, section_raw = readers[section]()
            values.update(section_values)
            raw[section] = section_raw
        return ProductLiveState(sku=str(sku), sections=requested, values=values, raw_sections=raw, verified_at=datetime.now(timezone.utc).isoformat())
