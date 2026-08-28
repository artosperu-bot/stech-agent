# STECH Multi-Agent SEO Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `completa el SEO de los que faltan` run as a resumable multi-worker batch that preserves the proven V7.2 Edge/ChatGPT prompt, stages every SKU in SQLite/Excel, and publishes through one verified S-TECH writer.

**Architecture:** Compatibility-first: the Research/SEO worker reuses the exact V7.2 `build_research_prompt()` behavior in a dedicated real Microsoft Edge session, so research + SEO output remains the proven flow. SQLite owns batch state; deterministic QA converts the validated V7.2 payload into a `FILL_MISSING` proposal; one Chrome/Playwright publisher re-reads S-TECH immediately before writing, presses `Aceptar`, and verifies the result. The OpenAI API model remains the conversational/orchestration brain and never clicks S-TECH.

**Tech Stack:** Python 3.11+, SQLite, openpyxl, Selenium 4.47+ for Research Edge, Playwright 1.55+ for S-TECH Chrome, OpenAI Responses API for intent/orchestration, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-multi-agent-seo-orchestrator-design.md`

## Global Constraints

- Preserve the exact V7.2 SEO prompt contract and validator: SKU/Part Number first, authoritative/official sources first, no invented technical facts, Peru intent, 35-70 validator title range, 120-170 validator description range, 5-9 keywords target, exactly 3 FAQ, at least one technical URL.
- `SEO_PRODUCTO_STECH_V1` is versioned/hashable; a temporary prompt never overwrites it.
- Existing different/partial S-TECH SEO is never overwritten by default. Batch mutation is `FILL_MISSING` only.
- Exact SKU is authoritative; ambiguous duplicate/conflict SKUs are blocked.
- Edge Research and Chrome S-TECH use separate browser resources.
- Research can be retried; S-TECH publication is single-writer and sequential.
- Every real write requires fresh pre-read, one S-TECH `Aceptar`, fresh post-read, exact verification, and audit.
- SQLite is orchestration truth. Excel is regenerated from SQLite and never concurrently edited by workers.
- No deletion, no multimedia writes, no OpenAI Web Search API, no direct S-TECH database writes.
- Full-catalog publish stays gated behind successful `PROD-TEST`/small-batch live certification.

---

### Task 1: Port V7.2 prompt/validator as an immutable SEO skill

**Files:**
- Create: `stech_agent/seo/__init__.py`
- Create: `stech_agent/seo/v72.py`
- Create: `stech_agent/prompts/__init__.py`
- Create: `stech_agent/prompts/registry.py`
- Create: `stech_agent/prompts/seo_producto_stech_v1.txt`
- Test: `tests/seo/test_v72_skill.py`

**Interfaces:**
- Produces: `build_research_prompt(product: dict, product_url: str | None = None) -> str`.
- Produces: `extract_json_object(raw: str) -> dict` and `validate_seo_payload(payload: dict) -> dict`.
- Produces: `PromptRegistry.get("SEO_PRODUCTO_STECH_V1") -> PromptDefinition` with `prompt_id`, `version`, `sha256`, `text`.

- [ ] **Step 1: Write failing prompt-equivalence and validator tests**

```python
def test_v72_prompt_keeps_exact_contract():
    prompt = build_research_prompt({"name":"Producto Test","sku":"PROD-TEST","source_brand":"TEST"})
    assert "SKU / Part Number de autoridad interna: PROD-TEST" in prompt
    assert '"titulo_seo": ""' in prompt
    assert '"fuentes_tecnicas": ["https://..."]' in prompt
    assert "Genera exactamente 3 FAQ" in prompt


