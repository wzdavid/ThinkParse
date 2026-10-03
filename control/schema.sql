CREATE TABLE IF NOT EXISTS blobs (
    sha256 TEXT PRIMARY KEY,
    byte_size BIGINT NOT NULL,
    storage_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    blob_sha256 TEXT NOT NULL REFERENCES blobs (sha256),
    file_name TEXT NOT NULL,
    legacy_options JSONB NOT NULL,
    tier TEXT NOT NULL,
    ocr_mode TEXT NOT NULL,
    engine TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    attempt INTEGER NOT NULL DEFAULT 0,
    upstream_job_id TEXT,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    legacy_backend TEXT NOT NULL,
    next_attempt_at TIMESTAMPTZ,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    upstream_base_url TEXT NOT NULL DEFAULT '',
    purged_at TIMESTAMPTZ,
    upstream_finished_at TIMESTAMPTZ,
    page_count INTEGER,
    batch_id TEXT,
    priority INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS tasks_status_created_idx ON tasks (status, created_at);

CREATE TABLE IF NOT EXISTS artifacts (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks (id),
    kind TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    filename TEXT
);

CREATE INDEX IF NOT EXISTS artifacts_task_idx ON artifacts (task_id);

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS upstream_base_url TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS purged_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS upstream_finished_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS page_count INTEGER;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS batch_id TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS tasks_queue_priority_idx ON tasks (priority DESC, created_at);

CREATE INDEX IF NOT EXISTS tasks_batch_idx ON tasks (batch_id, created_at) WHERE batch_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS control_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    storage_key TEXT NOT NULL,
    purpose TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    sha256 TEXT,
    mime_type TEXT,
    task_id TEXT
);

CREATE INDEX IF NOT EXISTS files_task_idx ON files (task_id);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    mime_type TEXT NOT NULL,
    sha256 TEXT,
    status TEXT NOT NULL,
    storage_key TEXT,
    file_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
