CREATE TABLE IF NOT EXISTS seo_audit_cache (
    sku TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    values_json TEXT NOT NULL DEFAULT '{}',
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL DEFAULT 'stech_live'
);
CREATE INDEX IF NOT EXISTS idx_seo_audit_cache_status ON seo_audit_cache(status, checked_at);
