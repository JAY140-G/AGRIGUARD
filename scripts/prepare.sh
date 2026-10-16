#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/.data/pip-cache}"
export npm_config_cache="${npm_config_cache:-$PWD/.data/npm-cache}"
mkdir -p .data/images backend/.wheels
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m pip download --only-binary=:all: -r backend/requirements.lock -d backend/.wheels
.venv/bin/python - <<'PY'
from pathlib import Path
import secrets,hashlib,json
p=Path('.env')
if not p.exists():
    content=Path('.env.example').read_text().replace('local-development-only-change-me',secrets.token_hex(20))
    p.write_text(content);p.chmod(0o600)
wheels={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('backend/.wheels').glob('*.whl')}
Path('backend/.wheels-manifest.json').write_text(json.dumps(wheels,indent=2))
PY
