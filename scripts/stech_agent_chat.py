from __future__ import annotations

import argparse
import json
from pathlib import Path

from stech_agent.agent.config import PlannerSettings
from stech_agent.agent.guided_menu import (
    confirmation_text,
    main_menu_text,
    normalize_local_command,
    resolve_product_reference,
    section_fields,
    section_menu_text,
)
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


def _print_history(runtime: AgentBrainRuntime, session_id: int) -> None:
    history = runtime.session_history(session_id)
    changes = history["changes"]
    if not changes:
        print("\nAgente> Todavía no tengo cambios verificados registrados en esta sesión.")
        return
    print(f"\nCAMBIOS DE LA SESIÓN {session_id}")
    for idx, change in enumerate(changes, start=1):
        state = "REVERTIDO" if change["reverted"] else "ACTIVO"
        label = change["name"] or change["sku"]
        print(f"{idx}. {label} ({change['sku']}) [{state}]")
        for field in change["fields"]:
            print(f"   {field}: {change['before'].get(field)} → {change['after'].get(field)}")
    print(f"Pendientes de deshacer: {history['pending_rollback']}")


def _guided_product(catalogs: CatalogRepository):
    reference = input("\nSKU o nombre exacto del producto: ").strip()
    return resolve_product_reference(catalogs.list_products(), reference)


def _guided_flow(section: str, runtime: AgentBrainRuntime, catalogs: CatalogRepository, session_id: int) -> None:
    product = _guided_product(catalogs)
    print(f"\nProducto seleccionado: {product.name or product.sku} ({product.sku})")

    if section == "multimedia":
        print("\nMULTIMEDIA")
        print(section_menu_text(section))
        print("\nAgente> La consulta/estructura de Multimedia está disponible como referencia; la subida y reemplazo de imágenes la conectaremos después para no arriesgar archivos del producto.")
        return

    print()
    print(section_menu_text(section))
    if section == "seo":
        print("V. Verificar si todo el SEO está completo")

    choice = input("\nElige uno o varios campos (ej. 1,2) o V para verificar SEO: ").strip()
    if not choice or choice == "0":
        print("Agente> Operación cancelada.")
        return
    if section == "seo" and choice.casefold() == "v":
        result = runtime.verify_seo_sku(product.sku)
        print(f"\nAgente> {result['message']}")
        return

    fields = section_fields(section)
    selected = []
    try:
        indexes = [int(part.strip()) for part in choice.split(",") if part.strip()]
    except ValueError:
        print("Agente> Selección inválida. Usa números separados por coma.")
        return
    for index in indexes:
        if index < 1 or index > len(fields):
            print(f"Agente> La opción {index} no existe.")
            return
        item = fields[index - 1]
        if not item.enabled:
            print(f"Agente> {item.label} todavía no está habilitado para escritura directa: {item.note}.")
            return
        if item not in selected:
            selected.append(item)
    if not selected:
        print("Agente> No seleccionaste campos.")
        return

    values = {}
    for item in selected:
        values[item.key] = input(f"Nuevo valor para {item.label}: ")

    print(confirmation_text(product, values))
    confirmation = input("Confirmación> ").strip().casefold()
    if confirmation != "aceptar":
        print("\nAgente> Cancelado. No abrí ni modifiqué S-TECH.")
        return

    result = runtime.execute_guided_update(
        session_id=session_id,
        sku=product.sku,
        section=section,
        values=values,
    )
    print(f"\nAgente> {result['message']}")


def _handle_local_command(
    local: str,
    *,
    runtime: AgentBrainRuntime,
    catalogs: CatalogRepository,
    session_id: int,
) -> bool:
    if local == "menu":
        print(main_menu_text())
        return True
    if local == "history":
        _print_history(runtime, session_id)
        return True
    if local == "rollback":
        history = runtime.session_history(session_id)
        pending = history["pending_rollback"]
        if not pending:
            print("\nAgente> No hay cambios verificados pendientes de deshacer en esta sesión.")
            return True
        print(f"\nHay {pending} cambio(s) verificado(s) pendiente(s) de deshacer.")
        print("El agente verificará que S-TECH todavía tenga los valores que él dejó antes de restaurarlos.")
        confirmation = input("Escribe DESHACER para continuar o CANCELAR: ").strip().casefold()
        if confirmation != "deshacer":
            print("Agente> Cancelado. No hice cambios.")
            return True
        result = runtime.rollback_session(session_id)
        print(f"\nAgente> {result['message']}")
        return True
    if local.startswith("guided:"):
        _guided_flow(local.split(":", 1)[1], runtime, catalogs, session_id)
        return True
    return False


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
    print("Puedes escribir órdenes naturales o escribir 'menu' para usar opciones guiadas.")
    print("Usa 'salir' para terminar.")
    if not args.dry_run:
        print("El navegador se abrirá automáticamente solo cuando una orden requiera leer o cambiar datos reales en S-TECH.")

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

            local = normalize_local_command(command)
            if local == "exit":
                break
            if local is not None:
                try:
                    if _handle_local_command(local, runtime=runtime, catalogs=catalogs, session_id=session_id):
                        continue
                except Exception as exc:
                    print(f"\nAgente> No pude completar esa opción: {type(exc).__name__}: {exc}")
                    continue

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

                decision_data = result.get("decision") or {}
                if result.get("resolved_skus") and not decision_data.get("clarification_required"):
                    sessions.replace_working_set(
                        session_id,
                        "current",
                        result["resolved_skus"],
                        query={
                            "instruction": command,
                            "decision": decision_data,
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
