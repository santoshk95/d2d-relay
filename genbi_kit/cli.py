"""`genbi` — the command line the Claude agent uses inside a project folder.

    genbi profile                      profile data/*.csv -> profile.md (tables, keys, relationships)
    genbi datagen [--check]            demo data: the tables of datagen.yaml -> data/*.csv (datagen.py)
    genbi sql "SELECT ..."             run DuckDB SQL over the data (raw file views + model views)
    genbi validate [plan.yaml|definition.yaml]
    genbi prototype                    run every visual's prototype SQL -> prototype/index.html
    genbi build --data-folder PATH     write the Power BI project to powerbi/
    genbi daxcheck                     every measure and visual query evaluated in Power BI's own engine
    genbi gates [--no-dax]             every review gate the app runs before review and publishing (gates.py)
    genbi catalog [type ...]           the visuals (Gen BI, Visual Atlas, visual library, this project's own):
                                       chart types, field wells, format options
    genbi visual new|edit|build|test|list|source ...   build a new custom visual (see vfactory.py)
    genbi read <path> [...]            what an attachment says: docx, xlsx/csv, pptx, pdf, images, video frames,
                                       audio metadata (reader.py; P10 Start)
    genbi deck build|check [deck.yaml] a deck from YAML -> .pptx + HTML twin + check.json (docs/; P11 studio)
    genbi doc build|check [doc.yaml]   a document from YAML -> .docx + HTML twin + check.json
    genbi repo clone|index|branch|status|commit|diff|log|scan|push   git through the toolkit for AI SDLC (repo.py; P16)
"""
import argparse
import json
import os
import sys
from pathlib import Path

from . import catalog, use_project, visuals_dir
from . import data as data_mod
from . import definition, prototype, report_builder
from . import validate as checks
from .profile import profile

def _root(start: Path) -> Path:
    """The project folder: the working folder, or the nearest one above it with request.md (Claude Code's shell
    stays in whatever folder a `cd` moved it to)."""
    for d in (start, *start.parents):
        if (d / "request.md").exists():
            return d
    return start


CWD = _root(Path.cwd())


def _load(path: str) -> dict:
    p = CWD / path
    if not p.exists():
        sys.exit(f"{path} not found in {CWD}")
    try:
        return definition.load(p)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not parse {path}: {e}")


def cmd_profile(_):
    print(profile(CWD))


def cmd_sql(args):
    defn = None
    if (CWD / "definition.yaml").exists():
        try:
            defn = definition.expand(definition.load(CWD / "definition.yaml"))
        except Exception as e:  # noqa: BLE001
            print(f"(model views unavailable: {e})", file=sys.stderr)
    con = data_mod.connect(CWD, defn)
    try:
        cols, rows = data_mod.query(con, args.query, args.limit)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"SQL error: {str(e).splitlines()[0]}")
    print(data_mod.as_text(cols, rows))
    print(f"({len(rows)} row{'s' if len(rows) != 1 else ''}{', limited' if len(rows) == args.limit else ''})")


def cmd_validate(args):
    path = args.file
    raw = _load(path)
    d = None
    if Path(path).name.startswith("plan"):
        errors = checks.plan(raw)
        summary = f"plan: {len(raw.get('kpis') or [])} KPIs, {len(raw.get('pages') or [])} pages"
    else:
        errors, d = checks.definition_errors(raw, CWD, not args.no_sql)
        summary = (f"definition: {len(d['tables'])} tables, {len(d['measures'])} measures, {len(d['pages'])} pages, "
                   f"{sum(len(p['visuals']) for p in d['pages'])} visuals") if d else "definition"
    if errors:
        print(f"{summary}\n{len(errors)} problem(s):")
        for i, e in enumerate(errors, 1):
            print(f"  {i}. {e}")
        sys.exit(1)
    if d is not None and not d["pages"]:
        print(f"{summary}\nModel OK — no pages yet; add the pages of the plan next")
        return
    print(f"{summary}\nOK — no problems found")


def cmd_prototype(args):
    raw = _load(args.file)
    errors, d = checks.definition_errors(raw, CWD, check_sql=False)
    if errors:
        print("Fix validation problems first (genbi validate):")
        for e in errors[:20]:
            print("  -", e)
        sys.exit(1)
    con = data_mod.connect(CWD, d)
    out = CWD / args.out
    errors = prototype.render(d, con, out)
    print(f"wrote {args.out} ({len(d['pages'])} pages, {sum(len(p['visuals']) for p in d['pages'])} visuals)")
    if errors:
        print(f"{len(errors)} visual(s) need attention:")
        for e in errors:
            print("  -", e)
        sys.exit(1)


