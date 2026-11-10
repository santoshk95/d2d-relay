"""The one agent helper the consulting packs share: "Ask Relay to draft the wording" on a step whose facts are already
records in sources/. The agent writes narrative.yaml — a few paragraphs, every number in them declared as a figure
with a `record:` source — and the check refuses anything the records do not hold (an undeclared number, a source that
does not resolve or disagrees, placeholder text, American spelling). A person reads it before it reaches a
deliverable; the deliverable's own checks run on it again. Not a pack (the loader skips files starting with "_")."""
from __future__ import annotations

import json

from .. import workbench as wb
from . import _consult as cx

FILE = "narrative.yaml"
PROMPT = """FILE narrative.yaml — read WORK.md, then facts.json in this folder: the records this step's deliverable quotes
(each top-level key is a record you cite as record:<key>#<path>, e.g. record:{first}#{path}).

Write narrative.yaml:

paragraphs:
  - text: "<two or three sentences in plain British English>"
    figures:
      - {{text: "<a number exactly as it appears in text>", source: "record:<key>#<path to that number>"}}

{what}

Every number you write must be declared under figures with the record path that holds it; write no number the records
do not hold, no forecast, no case study, no name that is not in facts.json. Three paragraphs at most."""


def _facts(ctx: wb.Ctx, names: tuple) -> dict:
    out = {}
    for n in names:
        v = cx.read(ctx, n)
        if v is not None:
            out[n] = v
    return out


def _first_path(facts: dict) -> tuple[str, str]:
    for k, v in facts.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, dict):
                    for k3, v3 in vv.items():
                        if isinstance(v3, (int, float)) and not isinstance(v3, bool):
                            return k, f"{kk}.{k3}"
                if isinstance(vv, (int, float)) and not isinstance(vv, bool):
                    return k, kk
    return (next(iter(facts), "record"), "totals")


