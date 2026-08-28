from __future__ import annotations

import argparse
import json
from pathlib import Path

from stech_agent.agent.config import PlannerSettings
from stech_agent.agent.guided_menu import (
    bulk_confirmation_text,
    create_confirmation_text,
    main_menu_text,
    normalize_local_command,
    product_create_reference_values,
    resolve_guided_scope,
    scope_kind_from_choice,
    scope_menu_text,
    section_fields,
    section_menu_text,
)
from stech_agent.agent.openai_brain import OpenAIPlanner
from stech_agent.agent.product_creation import prepare_new_product
from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.runtime_factory import build_live_runtime
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


def _preview_values(title: str, values, *, limit: int = 25) -> None:
    items = [str(value) for value in values if str(value).strip()]
    if not items:
        return
    print(f"{title}: {', '.join(items[:limit])}")
    if len(items) > limit:
        print(f"  ... y {len(items) - limit} opción(es) más.")


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


def _guided_create_product(
    runtime: AgentBrainRuntime,
    catalogs: CatalogRepository,
    sessions: SessionRepository,
    session_id: int,
    *,
    dry_run: bool,
) -> None:
    snapshot = catalogs.load_snapshot_data()
    refs = product_create_reference_values(snapshot.products)

    print("\nAGREGAR NUEVO PRODUCTO")
    print("Completa los datos obligatorios. El producto se creará inicialmente NO visible y sin oferta/destacados.")
    print("Los datos se validan contra el catálogo actual antes de abrir S-TECH.")
    print()
    _preview_values("Marcas existentes", refs["brands"])
    _preview_values("Categorías existentes", refs["categories"])

    sku = input("\nSKU / Part Number: ").strip()
    if not sku or sku.casefold() in {"cancelar", "0"}:
        print("Agente> Alta cancelada.")
        return
    name = input("Nombre del producto: ").strip()
    brand = input("Marca: ").strip()
    category = input("Categoría: ").strip()

    canonical_category = next(
        (value for value in refs["categories"] if str(value).casefold() == category.casefold()),
        None,
    )
    if canonical_category:
        _preview_values(
            f"Subcategorías de {canonical_category}",
            refs["subcategories_by_category"].get(canonical_category, ()),
        )
    subcategory = input("Subcategoría: ").strip()
    price = input("Precio de Venta: ").strip()
    stock = input("Stock Disponible: ").strip()

    print("\nDATOS OPCIONALES (Enter para dejar vacío / valor seguro)")
    description = input("Descripción: ").strip()
    discount = input("Precio con Descuento [0]: ").strip() or "0"
    main_specs = input("Especificaciones principales: ").strip()
    technical_specs = input("Especificaciones técnicas: ").strip()
    if refs["statuses"]:
        _preview_values("Estados observados en catálogo", refs["statuses"])
    status = input("Estado [vacío]: ").strip()

    raw_values = {
        "sku": sku,
        "name": name,
        "description": description,
        "brand": brand,
        "category": category,
        "subcategory": subcategory,
        "price": price,
        "discount": discount,
        "stock": stock,
        "status": status,
        "main_specs": main_specs,
        "technical_specs": technical_specs,
    }

    try:
        draft = prepare_new_product(snapshot, raw_values)
    except (ValueError, KeyError) as exc:
        print(f"\nAgente> No puedo preparar el alta: {exc}")
        print("No abrí S-TECH ni generé una importación.")
        return

    print(create_confirmation_text(draft))
    confirmation = input("Confirmación> ").strip().casefold()
    if confirmation != "crear":
        print("\nAgente> Cancelado. No abrí ni modifiqué S-TECH.")
        return
    if dry_run:
        print("\nAgente> Dry-run confirmado: la ficha es válida, pero no abrí S-TECH ni importé nada.")
        return

    result = runtime.create_product(raw_values, session_id=session_id)
    print(f"\nAgente> {result['message']}")
    if result.get("status") == "VERIFIED" and result.get("sku"):
        sessions.replace_working_set(
            session_id,
            "current",
            [str(result["sku"])],
            query={"source": "product_create", "sku": str(result["sku"])},
        )
        print(f"[MEMORIA] conjunto actual: 1 SKU ({result['sku']})")
        print("Agente> Puedes continuar, por ejemplo: 'ahora verifica su SEO' o 'cámbiale el stock'.")
    elif result.get("status") == "IMPORT_NOT_CERTIFIED":
        print("Agente> La ficha quedó validada, pero el alta real seguirá bloqueada hasta certificar una vez el importador con PROD-TEST.")


