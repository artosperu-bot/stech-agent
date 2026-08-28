import pytest

from stech_agent.stech.product_locator import NeedsReview, locate_exact_sku


class FakeInput:
    def __init__(self): self.fills = []; self.presses = []
    def fill(self, value): self.fills.append(value)
    def press(self, value): self.presses.append(value)


class FakeCell:
    def __init__(self, row=None, text=""): self.row = row; self.text = text
    def count(self): return 1
    @property
    def first(self): return self
    def locator(self, _): return self.row
    def inner_text(self, timeout=None): return self.text


class FakeNone:
    def count(self): return 0
    @property
    def first(self): return self


class FakeMany:
    def __init__(self, count): self._count = count
    def count(self): return self._count
    @property
    def first(self): return self


class FakeRow:
    def __init__(self, sku, name): self.sku = sku; self.name = name
    def get_by_role(self, role, **kwargs):
        if role == "gridcell" and kwargs.get("description") == "Columna Nombre": return FakeCell(text=self.name)
        if role == "gridcell" and kwargs.get("name") == self.name: return FakeCell(text=self.name)
        return FakeNone()
    def inner_text(self, timeout=None): return f"Audífonos JBL {self.name} {self.sku} S/ 10 1"


class FakePage:
    def __init__(self, sku, name="Producto", exact_count=1):
        self.sku_filter = FakeInput(); self.name_filter = FakeInput(); self.brand_filter = FakeInput(); self.category_filter = FakeInput()
        self.row = FakeRow(sku, name); self.sku = sku; self.exact_count = exact_count; self.waits = []
    def get_by_role(self, role, **kwargs):
        if role == "textbox" and kwargs.get("name") == "Celda de filtro":
            return {"Columna SKU": self.sku_filter, "Columna Nombre": self.name_filter, "Columna Marca": self.brand_filter, "Columna Categoría": self.category_filter}[kwargs.get("description")]
        if role == "gridcell" and kwargs.get("name") == self.sku and kwargs.get("exact") is True:
            if self.exact_count == 0: return FakeNone()
            if self.exact_count > 1: return FakeMany(self.exact_count)
            return FakeCell(row=self.row, text=self.sku)
        return FakeNone()
    def wait_for_timeout(self, ms): self.waits.append(ms)


def test_exact_sku_is_required_and_leading_zero_is_preserved():
    page = FakePage("0667C001", "Botella Canon")
    located = locate_exact_sku(page, "0667C001", expected_name="Botella Canon")
    assert located.sku == "0667C001" and located.name == "Botella Canon"
    assert page.sku_filter.fills[-1] == "0667C001" and page.sku_filter.presses == ["Enter"]


def test_zero_results_needs_review():
    with pytest.raises(NeedsReview, match="No se encontró"): locate_exact_sku(FakePage("A1", exact_count=0), "A1")


def test_multiple_exact_cells_needs_review():
    with pytest.raises(NeedsReview, match="múltiples"): locate_exact_sku(FakePage("A1", exact_count=2), "A1")


def test_name_mismatch_on_exact_sku_needs_review():
    with pytest.raises(NeedsReview, match="nombre esperado"): locate_exact_sku(FakePage("A1", name="Modelo Azul"), "A1", expected_name="Modelo Rojo")


def test_other_filters_are_cleared_before_sku_search():
    page = FakePage("A1"); locate_exact_sku(page, "A1")
    assert page.name_filter.fills == [""] and page.brand_filter.fills == [""] and page.category_filter.fills == [""]
