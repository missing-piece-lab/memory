"""graph_pg — the production graph: Postgres + pgvector, the same interface as graph_mem. `GRAPH_DSN=postgresql://...`
selects it. Keyword leg = Postgres full-text rank (websearch_to_tsquery), vector leg = pgvector cosine, fused with
reciprocal rank fusion in SQL. Schema: db/schema.sql (idempotent; `ensure_schema()` applies it with the embedding
dimension from EMBED_DIM). Needs `psycopg` (imported here only, so the rest of the engine runs without it).

Every write the engine makes goes through this file or graph_mem; nothing else touches the database, and the files
stay canonical: `docker compose down -v` loses nothing that `python -m engine.ingest` cannot rebuild — except the
findings history, which is why the compose file keeps a volume and the README says to dump it.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(os.path.dirname(HERE), "db", "schema.sql")

RECALL_SQL = """
WITH q AS (SELECT %(emb)s::vector AS emb, websearch_to_tsquery('english', %(text)s) AS tsq),
live AS (SELECT * FROM nodes WHERE status='active' AND valid_to IS NULL AND coalesce(type,'') <> ALL(%(excl)s::text[])),
vec AS (SELECT id, row_number() OVER (ORDER BY embedding <=> (SELECT emb FROM q)) AS rnk,
               1 - (embedding <=> (SELECT emb FROM q)) AS sim
        FROM live WHERE embedding IS NOT NULL AND %(has_vec)s::boolean ORDER BY embedding <=> (SELECT emb FROM q) LIMIT 50),
kw AS (SELECT id, row_number() OVER (ORDER BY ts_rank(content_tsv, (SELECT tsq FROM q)) DESC) AS rnk
       FROM live WHERE content_tsv @@ (SELECT tsq FROM q) LIMIT 50),
fused AS (SELECT id, SUM(1.0/(60 + rnk)) AS score FROM (SELECT id, rnk FROM vec UNION ALL SELECT id, rnk FROM kw) u GROUP BY id)
SELECT n.slug, n.title, n.description, n.body, n.project, n.type, round(f.score::numeric, 5), round(v.sim::numeric, 4)
FROM fused f JOIN nodes n ON n.id = f.id LEFT JOIN vec v ON v.id = f.id
ORDER BY f.score DESC LIMIT %(k)s"""

FLAGGED_SQL = """
WITH recent AS (
  SELECT f.node_id, f.id, f.verdict, f.reason, f.created_at,
         row_number() OVER (PARTITION BY f.node_id ORDER BY f.id DESC) AS rn
  FROM findings f JOIN nodes n ON n.id = f.node_id WHERE f.created_at > n.updated_at AND f.verdict IS NOT NULL)
SELECT n.slug, n.project,
       (array_agg(r.verdict ORDER BY r.id DESC) FILTER (WHERE r.verdict IN ('STALE','CONTRADICTED')))[1],
       (array_agg(r.reason  ORDER BY r.id DESC) FILTER (WHERE r.verdict IN ('STALE','CONTRADICTED')))[1],
       (array_agg(r.id      ORDER BY r.id DESC) FILTER (WHERE r.verdict IN ('STALE','CONTRADICTED')))[1],
       count(*) FILTER (WHERE r.verdict IN ('STALE','CONTRADICTED')), count(*), max(r.created_at)
