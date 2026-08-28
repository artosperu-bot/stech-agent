import pytest

from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.stech.import_certification import current_importer_version_hash, mark_prod_test_certified, require_mass_import_certified


def db(tmp_path):
    d = AgentDatabase(tmp_path / "agent.sqlite3"); migrate(d); return d


def test_mass_import_refuses_without_current_certification(tmp_path):
    with pytest.raises(RuntimeError, match="no está certificado"): require_mass_import_certified(db(tmp_path))


def test_certification_only_accepts_prod_test_zero_unrelated_and_restored(tmp_path):
    d = db(tmp_path)
    with pytest.raises(ValueError, match="PROD-TEST"): mark_prod_test_certified(d, sku="OTHER", unrelated_changes=0, restored=True, operator_confirmed=True)
    with pytest.raises(ValueError, match="cambios no relacionados"): mark_prod_test_certified(d, sku="PROD-TEST", unrelated_changes=1, restored=True, operator_confirmed=True)
    with pytest.raises(ValueError, match="restaurado"): mark_prod_test_certified(d, sku="PROD-TEST", unrelated_changes=0, restored=False, operator_confirmed=True)
    with pytest.raises(ValueError, match="confirmación"): mark_prod_test_certified(d, sku="PROD-TEST", unrelated_changes=0, restored=True, operator_confirmed=False)


def test_valid_certification_unlocks_current_importer_only(tmp_path):
    d = db(tmp_path)
    value = mark_prod_test_certified(d, sku="PROD-TEST", unrelated_changes=0, restored=True, operator_confirmed=True)
    assert value == current_importer_version_hash(); require_mass_import_certified(d)
