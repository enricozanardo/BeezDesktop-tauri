# Beez Desktop Two

Standalone Tokenized Intelligence client (SvelteKit + Tauri 2) with a **native Rust core**. No Python, no Toga, no setup scripts.

Repo: https://github.com/enricozanardo/BeezDesktopTwo  
Local path: `BeezMaster/BeezDesktopTwo/`

## Features

- Wallet create / import (encrypted local storage `BeezDesktopTwo`)
- Ask: specialised Smart nodes, citations, BZT settlement, optional Local MiniCPM
- Knowledge marketplace search / query / publish
- Client-side BGE embeddings (`BAAI/bge-small-en-v1.5`) downloaded in-app on first network Ask

## Install

Download the DMG / AppImage / MSI from GitHub Releases. That is the whole install.

## Dev

```bash
cd BeezMaster/BeezDesktopTwo
npm ci
npm run tauri:dev
```

On Ubuntu/Debian, compiling the Tauri window needs GLib/GTK/WebKit **once** (CI already installs these). If `pkg-config` cannot find `glib-2.0`:

```bash
./scripts/linux-dev-deps.sh
npm run tauri:dev
```

`npm run tauri:dev` also needs a graphical session (`DISPLAY` or `WAYLAND_DISPLAY`). A headless TTY/SSH login will fail at GTK init. GitHub Releases (AppImage/DMG/MSI) are the path for running the app on a desktop.

Native core tests (no GTK required):

```bash
cd src-tauri
cargo test -p beez-native
```
