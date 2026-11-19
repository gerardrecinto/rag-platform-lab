"""End-to-end check against a running stack: ingest, redaction, SSE, WebSocket, graph hit, retrieval eval, metrics."""
import json
import sys
import time

import httpx
import psycopg

BASE, TOKEN = "http://api:8000", "lab-token"
H = {"Authorization": f"Bearer {TOKEN}"}
DB = "postgresql://rag:rag@postgres:5432/rag"


def ok(msg):
    print("PASS", msg)


def fail(msg):
    print("FAIL", msg)
    sys.exit(1)


def sse_events(client, query):
    out = []
    with client.stream("POST", f"{BASE}/v1/chat/stream", json={"query": query}, headers=H) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def main():
    data = json.load(open("eval/golden.json"))
    c = httpx.Client(timeout=30)
    for _ in range(60):
        try:
            if c.get(f"{BASE}/readyz").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        fail("api never became ready")

    if c.post(f"{BASE}/v1/ingest", json={"source": "x", "text": "y"}).status_code != 401:
        fail("ingest accepted a request with no token")
    ok("ingest rejects a missing token")

    jobs = [c.post(f"{BASE}/v1/ingest", json=d, headers=H).json()["job_id"] for d in data["documents"]]
    for jid in jobs:
        for _ in range(60):
            j = c.get(f"{BASE}/v1/jobs/{jid}", headers=H).json()
            if j["status"] in ("done", "failed"):
                break
            time.sleep(1)
        if j["status"] != "done":
            fail(f"job {jid} ended {j}")
    ok(f"{len(jobs)} Celery ingest jobs finished")

    with psycopg.connect(DB) as conn:
        texts = " ".join(r[0] for r in conn.execute("SELECT text FROM chunks"))
    if "619-555-0142" in texts or "00123456" in texts:
        fail("identifier reached the vector store")
    if "[PHONE]" not in texts or "[MRN]" not in texts:
        fail("redaction markers missing")
    ok("phone and MRN were redacted before embedding and storage")

    ev = sse_events(c, "What is the first line treatment for chronic insomnia? My phone is 858-555-0199.")
    kinds = [e["type"] for e in ev]
    if kinds[0] != "sources" or kinds[-1] != "done" or "token" not in kinds:
        fail(f"unexpected SSE shape {kinds[:3]}...{kinds[-1]}")
    if ev[0]["redactions"] != 1:
        fail("query was not redacted")
    answer = "".join(e["text"] for e in ev if e["type"] == "token")
    if "CBT" not in answer and "Cognitive" not in answer:
        fail(f"answer not grounded: {answer}")
    ok("SSE stream: sources, tokens, done, query redacted, answer grounded")

    with httpx.Client() as _:
        from websockets.sync.client import connect  # bundled with uvicorn[standard]
        with connect(f"ws://api:8000/v1/chat/ws?token={TOKEN}") as ws:
            ws.send(json.dumps({"query": "How does burnout show up?"}))
            got = []
            while True:
                m = json.loads(ws.recv())
                got.append(m["type"])
                if m["type"] in ("done", "error"):
                    break
    if got[0] != "sources" or got[-1] != "done":
        fail(f"websocket events {got}")
    ok("WebSocket stream works")

    hits = 0
    for q in data["questions"]:
        top = sse_events(c, q["q"])[0]["sources"][0]["source"]
        hits += top == q["expect"]
    if hits != len(data["questions"]):
        fail(f"retrieval hit@1 {hits}/{len(data['questions'])}")
    ok(f"retrieval hit@1 {hits}/{len(data['questions'])} on the golden set")

    ev = sse_events(c, "Which habits help with insomnia and depression?")
    if not any(s["via"] == "graph" for s in ev[0]["sources"]):
        fail("no source came from the graph")
    ok("GraphRAG added a chunk through a shared term in Neo4j")

    with psycopg.connect(DB) as conn:
        n, est = conn.execute("SELECT count(*), bool_and(tokens_estimated) FROM llm_calls").fetchone()
    if n < 4 or est is not True:
        fail("llm_calls not recorded as expected")
    m = c.get(f"{BASE}/metrics").text
    if "rag_llm_tokens_total" not in m or "rag_retrieval_seconds_count" not in m:
        fail("metrics missing")
    ok(f"{n} model calls recorded with token estimates; Prometheus metrics exposed")
    print("ALL PASS")


main()
