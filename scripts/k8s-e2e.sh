#!/usr/bin/env bash
# Deploy the same stack to a kind cluster and run the end-to-end check through a port-forward.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -q -t rag-lab-app:local . >/dev/null
kind delete cluster --name rag-lab >/dev/null 2>&1 || true
kind create cluster --name rag-lab --wait 120s >/dev/null
kind load docker-image rag-lab-app:local --name rag-lab >/dev/null
kubectl apply -k k8s >/dev/null
for r in statefulset/postgres statefulset/neo4j deploy/redis deploy/api deploy/worker; do
  kubectl -n rag-lab rollout status "$r" --timeout=300s >/dev/null
done
echo "PASS all workloads rolled out (api x2, worker, postgres, redis, neo4j)"
for _ in $(seq 1 60); do
  kubectl -n rag-lab exec deploy/worker -- celery -A app.worker inspect ping >/dev/null 2>&1 && break
  sleep 3
done
# The check runs inside the cluster, so service names match the compose file.
kubectl -n rag-lab delete pod eval --ignore-not-found >/dev/null
kubectl -n rag-lab run eval --labels=app=eval --image=rag-lab-app:local --image-pull-policy=IfNotPresent --restart=Never \
  --command -- python eval/run_eval.py >/dev/null
for _ in $(seq 1 120); do
  phase=$(kubectl -n rag-lab get pod eval -o jsonpath='{.status.phase}')
  [ "$phase" = Succeeded ] || [ "$phase" = Failed ] && break
  sleep 2
done
kubectl -n rag-lab logs eval
[ "$phase" = Succeeded ]
