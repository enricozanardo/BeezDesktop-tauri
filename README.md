# Beez Desktop Two

Standalone Tokenized Intelligence client (SvelteKit + Tauri 2). **No Toga / BeeWare Beez Desktop dependency.**

## Features

- Wallet create / import (encrypted local storage `BeezDesktopTwo`)
- Ask: specialised Smart nodes, citations, BZT settlement, Local MiniCPM
- Knowledge marketplace search / query / publish
- Vendored `shared/` (BeezShared client_core) + Python sidecar

## Dev

```bash
uv venv .venv
uv pip install -r sidecar/requirements.txt -p .venv/bin/python
npm ci
npm run tauri:dev
```

The Tauri host prefers `.venv/bin/python` next to the project so Ask/Wallet work without system pip.

## Sidecar

The Rust host invokes `sidecar/beez_sidecar.py` with JSON lines. Wallet and Smart/Knowledge ops use the vendored `shared/` tree. Install Python deps once on the machine that runs the app.

## Release

Push a `v*` tag (or run the Release workflow). macOS DMG is notarized in CI.
