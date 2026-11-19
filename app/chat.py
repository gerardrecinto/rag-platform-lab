"""One answer path shared by SSE and WebSocket: redact, retrieve, stream, record."""
import hashlib
import json
import os
import time

from . import db, metrics, providers, retrieve
from .redact import redact

SYSTEM = ("Answer only from the numbered sources. Cite them like [1]. "
          "If the sources do not contain the answer, say so. Do not give medical advice.")


def build_prompt(query, hits):
    sources = "\n".join(f"[{i}] {h['text']}" for i, h in enumerate(hits, 1))
    return f"Sources:\n{sources}\n\nQuestion: {query}"


def events(query, provider=None):
    """Yield dicts: sources, token (many), done. Raises nothing for an empty index; it answers that it has no sources."""
    provider = provider or providers.build(os.environ.get("LLM_PROVIDER", "mock"), os.environ)
    clean, n = redact(query)
    t0 = time.perf_counter()
    hits = retrieve.search(clean)
    metrics.RETRIEVAL.observe(time.perf_counter() - t0)
    yield {"type": "sources", "sources": [{"n": i, "source": h["source"], "via": h["via"]} for i, h in enumerate(hits, 1)],
           "redactions": n}
    t1 = time.perf_counter()
    try:
        for piece in provider.stream(SYSTEM, build_prompt(clean, hits)):
            yield {"type": "token", "text": piece}
    except Exception as e:  # provider failure must reach the client and the metrics, not kill the stream silently
        metrics.PROVIDER_ERRORS.labels(provider.name).inc()
        yield {"type": "error", "message": f"{provider.name} failed: {type(e).__name__}"}
        return
    ms = int((time.perf_counter() - t1) * 1000)
    p_tok, c_tok, est = provider.usage or (0, 0, True)
    metrics.TOKENS.labels(provider.name, "prompt").inc(p_tok)
    metrics.TOKENS.labels(provider.name, "completion").inc(c_tok)
    metrics.LLM_LATENCY.labels(provider.name).observe(ms / 1000)
    qhash = hashlib.sha256(clean.encode()).hexdigest()[:16]
    with db.pool().connection() as conn:
        conn.execute("INSERT INTO llm_calls (provider, model, prompt_tokens, completion_tokens, tokens_estimated, "
                     "latency_ms, retrieved, query_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (provider.name, provider.model, p_tok, c_tok, est, ms, len(hits), qhash))
    yield {"type": "done", "usage": {"prompt_tokens": p_tok, "completion_tokens": c_tok, "estimated": est}, "latency_ms": ms}


def sse(event):
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
