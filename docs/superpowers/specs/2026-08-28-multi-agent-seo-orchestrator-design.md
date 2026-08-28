# STECH Multi-Agent SEO Orchestrator — Design

## Goal

Convert the current single-flow STECH Product Agent into an orchestrated pipeline that can process many products with specialized roles while preserving the existing safety guarantees around S-TECH writes.

Primary user command:

`de los productos que faltan complétales el SEO`

The system must be able to audit a scope, create work items only for SEO-incomplete/empty products, research product facts, generate only missing SEO fields, validate the result, stage it, publish to S-TECH, verify the saved result, and keep progress/recovery state.

## Selected browser architecture

Use two separate browser surfaces:

- **Microsoft Edge — Research/ChatGPT**
- **Google Chrome — S-TECH**

This preserves the browser paths already used by the project and keeps research isolated from production writes.

Initial concurrency:

- 1 Edge Research page
- 1 Chrome S-TECH page

Later, after measuring stability, Research may scale to 2–4 Edge pages. S-TECH publication remains single-writer and sequential.

## Design principles

1. The OpenAI API model remains the orchestrator/intelligence layer; it does not directly click S-TECH.
2. Research via Edge/ChatGPT is treated as an external information-gathering worker.
3. SQLite is the authoritative task-state store.
4. Excel is a staging/export view, not the source of truth for orchestration state.
5. Only one publisher may write to S-TECH at a time.
6. Existing SEO content is never silently overwritten. The default mutation mode is `FILL_MISSING`.
7. Every write must be followed by a fresh S-TECH read and verification.
8. A failed product does not invalidate successful products in the same batch.
9. Every state transition is resumable after process/browser failure.

## Pipeline

Each SKU moves through this state machine:

`DISCOVERED -> AUDITED -> RESEARCH_PENDING -> RESEARCHED -> SEO_PENDING -> SEO_GENERATED -> QA_PENDING -> READY -> PUBLISHING -> VERIFIED`

Failure/review states:

`RESEARCH_ERROR`, `QA_REVIEW`, `PUBLISH_ERROR`, `VERIFY_ERROR`, `BLOCKED_AMBIGUOUS`, `BLOCKED_UNSUPPORTED`.

Products already complete are marked `SEO_COMPLETE` and never enter the generation/publish path.

## Agents / workers

### 1. Orchestrator

Responsibilities:

- Interpret user intent and scope: all products, brand, category, subcategory, working set, explicit SKU list.
- Resolve the scope against the local catalog.
- Use the latest SEO audit to identify `SEO_EMPTY` + `SEO_INCOMPLETE` products.
- Create a batch and per-SKU work items in SQLite.
- Schedule work stages.
- Enforce that only one S-TECH publisher runs.
- Provide human-readable progress/status.

It never invents product facts and never writes directly to S-TECH.

### 2. Research Agent — Edge + ChatGPT

Responsibilities:

- Open/reuse a dedicated Edge research page.
- Search for authoritative product information using the product name, brand, SKU/part number, and local catalog context.
- Prefer official manufacturer product pages/manuals; use trusted retailer/distributor pages only as secondary sources.
- Extract structured facts and source URLs/titles.
- Return only factual product information; no SEO prose.
- Mark uncertain facts explicitly rather than guessing.

Research output is saved in SQLite as structured JSON and can also be exported to the staging workbook.

### 3. SEO Agent — OpenAI API model

Responsibilities:

- Receive current S-TECH SEO, validated research facts, product identity, and SEO rules.
- Generate only fields that are missing.
- Preserve all non-empty existing SEO fields.
- Produce:
  - SEO title
  - SEO description
  - keywords
  - 3 FAQ question/answer pairs
- Follow the STECH SEO prompt/rules, including Peru purchase intent and no unsupported technical claims.

No browser access.

### 4. QA Agent — deterministic first, model second

Deterministic checks:

- SKU/brand/model consistency.
- Required SEO fields present.
- FAQ count >= 3 and every FAQ has question + answer.
- No overwrite of protected existing values.
- No unsupported fields in the write patch.
- Length/format rules from the versioned SEO policy.
- Research provenance present for claims requiring technical facts.

Model QA is only used for semantic checks that deterministic rules cannot evaluate, such as whether generated text contradicts the validated facts.

Output:

- `READY`
- `QA_REVIEW` with explicit reasons

### 5. Staging Agent

Maintains a human-inspectable staging workbook and SQLite records.

Suggested workbook columns:

- Batch ID
- SKU
- Product name
- Brand
- Category
- Subcategory
- SEO audit status
- Current SEO title
- Current SEO description
- Current keywords
- Current FAQ count
- Research status
- Research source summary
- Proposed SEO title
- Proposed SEO description
- Proposed keywords
- Proposed FAQs
- QA status
- QA notes
- Publish status
- Verify status
- Last error
- Updated at

The workbook is continuously regenerated from SQLite; workers do not independently edit the same XLSX file concurrently.

### 6. Publisher Agent — Chrome + S-TECH

Single-writer only.

Responsibilities:

