#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$ROOT_DIR/external/Cello-v2"
REPO_URL="https://github.com/CIDARLAB/cello-v2.git"

if [ -d "$TARGET_DIR/.git" ]; then
  echo "Cello-v2 already exists at $TARGET_DIR"
  exit 0
fi

mkdir -p "$ROOT_DIR/external"
git clone "$REPO_URL" "$TARGET_DIR"
