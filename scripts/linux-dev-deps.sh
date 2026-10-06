#!/usr/bin/env bash
# Install system libraries required to *compile* Beez Desktop Two with Tauri on Ubuntu/Debian.
# End users who install a Release AppImage/deb do not need this.
set -euo pipefail
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is only for Linux development machines."
  exit 0
fi
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo apt-get install -y \
  pkg-config \
  build-essential \
  curl \
  wget \
  file \
  libglib2.0-dev \
  libgtk-3-dev \
  libwebkit2gtk-4.1-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev \
  libssl-dev
echo "Linux Tauri build dependencies installed. Re-run: npm run tauri:dev"