def test_v72_validator_requires_three_faq_and_url():
    with pytest.raises(ValueError, match="exactamente 3 FAQ"):
        validate_seo_payload(valid_payload(faqs=[]))
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest -q tests/seo/test_v72_skill.py`

Expected: import/module failures.

- [ ] **Step 3: Port V7.2 code without rewriting prompt wording**

Copy the proven V7.2 `REQUIRED_PAYLOAD_KEYS`, `clean_text`, `extract_json_object`, `validate_seo_payload`, and `build_research_prompt` semantics. The registry reads the prompt template resource and stores its SHA-256; runtime code cannot mutate the official prompt.

- [ ] **Step 4: Run GREEN + compile**

Run: `python -m pytest -q tests/seo/test_v72_skill.py && python -m compileall -q stech_agent`

- [ ] **Step 5: Commit**

```bash
git add stech_agent/seo stech_agent/prompts tests/seo/test_v72_skill.py
git commit -m "feat: preserve v72 seo prompt and validator"
```

### Task 2: Add durable SEO batch schema, state machine, and repository

**Files:**
- Create: `stech_agent/db/sql/002_seo_batches.sql`
- Modify: `stech_agent/db/migrations.py`
- Create: `stech_agent/seo/batches.py`
- Test: `tests/seo/test_batch_repository.py`

**Interfaces:**
- Produces: `SeoBatchRepository.create(session_id, skus, scope, publish) -> int`.
- Produces: `claim(batch_id, from_states, to_state, worker_id, lease_seconds) -> SeoBatchItem | None`.
- Produces: `transition(item_id, expected_state, new_state, error=None)`.
- Produces: `status(batch_id) -> dict` and `pause/resume/cancel`.

- [ ] **Step 1: Write failing migration/state tests**

```python
def test_batch_is_unique_per_sku_and_claim_is_exclusive(db):
    repo = SeoBatchRepository(db)
    batch = repo.create(1, ["A","B"], {"brand":"JBL"}, publish=True)
    first = repo.claim(batch, {"RESEARCH_PENDING"}, "RESEARCHING", "w1", 60)
    second = repo.claim(batch, {"RESEARCH_PENDING"}, "RESEARCHING", "w2", 60)
    assert first.sku != second.sku
```

Also assert duplicate `(batch_id, sku)` is impossible and stale `RESEARCHING/PUBLISHING` leases recover to a safe resumable state.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/seo/test_batch_repository.py`

- [ ] **Step 3: Implement migration 002 and repository**

Tables: `seo_batches`, `seo_batch_items`, `seo_research`, `seo_proposals`, `seo_publish_attempts`. Store JSON as TEXT, timestamps as SQLite timestamps, unique `(batch_id, sku)`, indexed `state`/`lease_until`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/seo/test_batch_repository.py`

- [ ] **Step 5: Commit**

```bash
git add stech_agent/db stech_agent/seo/batches.py tests/seo/test_batch_repository.py
git commit -m "feat: add durable seo batch state"
```

### Task 3: Restore the proven real Edge/ChatGPT research worker

**Files:**
- Modify: `pyproject.toml`
- Create: `stech_agent/research/__init__.py`
- Create: `stech_agent/research/edge_chatgpt.py`
- Test: `tests/research/test_edge_chatgpt.py`

**Interfaces:**
- Produces: `EdgeChatGPTWorker.start()`, `generate(product) -> ResearchSeoResult`, `is_alive()`, `close()`.
- `ResearchSeoResult` contains validated payload, raw text, raw diagnostic path, prompt hash, provider id.

- [ ] **Step 1: Write failing transport tests around pure helpers**

Test prompt echo rejection, login markers, response-candidate selection, transient/rate-limit classification, and complete JSON detection without launching Edge.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/research/test_edge_chatgpt.py`

- [ ] **Step 3: Port V7.2 Edge behavior**

Add `selenium>=4.47,<5`. Reuse real Edge profile `%LOCALAPPDATA%\STECH_PRODUCT_AGENT\profiles\research_edge_real`; find `msedge.exe`; launch/attach with remote debugging; verify full prompt delivery; wait for login when required; capture newest complete response; reject prompt/schema echo; validate through Task 1; persist raw response under the agent work/log directory. One worker owns one Edge profile lock.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/research/test_edge_chatgpt.py`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml stech_agent/research tests/research/test_edge_chatgpt.py
git commit -m "feat: restore edge chatgpt seo research worker"
```

### Task 4: Build deterministic QA + FILL_MISSING proposal worker

**Files:**
- Create: `stech_agent/seo/qa.py`
- Create: `stech_agent/seo/proposals.py`
- Test: `tests/seo/test_qa_and_fill_missing.py`

**Interfaces:**
- Produces: `classify_current_seo(values) -> SEO_COMPLETE|SEO_INCOMPLETE|SEO_EMPTY`.
- Produces: `build_fill_missing_patch(current, generated) -> dict`.
- Produces: `validate_proposal(current, generated, patch) -> QaResult`.

