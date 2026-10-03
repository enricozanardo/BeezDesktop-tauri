# Beez Desktop (Tauri)

SvelteKit UI wrapped by **Tauri 2**, with a **Python sidecar** that reuses
`client_core` (wallet, AES-256-GCM, ECDH, chunking, ZMQ). This is the
successor to BeeWare/Toga BeezDesktop; keep shipping Toga `0.6.x` until
these nine screens have production parity.

## Screens

Dashboard, Wallet, Files, Smart, Knowledge, Transactions, Blockchain,
Network, Settings. Version is shown in the sidebar and the window title.

## Develop

```bash
cd BeezDesktop-tauri
npm install
# optional: git submodule add git@github.com:enricozanardo/BeezShared.git shared
python3 sidecar/beez_sidecar.py <<< '{"method":"ping"}'
npm run tauri dev
```

Requires Rust (`rustup`), Node 22+, WebKitGTK on Linux, and Python 3.11+.

## Release

Push a `v*` tag. GitHub Actions builds Linux, macOS, and Windows artifacts.

## Config

Same `~/.beez` file as Toga BeezDesktop.
