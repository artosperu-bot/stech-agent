CREATE TABLE IF NOT EXISTS catalog_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    raw_headers_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalog_products (
    snapshot_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    source_order INTEGER NOT NULL,
    name TEXT,
    brand TEXT,
    category TEXT,
    subcategory TEXT,
    stock INTEGER,
    on_offer INTEGER,
    visible INTEGER,
    price TEXT,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    conflict_fields_json TEXT NOT NULL DEFAULT '[]',
    source_json TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, sku),
    FOREIGN KEY (snapshot_id) REFERENCES catalog_snapshots(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_catalog_products_sku ON catalog_products(sku);
CREATE INDEX IF NOT EXISTS idx_catalog_products_brand ON catalog_products(brand);
CREATE INDEX IF NOT EXISTS idx_catalog_products_ambiguous ON catalog_products(snapshot_id, ambiguous);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS working_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    skus_json TEXT NOT NULL,
    query_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, name),
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    action TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'PENDING',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS task_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    sku TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    resume_required INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(task_id, sku),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_items_claim ON task_items(task_id, state, position);

CREATE TABLE IF NOT EXISTS changesets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    action TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'DRAFT',
    field_mask_json TEXT NOT NULL,
    approval_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS changeset_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    changeset_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    FOREIGN KEY (changeset_id) REFERENCES changesets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    task_id INTEGER,
    event_type TEXT NOT NULL,
    sku TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prompt_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    sku TEXT,
    prompt_id TEXT NOT NULL,
    prompt_version TEXT,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}',
    response_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_web_cache (
    sku TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
