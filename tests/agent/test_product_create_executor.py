from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from stech_agent.agent.product_create_executor import ProductCreateExecutor
from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import ProductRecord
from stech_agent.stech.import_certification import mark_prod_test_certified


RAW_HEADERS = (
    "SKU", "Nombre del producto", "Descripcion", "Categoria", "Subcategoría", "Marca",
    "Precio", "Descuento", "Stock", "Es nuevo", "En oferta", "Recomendado", "Destacado",
    "Visible", "Estado", "Especificaciones principales (separadas por coma)",
    "Especificaciones técnicas (separadas por slash y dos puntos)", "Imagen", "Galería",
    "Regla de descuento", "Promociones",
)
CANONICAL_HEADERS = (
    "sku", "name", "description", "category", "subcategory", "brand", "price", "discount",
    "stock", "is_new", "on_offer", "recommended", "featured", "visible", "status", "main_specs",
    "technical_specs", "image", "gallery", "discount_rule", "promotions",
)


def snap(products, source="fixture.xlsx", checksum="x"):
    return CatalogSnapshotData(
        raw_headers=RAW_HEADERS,
        canonical_headers=CANONICAL_HEADERS,
        products=tuple(products), source_path=source, checksum=checksum,
    )


def existing():
    return ProductRecord(
        sku="J1", name="JBL Uno", brand="JBL", category="Audio",
        subcategory="Parlantes Bluetooth", price=Decimal("100"), stock=3,
        visible=True, status="Activo", source_order=1,
    )


def created():
    return ProductRecord(
        sku="NEW-001", name="JBL Nuevo", brand="JBL", category="Audio",
        subcategory="Parlantes Bluetooth", price=Decimal("199.90"), discount=Decimal("0"), stock=5,
        is_new=False, on_offer=False, recommended=False, featured=False, visible=False,
        source_order=2,
    )


class FakeTransfer:
    def __init__(self, repo, snapshots):
        self.repo = repo
        self.snapshots = list(snapshots)
        self.imported = []
        self.exports = 0

    def export_items(self, destination):
        snapshot = self.snapshots[self.exports]
        self.exports += 1
        sid = self.repo.save_snapshot(snapshot)
        return SimpleNamespace(snapshot_id=sid, path=Path(destination) / f"export_{sid}.xlsx")

    def import_items(self, path):
        self.imported.append(Path(path))
        return SimpleNamespace(path=Path(path))


def make_db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    mark_prod_test_certified(
        db, sku="PROD-TEST", unrelated_changes=0, restored=True, operator_confirmed=True,
    )
    return db


def draft_values():
    return {
        "sku": "NEW-001", "name": "JBL Nuevo", "brand": "JBL", "category": "Audio",
        "subcategory": "Parlantes Bluetooth", "price": "199.90", "stock": 5,
    }


def test_create_executor_imports_one_row_and_verifies_exact_new_sku(tmp_path):
    db = make_db(tmp_path)
    repo = CatalogRepository(db)
    transfer = FakeTransfer(repo, [snap([existing()], checksum="a"), snap([existing(), created()], checksum="b")])
    executor = ProductCreateExecutor(db=db, catalog_repository=repo, transfer=transfer, work_dir=tmp_path)

    result = executor.create(draft_values())

    assert result["status"] == "VERIFIED"
    assert result["sku"] == "NEW-001"
    assert result["created"] is True
    assert len(transfer.imported) == 1
    assert transfer.imported[0].exists()
    assert repo.get_by_sku("NEW-001", snapshot_id=result["after_snapshot_id"]) is not None


def test_create_executor_suspends_imports_if_existing_product_changes(tmp_path):
    db = make_db(tmp_path)
    repo = CatalogRepository(db)
    changed_old = ProductRecord(
        sku="J1", name="JBL Uno", brand="JBL", category="Audio",
        subcategory="Parlantes Bluetooth", price=Decimal("100"), stock=99,
        visible=True, status="Activo", source_order=1,
    )
    transfer = FakeTransfer(repo, [snap([existing()], checksum="a"), snap([changed_old, created()], checksum="b")])
    executor = ProductCreateExecutor(db=db, catalog_repository=repo, transfer=transfer, work_dir=tmp_path)

    result = executor.create(draft_values())

    assert result["status"] == "REVIEW"
    assert result["unrelated_changes"] == ["J1"]


def test_create_executor_blocks_if_importer_is_not_certified(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    repo = CatalogRepository(db)
    transfer = FakeTransfer(repo, [snap([existing()]), snap([existing(), created()])])
    executor = ProductCreateExecutor(db=db, catalog_repository=repo, transfer=transfer, work_dir=tmp_path)

    try:
        executor.create(draft_values())
    except RuntimeError as exc:
        assert "certificado" in str(exc).lower()
    else:
        raise AssertionError("La creación debió bloquearse sin certificación")
    assert transfer.exports == 0
    assert transfer.imported == []
