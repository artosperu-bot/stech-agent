from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from stech_agent.agent.product_creation import build_create_workbook, prepare_new_product
from stech_agent.db.repositories import AuditRepository, CatalogRepository
from stech_agent.domain.models import ProductRecord
from stech_agent.stech.import_certification import require_mass_import_certified, suspend_mass_imports
from stech_agent.stech.verifier import compare_expected_fields


def _stable_product_state(product: ProductRecord) -> dict[str, Any]:
    data = asdict(product)
    for key in ("source", "duplicate_sources", "conflict_fields", "source_order"):
        data.pop(key, None)
    return data


def _existing_changes(before: dict[str, ProductRecord], after: dict[str, ProductRecord]) -> list[str]:
    changed: list[str] = []
    for sku, old in before.items():
        new = after.get(sku)
        if new is None or _stable_product_state(old) != _stable_product_state(new):
            changed.append(sku)
    return changed


def _expected_created_values(values: dict[str, Any]) -> dict[str, Any]:
    expected: dict[str, Any] = {}
    for field, value in values.items():
        if field == "sku":
            continue
        if value in (None, ""):
            continue
        expected[field] = value
    return expected


class ProductCreateExecutor:
    def __init__(self, *, db, catalog_repository: CatalogRepository, transfer, work_dir: str | Path):
        self.db = db
        self.catalog_repository = catalog_repository
        self.transfer = transfer
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.audit = AuditRepository(db)

    def create(self, raw_values: dict[str, Any], *, session_id: int | None = None) -> dict[str, Any]:
        # Same importer as mass changes: never bypass its one-time live certification.
        require_mass_import_certified(self.db)

        before_receipt = self.transfer.export_items(self.work_dir / "snapshots")
        before_snapshot = self.catalog_repository.load_snapshot_data(before_receipt.snapshot_id)
        draft = prepare_new_product(before_snapshot, raw_values)
        before = {product.sku: product for product in before_snapshot.products}

        import_path = self.work_dir / "imports" / f"create_{draft.sku}.xlsx"
        workbook = build_create_workbook(before_snapshot, draft, import_path)
        self.audit.add(
            "PRODUCT_CREATE_PREPARED",
            {"fields": sorted(workbook.fields), "import_path": str(import_path)},
            session_id=session_id,
            sku=draft.sku,
        )

        self.transfer.import_items(import_path)
        after_receipt = self.transfer.export_items(self.work_dir / "snapshots")
        after_snapshot = self.catalog_repository.load_snapshot_data(after_receipt.snapshot_id)
        after = {product.sku: product for product in after_snapshot.products}

        added_skus = sorted(set(after) - set(before))
        removed_skus = sorted(set(before) - set(after))
        unrelated_changes = _existing_changes(before, after)
        created = after.get(draft.sku)

        expected = _expected_created_values(draft.values)
        created_mismatches: list[str] = []
        if created is None:
            created_mismatches.append("__missing_product__")
        else:
            actual = {field: getattr(created, field) for field in expected}
            check = compare_expected_fields(actual, expected)
            if not check.ok:
                created_mismatches = sorted(check.mismatches)

        exact_added = added_skus == [draft.sku]
        safe = exact_added and not removed_skus and not unrelated_changes and not created_mismatches
        if not safe:
            suspend_mass_imports(self.db)
            payload = {
                "added_skus": added_skus,
                "removed_skus": removed_skus,
                "unrelated_changes": unrelated_changes,
                "created_mismatches": created_mismatches,
                "before_snapshot_id": before_receipt.snapshot_id,
                "after_snapshot_id": after_receipt.snapshot_id,
            }
            self.audit.add("PRODUCT_CREATE_REVIEW", payload, session_id=session_id, sku=draft.sku)
            return {
                "status": "REVIEW",
                "created": created is not None,
                "sku": draft.sku,
                "message": (
                    f"La importación de {draft.sku} necesita revisión. Suspendí nuevas importaciones para no arriesgar el catálogo."
                ),
                **payload,
                "import_path": str(import_path),
            }

        self.audit.add(
            "PRODUCT_CREATE_VERIFIED",
            {
                "fields": sorted(expected),
                "before_snapshot_id": before_receipt.snapshot_id,
                "after_snapshot_id": after_receipt.snapshot_id,
                "import_path": str(import_path),
            },
            session_id=session_id,
            sku=draft.sku,
        )
        return {
            "status": "VERIFIED",
            "created": True,
            "sku": draft.sku,
            "name": created.name if created is not None else draft.values.get("name", ""),
            "message": f"Creé {created.name if created is not None else draft.values.get('name', draft.sku)} ({draft.sku}) y verifiqué el alta en S-TECH.",
            "before_snapshot_id": before_receipt.snapshot_id,
            "after_snapshot_id": after_receipt.snapshot_id,
            "import_path": str(import_path),
            "added_skus": added_skus,
            "removed_skus": [],
            "unrelated_changes": [],
            "created_mismatches": [],
        }
