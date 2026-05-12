#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Backend Python compile"
(
  cd "$ROOT_DIR/backend"
  PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/officehub-pycache}" python3 -m compileall app
)

echo "==> Frontend lint"
(
  cd "$ROOT_DIR/frontend"
  npm run lint
)

echo "==> Frontend production build"
(
  cd "$ROOT_DIR/frontend"
  npm run build
)

echo "Production checks passed."
