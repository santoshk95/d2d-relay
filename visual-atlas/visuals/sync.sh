#!/bin/sh
# Copy the shared code in common/ into every visual project (any folder with a pbiviz.json).
# pbiviz only bundles files inside the project folder, so each visual gets its own copy.
# Edit common/, never the copies. scripts/build.sh runs this before packaging.
set -e
cd "$(dirname "$0")"
for f in */pbiviz.json; do
  p=$(dirname "$f")
  mkdir -p "$p/src/common" "$p/style"
  cp common/*.ts "$p/src/common/"
  cp common/atlas.less "$p/style/atlas.less"
  echo "synced common/ -> $p"
done
# family visuals keep their roles and chart objects in caps.js; the shared Format pane objects are added here
for f in */caps.js; do
  if [ -e "$f" ]; then node ../tools/mk_caps.js "$(dirname "$f")"; fi
done
