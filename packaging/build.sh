#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
pip install pyinstaller
pyinstaller --noconfirm packaging/spiresight.spec
echo "Bundle: dist/SpireSight/  (or dist/SpireSight.app on macOS)"
