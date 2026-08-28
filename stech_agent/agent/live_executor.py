from __future__ import annotations

from typing import Any

from stech_agent.domain.models import FieldPatch
from stech_agent.stech.product_writer import ProductWriter, UnsupportedLiveField, _default_read_fields
from stech_agent.stech.session import StechSession


DIRECT_LIVE_FIELDS = frozenset({
    "stock",
    "price",
    "name",
    "description",
    "seo_title",
    "seo_description",
    "seo_keywords",
})


class StechLiveExecutor:
    """Executes only already-certified direct field updates for one SKU.

    The browser session is lazy and persistent for the lifetime of the chat.
    Unsupported fields are rejected before opening S-TECH.
    """

    def __init__(self, *, session: StechSession | None = None, log=None):
        self._log = log or print
        self._session = session
        self._owns_session = session is None

    def _ensure_session(self) -> StechSession:
        if self._session is None:
            self._session = StechSession(log=self._log, slow_mo=250)
        self._session.start()
        return self._session

    def execute_update(self, *, sku: str, expected_name: str | None, patch: FieldPatch) -> dict[str, Any]:
        unsupported = sorted(set(patch.fields) - DIRECT_LIVE_FIELDS)
        if unsupported:
            raise UnsupportedLiveField(
                "Estos campos todavía no tienen escritura directa certificada: " + ", ".join(unsupported)
            )
        if not patch.values:
            raise ValueError("No hay valores para ejecutar")

        session = self._ensure_session()
        before: dict[str, Any] = {}

        def capture_before(read_sku: str, fields: frozenset[str]):
            state = _default_read_fields(session.page, read_sku, fields)
            before.update(state.values)
            return state

        writer = ProductWriter(session.page, live_reader=capture_before)
        receipt = writer.update_product_fields(str(sku), patch, expected_name=expected_name)

        if receipt.status == "NOOP":
            after = dict(before)
        elif receipt.status == "VERIFIED":
            after = dict(before)
            after.update(patch.values)
        else:
            after = {}

        return {
            "status": receipt.status,
            "sku": str(sku),
            "name": expected_name or "",
            "before": before,
            "after": after,
            "changed_fields": sorted(receipt.changed_fields),
        }

    def close(self) -> None:
        if self._session is not None and self._owns_session:
            self._session.close()
        self._session = None
