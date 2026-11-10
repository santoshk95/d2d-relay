#!/usr/bin/env bash
# Build all Gen BI visuals: copy the shared renderers into each package, `pbiviz package`,
# collect the .pbiviz files, and bundle the same renderers for HTML prototypes.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf dist && mkdir -p dist/prototype

for pkg in packages/*/; do
  name=$(basename "$pkg")
  rm -rf "$pkg/src/lib" "$pkg/style" "$pkg/dist" "$pkg/.tmp"
  mkdir -p "$pkg/src/lib/charts" "$pkg/style"
  cp src/format.ts src/dom.ts src/theme.ts src/pbi.ts "$pkg/src/lib/"
  cp src/charts/*.ts "$pkg/src/lib/charts/"
  cp adapters/_base.ts "$pkg/src/base.ts"
  cp "adapters/$name.ts" "$pkg/src/visual.ts"
  cp style/visual.less "$pkg/style/visual.less"
  echo "=== packaging $name"
  (cd "$pkg" && pbiviz package --verbose 2>&1 | tail -25)
  cp "$pkg"/dist/*.pbiviz dist/
done

echo "=== prototype bundle"
esbuild src/prototype.ts --bundle --format=iife --target=es2019 --outfile=dist/prototype/genbi-visuals.js
cp style/visual.less dist/prototype/genbi-visuals.css
cp catalog.json dist/
ls -la dist dist/prototype
