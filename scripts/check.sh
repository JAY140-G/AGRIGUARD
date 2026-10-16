#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest -q backend
npm run typecheck --prefix frontend
npm run build --prefix frontend
