from pathlib import Path
from openpyxl import Workbook

from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository
from stech_agent.stech.catalog_transfer import CatalogTransfer


class FakeButton:
    def __init__(self): self.clicked=0
    @property
    def first(self): return self
    def count(self): return 1
    def click(self): self.clicked+=1
    def is_visible(self,timeout=None): return True

class FakeDownload:
    suggested_filename="items_export.xlsx"
    def __init__(self,source): self.source=Path(source); self.saved=None
    def save_as(self,target): self.saved=Path(target); self.saved.write_bytes(self.source.read_bytes())

class DownloadCtx:
    def __init__(self,download): self.value=download
    def __enter__(self): return self
    def __exit__(self,*args): return False

class FakePage:
    def __init__(self,download): self.download=download; self.buttons={"Exportar Items":FakeButton(),"OK":FakeButton()}
    def expect_download(self): return DownloadCtx(self.download)
    def get_by_role(self,role,**kwargs): return self.buttons.get(kwargs.get("name"),FakeButton())
    def wait_for_timeout(self,_ms): pass

class FakeSession:
    def __init__(self,page): self.page=page; self.calls=0
    def ensure_products_page(self): self.calls+=1; return self.page


def create_xlsx(path):
    wb=Workbook(); ws=wb.active; ws.append(["SKU","Nombre del producto","Marca","Stock"]); ws.append(["0667C001","Canon","CANON",4]); wb.save(path)


def test_export_items_saves_timestamped_file_and_persists_snapshot(tmp_path):
    source=tmp_path/"source.xlsx"; create_xlsx(source); db=AgentDatabase(tmp_path/"agent.sqlite3"); migrate(db); repo=CatalogRepository(db)
    page=FakePage(FakeDownload(source)); session=FakeSession(page); receipt=CatalogTransfer(session,repo).export_items(tmp_path/"exports")
    assert session.calls==1 and page.buttons["Exportar Items"].clicked==1 and receipt.path.exists()
    assert receipt.path.name.startswith("items_export_") and receipt.path.suffix==".xlsx" and receipt.product_count==1 and receipt.snapshot_id==repo.latest_snapshot_id()
    assert repo.get_by_sku("0667C001").sku=="0667C001" and len(receipt.checksum)==64

class FakeFileInput:
    def __init__(self): self.files=[]
    @property
    def first(self): return self
    def count(self): return 1
    def set_input_files(self,path): self.files.append(path)

class FakeTextChoice(FakeButton): pass

class FakeImportPage(FakePage):
    def __init__(self): self.buttons={"Importar Datos":FakeButton(),"Aceptar":FakeButton(),"OK":FakeButton()}; self.file_input=FakeFileInput(); self.choice=FakeTextChoice()
    def locator(self,css): return self.file_input
    def get_by_text(self,*args,**kwargs): return self.choice
    def wait_for_timeout(self,_ms): pass


def test_import_items_uses_add_update_and_file_input(tmp_path):
    source=tmp_path/"import.xlsx"; create_xlsx(source); page=FakeImportPage(); session=FakeSession(page); db=AgentDatabase(tmp_path/"db.sqlite3"); migrate(db)
    receipt=CatalogTransfer(session,CatalogRepository(db)).import_items(source)
    assert page.buttons["Importar Datos"].clicked==1 and page.file_input.files==[str(source)] and page.choice.clicked==1 and page.buttons["Aceptar"].clicked==1 and receipt.path==source
