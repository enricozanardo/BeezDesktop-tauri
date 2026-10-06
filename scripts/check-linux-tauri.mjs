#!/usr/bin/env node
/**
 * Fail fast on Linux if pkg-config cannot see GLib (required by Tauri WebKit).
 */
import { spawnSync } from 'node:child_process';

if (process.platform !== 'linux') {
	process.exit(0);
}

const display = process.env.WAYLAND_DISPLAY || process.env.DISPLAY;
if (!display) {
	console.error(`
Tauri cannot open a window: this Linux session has no display (DISPLAY and WAYLAND_DISPLAY are empty).

GTK headers compiled, but gtk_init failed. Run npm run tauri:dev from a graphical desktop terminal
(not SSH/TTY). If you only need the web UI, open http://localhost:5173 after npm run dev — native
Ask/wallet/chain calls require the Tauri window.

On a machine that already has a logged-in desktop, try:

  DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 npm run tauri:dev
`);
	process.exit(1);
}

const check = spawnSync('pkg-config', ['--exists', 'glib-2.0'], { encoding: 'utf8' });
if (check.status === 0) {
	process.exit(0);
}

console.error(`
Tauri cannot compile on this Linux machine: glib-2.0 / GTK / WebKit headers are missing.

Install them once (this is a compiler toolchain, not a Python sidecar):

  cd BeezDesktopTwo
  ./scripts/linux-dev-deps.sh

Then:

  npm run tauri:dev
`);
process.exit(1);
