from __future__ import annotations

from typing import Any


_EDIT_SELECTORS = (
    "[title='Editar']",
    "[title*='Editar' i]",
    "[aria-label*='Editar' i]",
    "[data-original-title*='Editar' i]",
    ".dx-link-edit",
    ".dx-icon-edit",
    "[class*='edit' i]",
)


def find_edit_control(row: Any):
    """Locate Editar strictly inside an already-validated product row.

    Preference order mirrors the proven S-TECH stock dry-run:
    semantic attributes/classes first, then the first clickable control in the
    final Actions cell, finally the exact DevExtreme/Codegen button class.
    """
    for selector in _EDIT_SELECTORS:
        loc = row.locator(selector)
        if loc.count() > 0:
            candidate = loc.first
            try:
                tag = candidate.evaluate("(el) => el.tagName.toLowerCase()")
            except Exception:
                tag = ""
            if tag not in ("button", "a"):
                clickable = candidate.locator(
                    "xpath=ancestor-or-self::button[1] | ancestor-or-self::a[1]"
                )
                if clickable.count() > 0:
                    candidate = clickable.first
            return candidate, f"semántico: {selector}"

    tds = row.locator("td")
    if tds.count() > 0:
        last_td = tds.last
        buttons = last_td.locator("button, a, .dx-button")
        if buttons.count() > 0:
            return buttons.first, "fallback: primer botón en última celda/Acciones"

    codegen = row.locator(
        ".dx-widget.dx-button.dx-button-mode-contained.dx-button-normal.btn"
    )
    if codegen.count() > 0:
        return codegen.first, "fallback: selector Codegen"

    raise RuntimeError("No pude identificar el botón Editar dentro de la fila exacta.")