def cmd_build(args):
    raw = _load(args.file)
    errors, d = checks.definition_errors(raw, CWD, check_sql=False)
    if errors:
        sys.exit("Fix validation problems first: " + "; ".join(errors[:5]))
    if args.data_folder:
        d["data"]["folder"] = args.data_folder if args.data_folder.endswith(("\\", "/")) else args.data_folder + "\\"
    project = report_builder.build(d, catalog(), CWD / args.out, visuals_dir=visuals_dir())
    print(f"wrote {project}")


def cmd_daxcheck(args):
    """Power BI's own engine (the DAX checker on the user's PC) evaluates every measure and visual query."""
    from . import daxcheck
    raw = _load(args.file)
    errors, d = checks.definition_errors(raw, CWD, check_sql=False)
    if errors:
        sys.exit("Fix validation problems first (genbi validate): " + "; ".join(errors[:5]))
    if not daxcheck.available():
        print("The DAX checker is not running on the user's PC, so the DAX was not checked now; the app checks it "
              "in Power BI's engine before publishing.")
        return
    try:
        s = daxcheck.summary(daxcheck.run(CWD, d, catalog(), timeout=240))
    except daxcheck.CheckError as e:
        sys.exit(f"DAX check did not finish: {e}")
    print(f"Power BI engine {s['engine']}: {s['measures']} measures and {s['visuals']} visual queries "
          f"evaluated in {s['seconds']} s under the report's default filters"
          + (f" (sampled: {'; '.join(s['sampled'])})" if s["sampled"] else ""))
    for v in s["values"][:args.show]:
        shown = v["error"] or (v["text"] if v.get("text") not in (None, "") else v["value"])
        print(f"  [{v['name']}] = {shown}")
    if len(s["values"]) > args.show:
        print(f"  … {len(s['values']) - args.show} more measures (--show N to list more)")
    if s["problems"]:
        print(f"{len(s['problems'])} problem(s) — Power BI would show these as broken fields or visuals:")
        for p in s["problems"]:
            print(f"  - {p}")
    if s["differences"]:
        print(f"{len(s['differences'])} difference(s) between Power BI's DAX and the prototype SQL — make them agree:")
        for p in s["differences"]:
            print(f"  - {p}")
    if s["problems"] or s["differences"]:
        sys.exit(1)
    print("OK — Power BI's engine accepts every measure and visual query"
          + (", and every visual's values and title match the prototype" if s["compared"] else ""))


def cmd_datagen(args):
    """Demo data: check datagen.yaml and write its tables to data/ (datagen.py), then profile them."""
    from . import datagen
    path = CWD / args.file
    if not path.exists():
        sys.exit(f"{args.file} not found — write the recipe first (CLAUDE.md, Demo data)")
    try:
        recipe = datagen.load(path)
        problems, plan = datagen.check(recipe, CWD / "data")
    except (datagen.RecipeError, ValueError) as e:
        sys.exit(f"{args.file}: {e}")
    if problems:
        sys.exit(f"{args.file} has a problem:\n  - " + "\n  - ".join(problems))
    if args.check:
        print(f"recipe OK: {len(plan['tables'])} tables, about {sum(t['rows'] for t in plan['tables'].values()):,} rows")
        return
    try:
        s = datagen.run(CWD, args.file)
    except datagen.RecipeError as e:
        sys.exit(f"{args.file}: {e}")
    print(f"wrote {len(s['tables'])} tables, {s['rows']:,} rows in {s['seconds']} s "
          f"(seed {s['seed']}, period {s['period'][0]} to {s['period'][1]}):")
    for t in s["tables"]:
        print(f"  data/{t['file']}: {t['rows']:,} rows · {', '.join(t['columns'])}" + ("" if t["generated"] else " (uploaded)"))
    for w in s["warnings"]:
        print(f"  warning: {w}")
    profile(CWD)
    print("profile.md updated. Check that the story shows in the data with `genbi sql`"
          + (": " + "; ".join(s["story"]) if s["story"] else ""))


