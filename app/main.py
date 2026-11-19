import base64
import hmac
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import iterate_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import chat, config, db, ingest_pb2, metrics
from .worker import ingest


@asynccontextmanager
async def lifespan(app):
    db.init_schema()
    yield


app = FastAPI(title="rag-platform-lab", lifespan=lifespan)


def require_token(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, config.API_TOKEN):
        metrics.REQUESTS.labels("auth", "401").inc()
        raise HTTPException(401, "missing or wrong bearer token")


class IngestRequest(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200_000)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    try:
        with db.pool().connection() as c:
            c.execute("SELECT 1")
    except Exception:
        raise HTTPException(503, "database not reachable")
    return {"ready": True}


@app.get("/metrics")
def prom():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/ingest", status_code=202, dependencies=[Depends(require_token)])
def post_ingest(req: IngestRequest):
    job_id = str(uuid.uuid4())
    msg = ingest_pb2.IngestJob(job_id=job_id, source=req.source, text=req.text)
    with db.pool().connection() as c:
        c.execute("INSERT INTO jobs (id, status) VALUES (%s, 'queued')", (job_id,))
    try:
        ingest.delay(base64.b64encode(msg.SerializeToString()).decode())
    except Exception:
        with db.pool().connection() as c:
            c.execute("UPDATE jobs SET status='failed', error='queue unavailable' WHERE id=%s", (job_id,))
        metrics.REQUESTS.labels("ingest", "503").inc()
        raise HTTPException(503, "queue unavailable, job not accepted")
    metrics.REQUESTS.labels("ingest", "202").inc()
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_job(job_id: str):
    with db.pool().connection() as c:
        row = c.execute("SELECT status, chunks, redactions, error FROM jobs WHERE id=%s", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "unknown job")
    return {"job_id": job_id, "status": row[0], "chunks": row[1], "redactions": row[2], "error": row[3]}


@app.post("/v1/chat/stream", dependencies=[Depends(require_token)])
async def chat_stream(req: ChatRequest):
    metrics.REQUESTS.labels("chat_stream", "200").inc()

    async def gen():
        async for ev in iterate_in_threadpool(chat.events(req.query)):
            yield chat.sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.websocket("/v1/chat/ws")
async def chat_ws(ws: WebSocket, token: str = ""):
    if not hmac.compare_digest(token, config.API_TOKEN):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            query = json.loads(await ws.receive_text()).get("query", "")
            if not query or len(query) > 2000:
                await ws.send_json({"type": "error", "message": "query must be 1 to 2000 characters"})
                continue
            async for ev in iterate_in_threadpool(chat.events(query)):
                await ws.send_json(ev)
    except WebSocketDisconnect:
        return
