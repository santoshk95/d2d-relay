"""Validate theme JSON files against Microsoft's report theme schema (tools/schema/reportThemeSchema-2.159.json).

usage: validate_themes.py [files...]   (default: visuals/themes/*.json)
"""
import glob
import json
import pathlib
import sys

import jsonschema

root = pathlib.Path(__file__).resolve().parent.parent
schema = json.loads((root / "tools/schema/reportThemeSchema-2.159.json").read_text(encoding="utf-8"))
validator = jsonschema.validators.validator_for(schema)(schema)
files = sys.argv[1:] or sorted(glob.glob(str(root / "visuals/themes/*.json")))
bad = 0
for f in files:
    errors = list(validator.iter_errors(json.loads(pathlib.Path(f).read_text(encoding="utf-8"))))
    path = pathlib.Path(f).resolve()
    shown = path.relative_to(root) if path.is_relative_to(root) else path
    print(("valid  " if not errors else f"{len(errors)} errors  ") + str(shown))
    for e in errors[:8]:
        print("   ", "/".join(map(str, e.absolute_path)), "-", e.message[:200])
    bad += bool(errors)
sys.exit(1 if bad else 0)