def _resolve_scope_interactive(
    catalogs: CatalogRepository,
    sessions: SessionRepository,
    session_id: int,
):
    print(scope_menu_text())
    raw_choice = input("Alcance> ").strip()
    if raw_choice == "0" or not raw_choice:
        return None
    kind = scope_kind_from_choice(raw_choice)
    if kind is None:
        print("Agente> Opción de alcance inválida.")
        return None

    value = None
    if kind == "single":
        value = input("SKU o nombre exacto del producto: ").strip()
    elif kind == "brand":
        value = input("Marca: ").strip()
    elif kind == "category":
        value = input("Categoría: ").strip()
    elif kind == "subcategory":
        value = input("Subcategoría: ").strip()

    working = sessions.get_working_set(session_id, "current")
    working_skus = tuple((working or {}).get("skus") or ())
    try:
        scope = resolve_guided_scope(
            catalogs.list_products(),
            kind,
            value=value,
            working_set_skus=working_skus,
        )
    except ValueError as exc:
        print(f"Agente> {exc}")
        return None

    print(f"\nAlcance seleccionado: {scope.label}")
    print(f"Productos encontrados: {scope.total_matches}")
    print(f"Productos aplicables: {len(scope.skus)}")
    if scope.blocked_skus:
        preview = ", ".join(scope.blocked_skus[:10])
        suffix = " ..." if len(scope.blocked_skus) > 10 else ""
        print(f"Bloqueados por datos ambiguos del export: {len(scope.blocked_skus)} ({preview}{suffix})")
    if not scope.skus:
        print("Agente> No quedan productos seguros para procesar en este alcance.")
        return None

    sessions.replace_working_set(
        session_id,
        "current",
        list(scope.skus),
        query={"source": "guided_scope", "scope": scope.label},
    )
    print(f"[MEMORIA] conjunto actual: {len(scope.skus)} SKU")
    return scope


def _completed_during_seo_audit(item: dict) -> bool:
    preparation = item.get("preparation") or {}
    return preparation.get("action") == "COMPLETED"


def _print_bulk_failures(result: dict) -> None:
    failures = [
        item for item in result.get("items", [])
        if not _completed_during_seo_audit(item)
        and item.get("status") not in {"VERIFIED", "NOOP", "SEO_COMPLETE", "SEO_INCOMPLETE"}
    ]
    if failures:
        print("\nINCIDENCIAS")
        for item in failures[:20]:
            print(f"- {item.get('sku')}: {item.get('message') or item.get('status')}")
        if len(failures) > 20:
            print(f"... y {len(failures) - 20} incidencia(s) más.")


def _print_seo_incomplete(result: dict) -> None:
    incomplete = [
        item for item in result.get("items", [])
        if item.get("status") == "SEO_INCOMPLETE" and not _completed_during_seo_audit(item)
    ]
    if incomplete:
        print("\nSEO INCOMPLETO")
        for item in incomplete[:20]:
            print(f"- {item.get('sku')}: {item.get('message')}")
        if len(incomplete) > 20:
            print(f"... y {len(incomplete) - 20} producto(s) incompletos más.")


