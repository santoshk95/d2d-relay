"""W4 Process modules — what the six packs share (brd, processdocs, raci, mining, controls, testdocs; docs/workbench.md).

  reading      every upload read into passages a requirement, a step or a control can cite: Word, PDF, slides, sheets
               and text through `genbi read`'s readers (genbi_kit.reader); e-mail (.eml), call transcripts (.vtt /
               .srt) and Confluence or SharePoint page exports (.html) here; images, audio and video are looked at by
               the agent (frames through ffmpeg in the agent image). Written to sources/segments.json, one id per passage.
  sources      a cited passage must exist and its quote must be in it; a number in a statement must be in a cited
               passage — nothing invented (check_sources, numbers_unsourced)
  sign-offs    one checkpoint per named person (each business owner, each UAT user, each RACI owner) next to the step's
               own confirm; the step cannot be confirmed until every one of them has signed (signoff_problems)
  documents    Word documents and their HTML twins through the P11 docs engine, in the tenant's template (build_doc)
  pushes       what a tracker or test-tool adapter wrote after its per-change approval, fed back to the work item
  vocabularies uploads of recordings, e-mail, transcripts, Visio and BPMN; lineage kinds for documents, requirements,
               stories, tests, processes, controls and roles — extended at import, so no shared file is edited
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import secrets as _secrets
import time
import traceback
from html.parser import HTMLParser
from pathlib import Path

from .. import auth, checkpoints, db, lineage, registry, store
from .. import workbench as wb

# ------------------------------------------------------------------ shared vocabularies (extended at import, no shared edit)

MEDIA = (".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg", ".webp")
TEXTS = (".docx", ".pdf", ".pptx", ".txt", ".md", ".eml", ".vtt", ".srt", ".html", ".htm", ".xlsx", ".csv", ".json", ".yaml", ".yml")
EXTRA_EXT = MEDIA + (".eml", ".vtt", ".srt", ".vsdx", ".bpmn", ".xes", ".log", ".tsv", ".html", ".htm")
wb.DATA_EXT = tuple(dict.fromkeys(tuple(wb.DATA_EXT) + EXTRA_EXT))
KINDS_ADDED = {"document": "Document", "requirement": "Requirement", "story": "User story", "test": "Test case", "process": "Process",
               "control": "Control", "role": "Role", "activity": "Activity"}
lineage.NODE_KINDS = tuple(dict.fromkeys(tuple(lineage.NODE_KINDS) + tuple(KINDS_ADDED)))
for _k, _v in KINDS_ADDED.items():
    lineage.KIND_LABEL.setdefault(_k, _v)

db.register_schema("""
CREATE TABLE IF NOT EXISTS w4_signoffs (
  id TEXT PRIMARY KEY, module TEXT NOT NULL, item TEXT NOT NULL, step TEXT NOT NULL, round TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT,
  checkpoint TEXT, status TEXT NOT NULL DEFAULT 'open', comment TEXT, decided REAL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS w4_signoffs_item ON w4_signoffs (item, step, round);
CREATE TABLE IF NOT EXISTS w4_pushes (
  approval TEXT PRIMARY KEY, module TEXT NOT NULL, item TEXT NOT NULL, step TEXT, connection TEXT, target TEXT, what TEXT, status TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, done REAL);
CREATE INDEX IF NOT EXISTS w4_pushes_item ON w4_pushes (item);
""")

REFRESH: dict = {}             # "<module>.<step>" -> fn(ctx) -> step result: redrawn when a sign-off or a push lands


def j(s, default):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:n] or "x"


# ------------------------------------------------------------------ reading: uploads -> passages

class _Text(HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br", "td", "th", "section", "article", "pre"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.heading = [], 0, None
        self.blocks: list[tuple[str | None, str]] = []
        self.cur: list[str] = []
        self.in_h = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "title"):
            self.skip += 1
        if tag in self.BLOCK:
            self._flush()
        if re.fullmatch(r"h[1-6]", tag):
            self.in_h = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "title") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            if self.in_h and re.fullmatch(r"h[1-6]", tag):
                self.heading = " ".join("".join(self.cur).split()) or self.heading
                self.cur = []
                self.in_h = False
                return
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.cur.append(data)

    def _flush(self):
        t = " ".join("".join(self.cur).split())
        if t and not self.in_h:
            self.blocks.append((self.heading, t))
        self.cur = [] if not self.in_h else self.cur


def _paras(text: str) -> list[str]:
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n|\n(?=[-*•] )", text or "") if p.strip()]


def _seg(file: str, key: str, loc: str, text: str, kind: str = "text", **extra) -> dict:
    return {"id": f"{file}#{key}", "file": file, "loc": loc, "kind": kind, "text": text[:4000], **extra}


def _docx_segments(path: Path, name: str) -> list[dict]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(path))
    out, heading, n = [], "", 0
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            t = " ".join(p.text.split())
            if not t:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.startswith("Heading") or style == "Title":
                heading = t
                continue
            n += 1
            out.append(_seg(name, f"p{n}", (f"§ {heading}, " if heading else "") + f"paragraph {n}", t))
        elif tag == "tbl":
            for r_i, r in enumerate(Table(child, d).rows, 1):
                cells = [" ".join(c.text.split()) for c in r.cells]
                if any(cells):
                    n += 1
                    out.append(_seg(name, f"p{n}", (f"§ {heading}, " if heading else "") + f"table row {r_i}", " | ".join(cells)))
    return out


def _sheet_segments(path: Path, name: str) -> list[dict]:
    rows: list[list] = []
    sheet = ""
    if path.suffix.lower() == ".csv" or path.suffix.lower() == ".tsv":
        with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
            rows = [r for r in csv.reader(fh, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")]
    else:
        import openpyxl
        book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        ws = book.worksheets[0]
        sheet = ws.title
        rows = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
        book.close()
    rows = [r for r in rows if any(str(v).strip() for v in r)]
    if not rows:
        return []
    head = [str(h).strip() or f"column {i + 1}" for i, h in enumerate(rows[0])]
    out = []
    for i, r in enumerate(rows[1:2001], 2):
        text = "; ".join(f"{h}: {str(v).strip()}" for h, v in zip(head, r) if str(v).strip())
        if text:
            out.append(_seg(name, f"row{i}", (f"sheet {sheet}, " if sheet else "") + f"row {i}", text, row={h: str(v).strip() for h, v in zip(head, r)}))
    return out


def _cue_segments(path: Path, name: str) -> list[dict]:
    txt = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", txt):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        tline = next((l for l in lines if "-->" in l), None)
        if not tline:
            continue
        start = tline.split("-->")[0].strip().replace(",", ".")
        hhmmss = re.match(r"(?:(\d+):)?(\d{1,2}):(\d{2})", start)
        stamp = (f"{int(hhmmss.group(1) or 0):02d}:{int(hhmmss.group(2)):02d}:{int(hhmmss.group(3)):02d}") if hhmmss else start
        body = " ".join(lines[lines.index(tline) + 1:])
        m = re.match(r"<v\s+([^>]+)>(.*)", body)
        speaker = ""
        if m:
            speaker, body = m.group(1).strip(), re.sub(r"</v>", "", m.group(2)).strip()
        else:
            m = re.match(r"([A-Z][\w .'-]{1,40}):\s+(.*)", body)
            if m:
                speaker, body = m.group(1).strip(), m.group(2).strip()
        body = re.sub(r"<[^>]+>", "", body).strip()
        if body:
            out.append(_seg(name, f"t{stamp}", f"{stamp}" + (f", {speaker}" if speaker else ""), (f"{speaker}: " if speaker else "") + body, speaker=speaker))
    return out


def _eml_segments(path: Path, name: str) -> list[dict]:
    from email import policy
    from email.parser import BytesParser
    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    if body is not None and body.get_content_type() == "text/html":
        p = _Text()
        p.feed(text)
        p._flush()
        text = "\n\n".join(t for _, t in p.blocks)
    head = f"e-mail from {msg.get('From', '')} on {msg.get('Date', '')}: {msg.get('Subject', '')}"
    out = [_seg(name, "subject", head[:200], f"Subject: {msg.get('Subject', '')}", sender=str(msg.get("From", "")), subject=str(msg.get("Subject", "")))]
    for i, ptxt in enumerate([p for p in _paras(text) if not p.startswith(">")], 1):
        out.append(_seg(name, f"p{i}", f"e-mail “{str(msg.get('Subject', ''))[:60]}”, paragraph {i}", ptxt, sender=str(msg.get("From", ""))))
    return out


def _html_segments(path: Path, name: str) -> list[dict]:
    p = _Text()
    p.feed(path.read_text(encoding="utf-8", errors="replace"))
    p._flush()
    return [_seg(name, f"p{i}", (f"§ {h}, " if h else "") + f"paragraph {i}", t) for i, (h, t) in enumerate(p.blocks, 1)]


def read_file(path: Path) -> tuple[dict, list[dict]]:
    """One upload -> (what was read, its passages). Never raises: a file that cannot be read says why."""
    name, ext = path.name, path.suffix.lower()
    info = {"name": name, "bytes": path.stat().st_size, "kind": "", "what": "", "note": ""}
    segs: list[dict] = []
    try:
        if ext == ".docx":
            info["kind"], segs = "document", _docx_segments(path, name)
            info["what"] = f"{len(segs)} paragraph(s) and table row(s)"
        elif ext in (".xlsx", ".csv", ".tsv"):
            info["kind"], segs = "sheet", _sheet_segments(path, name)
            info["what"] = f"{len(segs)} row(s)"
        elif ext in (".vtt", ".srt"):
            info["kind"], segs = "transcript", _cue_segments(path, name)
            info["what"] = f"{len(segs)} cue(s)" + (f", {len({s.get('speaker') for s in segs if s.get('speaker')})} speaker(s)" if segs else "")
        elif ext == ".eml":
            info["kind"], segs = "e-mail", _eml_segments(path, name)
            info["what"] = segs[0]["loc"] if segs else "empty"
        elif ext in (".html", ".htm"):
            info["kind"], segs = "page export", _html_segments(path, name)
            info["what"] = f"{len(segs)} paragraph(s)"
        elif ext in (".vsdx", ".bpmn", ".xes"):
            info["kind"] = {".vsdx": "Visio drawing", ".bpmn": "BPMN 2.0 export", ".xes": "event log (XES)"}[ext]
            info["what"] = "read by rules (shapes and links, or events), not as text"
        elif ext in MEDIA:
            from genbi_kit import reader
            kind = reader.kind_of(path) or "media"
            r = reader.read(path, write_cache=False)
            info["kind"] = {"video": "recording (video)", "audio": "recording (audio)", "image": "image"}.get(kind, kind)
            info["what"] = (f"{r.get('width')} × {r.get('height')} px" if r.get("width") else "") or (f"{(r.get('meta') or {}).get('duration_s')} s" if (r.get("meta") or {}).get("duration_s") else "")
            info["note"] = "Relay's agent looks at it itself (frames for a video, the picture for an image); a transcript next to a recording can be quoted"
            segs = [_seg(name, "media", info["kind"], "", kind="media")]
        else:
            from genbi_kit import reader
            r = reader.read(path, write_cache=False)
            info["kind"] = {"pdf": "PDF", "deck": "slides", "text": "text"}.get(r.get("kind") or "", r.get("kind") or "file")
            info["note"] = r.get("note") or ""
            if r.get("kind") == "pdf":
                for pg in r.get("page_texts") or []:            # PDF lines wrap anywhere: a passage is a sentence
                    text = " ".join((pg["text"] or "").split())
                    for i, ptxt in enumerate([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", text) if s.strip()], 1):
                        segs.append(_seg(name, f"page{pg['page']}.{i}", f"page {pg['page']}, sentence {i}", ptxt))
                info["what"] = f"{r.get('pages')} page(s), {len(segs)} sentence(s)"
            elif r.get("kind") == "deck":
                for s in r.get("slides") or []:
                    text = " ".join(x for x in (s.get("title"), s.get("text"), s.get("notes")) if x)
                    if text.strip():
                        segs.append(_seg(name, f"slide{s['slide']}", f"slide {s['slide']}" + (f" “{s['title'][:50]}”" if s.get("title") else ""), " ".join(text.split())))
                info["what"] = f"{len(r.get('slides') or [])} slide(s)"
            else:
                for i, ptxt in enumerate(_paras(r.get("text") or ""), 1):
                    segs.append(_seg(name, f"p{i}", f"paragraph {i}", ptxt))
                info["what"] = f"{len(segs)} paragraph(s)"
    except Exception as e:  # noqa: BLE001 - a broken file is reported, never a failed step
        info["note"] = f"could not be read: {str(e).splitlines()[0][:200] if str(e) else e.__class__.__name__}"
        info["error"] = True
    info["passages"] = sum(1 for s in segs if s["kind"] == "text")
    return info, segs


def read_uploads(ctx: wb.Ctx, exts: tuple | None = None, *, extra: list[dict] | None = None, evidence: bool = True) -> dict:
    """Read every upload (of these types) into passages; sources/segments.json is what the agent and the checks cite."""
    files, segs = [], []
    for f in ctx.files(exts):
        p = ctx.dir / "data" / f["name"]
        if not p.exists() or f["name"].endswith(".xlsx.csv"):
            continue
        info, s = read_file(p)
        files.append(info)
        segs += s
        if evidence:
            ctx.evidence(f"Read: {f['name']}", {"file": info, "rows": [{"passage": x["id"], "where": x["loc"], "text": x["text"][:300]} for x in s[:300]]},
                         kind="read", ok=not info.get("error"))
    segs += extra or []
    sdir = ctx.dir / "sources"
    sdir.mkdir(exist_ok=True)
    (sdir / "segments.json").write_text(json.dumps({"files": files, "segments": segs}, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"files": files, "segments": segs}


def request_segment(ctx: wb.Ctx) -> list[dict]:
    """The brief itself as a passage (a change request is a source of what changes)."""
    return [_seg("request", f"p{i}", f"the request, paragraph {i}", t) for i, t in enumerate(_paras(ctx.brief), 1)] if ctx.brief.strip() else []


def segments(ctx: wb.Ctx) -> dict:
    p = ctx.dir / "sources" / "segments.json"
    try:
        return {s["id"]: s for s in json.loads(p.read_text(encoding="utf-8")).get("segments") or []}
    except (OSError, ValueError):
        return {}


def files_table(read: dict) -> dict:
    return {"columns": ["File", "Kind", "What Relay read", "Passages", "Note"],
            "rows": [[f["name"], f["kind"], f["what"], f.get("passages", 0), f.get("note") or ""] for f in read["files"]]}


# ------------------------------------------------------------------ sources: nothing invented

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def norm(s) -> str:
    return " ".join(str(s or "").translate(_QUOTES).lower().split())


def quote_found(text: str, quote: str) -> bool:
    """The quote (ellipses allowed between parts) is in the passage, ignoring case, spaces and typographic quotes."""
    t, parts = norm(text), [norm(p) for p in re.split(r"\.\.\.|…", str(quote or "")) if norm(p)]
    if not parts:
        return False
    pos = 0
    for part in parts:
        k = t.find(part.strip(" .,;:"), pos)
        if k < 0:
            return False
        pos = k + len(part.strip(" .,;:"))
    return True


NUM_RE = re.compile(r"(?<![\w.\-/#])(?:[₹$€£]\s?)?\d[\d,]*(?:\.\d+)?(?![\w\-])")      # ids such as BR-001 or PAY-12 are not figures


def numbers(text: str) -> set[str]:
    """The figures a statement uses, normalised (₹5,00,000 -> 500000); single digits are words, not figures."""
    out = set()
    for m in NUM_RE.finditer(str(text or "")):
        d = re.sub(r"[^\d.]", "", m.group(0)).rstrip(".")
        if d and len(d.replace(".", "")) >= 2:
            out.add(d.rstrip("0").rstrip(".") if "." in d else d)
    return out


def numbers_unsourced(text: str, texts: list[str]) -> list[str]:
    have = set()
    for t in texts:
        have |= numbers(t)
    return sorted(n for n in numbers(text) if n not in have)


def parse_refs(v) -> list[dict]:
    """sources as the agent writes them ([{ref, quote}] or "id, id") or as a person types them."""
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                out.append({"ref": str(x.get("ref") or x.get("id") or "").strip(), "quote": str(x.get("quote") or "").strip()})
            elif str(x).strip():
                out.append({"ref": str(x).strip(), "quote": ""})
        return out
    return [{"ref": r.strip(), "quote": ""} for r in re.split(r"[;,\n]", str(v or "")) if r.strip()]


def person_source(v) -> str | None:
    m = re.match(r"^\s*stated by\s+(.+)$", str(v or ""), re.I)
    return m.group(1).strip() if m else None


def check_sources(where: str, refs: list[dict], segs: dict, *, need_quote: bool = True, statement: str = "") -> list[str]:
    """Problems with what an item cites: unknown passages, quotes not in them, numbers no cited passage holds."""
    if not refs:
        return [f"{where}: no source — every item must cite the passage it comes from (nothing invented)"]
    out, texts, media_only = [], [], True
    for r in refs:
        s = segs.get(r["ref"])
        if not s:
            out.append(f"{where}: cites {r['ref']!r}, which is not a passage in sources/segments.json")
            continue
        if s["kind"] == "media":
            continue
        media_only = False
        texts.append(s["text"])
        if need_quote and not r["quote"]:
            out.append(f"{where}: give the quote from {r['ref']} it rests on")
        elif r["quote"] and not quote_found(s["text"], r["quote"]):
            out.append(f"{where}: the quote “{r['quote'][:80]}” is not in {r['ref']} (quote the passage word for word)")
    if statement:
        miss = numbers_unsourced(statement, texts)
        if miss:
            out.append(f"{where}: {', '.join(miss)} is not in any cited passage" + (" (a recording alone cannot carry a figure)" if media_only else "") + " — cite the passage that says it, or take the figure out")
    return out


def where_text(refs: list[dict], segs: dict) -> str:
    out = []
    for r in refs:
        s = segs.get(r["ref"])
        out.append(f"{s['file']} · {s['loc']}" if s else r["ref"])
    return "; ".join(out)


# ------------------------------------------------------------------ YAML the agent writes

def load_yaml(path: Path) -> tuple[dict | None, list[str]]:
    import yaml
    if not path.exists():
        return None, [f"{path.name} was not written"]
    try:
        y = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return None, [f"{path.name} does not parse: {str(e).splitlines()[0][:200]}"]
    if not isinstance(y, dict):
        return None, [f"{path.name} must be a mapping"]
    return y, []


# ------------------------------------------------------------------ people and sign-offs (one checkpoint per named person)

SIGN_KIND = "w4.signoff"


def people(text: str) -> tuple[list[dict], list[str]]:
    """Workspace people named one per line (or comma-separated) by e-mail or name."""
    users = db.q("SELECT id, email, name FROM users WHERE active = 1")
    found, problems = [], []
    for raw in [x.strip() for x in re.split(r"[\n,;]", text or "") if x.strip()]:
        key = raw.lower()
        u = next((x for x in users if (x["email"] or "").lower() == key or (x["name"] or "").lower() == key or x["id"] == raw), None)
        if not u:
            problems.append(f"{raw} is not a person in this workspace")
        elif u["id"] not in {f["id"] for f in found}:
            found.append(u)
    return found, problems


def _share(item: str, uid: str, by: str | None) -> None:
    db.run("INSERT OR IGNORE INTO shares (project_id, principal_type, principal_id, permission, expires, created, created_by) VALUES (?, 'user', ?, 'view', NULL, ?, ?)",
           (item, uid, time.time(), by or "agent"))


def ask_signoff(ctx: wb.Ctx, users: list[dict], *, round_: str, what: str, items: list[str], step: str | None = None, role: str = "") -> list[dict]:
    """A sign-off checkpoint for each person (they can open the item to read it); earlier rounds' open ones are withdrawn."""
    sid = step or ctx.step_id
    for r in db.q("SELECT * FROM w4_signoffs WHERE item = ? AND step = ? AND round != ? AND status = 'open'", (ctx.id, sid, round_)):
        db.run("UPDATE checkpoints SET status = 'withdrawn', decided = ?, decided_by = 'system' WHERE id = ? AND status = 'open'", (time.time(), r["checkpoint"]))
        db.run("UPDATE w4_signoffs SET status = 'withdrawn' WHERE id = ?", (r["id"],))
    for u in users:
        if db.one("SELECT 1 FROM w4_signoffs WHERE item = ? AND step = ? AND round = ? AND user_id = ?", (ctx.id, sid, round_, u["id"])):
            continue
        _share(ctx.id, u["id"], ctx.who or ctx.owner)
        cp = checkpoints.open(SIGN_KIND, ctx.id, ctx.module_name, f"Sign-off: {ctx.title} — {u['name']} ({round_})", "text",
                              {"summary": what, "items": items[:12], "step": sid, "round": round_, "module": ctx.module,
                               "item": {"id": ctx.id, "title": ctx.title, "work": ctx.work, "module": ctx.module}},
                              link=wb.route_of(ctx.st) + f"?step={sid}", assignee=u["id"], agent=(ctx.spec.agent if ctx.spec else "") or "Relay", opened_by="agent")
        db.run("INSERT INTO w4_signoffs (id, module, item, step, round, user_id, role, checkpoint, status, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
               ("so-" + _secrets.token_hex(5), ctx.module, ctx.id, sid, round_, u["id"], role, cp["id"], time.time()))
    return signoffs(ctx.id, sid, round_)


def signoffs(item: str, step: str, round_: str) -> list[dict]:
    names = {r["id"]: r["name"] for r in db.q("SELECT id, name FROM users")}
    return [{**r, "name": names.get(r["user_id"], r["user_id"])} for r in db.q("SELECT * FROM w4_signoffs WHERE item = ? AND step = ? AND round = ? AND status != 'withdrawn' ORDER BY created", (item, step, round_))]


def signoff_records(item: str, step: str, round_: str) -> list[dict]:
    return [{"id": r["user_id"], "person": r["name"], "role": r.get("role") or "", "decision": {"open": "waiting", "accepted": "signed off", "sent_back": "asked for changes"}.get(r["status"], r["status"]),
             "when": time.strftime("%d %b %Y %H:%M", time.gmtime(r["decided"])) if r.get("decided") else "", "comment": r.get("comment") or ""} for r in signoffs(item, step, round_)]


def signoff_problems(item: str, step: str, round_: str) -> list[str]:
    rows = signoffs(item, step, round_)
    out = [f"{r['name']} asked for changes: {r.get('comment') or ''}".strip() for r in rows if r["status"] == "sent_back"]
    wait = [r["name"] for r in rows if r["status"] == "open"]
    if wait:
        out.append("Waiting for the sign-off of " + ", ".join(wait))
    return out


def _on_signoff(c: dict, decision: str, comment: str | None, who: str) -> None:
    r = db.one("SELECT * FROM w4_signoffs WHERE checkpoint = ?", (c["id"],))
    if not r:
        return
    db.run("UPDATE w4_signoffs SET status = ?, comment = ?, decided = ? WHERE id = ?", ("accepted" if decision == "accept" else "sent_back", (comment or "")[:1000] or None, time.time(), r["id"]))
    db.audit(f"w4.signoff.{'accepted' if decision == 'accept' else 'sent_back'}", r["item"], {"module": r["module"], "step": r["step"], "round": r["round"], "checkpoint": c["id"]}, who)
    try:
        store.log(r["item"], {"kind": "user", "text": ("Signed off" if decision == "accept" else "Asked for changes") + f" ({r['round']})" + (f" — {comment}" if comment else "")})
    except (KeyError, FileNotFoundError):
        return
    apply_refresh(r["item"], r["step"])
    if decision == "accept" and not signoff_problems(r["item"], r["step"], r["round"]):
        try:
            st = wb._load(r["item"])
            s = wb._step(st, r["step"])
            cp = checkpoints.get(s.get("checkpoint") or "")
            if cp and cp.get("assignee_id"):
                from .. import notify
                notify.add(cp["assignee_id"], "review", f"Everyone signed: {st['title']}", f"{s['name']} can now be confirmed", wb.route_of(st) + f"?step={r['step']}")
        except Exception:  # noqa: BLE001 - a courtesy
            pass


checkpoints.register_kind(SIGN_KIND, "Sign-off", _on_signoff)


def apply_refresh(item: str, step: str) -> None:
    """Redraw a step from what changed outside it (a sign-off, a push); the journey does not move."""
    try:
        st = wb._load(item)
    except (KeyError, FileNotFoundError, ValueError):
        return
    fn = REFRESH.get(f"{st['module']}.{st['work']}.{step}") or REFRESH.get(f"{st['module']}.{step}")
    if not fn:
        return
    try:
        ctx = wb.Ctx(item, step)
        out = wb._normalise(fn(ctx))
    except Exception:  # noqa: BLE001 - the decision is recorded either way
        traceback.print_exc()
        return

    def f(s):
        x = wb._step(s, step)
        wb._save_ctx(ctx, s)
        x.update(summary=out["summary"] or x.get("summary") or "", counts=out["counts"] or x.get("counts") or {}, items=out["items"] or x.get("items") or [])
        if out["data"] is not None:
            x["data"] = out["data"]
        if out["records"] is not None:
            x["records"] = wb._ids(out["records"])
    wb._mutate(item, f)


# ------------------------------------------------------------------ pushes: writes after their per-change approval, fed back

def request_push(ctx: wb.Ctx, connection_id: str, obj: str, payload: dict, what: str, *, step: str | None = None, items: list[str] | None = None) -> dict:
    """ctx.request_write, with what the approver reads in plain words and the link back to the step (a connection.write
    checkpoint: the adapter writes when, and only when, a named person accepts exactly this)."""
    from .. import connectors
    payload = {"from": f"{ctx.module}:{ctx.id}:{step or ctx.step_id}", **payload}
    c = ctx.connection(connection_id)
    link = wb.route_of(ctx.st) + f"?step={step or ctx.step_id}"
    try:
        try:
            cp = connectors.request_write(c, obj, payload, ctx.who or ctx.owner, module=ctx.module_name, what=what, items=items, link=link)
        except TypeError:                                  # before the consolidation's items / link
            cp = connectors.request_write(c, obj, payload, ctx.who or ctx.owner, module=ctx.module_name, what=what)
    except Exception as e:  # noqa: BLE001 - ScopeError / ConnectorError: shown to the person
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": what, "connection": c["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
    db.run("INSERT OR REPLACE INTO w4_pushes (approval, module, item, step, connection, target, what, status, result, created) VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting', '{}', ?)",
           (cp["id"], ctx.module, ctx.id, step or ctx.step_id, connection_id, c["kind"], what[:300], time.time()))
    return cp


def desk_sources(kind: str = "jira", op: str = "create") -> list[dict]:
    """The Service desk's sources (P12) that may do this (raise a ticket / add a comment) — the only way a W4 pack
    writes to Jira, each write after its own itsm.write approval."""
    try:
        from .. import itsm
    except Exception:  # noqa: BLE001
        return []
    out = []
    for s in db.q("SELECT * FROM itsm_sources WHERE kind = ? AND paused = 0 ORDER BY created", (kind,)):
        if itsm.may(s, op):
            out.append({"id": s["id"], "name": s["name"], "kind": s["kind"], "options": itsm._opts(s), "projects": j(s["projects"], [])})
    return out


def desk_options(u: dict) -> list[tuple[str, str]]:
    return [("", "None — Azure Boards, or CSV files to import")] + [(s["id"], f"{s['name']} · project {(s['options'].get('project') or (s['projects'] or ['?'])[0])}") for s in desk_sources()]


def desk_write(ctx: wb.Ctx, source_id: str, op: str, payload: dict, *, step: str, ref: str, name: str) -> dict:
    """One Service desk write (op create | comment) for one story or comment: itsm.request_write opens its itsm.write
    checkpoint with exactly what is written; the hook below records what came back."""
    from .. import itsm
    who = ctx.who or ctx.owner
    try:
        wr = itsm.request_write(source_id, op, payload, who=who, module=ctx.module_name, origin=f"{ctx.module}:{ctx.id}:{step}:{ref}",
                                link=wb.route_of(ctx.st) + f"?step={step}", assignee=who, name=name[:200])
    except itsm.ItsmError as e:
        raise wb.StepFailed(str(e)) from e
    db.run("INSERT OR REPLACE INTO w4_pushes (approval, module, item, step, connection, target, what, status, result, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (wr["id"], ctx.module, ctx.id, step, source_id, "jira", name[:300], "awaiting" if wr["status"] == "waiting" else wr["status"], json.dumps({"ref": ref}), time.time()))
    ctx._handoff({"kind": "write", "label": name[:200], "connection": wr.get("source"), "checkpoint": wr.get("checkpoint_id"), "status": "awaiting approval", "link": "#/validate"})
    return wr


def _desk_hook(wr: dict, event: str) -> None:
    """The Service desk tells the module that asked: written (with the key and link), failed, sent back, refused, withdrawn."""
    parts = str(wr.get("origin") or "").split(":")
    if len(parts) < 4:
        return
    item, step, ref = parts[1], parts[2], ":".join(parts[3:])
    res = wr.get("result") or {}
    ok = event == "written"
    out = {"created": [{"ref": ref, "key": res.get("key"), "url": res.get("url")}]} if ok and wr.get("op") == "create" else \
          {"updated": [{"ref": ref, "key": (wr.get("payload") or {}).get("key"), "url": res.get("url")}]} if ok else {"error": wr.get("error") or event}
    db.run("UPDATE w4_pushes SET status = ?, result = ?, done = ? WHERE approval = ?", ("written" if ok else "failed", json.dumps({"ref": ref, **out}), time.time(), wr["id"]))
    try:
        store.log(item, {"kind": "agent", "text": f"{wr.get('title')}: " + (f"written ({res.get('key') or 'comment'})" if ok else f"not written — {event}")})
    except (KeyError, FileNotFoundError):
        return
    apply_refresh(item, step)


try:                                                       # every W4 pack's origin prefix (module id) hears its Service desk writes
    from .. import itsm as _itsm
    for _m in ("brd", "processdocs", "raci", "mining", "controls", "testdocs"):
        _itsm.register_write_hook(_m, _desk_hook)
except Exception:  # noqa: BLE001 - without the Service desk, Jira is not offered
    pass


def pushes_of(item: str, step: str) -> list[dict]:
    return [{**r, "result": j(r["result"], {})} for r in db.q("SELECT * FROM w4_pushes WHERE item = ? AND step = ? ORDER BY created", (item, step))]


def push_of(item: str, step: str) -> dict | None:
    r = db.one("SELECT * FROM w4_pushes WHERE item = ? AND step = ? ORDER BY created DESC LIMIT 1", (item, step))
    return {**r, "result": j(r["result"], {})} if r else None


def pushes(item: str) -> list[dict]:
    return [{**r, "result": j(r["result"], {})} for r in db.q("SELECT * FROM w4_pushes WHERE item = ? ORDER BY created", (item,))]


def push_written(approval: str, result: dict, ok: bool = True) -> None:
    """Called by an adapter after it wrote (or failed to write) what a person approved."""
    r = db.one("SELECT * FROM w4_pushes WHERE approval = ?", (approval,))
    if not r:
        return
    db.run("UPDATE w4_pushes SET status = ?, result = ?, done = ? WHERE approval = ?", ("written" if ok else "failed", json.dumps(result, default=str)[:200000], time.time(), approval))
    try:
        store.log(r["item"], {"kind": "agent", "text": f"{r['what']}: " + ("written" if ok else "failed — " + str(result.get("error") or "")[:200])})
    except (KeyError, FileNotFoundError):
        return
    apply_refresh(r["item"], r["step"])


def latest_pushes(item: str, step: str) -> list[dict]:
    """The pushes of a step that still count: per story (a Service desk write) or per batch (a connection write), the latest."""
    last: dict = {}
    for p in pushes_of(item, step):
        last[p["result"].get("ref") if p["target"] == "jira" and p["result"].get("ref") else p["approval"]] = p
    return list(last.values())


def push_problems(item: str, step: str) -> list[str]:
    ps = latest_pushes(item, step)
    wait = [p for p in ps if p["status"] == "awaiting"]
    bad = [p for p in ps if p["status"] == "failed"]
    out = []
    if wait:
        out.append(f"Nothing is written yet for {len(wait)} of {len(ps)}: accept “{wait[0]['what']}”" + (" and the others" if len(wait) > 1 else "") + " in the Validation queue (each its own approval), then confirm here")
    if bad:
        out.append(f"{len(bad)} approved write(s) did not go through ({str(bad[0]['result'].get('error') or '')[:160]}) — run the step again")
    return out


def payload_from(payload: dict) -> tuple[str, str, str]:
    """(module, item, step) from a push payload's `from`."""
    parts = str(payload.get("from") or "").split(":")
    return (parts + ["", "", ""])[0], (parts + ["", "", ""])[1], (parts + ["", "", ""])[2]


# ------------------------------------------------------------------ documents through the P11 docs engine

def para(text: str, source: str) -> dict:
    """A paragraph whose figures are declared with the record they come from (the docs engine's rule)."""
    from genbi_kit.docs import spec as dspec
    return {"kind": "paragraph", "text": text, "figures": [{"text": t, "source": source} for t in dspec.figure_tokens(text)]}


def table(columns: list[str], rows: list[list], source: str, caption: str) -> dict:
    return {"kind": "table", "table": {"columns": columns, "rows": [[("" if v is None else str(v)) for v in r] for r in rows] or [["—"] * len(columns)],
                                       "source": source, "caption": caption}}


def build_doc(ctx: wb.Ctx, name: str, title: str, subtitle: str, sections: list[dict], records: dict, *, label: str, audience: str = "") -> dict:
    """A Word document and its HTML twin in the tenant's template (Admin › Branding), every table sourced from a record
    written into sources/; the engine's checks are kept as evidence. Returns the build info."""
    import yaml

    from genbi_kit.docs import build as docs_build

    from .. import studio
    d = ctx.dir
    sdir = d / "sources"
    sdir.mkdir(exist_ok=True)
    for k, v in records.items():
        (sdir / f"{k}.json").write_text(json.dumps(v, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    tpl = "tenant" if registry.templates().get("docx") else "relay"
    studio.write_brand(d, tpl)
    out = d / "docs" / name
    out.mkdir(parents=True, exist_ok=True)
    spec = {"kind": "doc", "title": title, "subtitle": subtitle, "audience": audience, "template": tpl, "sections": sections}
    (out / "doc.yaml").write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
    info = docs_build.build(out / "doc.yaml", out, workspace=store.root(), name=name)
    files = info.get("files") or {}
    if files.get("docx"):
        ctx.output(f"{name}.docx", (out / files["docx"]).read_bytes(), label=f"{label} (Word)")
    if files.get("twin"):
        ctx.output(f"{name}.html", (out / files["twin"]).read_bytes(), label=f"{label} (HTML preview)")
    rep = info.get("report") or {}
    ctx.evidence(f"Document checks: {label}", {"ok": rep.get("ok"), "template": info.get("template"),
                                                "rows": [{"check": c.get("label"), "status": c.get("status"), "summary": c.get("summary"),
                                                          "items": "; ".join(i["text"] for i in c.get("items") or [])[:600]} for c in rep.get("checks") or []]},
                 kind="document", ok=bool(rep.get("ok")))
    return info


def doc_problems(info: dict) -> list[str]:
    rep = info.get("report") or {}
    return [f"{c.get('label')}: {i['text']}" for c in rep.get("checks") or [] if c.get("status") == "fail" for i in c.get("items") or [] if i.get("level") == "fail"]


# ------------------------------------------------------------------ event logs (system logs, ERP / ticketing extracts, XES)

CASE_COLS = ("case_id", "case", "caseid", "case id", "case_key", "_case_key", "case:concept:name", "ticket", "ticket_id", "order_id", "invoice_id", "document", "doc_no", "incident")
ACT_COLS = ("activity", "activity_en", "concept:name", "event", "action", "step", "task", "activity_name", "status_change")      # Celonis: ACTIVITY_EN
TS_COLS = ("timestamp", "time:timestamp", "eventtime", "event_time", "time", "ts", "datetime", "date", "start", "start_time", "end_time")
RES_COLS = ("resource", "org:resource", "user_name", "user", "performer", "agent", "role", "assignee")


def eventlog_from_rows(name: str, cols: list[str], rows: list[dict], mapping: dict | None = None) -> dict | None:
    """Rows read from a platform (Celonis, Signavio PI) as an event log, the same shape read_eventlog gives."""
    m = mapping or eventlog_columns(cols)
    if not m:
        return None
    cases: dict = {}
    skipped = 0
    for r in rows:
        ts, act = parse_time(r.get(m["time"])), str(r.get(m["activity"]) or "").strip()
        if ts is None or not act:
            skipped += 1
            continue
        cases.setdefault(str(r.get(m["case"])).strip(), []).append((ts, act, str(r.get(m.get("resource") or "") or "").strip()))
    for k in cases:
        cases[k].sort(key=lambda e: e[0])
    return {"file": name, "columns": m, "cases": cases, "events": sum(len(v) for v in cases.values()), "skipped": skipped}


def eventlog_columns(header: list[str]) -> dict | None:
    low = {str(h).strip().lower(): h for h in header}

    def pick(cands):
        return next((low[c] for c in cands if c in low), None)
    m = {"case": pick(CASE_COLS), "activity": pick(ACT_COLS), "time": pick(TS_COLS), "resource": pick(RES_COLS)}
    return m if m["case"] and m["activity"] and m["time"] else None


def parse_time(v) -> float | None:
    import datetime as dt
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e11 else 1)
    if hasattr(v, "timestamp"):
        return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).timestamp()
    s = str(v).strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
        return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()
    except ValueError:
        pass
    for f in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M", "%Y/%m/%d %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return dt.datetime.strptime(s, f).replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def read_eventlog(path: Path, mapping: dict | None = None) -> dict | None:
    """A CSV / TSV / Excel / XES event log -> {"file", "columns", "cases": {case: [(time, activity, resource)]}, "events",
    "skipped"}; None when the file does not look like an event log (no case, activity and time columns)."""
    ext = path.suffix.lower()
    cases: dict = {}
    skipped = 0
    if ext == ".xes":
        from xml.etree import ElementTree as ET
        root = ET.parse(str(path)).getroot()
        local = lambda e: e.tag.rsplit("}", 1)[-1]  # noqa: E731
        for tr in [e for e in root if local(e) == "trace"]:
            cid = next((a.get("value") for a in tr if local(a) == "string" and a.get("key") == "concept:name"), None) or f"trace-{len(cases) + 1}"
            for ev in [e for e in tr if local(e) == "event"]:
                act = next((a.get("value") for a in ev if a.get("key") == "concept:name"), None)
                ts = parse_time(next((a.get("value") for a in ev if a.get("key") == "time:timestamp"), None))
                res = next((a.get("value") for a in ev if a.get("key") == "org:resource"), "")
                if act and ts is not None:
                    cases.setdefault(cid, []).append((ts, act, res or ""))
                else:
                    skipped += 1
        cols = {"case": "concept:name (trace)", "activity": "concept:name", "time": "time:timestamp", "resource": "org:resource"}
    else:
        if ext in (".csv", ".tsv", ".log"):
            with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
                sample = fh.read(4096)
                fh.seek(0)
                delim = "\t" if ext == ".tsv" or sample.count("\t") > sample.count(",") else ";" if sample.count(";") > sample.count(",") else ","
                rows = list(csv.reader(fh, delimiter=delim))
        elif ext == ".xlsx":
            import openpyxl
            book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            rows = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
            book.close()
        else:
            return None
        rows = [r for r in rows if r and any(str(v or "").strip() for v in r)]
        if len(rows) < 2:
            return None
        head = [str(h or "").strip() for h in rows[0]]
        cols = mapping or eventlog_columns(head)
        if not cols or not all(cols.get(k) in head for k in ("case", "activity", "time")):
            return None
        ix = {k: head.index(v) for k, v in cols.items() if v in head}
        for r in rows[1:]:
            get = lambda k: r[ix[k]] if k in ix and ix[k] < len(r) else None  # noqa: E731
            ts = parse_time(get("time"))
            act = str(get("activity") or "").strip()
            if ts is None or not act:
                skipped += 1
                continue
            cases.setdefault(str(get("case")).strip(), []).append((ts, act, str(get("resource") or "").strip()))
    for k in cases:
        cases[k].sort(key=lambda e: e[0])
    return {"file": path.name, "columns": cols, "cases": cases, "events": sum(len(v) for v in cases.values()), "skipped": skipped}


def eventlogs(ctx: wb.Ctx) -> list[dict]:
    out = []
    for f in ctx.files((".csv", ".tsv", ".xlsx", ".xes", ".log")):
        if f["name"].endswith(".xlsx.csv"):
            continue
        try:
            lg = read_eventlog(ctx.dir / "data" / f["name"])
        except Exception:  # noqa: BLE001 - not an event log after all
            lg = None
        if lg and lg["events"]:
            out.append(lg)
    return out


def dfg(cases: dict) -> dict:
    """Directly-follows counts {(a, b): n}, with "▶" before the first activity and "■" after the last."""
    out: dict = {}
    for evs in cases.values():
        seq = ["▶"] + [e[1] for e in evs] + ["■"]
        for a, b in zip(seq, seq[1:]):
            out[(a, b)] = out.get((a, b), 0) + 1
    return out


def variants(cases: dict) -> list[dict]:
    v: dict = {}
    for cid, evs in cases.items():
        key = tuple(e[1] for e in evs)
        d = v.setdefault(key, {"path": list(key), "cases": 0, "ids": [], "durations": []})
        d["cases"] += 1
        d["ids"].append(cid)
        d["durations"].append(evs[-1][0] - evs[0][0] if len(evs) > 1 else 0.0)
    return sorted(v.values(), key=lambda x: (-x["cases"], x["path"]))


def name_key(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", norm(s)))


def mined_map(lg: dict, min_share: float = 0.05) -> dict:
    """The process an event log shows, as a map (rules first, no AI): one task per activity, the frequent
    directly-follows links, a decision after an activity with more than one frequent way on."""
    n_cases = len(lg["cases"]) or 1
    counts = dfg(lg["cases"])
    acts = sorted({a for (a, b) in counts for a in (a, b) if a not in ("▶", "■")})
    freq = {a: sum(1 for evs in lg["cases"].values() if any(e[1] == a for e in evs)) for a in acts}
    keep = {k: v for k, v in counts.items() if v / n_cases >= min_share}
    ids = {a: f"S{i + 2}" for i, a in enumerate(acts)}
    steps = [{"id": "S1", "name": "Start", "type": "start", "lane": "L1", "next": [], "cases": n_cases}]
    by = {"▶": steps[0]}
    for a in acts:
        st = {"id": ids[a], "name": a, "type": "task", "lane": "L1", "next": [], "cases": freq[a]}
        steps.append(st)
        by[a] = st
    end = {"id": f"S{len(acts) + 2}", "name": "End", "type": "end", "lane": "L1", "next": [], "cases": sum(v for (a, b), v in counts.items() if b == "■")}
    steps.append(end)
    by["■"] = end
    g = 0
    for src in ["▶"] + acts:
        outs = sorted([(b, v) for (a, b), v in keep.items() if a == src], key=lambda x: -x[1])
        if len(outs) > 1 and src != "▶":
            g += 1
            gw = {"id": f"G{g}", "name": f"After {src}?", "type": "gateway", "lane": "L1", "next": [{"to": by[b]["id"], "when": f"{b} ({v} cases)"} for b, v in outs], "cases": sum(v for _, v in outs)}
            steps.append(gw)
            by[src]["next"] = [{"to": gw["id"], "when": ""}]
        else:
            by[src]["next"] = [{"to": by[b]["id"], "when": f"{v} cases" if src == "▶" and len(outs) > 1 else ""} for b, v in outs]
    if len(steps[0]["next"]) > 1:                      # several first activities: a decision right after the start
        g += 1
        gw = {"id": f"G{g}", "name": "Which first?", "type": "gateway", "lane": "L1", "next": [dict(n, when=n["when"] or "first") for n in steps[0]["next"]], "cases": n_cases}
        steps.append(gw)
        steps[0]["next"] = [{"to": gw["id"], "when": ""}]
    resources = {}
    for evs in lg["cases"].values():
        for e in evs:
            if e[2]:
                resources.setdefault(e[1], set()).add(e[2])
    for s in steps:
        if s["name"] in resources:
            s["resources"] = sorted(resources[s["name"]])[:6]
    return {"name": Path(lg["file"]).stem, "lanes": [{"id": "L1", "name": "Everyone (from the log)", "kind": "person"}], "steps": steps,
            "acts": {a: freq[a] for a in acts}, "cases": n_cases}


def conformance(proc: dict, lg: dict) -> dict:
    """How well a map fits what the log shows: the share of the log's directly-follows moves the map allows (gateways
    collapsed), the activities the map leaves out and the steps the log never shows."""
    steps = {s["id"]: s for s in proc.get("steps") or []}
    names = {sid: name_key(s.get("name")) for sid, s in steps.items()}

    def succ_tasks(sid, seen=None):
        seen = seen or set()
        out = set()
        for n in steps.get(sid, {}).get("next") or []:
            t = steps.get(n["to"])
            if not t or n["to"] in seen:
                continue
            seen.add(n["to"])
            if t["type"] == "gateway":
                out |= succ_tasks(n["to"], seen)
            else:
                out.add("■" if t["type"] == "end" else names[n["to"]])
        return out
    allowed = set()
    for sid, s in steps.items():
        if s["type"] in ("gateway", "end"):
            continue
        src = "▶" if s["type"] == "start" else names[sid]
        for t in succ_tasks(sid):
            allowed.add((src, t))
    act_names = {name_key(a) for evs in lg["cases"].values() for _, a, _ in evs}
    map_names = {v for sid, v in names.items() if steps[sid]["type"] not in ("start", "end", "gateway")}
    moves = dfg({k: [(t, name_key(a), r) for t, a, r in v] for k, v in lg["cases"].items()})
    total = sum(moves.values()) or 1
    fit = sum(v for k, v in moves.items() if k in allowed)
    bad = sorted(((k, v) for k, v in moves.items() if k not in allowed), key=lambda kv: -kv[1])
    return {"fitness": round(fit / total, 3), "moves": total, "allowed": fit, "missing": sorted(act_names - map_names), "unseen": sorted(map_names - act_names),
            "not_allowed": [{"from": a, "to": b, "times": v} for (a, b), v in bad[:20]]}


# ------------------------------------------------------------------ small things every pack needs

def user_name(uid: str | None) -> str:
    return (db.user(uid or "") or {}).get("name") or (uid or "—")


def when(t: float | None) -> str:
    return time.strftime("%d %b %Y %H:%M UTC", time.gmtime(t)) if t else "—"


def visible_items(u: dict, rows: list[dict], key: str = "item") -> list[dict]:
    ids = [r[key] for r in rows if r.get(key)]
    vis = auth.access_map(u, ids)
    return [r for r in rows if not r.get(key) or r[key] in vis]


def csv_text(columns: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    w.writerows(rows)
    return buf.getvalue()


def esc(s) -> str:
    return html.escape(str(s or ""))


def tracker_connection(ctx: wb.Ctx, kinds: tuple) -> dict | None:
    return next((c for c in ctx.connections() if c["kind"] in kinds), None)
