"""graph — open the graph the environment names. `GRAPH_DSN=postgresql://user:pass@host:5432/db` → Postgres + pgvector
(production); otherwise `GRAPH_PATH` (default ./graph.json) → the in-process graph. Every job calls this once."""
import os


def open_graph(path=None):
    dsn = os.environ.get("GRAPH_DSN")
    if dsn:
        from .graph_pg import PostgresGraph
        g = PostgresGraph(dsn)
        g.ensure_schema()
        return g
    from .graph_mem import MemoryGraph
    return MemoryGraph(path or os.environ.get("GRAPH_PATH", "graph.json"))
