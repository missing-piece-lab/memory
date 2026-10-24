"""config — the one place production configuration enters. `load_env()` reads a `.env` in the current directory (plain
KEY=VALUE lines, `#` comments, optional quotes; no dependency) into os.environ WITHOUT overriding what is already set,
so `cp .env.example .env` is enough and a shell export still wins. Every CLI calls it first; ENV_FILE names another file.

`check_embedding_dim()` is the early refusal: it embeds one short probe and compares the vector's length with EMBED_DIM
(the dimension the schema's vector(N) column was created with). A mismatch is one clear error at startup, not a failed
write on the thousandth memory. The graphs refuse a wrong-length vector too (`graph.set_embedding`), as the last wall.
"""
import os


def load_env(path=None):
    path = path or os.environ.get("ENV_FILE", ".env")
    if not os.path.isfile(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.split(" #", 1)[0].strip().strip('"').strip("'")
            if key.strip() and key.strip() not in os.environ:
                os.environ[key.strip()] = val; n += 1
    return n


def check_embedding_dim():
    """Raise SystemExit with one clear line when the embedder's vectors do not match EMBED_DIM. Returns the dim."""
    from . import embed as E
    cfg = E.config()
    try:
        n = len(E.embed("dimension probe", kind="query", cfg=cfg))
    except Exception as e:
        raise SystemExit(f"embedding: the {cfg['kind']} embedder at {cfg['url'] or '(local)'} did not answer ({type(e).__name__}) — fix EMBED_* before ingesting")
    if n != cfg["dim"]:
        raise SystemExit(f"embedding dimension: {cfg['kind']}/{cfg['model']} returns {n} floats but EMBED_DIM is {cfg['dim']} — "
                         f"set EMBED_DIM={n} (and recreate the vector({n}) column if the schema was made with another value)")
    return n
