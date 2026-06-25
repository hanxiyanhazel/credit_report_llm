#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$ROOT_DIR/offline_test/vendor"
HOST="${BACKEND_HOST:-127.0.0.1}"
PORT="${BACKEND_PORT:-8000}"
PY_BIN="${PYTHON_BIN:-python3.11}"
DATA_ROOT="${CREDIT_DEMO_2_DATA_ROOT:-$ROOT_DIR/data}"

if [[ ! -d "$VENDOR_DIR" ]]; then
  echo "vendor 目录不存在: $VENDOR_DIR" >&2
  echo "请先在 credit_demo_2_offline/offline_test 下完成离线安装。" >&2
  exit 1
fi

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  echo "未找到 Python 可执行文件: $PY_BIN" >&2
  echo "请设置 PYTHON_BIN，例如: PYTHON_BIN=python3.11" >&2
  exit 1
fi

export PYTHONPATH="$VENDOR_DIR${PYTHONPATH:+:$PYTHONPATH}"
export CREDIT_DEMO_2_DATA_ROOT="$DATA_ROOT"

cd "$ROOT_DIR"

echo "Starting credit_demo_2_offline on http://$HOST:$PORT"
echo "Using python: $PY_BIN"
echo "Using vendor: $VENDOR_DIR"
echo "Using data:   $CREDIT_DEMO_2_DATA_ROOT"

"$PY_BIN" -m uvicorn app:app --host "$HOST" --port "$PORT"