FROM recent r JOIN nodes n ON n.id = r.node_id
WHERE r.rn <= 3 AND n.status='active' AND n.valid_to IS NULL
GROUP BY n.slug, n.project HAVING count(*) FILTER (WHERE r.verdict IN ('STALE','CONTRADICTED')) >= 2 ORDER BY 8 DESC"""


def vec_literal(v):
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


class PostgresGraph:
    def __init__(self, dsn):
        import psycopg
        self.conn = psycopg.connect(dsn, autocommit=False)

    def ensure_schema(self, dim=None):
        from .embed import config
        dim = dim or config()["dim"]                            # the same default per embedder kind as the startup check
        with open(SCHEMA, encoding="utf-8") as fh, self.conn.cursor() as cur:
            cur.execute(fh.read().replace("{dim}", str(dim)))
        self.conn.commit()
        have = self._q("SELECT atttypmod FROM pg_attribute WHERE attrelid='nodes'::regclass AND attname='embedding'", fetch="one")
        if have and have[0] > 0 and have[0] != dim:         # the column was created with another dimension: say so, once, at startup
            raise SystemExit(f"schema: nodes.embedding is vector({have[0]}) but EMBED_DIM is {dim} — set EMBED_DIM={have[0]}, "
                             f"or `docker compose down -v` and ingest again with the new model")

    def save(self):
        self.conn.commit()

    def close(self):
        self.conn.commit(); self.conn.close()

    def _q(self, sql, params=None, fetch=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params or {})
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            return cur.rowcount

    # ── ingest ──────────────────────────────────────────────────────────────────────────────────────────────────
    def upsert(self, m):
        row = self._q("""INSERT INTO nodes (slug, title, description, body, type, project, refs, frontmatter)
            VALUES (%(slug)s, %(title)s, %(description)s, %(body)s, %(type)s, %(project)s, %(refs)s::jsonb, %(fm)s::jsonb)
            ON CONFLICT (slug) DO UPDATE SET
              title=EXCLUDED.title, description=EXCLUDED.description, body=EXCLUDED.body, type=EXCLUDED.type,
              project=EXCLUDED.project, refs=EXCLUDED.refs, frontmatter=EXCLUDED.frontmatter, status='active',
              updated_at = CASE WHEN (nodes.title, nodes.description, nodes.body) IS DISTINCT FROM
                                     (EXCLUDED.title, EXCLUDED.description, EXCLUDED.body) THEN now() ELSE nodes.updated_at END,
              embedding  = CASE WHEN (nodes.title, nodes.description, nodes.body) IS DISTINCT FROM
                                     (EXCLUDED.title, EXCLUDED.description, EXCLUDED.body) THEN NULL ELSE nodes.embedding END
            RETURNING (xmax = 0) OR embedding IS NULL""",
            {**{k: m[k] for k in ("slug", "title", "description", "body", "type", "project")},
             "refs": json.dumps(m.get("refs") or []), "fm": json.dumps(m.get("frontmatter") or {}, default=str)}, "one")
        return bool(row and row[0])

    def set_links(self, slug, links):
        self._q("DELETE FROM edges WHERE src_slug=%s AND relation='relates_to'", (slug,))
        for l in links:
            self._q("INSERT INTO edges (src_slug, dst_slug, relation) VALUES (%s, %s, 'relates_to') ON CONFLICT DO NOTHING", (slug, l))

    def apply_supersedes(self, pairs):
        self._q("DELETE FROM edges WHERE relation='supersedes'")
        closed = 0
        for src, targets in pairs.items():
            for dst in targets:
                self._q("INSERT INTO edges (src_slug, dst_slug, relation) VALUES (%s, %s, 'supersedes') ON CONFLICT DO NOTHING", (src, dst))
                closed += self._q("""UPDATE nodes SET valid_to = coalesce(valid_to, now()), invalidated_by=%s
                                     WHERE slug=%s AND EXISTS (SELECT 1 FROM nodes s WHERE s.slug=%s AND s.status='active')""", (src, dst, src))
        reopened = self._q("""UPDATE nodes n SET valid_to=NULL, invalidated_by=NULL WHERE n.invalidated_by IS NOT NULL AND NOT EXISTS
                              (SELECT 1 FROM edges e JOIN nodes s ON s.slug=e.src_slug WHERE e.dst_slug=n.slug AND e.relation='supersedes' AND s.status='active')""")
        return closed, reopened

    def archive_missing(self, keep):
        return self._q("UPDATE nodes SET status='archived', updated_at=now() WHERE status='active' AND NOT (slug = ANY(%s::text[]))", (list(keep),))  # noqa

    def unembedded(self):
        return [(s, f"{t}\n{d}\n{b}") for s, t, d, b in self._q("SELECT slug, title, description, body FROM nodes WHERE embedding IS NULL", fetch="all")]

    def set_embedding(self, slug, vec):
        from .embed import config
        if len(vec) != config()["dim"]:
            raise ValueError(f"refusing to write a {len(vec)}-float vector for {slug}: EMBED_DIM is {config()['dim']}")
        self._q("UPDATE nodes SET embedding=%s::vector WHERE slug=%s", (vec_literal(vec), slug))

    # ── recall ──────────────────────────────────────────────────────────────────────────────────────────────────
    def recall(self, query, qvec, k=5, exclude_types=()):
        rows = self._q(RECALL_SQL, {"emb": vec_literal(qvec) if qvec else None, "has_vec": bool(qvec), "text": query,
                                    "excl": list(exclude_types), "k": k}, "all")
        return [{"slug": s, "title": t, "description": d, "body": b, "project": p, "type": ty, "score": float(sc),
                 "sim": float(sim) if sim is not None else None} for s, t, d, b, p, ty, sc, sim in rows]

    def neighbors(self, slugs, exclude_types=()):
        out = {}
        for src, dst, title in self._q("""SELECT e.src_slug, n.slug, n.title FROM edges e JOIN nodes n ON n.slug=e.dst_slug
                WHERE e.src_slug = ANY(%s::text[]) AND e.relation='relates_to' AND n.status='active' AND n.valid_to IS NULL
                  AND coalesce(n.type,'') <> ALL(%s::text[])""", (list(slugs), list(exclude_types)), "all"):
            out.setdefault(src, []).append({"slug": dst, "title": title})
        return out

    def log_recall(self, source, session, query, returned, top_sim):
        self._q("INSERT INTO recall_events (source, session, query, returned, top_sim) VALUES (%s, %s, %s, %s, %s)",
                (source[:32], (session or "")[:64] or None, query[:2000], list(returned), top_sim))

    def count_active(self):
        return self._q("SELECT count(*) FROM nodes WHERE status='active' AND valid_to IS NULL", fetch="one")[0]

    # ── verifier ────────────────────────────────────────────────────────────────────────────────────────────────
    def active_with_refs(self):
        rows = self._q("""SELECT slug, project, type, refs, updated_at, frontmatter, body FROM nodes
                          WHERE status='active' AND valid_to IS NULL AND jsonb_array_length(refs) > 0 ORDER BY slug""", fetch="all")
        return [{"slug": s, "project": p, "type": t, "refs": r, "updated_at": u.isoformat(), "frontmatter": fm, "body": b}
                for s, p, t, r, u, fm, b in rows]

    def anchors(self, slug):
        return {ref: (sha, at.isoformat(), rp) for ref, sha, at, rp in
                self._q("SELECT ref, blob_sha, anchored_at, repo_path FROM anchors WHERE slug=%s", (slug,), "all")}

    def set_anchor(self, slug, ref, repo_path, sha):
        self._q("""INSERT INTO anchors (slug, ref, repo_path, blob_sha, anchored_at) VALUES (%s, %s, %s, %s, now())
                   ON CONFLICT (slug, ref) DO UPDATE SET repo_path=EXCLUDED.repo_path, blob_sha=EXCLUDED.blob_sha, anchored_at=now()""",
                (slug, ref, repo_path, sha))

    def start_run(self, mode):
        return self._q("INSERT INTO runs (mode) VALUES (%s) RETURNING id", (mode,), "one")[0]

    def finish_run(self, run_id, counts):
        self._q("UPDATE runs SET finished_at=now(), counts=%s::jsonb WHERE id=%s", (json.dumps(counts), run_id))

    def last_run(self):
        r = self._q("SELECT id, started_at, finished_at, mode, counts FROM runs ORDER BY id DESC LIMIT 1", fetch="one")
        return r and {"id": r[0], "started_at": r[1].isoformat(), "finished_at": r[2] and r[2].isoformat(), "mode": r[3], **(r[4] or {})}

    def add_finding(self, run_id, slug, result, details):
        return self._q("""INSERT INTO findings (run_id, node_id, slug, result, details)
                          SELECT %s, id, slug, %s, %s::jsonb FROM nodes WHERE slug=%s RETURNING id""",
                       (run_id, result, json.dumps(details), slug), "one")[0]

    def set_verdict(self, finding_id, verdict, reason):
        self._q("UPDATE findings SET verdict=%s, reason=%s WHERE id=%s", (verdict, reason, finding_id))

    def findings(self, slug, before_id=None, limit=3):
        rows = self._q("""SELECT id, run_id, slug, result, details, verdict, reason, created_at FROM findings
                          WHERE slug=%s AND (%s::bigint IS NULL OR id < %s) ORDER BY id DESC LIMIT %s""", (slug, before_id, before_id, limit), "all")
        return [{"id": i, "run_id": r, "slug": s, "result": res, "details": d, "verdict": v, "reason": rs, "created_at": c.isoformat()}
                for i, r, s, res, d, v, rs, c in rows]

    def flagged(self):
        return [{"slug": s, "project": p, "verdict": v, "reason": r, "finding_id": fid, "bad_votes": b, "votes": n, "last_seen": ls.isoformat()}
                for s, p, v, r, fid, b, n, ls in self._q(FLAGGED_SQL, fetch="all")]
