#!/bin/sh
set -e
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc -I proto --python_out=app proto/ingest.proto
