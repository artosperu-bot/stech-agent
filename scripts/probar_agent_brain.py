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
    parser = argparse.ArgumentParser(description="Prueba conversacional del Agent Brain sin ejecutar cambios")
    parser.add_argument("--db", default="./agent.sqlite3")
    parser.add_argument("--xlsx", help="Export normal de Items de S-TECH para ingerir antes de probar")
    parser.add_argument("--session-id", type=int)
    parser.add_argument("instruction", nargs="*", help="Si se indica, ejecuta una sola orden y termina")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = AgentDatabase(Path(args.db))
    migrate(db)
    catalogs = CatalogRepository(db)

    print("=" * 78)
    print(" STECH PRODUCT AGENT | AGENT BRAIN | DRY RUN")
    print("=" * 78)
    print("API OpenAI: solo interpretación/orquestación")
    print("NO web_search API. NO file_search API. NO computer_use API.")
    print("NO abre S-TECH. NO abre Edge. NO modifica productos.")
    print()

    if args.xlsx:
        snapshot = read_items_export(args.xlsx)
        snapshot_id = catalogs.save_snapshot(snapshot)
        print(f"[CATÁLOGO] Snapshot {snapshot_id}: {len(snapshot.products)} productos desde {args.xlsx}")
    elif catalogs.latest_snapshot_id() is None:
        raise RuntimeError("No hay catálogo. Ejecuta con --xlsx apuntando al export normal de S-TECH.")

    sessions = SessionRepository(db)
    session_id = args.session_id or sessions.create_session({"source": "probar_agent_brain.py"})
    settings = PlannerSettings.from_env()
    runtime = AgentBrainRuntime(db, OpenAIPlanner(settings))
    print(f"[MODELO] {settings.model}")
    print(f"[SESIÓN] {session_id}")
    print()

    def execute(command: str) -> None:
        result = runtime.plan(command, session_id=session_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["decision"]["clarification_required"] and result["resolved_skus"]:
            sessions.replace_working_set(
                session_id,
                "current",
                result["resolved_skus"],
                query={
                    "instruction": command,
                    "decision": result["decision"],
                    "query_explanation": result["query_explanation"],
                },
            )
            print(f"[MEMORIA] working set actual = {result['count']} SKU")

    if args.instruction:
        execute(" ".join(args.instruction))
        return 0

    print("Escribe órdenes naturales. Usa 'salir' para terminar.")
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
            execute(command)
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
