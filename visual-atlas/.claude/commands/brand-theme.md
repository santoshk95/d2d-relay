---
description: Generate Power BI report themes for a brand color
argument-hint: <hex color> [spectrum|analogous|mono]
---
Make brand themes for: **$ARGUMENTS**

1. Parse the hex color and the optional palette style (default `spectrum`).
2. Run `docker run --rm -v "$PWD":/work -w /work -e BRAND_COLOR=<hex> -e PALETTE=<style> visual-atlas node tools/mk_themes.js release/themes/brand`.
3. Validate: `docker run --rm -v "$PWD":/work -w /work visual-atlas python3 tools/validate_themes.py release/themes/brand/*.json`.
4. Show the 8 palette colors from the soft theme, and say where the four files are (flat, soft, 3d, soft-dark).
