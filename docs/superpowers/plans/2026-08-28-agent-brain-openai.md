# STECH Agent Brain OpenAI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que `gpt-5-mini-2025-08-07` interprete órdenes del usuario y produzca planes estrictos que el agente local pueda validar y ejecutar después.

**Architecture:** La API de OpenAI funciona únicamente como planner de texto. El modelo recibe una orden y contexto mínimo, devuelve JSON con `PlannerDecision`, y Python valida/convierte ese resultado a filtros y scopes de dominio. El primer slice es read-only mediante CLI `plan`.

**Tech Stack:** Python 3.11+, OpenAI Python SDK, python-dotenv, SQLite, pytest, catálogo y scopes existentes.

**Spec:** `docs/superpowers/specs/2026-08-28-agent-brain-openai-design.md`

## Global Constraints

- `OPENAI_MODEL=gpt-5-mini-2025-08-07` por defecto.
- `OPENAI_API_KEY` se lee desde entorno/`.env`; nunca se versiona.
- No pasar `tools` al Responses API; no web search, file search ni computer use.
- El modelo solo propone; `query_products` y `build_scoped_patch` validan localmente.
- El comando inicial es dry-run/read-only y no abre S-TECH ni Edge.
- SKU permanece string exacto.

---

### Task 1: Configuración segura del planner

**Files:**
- Create: `.env.example`
- Modify: `pyproject.toml`
- Create: `stech_agent/agent/__init__.py`
- Create: `stech_agent/agent/config.py`
- Test: `tests/agent/test_config.py`

**Interfaces:**
- Produces: `PlannerSettings.from_env() -> PlannerSettings` con `api_key` y `model`.

- [ ] **Step 1:** escribir tests para modelo por defecto, override y API key ausente.
- [ ] **Step 2:** ejecutar tests y confirmar RED.
- [ ] **Step 3:** agregar `openai` + `python-dotenv`, `.env.example` y `PlannerSettings`.
- [ ] **Step 4:** ejecutar tests y confirmar GREEN.

### Task 2: Schema estricto de PlannerDecision

**Files:**
- Create: `stech_agent/agent/schema.py`
- Test: `tests/agent/test_schema.py`

**Interfaces:**
- Produces: `PlannerDecision.from_dict(payload)` y `PLANNER_JSON_SCHEMA`.

- [ ] **Step 1:** tests para acción, filtros, campos, modos y rechazo de valores desconocidos.
- [ ] **Step 2:** confirmar RED.
- [ ] **Step 3:** implementar dataclass/enums y JSON Schema con `additionalProperties=false`.
- [ ] **Step 4:** confirmar GREEN.

### Task 3: Adaptador OpenAI sin herramientas web

**Files:**
- Create: `stech_agent/agent/openai_brain.py`
- Test: `tests/agent/test_openai_brain.py`

**Interfaces:**
- Consumes: `PlannerSettings`, `PlannerDecision`, `PLANNER_JSON_SCHEMA`.
- Produces: `OpenAIPlanner.plan(command, context) -> PlannerDecision`.

- [ ] **Step 1:** test con cliente fake que inspeccione request y verifique que no existe `tools`.
- [ ] **Step 2:** confirmar RED.
- [ ] **Step 3:** implementar `client.responses.create(...)` con `text.format=json_schema`, `strict=true` y parseo de `response.output_text`.
- [ ] **Step 4:** confirmar GREEN.

### Task 4: Conversión del plan al dominio local

**Files:**
- Create: `stech_agent/agent/resolver.py`
- Test: `tests/agent/test_resolver.py`

**Interfaces:**
- Produces: `resolve_decision(decision, products, working_set_skus=()) -> ResolvedPlan`.

- [ ] **Step 1:** tests para `brand`, stock, SKU exacto, working set y scope SEO.
- [ ] **Step 2:** confirmar RED.
- [ ] **Step 3:** construir `TargetSpec`, ejecutar `query_products`, resolver aliases/scopes y bloquear campos no autorizados.
- [ ] **Step 4:** confirmar GREEN.

### Task 5: CLI `plan` dry-run

**Files:**
- Modify: `stech_agent/cli.py`
- Test: `tests/agent/test_cli_plan.py`

**Interfaces:**
- CLI: `python -m stech_agent.cli --db DB plan "ORDEN" [--session-id ID]`.

- [ ] **Step 1:** test CLI con planner inyectable/fake.
- [ ] **Step 2:** confirmar RED.
- [ ] **Step 3:** cargar `.env`, snapshot más reciente y working set `current`, invocar planner y resolver localmente.
- [ ] **Step 4:** imprimir JSON con `decision`, `resolved_skus`, `count` y `dry_run=true`.
- [ ] **Step 5:** ejecutar suite completa + compileall.

### Task 6: Prueba manual en PC020

**Files:**
- Create: `scripts/probar_agent_brain.py`

**Interfaces:**
- Usa el mismo DB/snapshot y configuración real de `.env`.

- [ ] **Step 1:** ingerir el export real si aún no está ingerido.
- [ ] **Step 2:** probar `dime los JBL con stock mayor a 5`.
- [ ] **Step 3:** guardar esos SKU como working set y probar `de esos completa solo keywords donde falten`.
- [ ] **Step 4:** verificar que `research_required=true`, `mode=FILL_MISSING`, `fields=[seo_keywords]` y que no se abrió navegador.