- [ ] **Step 1: Write failing no-overwrite tests**

```python
def test_fill_missing_never_overwrites_existing_title():
    current = {"seo_title":"Manual title", "seo_description":"", "seo_keywords":"", "seo_faqs":[]}
    generated = generated_payload()
    patch = build_fill_missing_patch(current, generated)
    assert "seo_title" not in patch
    assert patch["seo_description"] == generated["descripcion_seo"]
```

Test partial FAQ behavior: preserve non-empty existing FAQ pairs; only fill missing slots up to 3; if existing structure cannot be safely merged, return `QA_REVIEW` rather than deleting/reordering content.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/seo/test_qa_and_fill_missing.py`

- [ ] **Step 3: Implement deterministic QA**

Use V7.2 validator first; require at least one source URL; reject generated brand/model identity conflict when the exact SKU evidence indicates another variant; authorize only `seo_title`, `seo_description`, `seo_keywords`, `seo_faq`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/seo/test_qa_and_fill_missing.py`

- [ ] **Step 5: Commit**

```bash
git add stech_agent/seo/qa.py stech_agent/seo/proposals.py tests/seo/test_qa_and_fill_missing.py
git commit -m "feat: build safe seo fill-missing proposals"
```

### Task 5: Project the batch state into a staging Excel

**Files:**
- Create: `stech_agent/seo/staging.py`
- Test: `tests/seo/test_staging_workbook.py`

**Interfaces:**
- Produces: `export_batch_staging(db, batch_id, path) -> Path`.

- [ ] **Step 1: Write failing workbook tests**

Assert one row per SKU with: batch id, SKU, product name, brand/category/subcategory, audit status, current SEO, generated SEO, sources, QA state/notes, publish state, last error, updated timestamp.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/seo/test_staging_workbook.py`

- [ ] **Step 3: Implement atomic workbook regeneration**

Write to `*.tmp.xlsx`, close workbook, `os.replace()` into final path. Workers never append to XLSX directly.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/seo/test_staging_workbook.py`

- [ ] **Step 5: Commit**

```bash
git add stech_agent/seo/staging.py tests/seo/test_staging_workbook.py
git commit -m "feat: export seo batch staging workbook"
```

### Task 6: Add the single-writer S-TECH SEO publisher including FAQ

**Files:**
- Modify: `stech_agent/stech/product_writer.py`
- Modify: `stech_agent/agent/live_executor.py`
- Create: `stech_agent/seo/publisher.py`
- Test: `tests/seo/test_publisher.py`

**Interfaces:**
- Produces: `SeoPublisher.publish(item_id) -> PublishResult`.
- Extends live writer to support `seo_faq` safely with exactly three desired FAQ slots under FILL_MISSING semantics.

- [ ] **Step 1: Write failing writer/publisher tests**

Fake the live reader/writer and prove: fresh pre-read; manual values added after staging are preserved; unsafe extra non-empty FAQ triggers review; `Aceptar` only when patch non-empty; post-read must match every intended field before `VERIFIED`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/seo/test_publisher.py`

- [ ] **Step 3: Implement FAQ setter and publisher**

Port the proven V7.2 selectors (`+ Añadir Pregunta`, question/answer textboxes) behind current `ProductWriter`; do not use arbitrary coordinates. Publisher serializes access with a process lock and records `before/intended/after/status/error` in `seo_publish_attempts` plus existing audit events.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/seo/test_publisher.py`

- [ ] **Step 5: Commit**

```bash
git add stech_agent/stech/product_writer.py stech_agent/agent/live_executor.py stech_agent/seo/publisher.py tests/seo/test_publisher.py
git commit -m "feat: publish and verify fill-missing seo"
```

### Task 7: Orchestrate research, QA, staging, and publishing as a resumable pipeline

**Files:**
- Create: `stech_agent/seo/orchestrator.py`
- Test: `tests/seo/test_orchestrator.py`

**Interfaces:**
- Produces: `SeoBatchOrchestrator.create_batch(...)`, `run(batch_id)`, `status(batch_id)`, `pause`, `resume`, `retry_reviews`.

- [ ] **Step 1: Write failing integration tests with fake workers**

