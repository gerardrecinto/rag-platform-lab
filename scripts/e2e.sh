#!/usr/bin/env bash
# Whole stack in Docker: Postgres with pgvector, Redis, Neo4j, API, Celery worker.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d --build >/dev/null
docker compose exec -T api python -m pytest -q tests
docker compose exec -T api python eval/run_eval.py
