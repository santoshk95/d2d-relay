"""Build and check a deliverable from its YAML: the model, the checks, the .pptx or .docx, the HTML twin and
check.json — used by `genbi deck|doc build|check` (the agent) and by the web app (studio.py, rfp.py).

  build(spec_path, out_dir, brand=…, template_path=…, workspace=…, renderer=…, evidence_base=…) -> info
  check(spec_path, brand=…, template_path=…, workspace=…) -> report

`sources/brand.json` next to the YAML (written by the web app) supplies the brand, the house style and the tenant
template files when the caller gives none, so the agent's command line and the app build the same thing."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import checks, docx_build, pptx_build, spec, twin
from .diagrams import Rasteriser
from .sources import Resolver
from .template import Template, load_template


def project_root(spec_path: Path) -> Path:
    """The project folder a YAML belongs to: the nearest folder above it with brief.md / request.md / project.json."""
    p = Path(spec_path).resolve()
    for d in (p.parent, *p.parent.parents):
        if any((d / n).exists() for n in ("project.json", "brief.md", "request.md")):
            return d
    return p.parent


def brand_from_folder(root: Path) -> dict:
    p = root / "sources" / "brand.json"
    try:
        b = json.loads(p.read_text(encoding="utf-8"))
        return b if isinstance(b, dict) else {}
    except (OSError, ValueError):
        return {}


def template_for(root: Path, brand: dict | None, template_path: str | None, docx_path: str | None, choice: str = "") -> Template:
    """The template to use: an explicit file, else the tenant's (sources/brand.json names them), else RELAY."""
    b = dict(brand or brand_from_folder(root))
    want_tenant = (choice or b.get("template") or "relay") != "relay"
    pptx = template_path or (b.get("template_pptx_file") if want_tenant else None)
    docx = docx_path or (b.get("template_docx_file") if want_tenant else None)
    pptx = str(root / pptx) if pptx and not Path(pptx).is_absolute() else pptx
    docx = str(root / docx) if docx and not Path(docx).is_absolute() else docx
    return load_template(pptx, b, docx=docx, workdir=root / ".genbi")


def prepare(spec_path: Path | str, brand: dict | None = None, template_path: str | None = None, docx_path: str | None = None,
            workspace: str | Path | None = None) -> tuple[dict, Template, Resolver, list[str], Path]:
    spec_path = Path(spec_path)
    root = project_root(spec_path)
    raw = spec.load(spec_path)
    errs = spec.shape_errors(raw)
    model = spec.normalise(raw)
    t = template_for(root, brand, template_path, docx_path, model["template"])
    resolver = Resolver(root, workspace)
    return model, t, resolver, errs, root


def check(spec_path: Path | str, brand: dict | None = None, template_path: str | None = None, docx_path: str | None = None,
          workspace: str | Path | None = None) -> dict:
    model, t, resolver, errs, _ = prepare(spec_path, brand, template_path, docx_path, workspace)
    report = checks.run(model, t, resolver, errs)
    report["title"] = model["title"]
    return report


def build(spec_path: Path | str, out_dir: Path | str, brand: dict | None = None, template_path: str | None = None, docx_path: str | None = None,
          workspace: str | Path | None = None, renderer=None, evidence_base: str = "", name: str | None = None, pdf: bool = False) -> dict:
    """Everything into out_dir: deck.pptx or doc.docx, twin.html, check.json (and deck.pdf when a renderer returns one)."""
    t0 = time.time()
    model, t, resolver, errs, root = prepare(spec_path, brand, template_path, docx_path, workspace)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = checks.run(model, t, resolver, errs)
    report["title"] = model["title"]
    base = name or ("deck" if model["kind"] == "deck" else "doc")
    info: dict = {"kind": model["kind"], "title": model["title"], "template": t.name, "partner": t.partner, "powered": t.powered, "out": str(out), "files": {}}
    if errs:                                                 # a YAML that does not even hold together: the report alone
        info.update(ok=False, report=report, seconds=round(time.time() - t0, 1))
        (out / "check.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        info["files"]["check"] = "check.json"
        return info
    html = twin.html(model, t, resolver, evidence_base, report)
    (out / "twin.html").write_text(html, encoding="utf-8")
    info["files"]["twin"] = "twin.html"
    with Rasteriser(renderer) as ras:
        if model["kind"] == "deck":
            info["deck"] = pptx_build.build(model, t, resolver, root, out / f"{base}.pptx", ras)
            info["files"]["pptx"] = f"{base}.pptx"
        else:
            info["doc"] = docx_build.build(model, t, resolver, root, out / f"{base}.docx", ras)
            info["files"]["docx"] = f"{base}.docx"
        info["renderer"] = ras.used
    if pdf and renderer is not None:
        try:
            data = renderer(html, "pdf")
        except TypeError:
            data = None
        if data:
            (out / f"{base}.pdf").write_bytes(data)
            info["files"]["pdf"] = f"{base}.pdf"
    report["built"] = {k: v for k, v in info.items() if k in ("deck", "doc", "files", "renderer")}
    (out / "check.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    info["files"]["check"] = "check.json"
    info.update(ok=report["ok"], report=report, seconds=round(time.time() - t0, 1), units=model["units"])
    return info


def summary_line(info: dict) -> str:
    r = info["report"]
    what = info.get("deck") or info.get("doc") or {}
    made = ", ".join(f"{k} {v}" for k, v in what.items() if k in ("slides", "blocks", "charts", "tables", "diagrams", "notes") and v)
    return (f"{'deck' if info['kind'] == 'deck' else 'document'} “{info['title']}” — {made or 'nothing built'}; template {info['template']}; "
            f"checks {'passed' if r['ok'] else 'FAILED'} ({r['counts']['fails']} problems, {r['counts']['warnings']} warnings)")
