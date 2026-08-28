from dataclasses import replace
from pathlib import Path
import pytest

from stech_agent.catalog.reader import CatalogSnapshotData
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.domain.models import FieldPatch, ProductRecord
from stech_agent.stech.catalog_transfer import ExportReceipt, ImportReceipt
from stech_agent.stech.import_certification import mark_prod_test_certified, require_mass_import_certified
from stech_agent.tools.stech_tools import StechTools


def snapshot(path: Path,products,checksum):
    headers=("SKU","Nombre del producto","Marca","Stock","Destacado"); canonical=("sku","name","brand","stock","featured"); rows=[]
    for p in products:
        source={"SKU":p.sku,"Nombre del producto":p.name,"Marca":p.brand,"Stock":p.stock,"Destacado":"Si" if p.featured else "No"}; rows.append(replace(p,source=source))
    return CatalogSnapshotData(headers,canonical,tuple(rows),str(path),checksum)

class FakeTransfer:
    def __init__(self,exports): self.exports=list(exports); self.imported=[]
    def export_items(self,destination):
        if not self.exports: raise AssertionError("unexpected export")
        return self.exports.pop(0)
    def import_items(self,path): self.imported.append(Path(path)); return ImportReceipt(path=Path(path),imported_at="now")


def setup_repo(tmp_path,snaps):
    db=AgentDatabase(tmp_path/"agent.sqlite3"); migrate(db); repo=CatalogRepository(db); receipts=[]
    for s in snaps:
        sid=repo.save_snapshot(s); receipts.append(ExportReceipt(Path(s.source_path),"now",s.checksum,sid,len(s.products)))
    return db,repo,receipts


def test_mass_apply_requires_certification_before_import(tmp_path):
    p=ProductRecord(sku="A",name="A",brand="JBL",stock=5,featured=False,source={}); db,repo,receipts=setup_repo(tmp_path,[snapshot(tmp_path/"a.xlsx",[p],"a")]); transfer=FakeTransfer(receipts)
    tools=StechTools(db=db,catalog_repository=repo,transfer=transfer,work_dir=tmp_path); preview=tools.prepare_changeset({"A":FieldPatch({"featured":True})},snapshot_id=receipts[0].snapshot_id)
    with pytest.raises(RuntimeError,match="no está certificado"): tools.apply_changeset({"A":FieldPatch({"featured":True})},confirmation_hash=preview.confirmation_hash)
    assert transfer.imported==[]


def test_mass_apply_verifies_only_requested_change_and_audits(tmp_path):
    before=ProductRecord(sku="A",name="A",brand="JBL",stock=5,featured=False,source={}); after=replace(before,featured=True)
    db,repo,receipts=setup_repo(tmp_path,[snapshot(tmp_path/"before.xlsx",[before],"before"),snapshot(tmp_path/"fresh.xlsx",[before],"fresh"),snapshot(tmp_path/"after.xlsx",[after],"after")])
    mark_prod_test_certified(db,sku="PROD-TEST",unrelated_changes=0,restored=True,operator_confirmed=True); transfer=FakeTransfer(receipts[1:]); tools=StechTools(db=db,catalog_repository=repo,transfer=transfer,work_dir=tmp_path)
    preview=tools.prepare_changeset({"A":FieldPatch({"featured":True})},snapshot_id=receipts[0].snapshot_id); receipt=tools.apply_changeset({"A":FieldPatch({"featured":True})},confirmation_hash=preview.confirmation_hash)
    assert receipt.status=="VERIFIED" and receipt.affected_skus==("A",) and len(transfer.imported)==1
    with db.connect() as con: events=con.execute("select event_type from audit_events order by id").fetchall()
    assert any(row[0]=="MASS_IMPORT_VERIFIED" for row in events)


def test_unrelated_change_suspends_further_mass_imports(tmp_path):
    before=ProductRecord(sku="A",name="A",brand="JBL",stock=5,featured=False,source={}); bad_after=replace(before,featured=True,stock=999)
    db,repo,receipts=setup_repo(tmp_path,[snapshot(tmp_path/"before.xlsx",[before],"before"),snapshot(tmp_path/"fresh.xlsx",[before],"fresh"),snapshot(tmp_path/"bad.xlsx",[bad_after],"bad")])
    mark_prod_test_certified(db,sku="PROD-TEST",unrelated_changes=0,restored=True,operator_confirmed=True); tools=StechTools(db=db,catalog_repository=repo,transfer=FakeTransfer(receipts[1:]),work_dir=tmp_path)
    preview=tools.prepare_changeset({"A":FieldPatch({"featured":True})},snapshot_id=receipts[0].snapshot_id); receipt=tools.apply_changeset({"A":FieldPatch({"featured":True})},confirmation_hash=preview.confirmation_hash)
    assert receipt.status=="REVIEW" and "stock" in receipt.unexpected_fields["A"]
    with pytest.raises(RuntimeError,match="suspendida"): require_mass_import_certified(db)


def test_confirmation_is_invalid_if_selected_product_changed_since_preview(tmp_path):
    before=ProductRecord(sku="A",name="A",brand="JBL",stock=5,featured=False,source={}); changed=replace(before,stock=6)
    db,repo,receipts=setup_repo(tmp_path,[snapshot(tmp_path/"before.xlsx",[before],"before"),snapshot(tmp_path/"fresh.xlsx",[changed],"fresh")]); mark_prod_test_certified(db,sku="PROD-TEST",unrelated_changes=0,restored=True,operator_confirmed=True)
    tools=StechTools(db=db,catalog_repository=repo,transfer=FakeTransfer(receipts[1:]),work_dir=tmp_path); preview=tools.prepare_changeset({"A":FieldPatch({"featured":True})},snapshot_id=receipts[0].snapshot_id)
    with pytest.raises(PermissionError,match="cambió"): tools.apply_changeset({"A":FieldPatch({"featured":True})},confirmation_hash=preview.confirmation_hash)
