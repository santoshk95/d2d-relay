#!/usr/bin/env python3
"""Generate the 8 pbiviz package folders (and catalog.json) from visuals.json.

Each package gets pbiviz.json, capabilities.json (data roles, mappings, format objects),
package.json, tsconfig.json, assets/icon.png and src/cards.json. build.sh then copies the
shared renderer code in and runs `pbiviz package`. Stdlib only.
"""
import json
import shutil
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_VERSION = "5.11.0"
VERSION = "1.0.1.0"          # bump when renderer code changes so Power BI replaces the old visual
TYPE = {"text": {"text": True}, "color": {"fill": {"solid": {"color": True}}}, "bool": {"bool": True},
        "number": {"numeric": True}}


def resolve_cards(spec: dict, common: dict) -> list[dict]:
    cards = []
    for c in spec["cards"]:
        if isinstance(c, str):
            cards.append({"object": c, **common[c]})
        else:
            cards.append(c)
    return cards


def capabilities(spec: dict, cards: list[dict]) -> dict:
    select = [{"for": {"in": name}} for name in spec["values"]]
    categorical: dict = {}
    if spec.get("categories"):
        categorical["categories"] = {"for": {"in": spec["categories"]},
                                     "dataReductionAlgorithm": {"top": {"count": spec.get("categoryCount", 1000)}}}
    if spec.get("series"):
        categorical["values"] = {"group": {"by": spec["series"], "select": select,
                                           "dataReductionAlgorithm": {"top": {"count": 200}}}}
    else:
        categorical["values"] = {"select": select}
    return {
        "dataRoles": [{"name": r["name"], "displayName": r["displayName"], "kind": r["kind"]} for r in spec["roles"]],
        "dataViewMappings": [{
            "conditions": [{r["name"]: {"max": r["max"]} for r in spec["roles"]}],
            "categorical": categorical,
        }],
        "objects": {c["object"]: {"displayName": c["displayName"], "properties": {
            p["name"]: {"displayName": p["displayName"], "type": TYPE[p["type"]]} for p in c["props"]}} for c in cards},
        "privileges": [],
        "sorting": {"default": {}},
        "supportsHighlight": False,
        "supportsMultiVisualSelection": True,
        "suppressDefaultTitle": True,
    }


# ---------- 20x20 icon, drawn pixel by pixel (no Pillow needed) ----------
def icon_png(glyph: str) -> bytes:
    W = 20
    px = [[(0, 0, 0, 0)] * W for _ in range(W)]
    orange, white = (221, 122, 18, 255), (255, 255, 255, 255)

    def rect(x0, y0, x1, y1, c=white):
        for y in range(max(0, y0), min(W, y1 + 1)):
            for x in range(max(0, x0), min(W, x1 + 1)):
                px[y][x] = c

    def line(x0, y0, x1, y1, c=white):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            rect(x0, y0, x0 + 1, y0 + 1, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    for y in range(W):                       # rounded orange tile
        for x in range(W):
            corner = min(x, W - 1 - x) + min(y, W - 1 - y)
            if corner >= 2 or (min(x, W - 1 - x) >= 1 and min(y, W - 1 - y) >= 1):
                px[y][x] = orange
    if glyph == "kpi":
        rect(4, 4, 11, 5); rect(4, 8, 13, 11); line(10, 15, 15, 13); rect(4, 14, 7, 15)
    elif glyph == "trend":
        line(3, 14, 7, 9); line(7, 9, 11, 11); line(11, 11, 16, 4)
    elif glyph == "bars":
        rect(9, 3, 16, 5); rect(9, 7, 13, 9); rect(5, 11, 9, 13); rect(9, 15, 11, 16)
    elif glyph == "quadrant":
        rect(10, 3, 10, 16); rect(3, 10, 16, 10); rect(5, 5, 6, 6); rect(13, 4, 15, 6); rect(12, 13, 13, 14); rect(4, 13, 5, 14)
    elif glyph == "treemap":
        rect(3, 3, 11, 16); rect(13, 3, 16, 9); rect(13, 11, 16, 16)
    elif glyph == "heatmap":
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0 or (i, j) == (1, 1):
                    rect(3 + j * 5, 3 + i * 5, 6 + j * 5, 6 + i * 5)
    elif glyph == "funnel":
        rect(3, 3, 16, 5); rect(5, 7, 14, 9); rect(7, 11, 12, 13); rect(9, 15, 10, 16)
    elif glyph == "narrative":
        rect(3, 4, 5, 6); rect(8, 4, 16, 5); rect(3, 9, 5, 11); rect(8, 9, 14, 10); rect(3, 14, 5, 16); rect(8, 14, 15, 15)

    raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in px)
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, W, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> None:
    spec = json.loads((ROOT / "visuals.json").read_text(encoding="utf-8"))
    common = spec["common_cards"]
    catalog = {}
    for name, v in spec["visuals"].items():
        pkg = ROOT / "packages" / name
        shutil.rmtree(pkg, ignore_errors=True)
        (pkg / "src").mkdir(parents=True)
        (pkg / "assets").mkdir()
        cards = resolve_cards(v, common)
        dump = lambda path, obj: (pkg / path).write_text(json.dumps(obj, indent=2), encoding="utf-8")
        dump("pbiviz.json", {
            "visual": {"name": name.lower(), "displayName": v["displayName"], "guid": v["guid"],
                       "visualClassName": "Visual", "version": VERSION, "description": v["description"],
                       "supportUrl": "https://example.com/genbi/support", "gitHubUrl": ""},
            "apiVersion": API_VERSION,
            "author": {"name": "Gen BI", "email": "genbi@example.com"},
            "assets": {"icon": "assets/icon.png"},
            "style": "style/visual.less",
            "capabilities": "capabilities.json",
            "dependencies": None,
            "stringResources": [],
            "version": VERSION,
        })
        dump("capabilities.json", capabilities(v, cards))
        dump("package.json", {"name": f"genbi-{name.lower()}", "version": "1.0.0", "private": True,
                              "description": v["description"], "license": "MIT",
                              "dependencies": {"powerbi-visuals-api": "~5.11.1"}})
        dump("tsconfig.json", {"compilerOptions": {
            "allowJs": False, "emitDecoratorMetadata": True, "experimentalDecorators": True, "target": "es2022",
            "sourceMap": True, "outDir": "./.tmp/build/", "moduleResolution": "node", "declaration": False,
            "lib": ["es2022", "dom"], "resolveJsonModule": True, "esModuleInterop": True, "skipLibCheck": True},
            "files": ["./src/visual.ts"]})
        dump("src/cards.json", cards)
        (pkg / "assets" / "icon.png").write_bytes(icon_png(v["glyph"]))
        catalog[name] = {
            "guid": v["guid"], "displayName": v["displayName"],
            "roles": {r["name"]: r["kind"] for r in v["roles"]},
            "objects": {c["object"]: {p["name"]: p["type"] for p in c["props"]} for c in cards},
        }
        print(f"scaffolded {name:11s} {v['guid']}")
    (ROOT / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
