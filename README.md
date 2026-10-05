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

Native core tests (no GTK required):

```bash
cd src-tauri
cargo test -p beez-native
```
