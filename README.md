# Beez Desktop Two (Tauri)

SvelteKit UI wrapped by **Tauri 2**, with a **Python sidecar** that reuses
`client_core`. Product name is **Beez Desktop Two**; the GitHub repository
remains `BeezDesktop-tauri` and the Apple identifier stays `io.beez.desktop`.
Toga **Beez Desktop** `0.6.x` is the BeeWare client.

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
