#!/usr/bin/env bash
# Render every test case of the packaged visuals in the mock Power BI host and run the checks.
# Screenshots go to visuals/test/out/. Fails if a case throws or a check fails.
# Run scripts/build.sh first (it creates the .pbiviz files this reads).
# Each family is "<visual folder>:<prefix>": cases in visuals/test/<prefix>_cases.js, checks (optional) in <prefix>_checks.js.
# ONLY=compare bash scripts/test.sh   runs one family.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$ROOT/visuals/test"; OUT="$T/out"; mkdir -p "$OUT"
FAMILIES="atlasFlow:flow atlasColumns:cols atlasDistribution:dist atlasCompare:compare atlasHierarchy:hierarchy atlasProportion:proportion atlasTime:time atlasFinance:finance atlasGauges:gauges atlasText:text atlasLines:lines atlasParts:parts atlasScatter:scatter"
status=0
cd "$T"
for f in $FAMILIES; do
  v="${f%%:*}"; p="${f##*:}"
  if [ -n "${ONLY:-}" ] && [ "$ONLY" != "$p" ]; then continue; fi
  python3 "$ROOT/tools/extract_bundle.py" "$(ls "$ROOT"/visuals/$v/dist/*.pbiviz | head -1)" "$OUT/$p"
  python3 build_page.py "${p}_test" "$OUT/$p.js" "$OUT/$p.css" "${p}_cases.js"
  python3 shoot.py "${p}_test" "$OUT/${p}_test.png" || status=1
  if [ -f "${p}_checks.js" ]; then python3 shoot.py "${p}_test" "$OUT/${p}_checks.png" "@${p}_checks.js" || status=1; fi
  if [ "$p" = "cols" ]; then python3 shoot.py cols_test "$OUT/cols_format.png" @format_checks.js || status=1; fi
  echo "screenshot: visuals/test/out/${p}_test.png"
done
[ $status -eq 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit $status
