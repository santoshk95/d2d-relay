"""Create the project files of a new Atlas family visual (everything except caps.js and src/).

usage: python3 tools/scaffold.py <name> "<Display Name>" "<description>" "<icon spec>"
  name          folder and visual name, e.g. atlasCompare
  icon spec     shapes on a 20x20 grid: "r x y w h" (rectangle) or "c x y r" (circle), separated by ";"
Copies package.json, package-lock.json, tsconfig.json and eslint.config.mjs from atlasColumns, writes
pbiviz.json with a new GUID (never change it afterwards), assets/icon.png and style/visual.less.
Does nothing if the folder already has a pbiviz.json.
"""
import json
import pathlib
import shutil
import struct
import sys
import uuid
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
name, display, desc, icon = sys.argv[1:5]
d = ROOT / "visuals" / name
if (d / "pbiviz.json").exists():
    sys.exit(f"{d} already exists")
src = ROOT / "visuals" / "atlasColumns"
for sub in ("src", "style", "assets", "stringResources/en-US"):
    (d / sub).mkdir(parents=True, exist_ok=True)
for f in ("tsconfig.json", "eslint.config.mjs"):
    shutil.copyfile(src / f, d / f)
slug = "atlas-" + "".join("-" + c.lower() if c.isupper() else c for c in name[5:]).strip("-")
for f in ("package.json", "package-lock.json"):
    (d / f).write_text((src / f).read_text(encoding="utf-8").replace("atlas-columns", slug).replace("Atlas Columns custom visual", f"{display} custom visual"), encoding="utf-8")
guid = name + uuid.uuid4().hex.upper()
(d / "pbiviz.json").write_text(json.dumps({
    "visual": {"name": name, "displayName": display, "guid": guid, "visualClassName": "Visual", "version": "1.0.0.0",
               "description": desc, "supportUrl": "https://learn.microsoft.com/power-bi/developer/visuals/", "gitHubUrl": ""},
    "apiVersion": "5.11.1", "author": {"name": "Visual Atlas", "email": "atlas@example.com"}, "assets": {"icon": "assets/icon.png"},
    "externalJS": None, "style": "style/visual.less", "capabilities": "capabilities.json", "dependencies": None, "stringResources": [], "version": "1.0.0.0"
}, indent=2) + "\n", encoding="utf-8")
(d / "style" / "visual.less").write_text('@import "atlas.less";\n', encoding="utf-8")

# 20x20 icon in the Atlas blue
W = H = 20
px = [[(0, 0, 0, 0)] * W for _ in range(H)]
blue, dark = (42, 120, 214, 255), (25, 70, 140, 255)
for k, part in enumerate(p.strip() for p in icon.split(";") if p.strip()):
    t, *a = part.split()
    a = [float(x) for x in a]
    col = dark if k % 2 else blue
    for y in range(H):
        for x in range(W):
            if t == "r" and a[0] <= x < a[0] + a[2] and a[1] <= y < a[1] + a[3]:
                px[y][x] = col
            elif t == "c" and (x + 0.5 - a[0]) ** 2 + (y + 0.5 - a[1]) ** 2 <= a[2] ** 2:
                px[y][x] = col
raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in px)
chunk = lambda t, data: struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
(d / "assets" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
print(f"created visuals/{name} with GUID {guid}")