def cmd_gates(args):
    """Every review gate the app runs before the user's review and before publishing (gates.py, display.py)."""
    from . import daxcheck, display, gates
    raw = _load(args.file)
    errors, d = checks.definition_errors(raw, CWD, check_sql=False)
    if not errors and not d["pages"]:
        errors = ["no pages yet — add the pages of the plan"]
    found = [gates.gate("definition", errors, ok="valid")]
    if not errors:
        con = data_mod.connect(CWD, d)
        n = sum(len(p["visuals"]) for p in d["pages"])
        found.append(gates.gate("prototype", prototype.render(d, con, CWD / "prototype" / "index.html"),
                                ok=f"{n} visuals drawn from the data (prototype/index.html)"))
        found.append(gates.custom_visuals(CWD, d))
        if args.no_dax:
            dax = {"checked": False, "reason": "skipped (--no-dax)"}
        elif not daxcheck.available():
            dax = {"checked": False, "reason": "the DAX checker is not running on the user's PC"}
        else:
            try:
                dax = daxcheck.summary(daxcheck.run(CWD, d, catalog(), timeout=240))
            except daxcheck.CheckError as e:
                dax = {"checked": False, "reason": str(e)}
        found += gates.dax_gates(dax)
        found += gates.file_gates(CWD, d, catalog(), visuals_dir(), con, dax=dax)
        found.append(gates.gate("display", skip="skipped (--no-display)") if args.no_display
                     else display.check(CWD / "prototype" / "index.html"))
    found = gates.ordered(found)
    for g in found:
        print(f"[{gates.MARK[g['status']]}] {g['name']} — {g['summary']}")
        for i in g["items"]:
            if i["level"] != "info" or args.all:
                print(f"    {i['level']}: {i['text']}")
    bad = gates.failed(found)
    if bad:
        sys.exit(f"\n{len(bad)} gate(s) failed: {', '.join(g['name'] for g in bad)} — fix every 'fail' item; the app "
                 f"blocks approval and publishing until they pass")
    warns = sum(g["status"] == "warn" for g in found)
    print("\nOK — every gate passes" + (f" ({warns} with warnings: fix those that matter to the user)" if warns else ""))


def _kind(t) -> str:
    return "|".join(t["enum"]) if isinstance(t, dict) else t


def cmd_catalog(args):
    """All visuals in brief, or every field well and Format option of the ones named."""
    from . import stock
    cat = catalog()
    if args.types and [t.lower() for t in args.types] in (["pbi"], ["powerbi"], ["stock"], ["builtin"]):
        print(f"Power BI's own visuals (`type: pbi.<visual>`; no custom visual embedded; every Format-pane option from Power BI's "
              f"theme schema {stock.SCHEMA_VERSION}; `genbi catalog pbi.<visual>` shows the wells and every option):")
        groups: dict = {}
        for name, v in stock.catalog().items():
            groups.setdefault(v["group"], []).append((name, v))
        for group, items in groups.items():
            print(f"  {group}:")
            for name, v in items:
                wells = ", ".join(f"{r}{'*' if any(r in g for g in v['required']) else ''} ({i['displayName']})" for r, i in v["role_info"].items())
                print(f"    {name}: {v['displayName']} — {wells}")
        print("\n(* = needed by at least one field combination; wells also take the aliases `genbi catalog pbi.<visual>` lists)")
        return
    if not args.types:
        print("Relay visuals (draw their own card; insight titles via a `title` well):")
        for name, v in cat.items():
            if v.get("family") not in ("atlas", "powerbi"):
                print(f"  {name}: {v['displayName']} — fields: {', '.join(v['roles'])}")
        print("\nPower BI's own visuals: `genbi catalog pbi` lists them (pbi.cardVisual, pbi.clusteredColumnChart, pbi.lineChart, "
              "pbi.donutChart, pbi.pivotTable, … — 31 types)")
        fields = lambda v: ", ".join(f"{r}{'*' if any(r in g for g in v['required']) else ''}" for r in v["roles"])
        print("\nVisual Atlas visuals (type + chart; Power BI container with title/subtitle; see `genbi catalog <type>`):")
        for name, v in cat.items():
            if v.get("origin") == "atlas":
                print(f"  {name}: chart = {' | '.join(v['chart_types'])}\n      fields: {fields(v)}")
        for origin, head in (("library", "Visual library (custom visuals built for earlier reports; use them like Atlas visuals):"),
                             ("project", "This project's custom visuals (visuals/<name>/, `genbi visual list`):")):
            own = {n: v for n, v in cat.items() if v.get("origin") == origin}
            if own:
                print(f"\n{head}")
                for name, v in own.items():
                    print(f"  {name}: {v['displayName']} — {v['description']}\n      fields: {fields(v)}"
                          + (f"; chart = {' | '.join(v['chart_types'])}" if v["chart_types"] else ""))
        print("\n(* = needed by at least one field combination)")
        return
    for name in args.types:
        v = cat.get(name)
        if not v:
            sys.exit(f"unknown visual {name}; run `genbi catalog` (or `genbi catalog pbi` for Power BI's own visuals) for the list")
        if v.get("family") == "powerbi":
            print("\n".join(stock.describe(v)))
            continue
        print(f"{name}: {v['displayName']}" + (f" — {v['description']}" if v.get("description") else ""))
        if v.get("chart_types"):
            print(f"  chart: {' | '.join(v['chart_types'])}")
        print("  fields:")
        for r, k in v["roles"].items():
            info = (v.get("role_info") or {}).get(r, {})
            cap = info.get("max")
            print(f"    {r} ({'column' if k == 'Grouping' else 'measure'}"
                  + (f", max {cap}" if cap is not None else ", several") + (", drill hierarchy" if r in v.get("drill", []) else "")
                  + f"){': ' + info['description'] if info.get('description') else ''}")
        if v.get("required"):
            print("  needs: " + " or ".join(" + ".join(g) for g in v["required"]))
        if v.get("sorting"):
            print("  sort: supported (`sort: [\"[Measure]\", desc]`)")
        for obj, props in v["objects"].items():
            print(f"  format.{obj}: " + ", ".join(f"{p} ({_kind(t)})" for p, t in props.items()))


