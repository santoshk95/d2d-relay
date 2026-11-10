"""Validate a generated PBIR report folder against Microsoft's published JSON schemas.

usage: python3 tools/validate_report.py "release/report/Visual Atlas Test.Report"
Each file's own $schema URL is downloaded (with the files it references) and cached in tools/schema/pbir/.
Needs network access the first time, and the jsonschema package (in the Docker image).
"""
import json
import pathlib
import sys
import urllib.request

from jsonschema import Draft7Validator, validators
from referencing import Registry, Resource

CACHE = pathlib.Path(__file__).resolve().parent / "schema" / "pbir"


def fetch(url):
    f = CACHE / (url.split("/json-schemas/")[-1].replace("/", "_"))
    if not f.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=30) as r:
            f.write_bytes(r.read())
    return json.loads(f.read_text(encoding="utf-8"))


registry = Registry(retrieve=lambda uri: Resource.from_contents(fetch(uri)))
root = pathlib.Path(sys.argv[1])
bad = 0
files = [root / "definition.pbir"] + sorted((root / "definition").rglob("*.json"))
for f in files:
    doc = json.loads(f.read_text(encoding="utf-8"))
    url = doc.get("$schema") or "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
    schema = fetch(url)
    cls = validators.validator_for(schema, default=Draft7Validator)
    errs = sorted(cls(schema, registry=registry).iter_errors(doc), key=lambda e: list(e.path))
    rel = f.relative_to(root)
    if errs:
        bad += 1
        for e in errs[:6]:
            print(f"FAIL {rel}: {'/'.join(map(str, e.path))}: {e.message[:300]}")
    else:
        print(f"ok   {rel}")
print("ALL VALID" if not bad else f"{bad} FILE(S) INVALID")
sys.exit(1 if bad else 0)
