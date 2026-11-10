#!/usr/bin/env bash
# Package both custom visuals and copy the .pbiviz files to release/.
# Needs Node.js and powerbi-visuals-tools (pbiviz) - both are in the Docker image.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/visuals"
bash ./sync.sh                                   # shared code from common/ into each visual
mkdir -p "$ROOT/release"
# every folder with a pbiviz.json, or a list: VISUALS="atlasColumns" bash scripts/build.sh
for v in ${VISUALS:-$(ls -d */pbiviz.json | xargs -n1 dirname)}; do
  echo "== packaging $v"
  (
    cd "$v"
    if [ ! -d node_modules ]; then npm ci --no-audit --no-fund || npm install --no-audit --no-fund; fi
    rm -rf dist
    pbiviz package
    ver=$(node -p "require('./pbiviz.json').visual.version")
    name=$(node -p "require('./pbiviz.json').visual.displayName.replace(/\\s+/g, '')")
    cp dist/*.pbiviz "$ROOT/release/$name.$ver.pbiviz"
    echo "-> release/$name.$ver.pbiviz"
  )
done
