from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from stech_agent.catalog.query import query_products
from stech_agent.catalog.reader import read_items_export
from stech_agent.config import AgentPaths
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository, SessionRepository, TaskRepository
from stech_agent.domain.models import TargetSpec


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stech-agent")
    parser.add_argument("--db", default=str(AgentPaths.default().database))
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("xlsx")

    show = sub.add_parser("show-sku")
    show.add_argument("sku")

    filt = sub.add_parser("filter")
    filt.add_argument("--brand")
    filt.add_argument("--category")
    filt.add_argument("--subcategory")
    filt.add_argument("--stock-lt", type=int)
    filt.add_argument("--stock-gt", type=int)
    filt.add_argument("--on-offer", choices=["true", "false"])
    filt.add_argument("--visible", choices=["true", "false"])

    ws = sub.add_parser("working-set")
    ws.add_argument("session_id", type=int)
    ws.add_argument("name")
    ws.add_argument("skus", nargs="+")

    task = sub.add_parser("task-status")
    task.add_argument("task_id", type=int)
    return parser


def _bool_arg(value: str | None):
    if value is None:
        return None
    return value == "true"


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = AgentDatabase(Path(args.db))
    migrate(db)
    catalogs = CatalogRepository(db)

    if args.command == "ingest":
        snap = read_items_export(args.xlsx)
        snapshot_id = catalogs.save_snapshot(snap)
        meta = catalogs.get_snapshot_meta(snapshot_id)
        print(json.dumps({"snapshot_id": snapshot_id, "products": len(snap.products), "created_at": meta["created_at"]}, ensure_ascii=False))
        return 0

    if args.command == "show-sku":
        product = catalogs.get_by_sku(args.sku)
        if product is None:
            print(json.dumps({"found": False, "sku": args.sku}, ensure_ascii=False))
            return 2
        meta = catalogs.get_snapshot_meta()
        print(json.dumps({
            "found": True,
            "sku": product.sku,
            "name": product.name,
            "brand": product.brand,
            "stock": product.stock,
            "ambiguous": product.ambiguous,
            "conflict_fields": sorted(product.conflict_fields),
            "snapshot_at": meta["created_at"],
        }, ensure_ascii=False))
        return 0

    if args.command == "filter":
        target = TargetSpec(
            brand=args.brand,
            category=args.category,
            subcategory=args.subcategory,
            stock_lt=args.stock_lt,
            stock_gt=args.stock_gt,
            on_offer=_bool_arg(args.on_offer),
            visible=_bool_arg(args.visible),
        )
        result = query_products(catalogs.list_products(), target)
        meta = catalogs.get_snapshot_meta()
        print(json.dumps({"skus": result.skus, "count": len(result.skus), "explanation": result.explanation, "snapshot_at": meta["created_at"] if meta else None}, ensure_ascii=False))
        return 0

    if args.command == "working-set":
        result = SessionRepository(db).replace_working_set(args.session_id, args.name, args.skus)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.command == "task-status":
        task = TaskRepository(db).get_task(args.task_id)
        print(json.dumps(task or {"found": False}, ensure_ascii=False))
        return 0 if task else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
