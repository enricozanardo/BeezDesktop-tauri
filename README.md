# Beez Desktop Two

Standalone Tokenized Intelligence client (SvelteKit + Tauri 2). **No Toga / BeeWare Beez Desktop dependency.**

Repo: https://github.com/enricozanardo/BeezDesktopTwo  
Local path (same level as the other Beez* components): `BeezMaster/BeezDesktopTwo/`

## Features

- Wallet create / import (encrypted local storage `BeezDesktopTwo`)
- Ask: specialised Smart nodes, citations, BZT settlement, Local MiniCPM
- Knowledge marketplace search / query / publish
- Vendored `shared/` (BeezShared client_core) + Python sidecar

## Dev

```bash
cd BeezMaster/BeezDesktopTwo
./scripts/setup_sidecar.sh
npm ci
npm run tauri:dev
```

The Tauri host prefers `.venv/bin/python` next to the project so Ask/Wallet work without system pip.

## Sidecar

The Rust host invokes `sidecar/beez_sidecar.py` with JSON lines. Wallet and Smart/Knowledge ops use the vendored `shared/` tree. Install Python deps once on the machine that runs the app.

## Release

Push a `v*` tag (or run the Release workflow). macOS DMG is notarized in CI.
