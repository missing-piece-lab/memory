-- The derived graph. Idempotent: safe to re-run. `{dim}` is the embedding dimension (engine.graph_pg.ensure_schema fills it
-- from EMBED_DIM). vector(N) is fixed once created: it must match EMBED_DIM and the model; ensure_schema refuses a mismatch.
-- The files are canonical; every table here is rebuilt by `python -m engine.ingest` except the findings history.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS nodes (
    id             BIGSERIAL PRIMARY KEY,
    slug           TEXT UNIQUE NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    body           TEXT NOT NULL,
    type           TEXT,                              -- user | feedback | project | reference
    project        TEXT,                              -- the evidence scope
    status         TEXT NOT NULL DEFAULT 'active',    -- active | archived (a file that left the store; never deleted)
    written_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(), -- moves on a CONTENT change only; verdicts and anchors key off it
    valid_to       TIMESTAMPTZ,                       -- closed when another memory supersedes this one
    invalidated_by TEXT,
    refs           JSONB NOT NULL DEFAULT '[]'::jsonb, -- the references the body asserts (engine.store.extract_refs)
    frontmatter    JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding      vector({dim}),
    content_tsv    tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,'') || ' ' || coalesce(body,''))) STORED
);
CREATE INDEX IF NOT EXISTS nodes_tsv_idx   ON nodes USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS nodes_embed_idx ON nodes USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS edges (
    src_slug TEXT NOT NULL,
    dst_slug TEXT NOT NULL,                           -- may point at a memory not yet written: a dangling edge is a TODO
    relation TEXT NOT NULL DEFAULT 'relates_to',      -- relates_to ([[link]]) | supersedes
    PRIMARY KEY (src_slug, dst_slug, relation)
);

CREATE TABLE IF NOT EXISTS runs (
    id          BIGSERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    mode        TEXT,
    counts      JSONB
);

CREATE TABLE IF NOT EXISTS findings (                 -- one row per memory per sweep; the history the 2-of-3 rule reads
    id         BIGSERIAL PRIMARY KEY,
    run_id     BIGINT REFERENCES runs(id) ON DELETE CASCADE,
    node_id    BIGINT REFERENCES nodes(id) ON DELETE CASCADE,
    slug       TEXT NOT NULL,
    result     TEXT NOT NULL,                         -- ok | drift | changed | uncheckable_only
    details    JSONB NOT NULL,                        -- [{ref, kind, status, found_in}]
    verdict    TEXT,                                  -- CONFIRMED | STALE | CONTRADICTED | UNCLEAR | NULL = not judged
    reason     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS findings_slug_idx ON findings (slug, id DESC);

CREATE TABLE IF NOT EXISTS anchors (                  -- every ok reference pinned to the git blob of the file it resolved to
    slug        TEXT NOT NULL,
    ref         TEXT NOT NULL,
    repo_path   TEXT,
    blob_sha    TEXT NOT NULL,
    anchored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (slug, ref)
);

CREATE TABLE IF NOT EXISTS recall_events (            -- every recall, whoever asked; the only thing written on read
    id       BIGSERIAL PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source   TEXT NOT NULL,
    session  TEXT,
    query    TEXT NOT NULL,
    returned TEXT[] NOT NULL DEFAULT '{}',
    top_sim  NUMERIC(6,4)
);
