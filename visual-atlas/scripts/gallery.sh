#!/usr/bin/env bash
# Rebuild the Visual Atlas gallery page (one self-contained HTML file) from gallery/src.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
node "$ROOT/gallery/scripts/build.mjs"
node --check "$ROOT/gallery/dist/bundle.js"
cp "$ROOT/gallery/dist/power-bi-visual-atlas.html" "$ROOT/release/"
echo "open gallery/dist/preview.html in a browser to look at it locally"