def action(records: tuple, what: str, agent: str = "Writer", rebuild=None) -> wb.Action:
    """A step action: the agent drafts narrative.yaml from the step's records (names under sources/). With `rebuild`
    (the step's own run), the deliverable is built again with the wording in it, and the step shows the new build."""
    def prompt(ctx: wb.Ctx) -> str:
        facts = _facts(ctx, records)
        if not facts:
            raise wb.StepFailed("There is nothing to write about yet: run the step first.")
        (ctx.dir / "facts.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        k, p = _first_path(facts)
        return PROMPT.format(first=k, path=p, what=what)

    def done(ctx: wb.Ctx, res: dict) -> dict:
        out = after(ctx, res)
        if rebuild is None:
            return out
        built = rebuild(ctx) or {}
        if built.get("ok") is False:
            raise wb.StepFailed("With the drafted wording the deliverable does not pass its checks: " + (built.get("summary") or "")[:400])
        return {**built, "summary": out["summary"] + " " + (built.get("summary") or "")}
    return wb.Action(label="Ask Relay to draft the wording", kind="agent", prompt=prompt, check=check, after=done, agent=agent, turns=20, timeout_s=900,
                     help="The agent writes a few paragraphs from this step's records — every number with its source. You read them before they go into the deliverable.")


def clear(ctx: wb.Ctx) -> None:
    """New facts: wording drafted for the earlier ones no longer applies."""
    ctx.put("narrative", [])
    try:
        (ctx.dir / FILE).unlink()
    except OSError:
        pass


def load(ctx: wb.Ctx) -> list[dict]:
    import yaml
    p = ctx.dir / FILE
    if not p.exists():
        return []
    try:
        y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    paras = y.get("paragraphs") if isinstance(y, dict) else None
    out = []
    for x in paras or []:
        if isinstance(x, dict) and str(x.get("text") or "").strip():
            out.append({"text": str(x["text"]).strip(), "figures": [{"text": str(f.get("text") or ""), "source": str(f.get("source") or ""),
                                                                    "value": _value(f)} for f in (x.get("figures") or []) if isinstance(f, dict)]})
    return out


def check(ctx: wb.Ctx) -> list[str]:
    import yaml
    from genbi_kit.docs import spec as docs_spec
    from genbi_kit.docs.template import BRITISH, PLACEHOLDER_RE
    p = ctx.dir / FILE
    if not p.exists():
        return [f"{FILE} was not written"]
    try:
        y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return [f"{FILE} does not parse: {str(e).splitlines()[0][:200]}"]
    if not isinstance(y, dict) or not isinstance(y.get("paragraphs"), list) or not y["paragraphs"]:
        return [f"{FILE} needs `paragraphs:` — a list of {{text, figures}}"]
    if len(y["paragraphs"]) > 3:
        return ["three paragraphs at most"]
    res = cx.resolver(ctx)
    probs = []
    for i, para in enumerate(y["paragraphs"], 1):
        if not isinstance(para, dict) or not str(para.get("text") or "").strip():
            probs.append(f"paragraph {i}: text is empty")
            continue
        text = str(para["text"])
        figs = [f for f in (para.get("figures") or []) if isinstance(f, dict)]
        covered = set()
        for f in figs:
            ft, src = str(f.get("text") or ""), str(f.get("source") or "")
            num = docs_spec.norm_number(__import__("re").sub(r"[A-Za-z]+", "", ft))      # "2,800.16 USD" -> "2800.16"
            r = res.resolve(src) if src else {"ok": False, "why": "no source", "value": None}
            if not r["ok"]:
                probs.append(f"paragraph {i}: figure {ft!r} — {src or '(no source)'}: {r['why']}")
                continue
            if r.get("value") is not None:
                try:
                    want = float(f["value"]) if f.get("value") is not None else float(num)
                    if abs(want - float(r["value"])) > max(0.5, abs(float(r["value"])) * 0.005):
                        probs.append(f"paragraph {i}: figure {ft!r} says {want:g} but {src} holds {float(r['value']):g}")
                except (TypeError, ValueError):
                    probs.append(f"paragraph {i}: figure {ft!r} is not a number")
            covered.add(num)
            if f.get("value") is not None:
                covered.add(docs_spec.norm_number(str(f["value"])))
        for tok in docs_spec.figure_tokens(text):
            if docs_spec.norm_number(tok) not in covered:
                probs.append(f"paragraph {i}: the number {tok!r} is not a declared figure with a record source (declare it, or take it out)")
        m = PLACEHOLDER_RE.search(text)
        if m:
            probs.append(f"paragraph {i}: placeholder text {m.group(0)!r}")
        for w in __import__("re").findall(r"[A-Za-z]+", text):
            if w.lower() in BRITISH:
                probs.append(f"paragraph {i}: “{w}” — the house style spells it “{BRITISH[w.lower()]}”")
                break
    return probs


def after(ctx: wb.Ctx, res: dict) -> dict:
    paras = load(ctx)
    ctx.put("narrative", paras)
    ctx.evidence("Wording drafted by Relay", {"paragraphs": paras, "note": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"Relay drafted {len(paras)} paragraph(s) from this step's records — every number with its source. Read them before you confirm; "
                       "they go into the deliverable as written, and its checks run on them again."}


def blocks(ctx: wb.Ctx, title: str = "In short") -> list[dict]:
    """The drafted paragraphs as document blocks (each with its figures), or nothing when no draft was made."""
    paras = ctx.get("narrative") or []
    if not paras:
        return []
    out = [{"kind": "heading", "title": title}]
    for p in paras:
        out.append({"kind": "paragraph", "text": p["text"], "figures": [{"text": f["text"], "source": f["source"], "value": _value(f)} for f in p.get("figures") or []]})
    return out


def _value(f: dict):
    """The figure's number (given, or read from its text without a currency code), so the docs checks compare it."""
    if f.get("value") is not None:
        try:
            return float(f["value"])
        except (TypeError, ValueError):
            return None
    from genbi_kit.docs import spec as docs_spec
    try:
        return float(docs_spec.norm_number(__import__("re").sub(r"[A-Za-z]+", "", str(f.get("text") or ""))))
    except ValueError:
        return None
