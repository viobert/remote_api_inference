#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-default}"

if [[ -f "$TARGET" ]]; then
  CONFIG_PATH="$TARGET"
else
  CONFIG_PATH="configs/runs/${TARGET}.yaml"
fi

cd "$REPO_ROOT"
PYTHONPATH=src python -m inference.batch_runner --config "$CONFIG_PATH"
