#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="${REQ_FILE:-$ROOT_DIR/requirements_py311_offline.txt}"
WHEELHOUSE_DIR="${WHEELHOUSE_DIR:-$ROOT_DIR/wheelhouse}"
PY_BIN="${PYTHON_BIN:-python3.11}"

# Default target is common Xinchuang Linux ARM64.
TARGET_PLATFORM="${TARGET_PLATFORM:-manylinux2014_aarch64}"
TARGET_ABI="${TARGET_ABI:-cp311}"
TARGET_IMPL="${TARGET_IMPL:-cp}"
TARGET_PY_VERSION="${TARGET_PY_VERSION:-3.11}"

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  echo "未找到 Python 可执行文件: $PY_BIN" >&2
  echo "请设置 PYTHON_BIN，例如: PYTHON_BIN=python3.11" >&2
  exit 1
fi

if [[ ! -f "$REQ_FILE" ]]; then
  echo "依赖文件不存在: $REQ_FILE" >&2
  exit 1
fi

mkdir -p "$WHEELHOUSE_DIR"

echo "Building wheelhouse:"
echo "  req_file:   $REQ_FILE"
echo "  output:     $WHEELHOUSE_DIR"
echo "  platform:   $TARGET_PLATFORM"
echo "  py_version: $TARGET_PY_VERSION"
echo "  impl/abi:   $TARGET_IMPL/$TARGET_ABI"

"$PY_BIN" -m pip download \
  -r "$REQ_FILE" \
  --dest "$WHEELHOUSE_DIR" \
  --only-binary=:all: \
  --platform "$TARGET_PLATFORM" \
  --platform any \
  --implementation "$TARGET_IMPL" \
  --abi "$TARGET_ABI" \
  --python-version "$TARGET_PY_VERSION"

echo "Wheelhouse build done."
