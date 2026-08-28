from __future__ import annotations

import argparse
import json
from pathlib import Path

from stech_agent.agent.config import PlannerSettings
from stech_agent.agent.openai_brain import OpenAIPlanner
from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.catalog.reader import read_items_export
from stech_agent.db.connection import AgentDatabase
from stech_agent.db.migrations import migrate
from stech_agent.db.repositories import CatalogRepository, SessionRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="STECH Product Agent - chat con ejecución real")
    parser.add_argument("--db", default="./agent.sqlite3")
    parser.add_argument("--xlsx", help="Export normal de Items de S-TECH para refrescar el catálogo antes de iniciar")
    parser.add_argument("--session-id", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Solo interpreta; no abre S-TECH ni guarda cambios")
    parser.add_argument("--technical", action="store_true", help="Muestra también el JSON técnico")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = AgentDatabase(Path(args.db))
    migrate(db)
    catalogs = CatalogRepository(db)

    print("=" * 78)
    print(" STECH PRODUCT AGENT")
    print("=" * 78)
    print("MODO:", "SOLO LECTURA / DRY RUN" if args.dry_run else "EJECUCIÓN REAL")
    print("El modelo interpreta la orden; Python valida y S-TECH ejecuta solo campos certificados.")
    print()

    if args.xlsx:
        snapshot = read_items_export(args.xlsx)
        snapshot_id = catalogs.save_snapshot(snapshot)
        print(f"[CATÁLOGO] Snapshot {snapshot_id}: {len(snapshot.products)} productos desde {args.xlsx}")
    elif catalogs.latest_snapshot_id() is None:
        raise RuntimeError("No hay catálogo. Inicia con --xlsx apuntando al export normal de S-TECH.")

    sessions = SessionRepository(db)
    session_id = args.session_id or sessions.create_session({"source": "stech_agent_chat.py"})
    settings = PlannerSettings.from_env()
    runtime = AgentBrainRuntime(db, OpenAIPlanner(settings))

    print(f"[MODELO] {settings.model}")
    print(f"[SESIÓN] {session_id}")
    print("Escribe órdenes naturales. Usa 'salir' para terminar.")
    if not args.dry_run:
        print("El navegador se abrirá automáticamente solo cuando una orden requiera un cambio real en S-TECH.")

    try:
        while True:
            try:
                command = input("\nTú> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not command:
                continue
            if command.casefold() in {"salir", "exit", "quit"}:
                break

            try:
                result = runtime.plan(command, session_id=session_id) if args.dry_run else runtime.execute(command, session_id=session_id)
                if args.dry_run:
                    decision = result["decision"]
                    if decision.get("clarification_required"):
                        message = decision.get("clarification_question") or "Necesito una aclaración."
                    else:
                        message = f"Entendí {decision['action']}. Encontré {result['count']} producto(s). No hice cambios."
                else:
                    message = result.get("message") or "Orden procesada."
                print(f"\nAgente> {message}")

                if result.get("resolved_skus") and not result["decision"].get("clarification_required"):
                    sessions.replace_working_set(
                        session_id,
                        "current",
                        result["resolved_skus"],
                        query={
                            "instruction": command,
                            "decision": result["decision"],
                            "query_explanation": result.get("query_explanation"),
                        },
                    )
                    print(f"[MEMORIA] conjunto actual: {len(result['resolved_skus'])} SKU")

                if args.technical:
                    print("\n[DETALLE TÉCNICO]")
                    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            except Exception as exc:
                print(f"\nAgente> Ocurrió un error y no pude completar la orden: {type(exc).__name__}: {exc}")
    finally:
        runtime.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
