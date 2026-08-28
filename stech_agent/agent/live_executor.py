from __future__ import annotations

from typing import Any, Iterable

from stech_agent.domain.models import FieldPatch
from stech_agent.stech.product_reader import ProductReader
from stech_agent.stech.product_writer import ProductWriter, UnsupportedLiveField, _default_read_fields
from stech_agent.stech.session import StechSession
from stech_agent.stech.verifier import compare_expected_fields


DIRECT_LIVE_FIELDS = frozenset({
    "stock",
    "price",
    "name",
    "description",
    "seo_title",
    "seo_description",
    "seo_keywords",
})

SEO_READ_FIELDS = frozenset({
    "seo_title",
    "seo_description",
    "seo_keywords",
    "seo_faq",
    "seo_faqs",
})


class StechLiveExecutor:
    """Executes only already-certified direct field updates for one SKU.

    The browser session is lazy and persistent for the lifetime of the chat.
    Unsupported fields are rejected before opening S-TECH. Reads and rollback
    reuse the same session so the agent can verify before writing.
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

    def read_fields(self, *, sku: str, fields: Iterable[str], expected_name: str | None = None) -> dict[str, Any]:
        requested = tuple(dict.fromkeys(str(field) for field in fields))
        unknown = sorted(set(requested) - (DIRECT_LIVE_FIELDS | SEO_READ_FIELDS))
        if unknown:
            raise UnsupportedLiveField(
                "Estos campos todavía no tienen lectura live certificada: " + ", ".join(unknown)
            )

        session = self._ensure_session()
        values: dict[str, Any] = {}
        seo_requested = any(field in SEO_READ_FIELDS for field in requested)
        non_seo = frozenset(field for field in requested if field in DIRECT_LIVE_FIELDS and not field.startswith("seo_"))

        if non_seo:
            from stech_agent.stech.product_open import open_product_editor

            open_product_editor(session.page, str(sku), expected_name)
            values.update(_default_read_fields(session.page, str(sku), non_seo).values)

        if seo_requested:
            state = ProductReader(session.page).read_product(
                str(sku),
                sections=("seo",),
                expected_name=expected_name,
            )
            for field in requested:
                if field == "seo_faq":
                    values["seo_faqs"] = state.values.get("seo_faqs", [])
                elif field in state.values:
                    values[field] = state.values.get(field)

        return values

    def restore_if_unchanged(
        self,
        *,
        sku: str,
        expected_name: str | None,
        expected_current: dict[str, Any],
        restore_values: dict[str, Any],
    ) -> dict[str, Any]:
        unsupported = sorted((set(expected_current) | set(restore_values)) - DIRECT_LIVE_FIELDS)
        if unsupported:
            raise UnsupportedLiveField(
                "No puedo deshacer todavía estos campos por navegador: " + ", ".join(unsupported)
            )
        if set(expected_current) != set(restore_values):
            raise ValueError("Rollback inválido: current y restore deben tener los mismos campos")

        actual = self.read_fields(
            sku=str(sku),
            fields=tuple(expected_current),
            expected_name=expected_name,
        )
        check = compare_expected_fields(actual, expected_current)
        if not check.ok:
            return {
                "status": "CONFLICT",
                "sku": str(sku),
                "name": expected_name or "",
                "before": actual,
                "after": actual,
                "changed_fields": [],
            }

        patch = FieldPatch(dict(restore_values))
        outcome = self.execute_update(
            sku=str(sku),
            expected_name=expected_name,
            patch=patch,
        )
        return outcome

    def close(self) -> None:
        if self._session is not None and self._owns_session:
            self._session.close()
        self._session = None