def _guided_flow(
    section: str,
    runtime: AgentBrainRuntime,
    catalogs: CatalogRepository,
    sessions: SessionRepository,
    session_id: int,
    *,
    dry_run: bool,
) -> None:
    scope = _resolve_scope_interactive(catalogs, sessions, session_id)
    if scope is None:
        return

    if section == "multimedia":
        print("\nMULTIMEDIA")
        print(section_menu_text(section))
        print(
            "\nAgente> El alcance ya quedó seleccionado. La lectura estructural de Multimedia "
            "está en preparación y la subida/reemplazo de imágenes se conectará después para no arriesgar archivos del producto."
        )
        return

    print()
    print(section_menu_text(section))
    if section == "seo":
        print("V. Verificar/completar SEO faltante producto por producto")

    choice = input("\nElige uno o varios campos (ej. 1,2) o V para verificar SEO: ").strip()
    if not choice or choice == "0":
        print("Agente> Operación cancelada.")
        return

    if section == "seo" and choice.casefold() == "v":
        if dry_run:
            print("\nAgente> Estás en dry-run; no abrí S-TECH. Inicia sin --dry-run para verificar el SEO real.")
            return
        print(f"\nVERIFICAR / COMPLETAR SEO\nAlcance: {scope.label}\nProductos a revisar: {len(scope.skus)}")
        print(
            "Se revisarán uno por uno. Si un producto ya tiene SEO completo, se deja tal cual. "
            "Si está vacío o parcial, Edge/ChatGPT aplicará el prompt SEO V7.2, S-TECH completará "
            "solo lo faltante, lo guardará con Aceptar, lo verificará y recién seguirá al siguiente."
        )
        confirmation = input("Escribe VERIFICAR para continuar o CANCELAR: ").strip().casefold()
        if confirmation != "verificar":
            print("Agente> Cancelado. No abrí S-TECH.")
            return
        result = runtime.verify_seo_skus(
            scope.skus,
            scope_label=scope.label,
            session_id=session_id,
        )
        print(f"\nAgente> {result['message']}")
        if result.get("preparation_batch_id"):
            print(f"[SEO] Lote: {result['preparation_batch_id']}")
        _print_seo_incomplete(result)
        _print_bulk_failures(result)
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

    print(bulk_confirmation_text(scope, values))
    confirmation = input("Confirmación> ").strip().casefold()
    if confirmation != "aceptar":
        print("\nAgente> Cancelado. No abrí ni modifiqué S-TECH.")
        return
    if dry_run:
        print("\nAgente> Dry-run confirmado: no abrí S-TECH ni hice cambios.")
        return

    if len(scope.skus) == 1:
        result = runtime.execute_guided_update(
            session_id=session_id,
            sku=scope.skus[0],
            section=section,
            values=values,
        )
    else:
        result = runtime.execute_guided_bulk_update(
            session_id=session_id,
            skus=scope.skus,
            section=section,
            values=values,
            scope_label=scope.label,
        )
    print(f"\nAgente> {result['message']}")
    _print_bulk_failures(result)


def _handle_local_command(
    local: str,
    *,
    runtime: AgentBrainRuntime,
    catalogs: CatalogRepository,
    sessions: SessionRepository,
    session_id: int,
    dry_run: bool,
) -> bool:
    if local == "menu":
        print(main_menu_text())
        return True
    if local == "history":
        _print_history(runtime, session_id)
        return True
    if local == "rollback":
        if dry_run:
            print("\nAgente> Estás en dry-run; no ejecutaré rollback sobre S-TECH.")
            return True
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
    if local == "create_product":
        _guided_create_product(
            runtime,
            catalogs,
            sessions,
            session_id,
            dry_run=dry_run,
        )
        return True
    if local.startswith("guided:"):
        _guided_flow(
            local.split(":", 1)[1],
            runtime,
            catalogs,
            sessions,
            session_id,
            dry_run=dry_run,
        )
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
    planner = OpenAIPlanner(settings)
    runtime = AgentBrainRuntime(db, planner) if args.dry_run else build_live_runtime(db, planner)

    print(f"[MODELO] {settings.model}")
    print(f"[SESIÓN] {session_id}")
    print("Puedes escribir órdenes naturales o escribir 'menu' para usar opciones guiadas.")
    print("Usa 'salir' para terminar.")
    if not args.dry_run:
        print("El navegador se abrirá automáticamente solo cuando una orden requiera leer o cambiar datos reales en S-TECH.")
        print(
            "En auditorías SEO, si un producto está vacío/parcial, Edge/ChatGPT usará el prompt V7.2, "
            "S-TECH completará solo lo faltante, lo verificará y recién seguirá al siguiente."
        )

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
                    if _handle_local_command(
                        local,
                        runtime=runtime,
                        catalogs=catalogs,
                        sessions=sessions,
                        session_id=session_id,
                        dry_run=args.dry_run,
                    ):
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
                if result.get("preparation_batch_id"):
                    print(f"[SEO] Lote: {result['preparation_batch_id']}")

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