def cmd_visual(args):
    """The visual factory: build a new Power BI custom visual when nothing in the catalog fits."""
    from . import vfactory as vf
    try:
        VISUAL[args.action](vf, args)
    except vf.VisualError as e:
        sys.exit(str(e))


def _v_created(dest: Path, how: str, name: str) -> None:
    rel = dest.relative_to(CWD).as_posix()
    print(f"created {rel}/ {how}:")
    for f in sorted(p for p in dest.rglob("*") if p.is_file() and "common" not in p.relative_to(dest).parts):
        print(f"  {f.relative_to(CWD).as_posix()}")
    print(f"  {rel}/src/common/  the Visual Atlas framework: read it, never edit it (every build refreshes it)")
    print(f"next: edit caps.js and src/*.ts, then `genbi visual build {name}` and `genbi visual test {name}`")


def _v_new(vf, args):
    _v_created(vf.new(CWD, args.name, args.title, args.description, args.like), f"from {args.like}", args.name)


def _v_edit(vf, args):
    _v_created(vf.edit(CWD, args.name), "from the visual library (same name and GUID)", args.name)


def _v_build(vf, args):
    print(f"building {args.name} (caps.js, TypeScript, ESLint, pbiviz package)...", flush=True)
    info = vf.build(CWD, args.name)
    print(f"built visuals/dist/{args.name}.pbiviz v{info['version']} ({info['bytes'] // 1024} KB, {info['seconds']} s)")
    print("fields: " + ", ".join(f"{r} ({'column' if k == 'Grouping' else 'measure'})" for r, k in info["roles"].items())
          + ("; needs " + " or ".join(" + ".join(g) for g in info["required"]) if info["required"] else ""))
    print("format objects: " + ", ".join(info["objects"]))
    for w in info["warnings"]:
        print("  " + w)
    print(f"next: `genbi visual test {args.name}`, then Read visuals/{args.name}/test.png")


def _v_test(vf, args):
    res = vf.test(CWD, args.name)
    print(f"tested {args.name} v{res['version']} in headless Chromium: {len(res['cases'])} case(s): {', '.join(res['cases'])}")
    print(f"screenshot: {res['screenshot']} — Read it and check the design: labels readable and not overlapping, "
          "nothing cut off, colors from the palette, legend and axes right")
    for n in res["notes"]:
        print(f"  note: {n}")
    if res["problems"]:
        print(f"{len(res['problems'])} problem(s):")
        for p in res["problems"]:
            print(f"  - {p}")
        sys.exit(1)
    print("OK — no problems found")


