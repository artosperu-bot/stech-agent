from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from stech_agent.catalog.import_builder import build_import_workbook
from stech_agent.db.repositories import AuditRepository, CatalogRepository
from stech_agent.domain.models import FieldPatch, ProductRecord
from stech_agent.stech.import_certification import require_mass_import_certified, suspend_mass_imports
from stech_agent.stech.verifier import compare_expected_fields


@dataclass(frozen=True, slots=True)
class ChangeSetPreview:
    confirmation_hash: str
    snapshot_id: int
    affected_skus: tuple[str, ...]
    fields: frozenset[str]
    before_after: dict[str, dict[str, dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class MassChangeReceipt:
    status: str
    affected_skus: tuple[str, ...]
    before_snapshot_id: int
    after_snapshot_id: int | None
    import_path: Path | None
    unexpected_fields: dict[str, tuple[str, ...]]


def _json_default(value: Any):
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, frozenset): return sorted(value)
    raise TypeError(type(value).__name__)


def _stable_product_state(product: ProductRecord) -> dict[str, Any]:
    data = asdict(product)
    for key in ("source", "duplicate_sources", "conflict_fields", "source_order"): data.pop(key, None)
    return data


def _confirmation_payload(products: dict[str, ProductRecord], patches: dict[str, FieldPatch]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for sku in sorted(patches):
        if sku not in products: raise ValueError(f"SKU no existe en snapshot: {sku}")
        product = products[sku]
        if product.ambiguous: raise ValueError(f"SKU ambiguo {sku}; no puede formar parte de una modificación")
        payload[sku] = {"before": _stable_product_state(product), "patch": {key: patches[sku].values[key] for key in sorted(patches[sku].values)}}
    return payload


def changeset_confirmation_hash(products: dict[str, ProductRecord], patches: dict[str, FieldPatch]) -> str:
    payload = _confirmation_payload(products, patches)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    return sha256(encoded.encode("utf-8")).hexdigest()


class StechTools:
    def __init__(self, *, db, catalog_repository: CatalogRepository, transfer, work_dir: str | Path):
        self.db = db
        self.catalog_repository = catalog_repository
        self.transfer = transfer
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.audit = AuditRepository(db)

    def export_catalog(self):
        return self.transfer.export_items(self.work_dir / "snapshots")

    def prepare_changeset(self, patches: dict[str, FieldPatch], *, snapshot_id: int | None = None) -> ChangeSetPreview:
        if not patches: raise ValueError("No hay cambios")
        snapshot = self.catalog_repository.load_snapshot_data(snapshot_id)
        products = {p.sku: p for p in snapshot.products}
        digest = changeset_confirmation_hash(products, patches)
        fields: set[str] = set()
        before_after: dict[str, dict[str, dict[str, Any]]] = {}
        for sku, patch in patches.items():
            p = products.get(sku)
            if p is None: raise ValueError(f"SKU no existe en snapshot: {sku}")
            if p.ambiguous: raise ValueError(f"SKU ambiguo {sku}; no puede modificarse")
            fields.update(patch.fields)
            before_after[sku] = {"before": {field: getattr(p, field) for field in patch.fields}, "after": {field: patch.values[field] for field in patch.fields}}
        return ChangeSetPreview(confirmation_hash=digest, snapshot_id=int(self.catalog_repository.get_snapshot_meta(snapshot_id)["id"]), affected_skus=tuple(patches.keys()), fields=frozenset(fields), before_after=before_after)

    def _verify_post_import(self, before: dict[str, ProductRecord], after: dict[str, ProductRecord], patches: dict[str, FieldPatch]) -> dict[str, tuple[str, ...]]:
        unexpected: dict[str, tuple[str, ...]] = {}
        skip = {"source", "duplicate_sources", "conflict_fields", "source_order"}
        dataclass_fields = [key for key in ProductRecord.__dataclass_fields__ if key not in skip]
        for sku, patch in patches.items():
            old = before[sku]
            new = after.get(sku)
            problems: set[str] = set()
            if new is None:
                unexpected[sku] = ("__missing_product__",)
                continue
            for field in dataclass_fields:
                expected = old.sku if field == "sku" else (patch.values[field] if field in patch.fields else getattr(old, field))
                actual = getattr(new, field)
                if not compare_expected_fields({field: actual}, {field: expected}).ok: problems.add(field)
            for field in set(old.extra) | set(new.extra):
                if not compare_expected_fields({field: new.extra.get(field)}, {field: old.extra.get(field)}).ok: problems.add(field)
            if problems: unexpected[sku] = tuple(sorted(problems))
        return unexpected

    def apply_changeset(self, patches: dict[str, FieldPatch], *, confirmation_hash: str) -> MassChangeReceipt:
        require_mass_import_certified(self.db)
        fresh_receipt = self.export_catalog()
        fresh = self.catalog_repository.load_snapshot_data(fresh_receipt.snapshot_id)
        before = {p.sku: p for p in fresh.products}
        actual_confirmation = changeset_confirmation_hash(before, patches)
        if actual_confirmation != confirmation_hash:
            raise PermissionError("El producto o la selección cambió desde la propuesta; se requiere nueva confirmación")
        import_path = self.work_dir / "imports" / f"changeset_{actual_confirmation[:12]}.xlsx"
        build_import_workbook(fresh, patches, import_path)
        self.audit.add("MASS_IMPORT_PREPARED", {"skus": list(patches), "fields": sorted({f for p in patches.values() for f in p.fields}), "confirmation_hash": actual_confirmation})
        self.transfer.import_items(import_path)
        after_receipt = self.export_catalog()
        after = {p.sku: p for p in self.catalog_repository.load_snapshot_data(after_receipt.snapshot_id).products}
        unexpected = self._verify_post_import(before, after, patches)
        if unexpected:
            suspend_mass_imports(self.db)
            self.audit.add("MASS_IMPORT_REVIEW", {"unexpected_fields": {k: list(v) for k, v in unexpected.items()}})
            return MassChangeReceipt(status="REVIEW", affected_skus=tuple(patches.keys()), before_snapshot_id=fresh_receipt.snapshot_id, after_snapshot_id=after_receipt.snapshot_id, import_path=import_path, unexpected_fields=unexpected)
        for sku, patch in patches.items(): self.audit.add("MASS_IMPORT_VERIFIED", {"fields": sorted(patch.fields)}, sku=sku)
        return MassChangeReceipt(status="VERIFIED", affected_skus=tuple(patches.keys()), before_snapshot_id=fresh_receipt.snapshot_id, after_snapshot_id=after_receipt.snapshot_id, import_path=import_path, unexpected_fields={})
