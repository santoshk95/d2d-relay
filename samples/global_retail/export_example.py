#!/usr/bin/env python3
"""Export the tested Atlas Retail reference as the agent's worked example (genbi_kit/examples).

Converts the hand-built definition to the authoring form the agent writes: `rows` page layouts,
report-wide `filters`, the `date_table` shorthand and plain measures on KPI cards (the toolkit adds
the "(card)" helpers itself).
"""
import re
from pathlib import Path

import yaml

import reference as ref

OUT = Path(__file__).resolve().parents[2] / "genbi_kit" / "examples" / "atlas_retail.yaml"


class Literal(str):
    pass


yaml.add_representer(Literal, lambda dumper, s: dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|"))


def multiline(value):
    return Literal(value) if isinstance(value, str) and "\n" in value else value


def main() -> None:
    d = ref.DEFINITION
    tables = []
    for t in d["tables"]:
        if t["name"] == "Date":
            tables.append({"name": "Date", "description": t.get("description"),
                           "date_table": {"start": "2024-01-01", "end": "2026-12-31", "is_past_from": "Sales[Date]",
                                          "events": [{"name": "Spring sale", "from": "03-20", "to": "04-05"},
                                                     {"name": "Summer sale", "from": "07-01", "to": "07-16"},
                                                     {"name": "Autumn promo", "from": "10-01", "to": "10-19"},
                                                     {"name": "Black Friday", "from": "11-24", "to": "11-30"},
                                                     {"name": "Christmas", "from": "12-10", "to": "12-24"}]}})
            continue
        if t["name"] == "Metrics":
            continue
        out = {k: t[k] for k in ("name", "csv", "dax", "description") if t.get(k)}
        out["columns"] = [{k: v for k, v in {"name": c["name"], "source": c.get("source") if c.get("source") != c["name"] else None,
                                              "type": c["type"], "hidden": c.get("hidden") or None,
                                              "sortBy": c.get("sortBy")}.items() if v is not None}
                          for c in t["columns"]]
        tables.append(out)
    measures = [{"name": m["name"], "format": m["format"], "folder": m["folder"],
                 **({"description": m["description"]} if m.get("description") else {}),
                 "expression": multiline(m["expression"])}
                for m in d["measures"] if not m["name"].endswith("(card)")]
    pages = []
    for page in d["pages"]:
        body = [v for v in page["visuals"] if v["type"] not in ("pageNavigator", "slicer", "textbox")]
        rows = {}
        for v in body:
            rows.setdefault(v["y"], []).append(v)
        out_rows = []
        for y in sorted(rows):
            vs = sorted(rows[y], key=lambda v: v["x"])
            widths = [v["w"] for v in vs]
            row = {"visuals": []}
            if vs[0]["type"] == "narrative":
                row["height"] = vs[0]["h"]
            for v in vs:
                item = {k: v[k] for k in ("id", "type") if k in v}
                fields = {}
                for role, refs in (v["fields"] if isinstance(v.get("fields"), dict) else {}).items():
                    fix = lambda r: re.sub(r" \(card\)\]$", "]", r)
                    fields[role] = [fix(r) for r in refs] if isinstance(refs, list) else fix(refs)
                if v["type"] == "table":
                    item.update(fields=v["fields"], title=v.get("title"), sort=list(v["sort"]))
                else:
                    item["fields"] = fields
                    if v.get("format"):
                        item["format"] = v["format"]
                if len(set(widths)) > 1:
                    item["span"] = round(v["w"] / min(widths), 1)
                row["visuals"].append(item)
            out_rows.append(row)
        pages.append({"name": page["name"], "rows": out_rows})
    example = {
        "name": d["name"], "description": d["description"], "theme": d["theme"],
        "tables": tables,
        "calculated_columns": [c for c in d["calculated_columns"] if c["name"] != "Is Past"],
        "relationships": [f"{r['from']} -> {r['to']}" for r in d["relationships"]],
        "measures": measures,
        "filters": [{"field": "Date[Year]", "label": "Period", "default": 2026}, {"field": "Country[Region]", "label": "Region"},
                    {"field": "Store[Channel]", "label": "Channel"}, {"field": "Category[Category]", "label": "Category"}],
        "pages": pages,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("# Atlas Retail — tested reference definition (no prototype SQL). Patterns, not a template.\n"
                   + yaml.dump(example, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    print(f"wrote {OUT} ({len(measures)} measures, {len(pages)} pages)")


if __name__ == "__main__":
    main()
