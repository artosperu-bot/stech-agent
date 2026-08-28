from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from stech_agent.catalog.reader import read_items_export
from stech_agent.db.repositories import CatalogRepository
from stech_agent.stech.selectors import locate


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    path: Path
    downloaded_at: str
    checksum: str
    snapshot_id: int
    product_count: int


@dataclass(frozen=True, slots=True)
class ImportReceipt:
    path: Path
    imported_at: str


class CatalogTransfer:
    def __init__(self, session, catalog_repository: CatalogRepository):
        self.session = session
        self.catalog_repository = catalog_repository

    def export_items(self, destination_dir: str | Path) -> ExportReceipt:
        page = self.session.ensure_products_page()
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%d_%H%M%S")
        with page.expect_download() as download_info:
            locate(page, "export_items").click()
        download = download_info.value
        suggested = getattr(download, "suggested_filename", "items_export.xlsx") or "items_export.xlsx"
        suffix = Path(suggested).suffix.lower() or ".xlsx"
        if suffix not in {".xlsx", ".xls"}: suffix = ".xlsx"
        target = destination / f"items_export_{stamp}{suffix}"
        download.save_as(str(target))
        try:
            ok = page.get_by_role("button", name="OK")
            if ok.count() and ok.first.is_visible(timeout=800): ok.first.click()
        except Exception: pass
        try: page.wait_for_timeout(250)
        except Exception: pass
        snapshot = read_items_export(target)
        snapshot_id = self.catalog_repository.save_snapshot(snapshot)
        return ExportReceipt(path=target, downloaded_at=now.isoformat(), checksum=snapshot.checksum, snapshot_id=snapshot_id, product_count=len(snapshot.products))

    def import_items(self, workbook_path: str | Path) -> ImportReceipt:
        path = Path(workbook_path)
        if not path.exists(): raise FileNotFoundError(path)
        page = self.session.ensure_products_page()
        locate(page, "import_data").click()
        try: page.wait_for_timeout(300)
        except Exception: pass
        file_input = page.locator("input[type='file']")
        if not file_input.count(): raise RuntimeError("No apareció el selector de archivo de Importar Datos")
        file_input.first.set_input_files(str(path))
        choice = page.get_by_text(re.compile(r"^Agregar\s*/\s*Actualizar", re.I))
        if not choice.count(): raise RuntimeError("No apareció la opción segura Agregar / Actualizar")
        choice.first.click()
        locate(page, "accept").click()
        try:
            ok = page.get_by_role("button", name="OK")
            if ok.count() and ok.first.is_visible(timeout=2500): ok.first.click()
        except Exception: pass
        return ImportReceipt(path=path, imported_at=datetime.now(timezone.utc).isoformat())
