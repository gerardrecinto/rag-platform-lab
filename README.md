# rag-platform-lab

A small platform for retrieval-augmented generation: a FastAPI service that streams answers over SSE and WebSocket, a Celery worker that ingests documents, and a pipeline that scrubs identifiers before anything is stored or sent to a model.

It is for engineers who want to see how the pieces of a production RAG service fit: async API, queue, vector search, a graph step, provider adapters, metrics and a Kubernetes deploy. Documents are synthetic. It is not a HIPAA compliance claim and has not handled real patient data.

## Run it

Needs Docker. About 3 minutes the first time.

```bash
git clone https://github.com/gerardrecinto/rag-platform-lab.git && cd rag-platform-lab
bash scripts/e2e.sh        # unit tests, then the full stack check; ends with ALL PASS
```

Then try it by hand (the stack stays up):

```bash
curl -s -X POST localhost:8000/v1/ingest -H 'Authorization: Bearer lab-token' -H 'content-type: application/json' \
  -d '{"source":"note.md","text":"CBT-I is the first line treatment for chronic insomnia."}'
curl -N -X POST localhost:8000/v1/chat/stream -H 'Authorization: Bearer lab-token' -H 'content-type: application/json' \
  -d '{"query":"What treats insomnia?"}'
```

The compose file publishes only the API on 8000. Stop with `docker compose down -v`. If a first build fails, check `docker info` and that port 8000 is free.

`bash scripts/k8s-e2e.sh` deploys the same stack to a kind cluster (needs kind and kubectl) and runs the check inside the cluster.

## What the check proves

1. Ingest needs a bearer token; four Celery jobs finish, with the payload carried as a Protobuf message.
2. A phone number and an MRN in a document never reach the vector store; they become `[PHONE]` and `[MRN]`.
3. `POST /v1/chat/stream` sends `sources`, many `token` events, then `done`, with the query redacted first and the answer grounded in the retrieved text.
4. The WebSocket route streams the same events.
5. Retrieval picks the expected document first for 4 of 4 golden questions.
6. A chunk reaches the answer through a shared term in Neo4j (the GraphRAG step).
7. Every model call is recorded (tokens, latency, provider) and exposed on `/metrics`.

## Design

| Piece | Choice | Why, and what it costs |
|---|---|---|
| Vector store | Postgres with pgvector, HNSW index | One database for relations and vectors. Cost: not a dedicated vector engine; revisit at tens of millions of chunks. |
| Queue | Celery on Redis, late acks, bounded retries | Ingest survives a worker crash. Cost: a task can run twice, so jobs are keyed by id. |
| Wire format | Protobuf `IngestJob` inside the Celery envelope | A typed contract between API and worker. Cost: a code generation step at build. |
| Providers | Adapters for Anthropic, OpenAI-compatible and Bedrock; a mock by default | Swap by env var. Tested with mocked transports, never called live. |
| Graph | Neo4j links chunks to clinical terms | Pulls in related chunks plain vector search misses. The term list is short and synthetic. |

## Limits

- Embeddings are a deterministic hashing function so the lab needs no model download or API key. Swap `app/embed.py` for a real model.
- Provider adapters were not run against live APIs. Token counts from the mock are estimates and the table says so.
- No Langfuse. Latency, token use and errors are Prometheus metrics and a `llm_calls` table; output-quality scoring beyond the retrieval hit rate is not built.
- Redaction is pattern based. It misses names and free-text identifiers.
- The Bedrock adapter uses `converse` and streams the finished text in pieces; it is not `converse_stream`.
- The NetworkPolicy lets only the API, the worker and the check pod reach the data stores. kind's default network plugin enforced it: the first check pod was blocked until it was allowed. The HPA needs metrics-server, which kind does not ship, so it reports no metrics.
- No Java or Kotlin.

MIT license.
