from decimal import Decimal

from openpyxl import Workbook
import pytest

from stech_agent.catalog.diff import build_diff
from stech_agent.catalog.query import query_products
from stech_agent.catalog.reader import CatalogSnapshotData, read_items_export
from stech_agent.cli import main
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import MIGRATIONS, migrate
from stech_agent.db.repositories import AuditRepository, CatalogRepository, SessionRepository, TaskRepository
from stech_agent.domain.fields import coerce_field, resolve_header
from stech_agent.domain.models import ActionType, AgentPlan, FieldPatch, ProductRecord, RiskLevel, TargetSpec
from stech_agent.domain.policy import PolicyEngine
from stech_agent.tasks.runner import TaskRunner


def make_book(path, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def make_db(tmp_path):
    db = AgentDatabase(tmp_path / "agent.sqlite3")
    migrate(db)
    return db


def test_sku_preserves_leading_zero_and_delete_action_does_not_exist():
    p = ProductRecord(sku="0667C001", name="Canon", source={})
    assert p.sku == "0667C001"
    assert "DELETE_PRODUCT" not in {item.name for item in ActionType}


def test_field_patch_has_explicit_mask_only():
    patch = FieldPatch(values={"featured": True})
    assert patch.fields == frozenset({"featured"})
    assert "stock" not in patch.fields


def test_current_excel_headers_resolve_and_unknown_is_preserved():
    assert resolve_header("SKU") == "sku"
    assert resolve_header("Nombre del producto") == "name"
    assert resolve_header("Subcategoría") == "subcategory"
    assert resolve_header("En oferta") == "on_offer"
    assert resolve_header("Especificaciones técnicas (separadas por slash y dos puntos)") == "technical_specs"
    assert resolve_header("Proveedor Nuevo") == "extra:proveedor_nuevo"
    assert coerce_field("sku", "0667C001") == "0667C001"
    assert coerce_field("price", "119.00") == Decimal("119.00")


def test_reader_uses_headers_not_column_positions(tmp_path):
    path = make_book(
        tmp_path / "items.xlsx",
        ["Marca", "Nombre del producto", "SKU", "Precio", "Stock"],
        [["CANON", "Canon test", "0667C001", "119.00", 4]],
    )
    snap = read_items_export(path)
    p = snap.products[0]
    assert p.sku == "0667C001"
    assert p.name == "Canon test"
    assert p.price == Decimal("119.00")


def test_unknown_columns_are_preserved(tmp_path):
    path = make_book(
        tmp_path / "extra.xlsx",
        ["SKU", "Nombre del producto", "Proveedor Nuevo"],
        [["A1", "Producto", "Proveedor X"]],
    )
    p = read_items_export(path).products[0]
    assert p.source["Proveedor Nuevo"] == "Proveedor X"
    assert p.extra["extra:proveedor_nuevo"] == "Proveedor X"


def test_duplicate_sku_with_conflicting_name_is_rejected(tmp_path):
    path = make_book(
        tmp_path / "dupe-name.xlsx",
        ["SKU", "Nombre del producto"],
        [["A1", "Uno"], ["A1", "Dos"]],
    )
    with pytest.raises(ValueError, match="SKU duplicado"):
        read_items_export(path)


def test_duplicate_sku_with_business_conflict_is_marked_ambiguous(tmp_path):
    path = make_book(
        tmp_path / "dupe-business.xlsx",
        ["SKU", "Nombre del producto", "Precio", "Stock", "Estado"],
        [["A1", "Uno", 10, 5, "Si"], ["A1", "Uno", 12, 2, "No"]],
    )
    p = read_items_export(path).products[0]
    assert p.ambiguous is True
    assert {"price", "stock", "status"} <= p.conflict_fields
    assert len(p.duplicate_sources) == 1


def test_migration_uses_wal_full_and_is_idempotent(tmp_path):
    db = make_db(tmp_path)
    migrate(db)
    with db.connect() as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA synchronous").fetchone()[0] == 2
        applied = con.execute("SELECT version, filename FROM schema_migrations ORDER BY version").fetchall()
        assert [(r[0], r[1]) for r in applied] == list(MIGRATIONS)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"catalog_snapshots", "catalog_products", "working_sets", "tasks", "task_items", "audit_events", "changesets", "prompt_runs"} <= tables


def test_repository_saves_exact_sku_and_ambiguity_index(tmp_path):
    db = make_db(tmp_path)
    repo = CatalogRepository(db)
    snap = CatalogSnapshotData(
        raw_headers=("SKU", "Nombre del producto", "Stock"),
        canonical_headers=("sku", "name", "stock"),
        products=(ProductRecord(
            sku="0667C001",
            name="Canon",
            stock=5,
            source={"SKU": "0667C001", "Stock": 5},
            duplicate_sources=({"SKU": "0667C001", "Stock": 2},),
            conflict_fields=frozenset({"stock"}),
        ),),
        source_path="x.xlsx",
        checksum="abc",
    )
    sid = repo.save_snapshot(snap)
    assert repo.get_by_sku("0667C001", snapshot_id=sid).sku == "0667C001"
    assert repo.list_ambiguous_skus(snapshot_id=sid) == [{"sku": "0667C001", "conflict_fields": ["stock"]}]


