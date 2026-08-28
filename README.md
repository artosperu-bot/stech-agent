# STECH Product Agent

Agente local, seguro y orientado por **SKU exacto** para operar el catálogo de productos de S-TECH mediante lenguaje natural, Excel exportado, SQLite, navegador y herramientas determinísticas.

## Estado actual

La rama `feat/product-agent-foundation` implementa el **Foundation Core**:

- lectura dinámica del Excel exportado por encabezados, no por posiciones;
- SKU tratado siempre como texto y con ceros iniciales preservados;
- detección de SKU duplicados y conflictos de datos;
- consultas determinísticas por SKU, marca, categoría, stock y flags;
- SQLite en WAL + `synchronous=FULL`;
- sesiones y `working sets` conversacionales persistentes;
- tareas persistentes con recuperación después de un cierre inesperado;
- auditoría;
- `FieldPatch` con máscara explícita de campos;
- motor de políticas y niveles de riesgo;
- CLI de desarrollo de solo lectura.

## Regla de seguridad principal

**La eliminación de productos no existe en `ActionType` ni en el registro de acciones de producción.**

El futuro agente podrá leer, comparar, exportar, preparar cambios, actualizar campos autorizados, generar/cargar SEO y crear productos, pero no dispondrá de una herramienta genérica de eliminación.

## Desarrollo

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m compileall -q stech_agent
```

Ejemplo de ingestión local:

```bash
python -m stech_agent.cli --db ./agent.sqlite3 ingest ./items_export.xlsx
python -m stech_agent.cli --db ./agent.sqlite3 show-sku 0667C001
python -m stech_agent.cli --db ./agent.sqlite3 filter --brand EPSON --stock-lt 3
```

## Arquitectura objetivo

```text
UI / Chat
   ↓
Agent Planner
   ↓
Policy + Working Set + Task Runner
   ↓
┌────────────┬──────────────┬───────────────┐
│ Catalog    │ S-TECH Tools │ Research/SEO  │
│ Excel/DB   │ Playwright   │ Edge/ChatGPT  │
└────────────┴──────────────┴───────────────┘
   ↓
Verify + Audit
```

Los siguientes hitos serán: herramientas S-TECH por SKU exacto, integración del prompt SEO existente como skill, agente conversacional y UI local.
