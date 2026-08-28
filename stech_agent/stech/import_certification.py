from __future__ import annotations

from hashlib import sha256

from stech_agent.db.connection import AgentDatabase


IMPORTER_VERSION = "stech-import-v1"
CERTIFICATION_KEY = "mass_import_certified_version"
SUSPENSION_KEY = "mass_import_suspended"


def current_importer_version_hash() -> str:
    return sha256(IMPORTER_VERSION.encode("utf-8")).hexdigest()


def require_mass_import_certified(db: AgentDatabase) -> None:
    expected = current_importer_version_hash()
    with db.connect() as con:
        row = con.execute("SELECT value FROM app_meta WHERE key=?", (CERTIFICATION_KEY,)).fetchone()
        suspended = con.execute("SELECT value FROM app_meta WHERE key=?", (SUSPENSION_KEY,)).fetchone()
    if suspended and suspended[0] == "1":
        raise RuntimeError("La importación masiva está suspendida hasta revisión del operador")
    if not row or row[0] != expected:
        raise RuntimeError("El importador masivo no está certificado para esta versión")


def mark_prod_test_certified(db: AgentDatabase, *, sku: str, unrelated_changes: int, restored: bool, operator_confirmed: bool) -> str:
    if str(sku) != "PROD-TEST": raise ValueError("La certificación solo puede ejecutarse con SKU exacto PROD-TEST")
    if unrelated_changes != 0: raise ValueError("La certificación detectó cambios no relacionados")
    if not restored: raise ValueError("PROD-TEST debe quedar restaurado al valor original")
    if not operator_confirmed: raise ValueError("Falta confirmación explícita del operador")
    version_hash = current_importer_version_hash()
    with db.transaction(immediate=True) as con:
        con.execute("INSERT INTO app_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (CERTIFICATION_KEY, version_hash))
        con.execute("INSERT INTO app_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (SUSPENSION_KEY, "0"))
    return version_hash


def suspend_mass_imports(db: AgentDatabase) -> None:
    with db.transaction(immediate=True) as con:
        con.execute("INSERT INTO app_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (SUSPENSION_KEY, "1"))
