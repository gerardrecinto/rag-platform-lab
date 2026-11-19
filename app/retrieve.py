import numpy as np

from . import config, db, graph
from .embed import embed


def search(query, k=None):
    """Vector search, then add chunks linked through shared graph terms. Returns dicts with id, source, text, via."""
    k = k or config.TOP_K
    q = np.array(embed(query))
    with db.pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, source, text FROM chunks ORDER BY embedding <=> %s LIMIT %s", (q, k)).fetchall()
        hits = [{"id": r[0], "source": r[1], "text": r[2], "via": "vector"} for r in rows]
        extra = graph.related_chunks([h["id"] for h in hits[:2]])
        if extra:
            more = conn.execute("SELECT id, source, text FROM chunks WHERE id = ANY(%s)", (extra,)).fetchall()
            hits += [{"id": r[0], "source": r[1], "text": r[2], "via": "graph"} for r in more]
    return hits