Prove: SEO_COMPLETE items never enter research; one failed research SKU does not stop others; READY items can publish while later items are researching; publisher concurrency never exceeds 1; restart resumes non-terminal items and never republishes VERIFIED items.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/seo/test_orchestrator.py`

- [ ] **Step 3: Implement worker loops**

Phase 1 uses one Research Edge worker, one deterministic QA worker, one staging exporter, one S-TECH publisher. Maintain batch `publish_enabled` so `solo déjalos listos` stops at READY. Emit human progress counts after every state change.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/seo/test_orchestrator.py`

- [ ] **Step 5: Commit**

```bash
git add stech_agent/seo/orchestrator.py tests/seo/test_orchestrator.py
git commit -m "feat: orchestrate resumable seo workers"
```

### Task 8: Connect natural chat/menu commands and mandatory batch confirmation

**Files:**
- Modify: `stech_agent/agent/runtime.py`
- Modify: `stech_agent/agent/openai_brain.py`
- Modify: `stech_agent/agent/guided_menu.py`
- Modify: `scripts/stech_agent_chat.py`
- Test: `tests/agent/test_seo_batch_commands.py`

**Interfaces:**
- Natural commands: `completa el SEO de los que faltan`, `solo JBL`, `no publiques todavía`, `cómo va el lote`, `pausa`, `continúa`, `exporta staging`.

- [ ] **Step 1: Write failing conversation tests**

Assert `de los que faltan complétales el SEO` resolves only latest audit `SEO_EMPTY + SEO_INCOMPLETE`, excludes ambiguous SKUs, displays preflight counts, and requires exact `ACEPTAR` before any publish-capable batch starts.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/agent/test_seo_batch_commands.py`

- [ ] **Step 3: Implement chat/menu bridge**

Add a guided SEO option `Completar faltantes`. Chat prints batch id and live progress, not raw JSON. `solo preparar` creates the same batch with publishing disabled.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/agent/test_seo_batch_commands.py`

- [ ] **Step 5: Commit**

```bash
git add stech_agent/agent scripts/stech_agent_chat.py tests/agent/test_seo_batch_commands.py
git commit -m "feat: expose seo batch orchestration in chat"
```

### Task 9: Full verification and Windows live certification path

**Files:**
- Create: `scripts/certificar_seo_multiagente.py`
- Create: `tests/manual/seo_multiagent_live.md`

**Interfaces:**
- `--sku PROD-TEST --generate-only` verifies Edge prompt/result without S-TECH mutation.
- `--sku PROD-TEST --publish` requires explicit confirmation and performs one reversible/controlled SEO publish only when safe.
- `--brand <small-brand> --generate-only` proves a small batch before full catalog.

- [ ] **Step 1: Run entire automated suite**

Run: `python -m pytest -q`

Expected: zero failures.

- [ ] **Step 2: Compile**

Run: `python -m compileall -q stech_agent scripts`

Expected: exit code 0.

- [ ] **Step 3: Run Edge generate-only live smoke on Windows**

Expected: Edge uses logged-in Research profile, exact V7.2 prompt is delivered, validated payload + source URL persist in SQLite/staging, Chrome does not open.

- [ ] **Step 4: Run one controlled S-TECH publish**

Expected: exact SKU, fresh pre-read, FILL_MISSING only, one `Aceptar`, fresh read, exact VERIFIED result. If existing SEO differs/partial in a way that cannot be safely merged, result is REVIEW and no overwrite.

- [ ] **Step 5: Run small brand generate-only, then small controlled publish**

Only after both pass should the chat allow a full-catalog publish batch.

- [ ] **Step 6: Commit certification utilities**

```bash
git add scripts/certificar_seo_multiagente.py tests/manual/seo_multiagent_live.md
git commit -m "test: add multi-agent seo live certification"
```

## Self-review

- Spec coverage: batch persistence, Edge Research, exact V7.2 prompt, staging Excel, deterministic QA, single writer, FILL_MISSING, verification, recovery, chat/menu, pause/status, and live certification all map to tasks above.
- No placeholders: every production capability has an explicit interface/test path; full-catalog publish is deliberately gated by live certification rather than left undefined.
- Type consistency: the central identifiers are `batch_id`, `item_id`, exact string `sku`, and state transitions owned by `SeoBatchRepository`; workers exchange persisted records, not shared browser objects.
