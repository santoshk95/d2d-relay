"""Pull the compiled JS and CSS out of a packaged .pbiviz so the mock host can load them.

usage: extract_bundle.py <file.pbiviz> <out-prefix>   ->  <out-prefix>.js and <out-prefix>.css
"""
import json
import pathlib
import sys
import zipfile

src, out = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(src) as z:
    name = next(n for n in z.namelist() if n.startswith("resources/") and n.endswith(".pbiviz.json"))
    pkg = json.loads(z.read(name))
out.parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(f"{out}.js").write_text(pkg["content"]["js"], encoding="utf-8")
pathlib.Path(f"{out}.css").write_text(pkg["content"]["css"], encoding="utf-8")
print(f"{pathlib.Path(src).name}: {pkg['visual']['displayName']} {pkg['visual']['version']}, {len(pkg['content']['js'])} bytes of JS -> {out}.js")
