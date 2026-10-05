#!/usr/bin/env bash
# Create project .venv and install Beez Desktop Two sidecar dependencies.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if command -v uv >/dev/null 2>&1; then
  uv venv .venv
  uv pip install -r sidecar/requirements.txt -p .venv/bin/python
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -U pip
  .venv/bin/python -m pip install -r sidecar/requirements.txt
fi
echo "Sidecar venv ready: $ROOT/.venv"
.venv/bin/python - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
sys.path.insert(0, str(Path("sidecar").resolve()))
import beez_sidecar
print(json.dumps(beez_sidecar.handle({"method": "ping"})))
PY
