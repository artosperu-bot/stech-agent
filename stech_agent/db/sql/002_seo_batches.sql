CREATE TABLE IF NOT EXISTS seo_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    scope_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'RUNNING',
    publish_enabled INTEGER NOT NULL DEFAULT 0,
    total_items INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS seo_batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    sku TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'RESEARCH_PENDING',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, sku),
    FOREIGN KEY (batch_id) REFERENCES seo_batches(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_seo_batch_items_claim ON seo_batch_items(batch_id, state, position);
CREATE INDEX IF NOT EXISTS idx_seo_batch_items_lease ON seo_batch_items(batch_id, lease_until);

CREATE TABLE IF NOT EXISTS seo_research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_item_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    facts_json TEXT NOT NULL DEFAULT '{}',
    sources_json TEXT NOT NULL DEFAULT '[]',
    raw_text TEXT,
    raw_path TEXT,
    prompt_id TEXT,
    prompt_version TEXT,
    prompt_hash TEXT,
    provider_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_item_id),
    FOREIGN KEY (batch_item_id) REFERENCES seo_batch_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS seo_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_item_id INTEGER NOT NULL,
    current_seo_json TEXT NOT NULL DEFAULT '{}',
    generated_json TEXT NOT NULL DEFAULT '{}',
    proposed_patch_json TEXT NOT NULL DEFAULT '{}',
    qa_status TEXT NOT NULL,
    qa_notes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_item_id),
    FOREIGN KEY (batch_item_id) REFERENCES seo_batch_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS seo_publish_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_item_id INTEGER NOT NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    intended_patch_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_item_id) REFERENCES seo_batch_items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_seo_publish_attempts_item ON seo_publish_attempts(batch_item_id, id);
