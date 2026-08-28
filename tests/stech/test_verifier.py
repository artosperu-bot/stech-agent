from decimal import Decimal

from stech_agent.stech.verifier import compare_expected_fields


def test_verifier_accepts_normalized_boolean_and_decimal():
    result = compare_expected_fields({"visible": "Si", "price": Decimal("10.00"), "name": " Producto  X "}, {"visible": True, "price": "10.0", "name": "Producto X"})
    assert result.ok is True and result.mismatches == {}


def test_verifier_reports_only_requested_mismatches():
    result = compare_expected_fields({"featured": False, "stock": 10}, {"featured": True})
    assert result.ok is False and set(result.mismatches) == {"featured"} and "stock" not in result.mismatches


def test_verify_fields_reads_only_needed_sections():
    from stech_agent.stech.product_reader import ProductLiveState
    from stech_agent.stech.verifier import verify_fields
    calls = []
    class Reader:
        def read_product(self, sku, sections, expected_name=None):
            calls.append((sku, tuple(sections)))
            return ProductLiveState(sku=sku, sections=tuple(sections), values={"stock": "10", "seo_title": "X"}, raw_sections={}, verified_at="now")
    result = verify_fields(Reader(), "A", {"stock": 10, "seo_title": "X"})
    assert result.ok is True and calls == [("A", ("pricing_stock", "seo"))]
