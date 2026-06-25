#!/usr/bin/env bash
set -euo pipefail

HOST="${BACKEND_HOST:-127.0.0.1}"
PORT="${BACKEND_PORT:-8000}"

cd "$(dirname "$0")"
python3 -m uvicorn app:app --host "$HOST" --port "$PORT" --reload