def test_working_set_replacement_increments_version(tmp_path):
    repo = SessionRepository(make_db(tmp_path))
    session_id = repo.create_session()
    first = repo.replace_working_set(session_id, "current", ["A", "B"], {"brand": "EPSON"})
    second = repo.replace_working_set(session_id, "current", ["B"], {"stock_lt": 3})
    assert first["version"] == 1
    assert second["version"] == 2
    assert second["skus"] == ["B"]


def test_task_and_audit_are_persisted(tmp_path):
    db = make_db(tmp_path)
    task_id = TaskRepository(db).create_task("READ", ["A", "B"], {})
    audit_id = AuditRepository(db).add("TASK_CREATED", {"task_id": task_id}, task_id=task_id)
    assert audit_id > 0
    assert TaskRepository(db).get_task(task_id)["item_count"] == 2


def test_query_is_deterministic_and_preserves_explicit_sku_order():
    products = [
        ProductRecord(sku="A", name="A", brand="EPSON", stock=2, on_offer=True, source_order=1, source={}),
        ProductRecord(sku="B", name="B", brand="EPSON", stock=5, on_offer=False, source_order=2, source={}),
        ProductRecord(sku="C", name="C", brand="CANON", stock=1, on_offer=True, source_order=3, source={}),
    ]
    assert query_products(products, TargetSpec(brand="EPSON", stock_lt=3, on_offer=True)).skus == ["A"]
    assert query_products(products, TargetSpec(skus=("C", "A"))).skus == ["C", "A"]
    assert query_products(products, TargetSpec(brand="EPSON", working_set_skus=("B", "C"))).skus == ["B"]


def test_diff_never_introduces_unrequested_fields():
    before = ProductRecord(sku="A", name="X", stock=8, featured=False, visible=True, source={})
    diff = build_diff(before, FieldPatch(values={"featured": True}))
    assert list(diff.changes) == ["featured"]
    assert diff.changes["featured"].before is False
    assert diff.changes["featured"].after is True


def test_policy_risk_and_unknown_field_rejection():
    policy = PolicyEngine()
    read = policy.evaluate(AgentPlan(ActionType.EXPORT, TargetSpec(brand="EPSON")))
    assert read.allowed and read.risk is RiskLevel.R0 and not read.requires_confirmation

    visibility = policy.evaluate(
        AgentPlan(ActionType.UPDATE_FIELDS, TargetSpec(brand="EPSON"), FieldPatch({"visible": False})),
        estimated_count=30,
    )
    assert visibility.allowed and visibility.risk is RiskLevel.R2 and visibility.requires_confirmation

    price = policy.evaluate(AgentPlan(ActionType.UPDATE_FIELDS, TargetSpec(skus=("A",)), FieldPatch({"price": "10.00"})))
    assert price.risk is RiskLevel.R3 and price.requires_confirmation

    unknown = policy.evaluate(AgentPlan(ActionType.UPDATE_FIELDS, TargetSpec(skus=("A",)), FieldPatch({"whatever": 1})))
    assert not unknown.allowed


def test_crash_recovery_requeues_running_item_before_next_pending(tmp_path):
    db = make_db(tmp_path)
    repo = TaskRepository(db)
    task_id = repo.create_task("GENERATE_SEO", ["A", "B"], {})
    runner = TaskRunner(db, task_id)
    first = runner.claim_next()
    assert first.sku == "A"
    assert TaskRunner(db, task_id).recover_inflight() == 1
    recovered = TaskRunner(db, task_id).claim_next()
    assert recovered.sku == "A"
    assert recovered.resume_required is True
    assert repo.list_items(task_id)[1]["state"] == "PENDING"


def test_cli_ingest_show_and_filter(tmp_path, capsys):
    xlsx = make_book(
        tmp_path / "items.xlsx",
        ["SKU", "Nombre del producto", "Marca", "Stock", "En oferta"],
        [["0667C001", "Canon", "CANON", 1, "No"], ["E1", "Epson", "EPSON", 2, "Sí"], ["E2", "Epson 2", "EPSON", 8, "No"]],
    )
    db = tmp_path / "agent.sqlite3"
    assert main(["--db", str(db), "ingest", str(xlsx)]) == 0
    capsys.readouterr()
    assert main(["--db", str(db), "show-sku", "0667C001"]) == 0
    assert "0667C001" in capsys.readouterr().out
    assert main(["--db", str(db), "filter", "--brand", "EPSON", "--stock-lt", "3"]) == 0
    out = capsys.readouterr().out
    assert "E1" in out and "E2" not in out
