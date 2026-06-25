#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="${REQ_FILE:-$ROOT_DIR/requirements_py311_offline.txt}"
WHEELHOUSE_DIR="${WHEELHOUSE_DIR:-$ROOT_DIR/wheelhouse}"
VENDOR_DIR="${VENDOR_DIR:-$ROOT_DIR/vendor}"
PY_BIN="${PYTHON_BIN:-python3.11}"

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  echo "未找到 Python 可执行文件: $PY_BIN" >&2
  echo "请设置 PYTHON_BIN，例如: PYTHON_BIN=python3.11" >&2
  exit 1
fi

if [[ ! -f "$REQ_FILE" ]]; then
  echo "依赖文件不存在: $REQ_FILE" >&2
  exit 1
fi

if [[ ! -d "$WHEELHOUSE_DIR" ]]; then
  echo "wheelhouse 目录不存在: $WHEELHOUSE_DIR" >&2
  exit 1
fi

mkdir -p "$VENDOR_DIR"

"$PY_BIN" -m pip install \
  --no-index \
  --find-links "$WHEELHOUSE_DIR" \
  --target "$VENDOR_DIR" \
  -r "$REQ_FILE"

echo "Vendor install done: $VENDOR_DIR"