def _v_list(vf, args):
    mine = vf.status(CWD)
    print("This project's custom visuals:" if mine else "This project has no custom visuals.")
    for v in mine:
        state = ("not built" if not v["built"] else "changed since the last build: rebuild" if v["stale"]
                 else "tested OK" if v["tested"] else "built, not tested on this build")
        print(f"  {v['name']}: {v['title']} v{v['version']} — {state}")
    lib = vf.library()
    print("\nVisual library (use these by type like any visual; `genbi visual edit <name>` to change one):" if lib
          else "\nThe visual library is empty.")
    for r in lib:
        print(f"  {r['name']}: {r['title']} v{r['version']} — {r.get('description', '')}\n      fields: "
              + ", ".join(f"{k} ({'column' if t == 'Grouping' else 'measure'})" for k, t in r.get("roles", {}).items()))
    print("\nTemplates for `genbi visual new --like`: starter, " + ", ".join(vf.families())
          + (", " + ", ".join(r["name"] for r in lib) if lib else ""))


def _v_source(vf, args):
    files = vf.source_files(args.name)
    if args.file:
        files = [f for f in files if f.name == args.file]
        if not files:
            sys.exit(f"{args.name} has no file {args.file}; run `genbi visual source {args.name}` for all of them")
    for f in files:
        print(f"==> {f.name} <==")
        print(f.read_text(encoding="utf-8"))


VISUAL = {"new": _v_new, "edit": _v_edit, "build": _v_build, "test": _v_test, "list": _v_list, "source": _v_source}


def cmd_read(args):
    """P10: read an attachment (or every file of a folder) and print what it says; the extraction is cached in
    `.read/` next to the file, where the web app shows it on the Start page."""
    from . import reader
    failed = 0
    for a in args.paths:
        p = Path(a) if Path(a).is_absolute() else CWD / a
        targets = sorted(x for x in p.iterdir() if x.is_file() and reader.kind_of(x)) if p.is_dir() else [p]
        if not targets:
            print(f"{a}: nothing to read")
        for t in targets:
            try:
                info = reader.read(t)
            except reader.ReadError as e:
                print(f"{t.name}: {e}")
                failed += 1
                continue
            print(reader.report(info))
            print()
    if failed:
        sys.exit(1)


