#!/usr/bin/env bash
# Regenerate the four report themes from the gallery's brand engine and validate them against the schema.
# Brand themes: BRAND_COLOR=#0f766e PALETTE=analogous bash scripts/themes.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
node "$ROOT/tools/mk_themes.js" "$ROOT/visuals/themes"
python3 "$ROOT/tools/validate_themes.py"
mkdir -p "$ROOT/release/themes" && cp "$ROOT"/visuals/themes/*.json "$ROOT/release/themes/"
