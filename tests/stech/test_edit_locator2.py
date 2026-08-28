from __future__ import annotations

from stech_agent.stech.edit_locator import find_edit_control


class FakeLocator:
    def __init__(self, *, count=0, first=None, last=None, tag="button"):
        self._count = count
        self.first = first or self
        self.last = last or self
        self._tag = tag

    def count(self):
        return self._count

    def locator(self, selector):
        return FakeLocator(count=0)

    def evaluate(self, script):
        if "tagName" in script:
            return self._tag
        return None


class RowWithActions:
    def __init__(self):
        self.edit = FakeLocator(count=1, tag="button")

    def locator(self, selector):
        if selector in {
            "[title='Editar']",
            "[title*='Editar' i]",
            "[aria-label*='Editar' i]",
            "[data-original-title*='Editar' i]",
            ".dx-link-edit",
            ".dx-icon-edit",
            "[class*='edit' i]",
        }:
            return FakeLocator(count=0)
        if selector == "td":
            edit = self.edit

            class LastTd(FakeLocator):
                def locator(inner_self, inner_selector):
                    assert inner_selector == "button, a, .dx-button"
                    return FakeLocator(count=1, first=edit)

            return FakeLocator(count=1, last=LastTd(count=1))
        return FakeLocator(count=0)


def test_find_edit_control_falls_back_to_actions_cell_when_accessible_name_is_missing():
    row = RowWithActions()
    control, method = find_edit_control(row)
    assert control is row.edit
    assert method == "fallback: primer botón en última celda/Acciones"