def cmd_docs(args):
    """P11: `genbi deck|doc build|check` — a deliverable from deck.yaml / doc.yaml (docs/build.py). `check` prints every
    check and exits 1 on a failure; `build` also writes the .pptx / .docx, the HTML twin and check.json to --out."""
    from .docs import build as docs_build
    from .docs import checks as docs_checks
    from .docs.spec import DocError
    kind = args.cmd
    spec_path = CWD / (args.file or f"{kind}.yaml")
    try:
        if args.action == "check":
            report = docs_build.check(spec_path, template_path=args.template, workspace=os.environ.get("WORKSPACES"))
        else:
            info = docs_build.build(spec_path, CWD / args.out, template_path=args.template, workspace=os.environ.get("WORKSPACES"))
            report = info["report"]
            for k, f in info["files"].items():
                print(f"wrote {args.out}/{f}")
            print(docs_build.summary_line(info))
    except DocError as e:
        sys.exit(f"{spec_path.name}: {e}")
    print(docs_checks.text_report(report, spec_path.name))
    if not report["ok"]:
        sys.exit(f"\n{report['counts']['fails']} problem(s) — fix every 'fail' item in {spec_path.name}; the app will not send a deliverable that fails its checks")
    print("\nOK — every check passes" + (f" ({report['counts']['warnings']} warnings: look at them)" if report["counts"]["warnings"] else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="genbi", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("profile").set_defaults(fn=cmd_profile)
    p = sub.add_parser("sql")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_sql)
    p = sub.add_parser("validate")
    p.add_argument("file", nargs="?", default="definition.yaml")
    p.add_argument("--no-sql", action="store_true")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("prototype")
    p.add_argument("file", nargs="?", default="definition.yaml")
    p.add_argument("--out", default="prototype/index.html")
    p.set_defaults(fn=cmd_prototype)
    p = sub.add_parser("build")
    p.add_argument("file", nargs="?", default="definition.yaml")
    p.add_argument("--out", default="powerbi")
    p.add_argument("--data-folder")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("daxcheck")
    p.add_argument("file", nargs="?", default="definition.yaml")
    p.add_argument("--show", type=int, default=40, help="measure values to list")
    p.set_defaults(fn=cmd_daxcheck)
    p = sub.add_parser("datagen", help="demo data: write the tables of datagen.yaml to data/")
    p.add_argument("file", nargs="?", default="datagen.yaml")
    p.add_argument("--check", action="store_true", help="only check the recipe")
    p.set_defaults(fn=cmd_datagen)
    p = sub.add_parser("gates", help="every review gate: definition, prototype, Power Query, data, DAX, report files, "
                                     "consistency, best practices, accessibility, display")
    p.add_argument("file", nargs="?", default="definition.yaml")
    p.add_argument("--no-dax", action="store_true", help="skip the DAX check in Power BI's engine")
    p.add_argument("--no-display", action="store_true", help="skip drawing the prototype in a headless browser")
    p.add_argument("--all", action="store_true", help="also list the notes (info items)")
    p.set_defaults(fn=cmd_gates)
    p = sub.add_parser("catalog")
    p.add_argument("types", nargs="*", help="visual types to describe in full (e.g. atlasFlow)")
    p.set_defaults(fn=cmd_catalog)
    p = sub.add_parser("visual", help="build a new custom visual")
    vs = p.add_subparsers(dest="action", required=True)
    q = vs.add_parser("new", help="start a visual in visuals/<name>/")
    q.add_argument("name", help="the visual type, camelCase (e.g. radialBars)")
    q.add_argument("--title", default="", help="display name in Power BI")
    q.add_argument("--description", default="")
    q.add_argument("--like", default="starter", help="starter, an Atlas family or a library visual to start from")
    vs.add_parser("edit", help="copy a library visual into the project to change it").add_argument("name")
    vs.add_parser("build", help="compile and package with pbiviz").add_argument("name")
    vs.add_parser("test", help="render in headless Chromium, screenshot to visuals/<name>/test.png").add_argument("name")
    vs.add_parser("list", help="this project's custom visuals and the visual library")
    q = vs.add_parser("source", help="print a template's source (starter, an Atlas family, common, a library visual)")
    q.add_argument("name")
    q.add_argument("file", nargs="?")
    p.set_defaults(fn=cmd_visual)
    p = sub.add_parser("read", help="what an attachment says (docx, xlsx, csv, pptx, pdf, image, video, audio, text)")
    p.add_argument("paths", nargs="+", help="files, or a folder such as attachments/")
    p.set_defaults(fn=cmd_read)
    for kind, label in (("deck", "a deck (.pptx) from deck.yaml"), ("doc", "a document (.docx) from doc.yaml")):     # P11: the studio engine
        p = sub.add_parser(kind, help=f"{label}: build or check it (docs/)")
        p.add_argument("action", choices=["build", "check"])
        p.add_argument("file", nargs="?", help=f"the YAML (default {kind}.yaml)")
        p.add_argument("--out", default="builds/latest", help="folder for the .pptx/.docx, the HTML twin and check.json")
        p.add_argument("--template", default=None, help="a tenant .pptx/.potx (or .docx/.dotx) template; default: the brand's, else RELAY")
        p.set_defaults(fn=cmd_docs)
    p = sub.add_parser("repo", help="git through the toolkit (P16 AI SDLC): clone, index, branch, status, commit, diff, log, scan, push")
    rs = p.add_subparsers(dest="action", required=True)
    q = rs.add_parser("clone", help="clone a repository into repo/ (the credential comes from the run, never a URL)")
    q.add_argument("url"); q.add_argument("--branch", default=None); q.add_argument("--depth", type=int, default=None)
    rs.add_parser("index", help="languages, test / lint commands, CODEOWNERS, contributing notes -> repo-index.yaml")
    rs.add_parser("branch", help="create (from HEAD) and switch to a branch").add_argument("name")
    rs.add_parser("status")
    q = rs.add_parser("commit", help="stage the named paths (default: every change) and commit")
    q.add_argument("-m", "--message", required=True); q.add_argument("paths", nargs="*")
    rs.add_parser("diff", help="the working tree vs HEAD, or --base <ref>..HEAD").add_argument("--base", default=None)
    rs.add_parser("log").add_argument("-n", type=int, default=20)
    rs.add_parser("scan", help="the regex secret scan over the clone")
    rs.add_parser("push", help="push the branch (the credential comes from the run)").add_argument("--branch", default=None)
    for sp in rs.choices.values():
        sp.add_argument("--dir", default="repo", help="the clone folder (default repo/)")
    p.set_defaults(fn=lambda a: __import__("genbi_kit.repo", fromlist=["cmd_repo"]).cmd_repo(a))
    args = ap.parse_args(argv)
    use_project(CWD)
    args.fn(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:            # `genbi … | head` stopped reading: not an error
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
