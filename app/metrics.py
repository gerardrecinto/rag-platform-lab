from prometheus_client import Counter, Histogram

REQUESTS = Counter("rag_requests_total", "Requests by route and status", ["route", "status"])
RETRIEVAL = Histogram("rag_retrieval_seconds", "Vector and graph retrieval time")
LLM_LATENCY = Histogram("rag_llm_seconds", "Model streaming time", ["provider"])
TOKENS = Counter("rag_llm_tokens_total", "Tokens used", ["provider", "kind"])
PROVIDER_ERRORS = Counter("rag_provider_errors_total", "Provider failures", ["provider"])
INGEST_CHUNKS = Counter("rag_ingest_chunks_total", "Chunks stored")
