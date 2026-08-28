# STECH Agent Brain con OpenAI — Diseño

## Objetivo

Agregar un cerebro de orquestación mínimo al STECH Product Agent. La API de OpenAI se usa **solo para interpretar lenguaje natural y devolver un plan estructurado**. No se habilitan herramientas OpenAI de web search, file search, computer use ni navegación.

## Configuración

El proceso local carga `.env` y usa:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini-2025-08-07
```

`.env` permanece ignorado por Git. Se versiona únicamente `.env.example`.

## Fuente de catálogo

El catálogo operativo nace del Excel normal de `Exportar Items` de S-TECH. El formato observado tiene 21 columnas y puede traer SKU numéricos o SKU textuales con ceros iniciales. El lector existente sigue siendo la autoridad para normalizar el archivo y SQLite guarda el snapshot.

El modelo no recibe el Excel completo. Recibe solamente:

- la orden del usuario;
- el esquema de acciones/campos permitidos;
- un resumen pequeño del contexto actual;
- el `working set` cuando exista.

Los filtros reales se ejecutan localmente contra el snapshot mediante `query_products()`.

## Separación de responsabilidades

```text
Usuario
  ↓
OpenAI Planner Brain
  ↓ JSON estricto
PlannerDecision
  ↓
Policy / Scope / Query local
  ↓
Python tools
  ├─ catálogo / SQLite
  ├─ S-TECH / Playwright
  └─ Research / Edge + ChatGPT (solo cuando corresponda)
```

El modelo **no ejecuta** S-TECH y no recibe una herramienta genérica para hacer clic. Tampoco investiga por web desde la API.

## PlannerDecision

La primera versión produce esta intención estructurada:

- `action`: acción canónica del dominio (`READ`, `EXPORT`, `COMPARE`, `UPDATE_FIELDS`, `GENERATE_SEO`, `UPLOAD_SEO`, etc.);
- `target`: `skus`, `brand`, `category`, `subcategory`, `stock_lt`, `stock_gt`, `on_offer`, `visible`, `use_working_set`;
- `section`: sección lógica opcional (`basic`, `pricing`, `features`, `multimedia`, `seo`, `commercial`);
- `fields`: lista de campos canónicos autorizados;
- `mode`: `READ`, `FILL_MISSING`, `PATCH` o `REPLACE_SECTION`;
- `research_required`: indica que un paso posterior debe usar el Research Edge existente;
- `clarification_required` y `clarification_question`: cuando una orden no puede ejecutarse de forma segura;
- `explanation`: resumen corto de lo que entendió, sin cadena de razonamiento privada.

## Reglas del planner

1. `"de esos"`, `"estos"`, `"los anteriores"` usa `use_working_set=true`.
2. `"solo keywords"` autoriza únicamente `seo_keywords`.
3. `"completa SEO donde falte"` produce `section=seo`, `mode=FILL_MISSING` y los cuatro campos SEO.
4. `"revisa/dime/muestra"` es lectura y nunca mutación.
5. `"investiga"` marca `research_required=true`; la API no hace la investigación.
6. Si una mutación no determina con seguridad sección/campos/objetivo, devuelve aclaración en vez de adivinar.
7. El output del modelo nunca es una autorización suficiente por sí mismo: se vuelve a validar con `resolve_section`, `resolve_field_path`, `build_scoped_patch` y las políticas del dominio.

## Primer vertical slice para probar

Agregar un comando CLI `plan` que permita probar el cerebro sin modificar S-TECH:

```bash
python -m stech_agent.cli --db ./agent.sqlite3 plan "de esos completa solo keywords donde falten" --session-id 1
```

El comando debe imprimir el `PlannerDecision`, el target local resuelto y la cantidad de SKU seleccionados. No abre S-TECH, no abre Edge y no guarda cambios.

Esto permite validar primero la inteligencia de orquestación con órdenes reales antes de conectar el ejecutor conversacional.
