import base64

import numpy as np
from celery import Celery

from . import config, db, graph, metrics
from . import ingest_pb2
from .chunk import chunk
from .embed import embed
from .redact import redact

celery = Celery("rag", broker=config.REDIS_URL, backend=config.REDIS_URL)
celery.conf.task_acks_late = True
celery.conf.worker_prefetch_multiplier = 1


def process(job):
    """Redact, chunk, embed and store one IngestJob. Returns an IngestResult."""
    clean, n = redact(job.text)
    pieces = chunk(clean)
    with db.pool().connection() as conn:
        for i, piece in enumerate(pieces):
            cid = conn.execute("INSERT INTO chunks (source, ord, text, embedding) VALUES (%s,%s,%s,%s) RETURNING id",
                               (job.source, i, piece, np.array(embed(piece)))).fetchone()[0]
            graph.add_chunk(cid, piece)
    return ingest_pb2.IngestResult(job_id=job.job_id, chunks=len(pieces), redactions=n)


@celery.task(bind=True, autoretry_for=(Exception,), retry_backoff=2, max_retries=3)
def ingest(self, payload_b64):
    job = ingest_pb2.IngestJob.FromString(base64.b64decode(payload_b64))
    with db.pool().connection() as conn:
        conn.execute("UPDATE jobs SET status='running', updated_at=now() WHERE id=%s", (job.job_id,))
    try:
        result = process(job)
    except Exception as e:
        if self.request.retries >= self.max_retries:
            with db.pool().connection() as conn:
                conn.execute("UPDATE jobs SET status='failed', error=%s, updated_at=now() WHERE id=%s",
                             (type(e).__name__, job.job_id))
        raise
    metrics.INGEST_CHUNKS.inc(result.chunks)
    with db.pool().connection() as conn:
        conn.execute("UPDATE jobs SET status='done', chunks=%s, redactions=%s, updated_at=now() WHERE id=%s",
                     (result.chunks, result.redactions, job.job_id))
    return {"chunks": result.chunks, "redactions": result.redactions}