- Consume only `READY` work items.
- Open exact SKU in S-TECH.
- Re-read current SEO immediately before writing.
- Recompute the safe `FILL_MISSING` patch against the fresh current values.
- If a supposedly empty field was filled manually after staging, skip that field rather than overwrite it.
- Enter only supported/authorized fields.
- Press S-TECH `Aceptar` exactly once.
- Re-open/re-read the product.
- Compare all intended fields with actual saved values.
- Mark `VERIFIED` only on exact verification.

If verification differs, mark `VERIFY_ERROR` and do not report success.

## Batch behavior

Example command:

`de los productos que faltan complétales el SEO`

Expected behavior:

1. Resolve the current SEO audit.
2. Select only `SEO_EMPTY` + `SEO_INCOMPLETE` SKUs.
3. Show a preflight summary before any write:
   - total selected
   - already complete
   - empty
   - partial
   - ambiguous/blocked
4. Ask for `ACEPTAR` before starting a batch that can write.
5. Start the pipeline.
6. Continue independent work items even if one fails.
7. End with counts by state.

Example progress output:

`Lote SEO #12 — 845 productos`

`Research: 120/845 | SEO generado: 98 | QA READY: 91 | Publicados: 54 | Verificados: 52 | Review/Error: 2`

## Concurrency

Phase 1:

- Research workers: 1
- SEO generation workers: up to 2 API calls in parallel
- QA workers: up to 2
- Publisher workers: exactly 1

Phase 2 after live stability data:

- Research workers: 2–4 Edge tabs/pages
- SEO/QA concurrency may scale independently
- Publisher remains exactly 1

Use SQLite task claiming/leases so two workers cannot claim the same SKU/stage.

## SQLite additions

Add normalized tables rather than encoding everything in one JSON blob.

### seo_batches

- id
- session_id
- scope_json
- status
- created_at
- started_at
- completed_at
- total_items

### seo_batch_items

- id
- batch_id
- sku
- state
- attempt_count
- lease_owner
- lease_until
- last_error
- updated_at

Unique constraint: `(batch_id, sku)`.

### seo_research

- batch_item_id
- facts_json
- sources_json
- confidence/status
- created_at

### seo_proposals

- batch_item_id
- current_seo_json
- proposed_patch_json
- qa_status
- qa_notes_json
- created_at

### seo_publish_attempts

- batch_item_id
- before_json
- intended_patch_json
- after_json
- status
- error
- created_at

Existing audit events remain useful for live verified writes and rollback.

## Recovery and idempotency

On restart:

- `PUBLISHING` items whose lease expired are returned to `READY` only after a fresh S-TECH read.
- `RESEARCH_PENDING`, `SEO_PENDING`, and `QA_PENDING` are safe to retry.
- `VERIFIED` items are terminal unless the user explicitly requests re-audit.
- No stage assumes browser state survived a crash.

Each worker rehydrates its necessary context from SQLite.

## Human commands

The chat should support natural commands such as:

- `completa el SEO de los que faltan`
- `hazlo solo para JBL`
- `pausa el lote`
- `continúa el lote`
- `cómo va el lote`
- `muéstrame los que están en review`
- `de los errores reintenta solo research`
- `no publiques todavía, solo déjalos listos`
- `exporta el staging a Excel`

Guided menu should expose equivalent actions without requiring exact wording.

## Safety gates

Before batch publication:

- Scope must be explicit/resolved.
- Ambiguous SKUs are excluded.
- SEO audit exists or is refreshed.
- Proposed patch must be `FILL_MISSING` unless the user explicitly requests replacement.
- Existing non-empty SEO cannot be overwritten by default.
- Publisher must re-read before write.
- S-TECH `Aceptar` required for every actual product save.
- Fresh post-save verification required.
- All failures are visible in batch status.

## Testing strategy

1. Unit tests for state transitions and leases.
2. Unit tests that `FILL_MISSING` never overwrites non-empty SEO.
3. Unit tests for research/SEO/QA contracts.
4. Unit tests for workbook generation from SQLite.
5. Integration tests with fake Research/Publisher workers.
6. Live read-only test against `PROD-TEST`.
7. Live one-product publish/verify test on `PROD-TEST`.
8. Small brand batch read/generate without publish.
9. Small controlled batch publish.
10. Only after those pass, allow full-catalog batch execution.

## Implementation sequence

1. Batch schema + repositories + state machine.
2. Orchestrator commands/status/pause/resume.
3. Staging workbook projection.
4. Research worker abstraction and Edge research implementation.
5. SEO generation worker using current model/API.
6. Deterministic QA + optional model QA.
7. Publisher integration with current `ProductWriter` and fresh pre-write reads.
8. Guided menu integration.
9. Live certification in progressively larger scopes.

## Explicit non-goals for first release

- No two concurrent S-TECH writers.
- No image/multimedia generation/upload in the SEO pipeline.
- No autonomous deletion.
- No automatic overwrite of existing SEO.
- No dependence on OpenAI Web Search API.
- No embeddings/RAG requirement for this pipeline; local catalog + SQLite + research facts are sufficient initially.
