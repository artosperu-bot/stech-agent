from __future__ import annotations

from typing import Any

from stech_agent.stech.edit_locator import find_edit_control
from stech_agent.stech.product_locator import locate_exact_sku
from stech_agent.stech.selectors import locate


def open_product_editor(page: Any, sku: str, expected_name: str | None = None):
    """Open Editar for one exact-SKU row without horizontally scrolling the grid."""
    located = locate_exact_sku(page, sku, expected_name=expected_name)
    edit, method = find_edit_control(located.row)

    # Proven in the previous S-TECH dry-run: Playwright's normal click can
    # horizontally move the DevExtreme grid. Native DOM click keeps the
    # validated row and Actions cell stable.
    try:
        edit.evaluate("(el) => { el.click(); return 'ok'; }")
    except Exception:
        edit.click()

    # Do not proceed until the actual editor is visible.
    try:
        page.get_by_text("Editar item", exact=True).wait_for(state="visible", timeout=10_000)
    except Exception:
        locate(page, "tab_basic").wait_for(state="visible", timeout=20_000)

    return located, method
