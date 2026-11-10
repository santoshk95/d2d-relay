"""The document index of Document & knowledge assistants (registry id `assist`): documents read into passages with
their page (or section), kept per corpus in the tenant's own database, searched with full-text search — SQLite FTS5,
or PostgreSQL's text search (to_tsvector / to_tsquery, ranked by ts_rank) — the way the RFP library searches, with no
vector database. An answer is made of sentences taken word for word from the passages found, each with its citation;
when nothing in the documents answers the question, the answer says so. Nothing is invented."""
from __future__ import annotations

import hashlib
import json
import re
import secrets as _secrets
import time
from pathlib import Path

from .. import db

STOP = set("the a an and or of to in on for with by at from is are was were be been being this that these those it its as what which who whom whose when where why how "
           "do does did can could should would may might must shall will not no yes our your their there here about into than then so such any all each per via "
           "please tell me us we you they he she him her them i say says said".split())
DOC_EXT = (".pdf", ".docx", ".txt", ".md", ".pptx")
PASSAGE_CHARS = 900

db.register_schema("""
CREATE TABLE IF NOT EXISTS assist_chunks (
  id TEXT PRIMARY KEY, corpus TEXT NOT NULL, doc TEXT NOT NULL, title TEXT, page INTEGER, section TEXT, text TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS assist_chunks_corpus ON assist_chunks (corpus);
""")
if db.BACKEND == "sqlite":
    db.register_schema("CREATE VIRTUAL TABLE IF NOT EXISTS assist_chunks_fts USING fts5(id UNINDEXED, corpus UNINDEXED, title, text);")
else:
    db.register_schema("CREATE INDEX IF NOT EXISTS assist_chunks_tsv ON assist_chunks USING GIN (to_tsvector('english', text));")


# ------------------------------------------------------------------ reading documents into passages

def _split(text: str, page: int | None, section: str | None) -> list[dict]:
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    out, buf = [], ""
    for para in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        if len(buf) + len(para) > PASSAGE_CHARS and buf:
            out.append({"page": page, "section": section, "text": buf.strip()})
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        out.append({"page": page, "section": section, "text": buf.strip()})
    return out


def read(path: Path) -> tuple[str, list[dict]]:
    """(title, passages) of one document: PDF by page, Word by heading, PowerPoint by slide, text and Markdown by
    heading. Raises ValueError with the reason when it cannot be read."""
    ext = path.suffix.lower()
    title, out = path.stem.replace("_", " ").replace("-", " ").strip(), []
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(path))
        for i, pg in enumerate(r.pages, 1):
            out += _split(pg.extract_text() or "", i, None)
        meta = (r.metadata or {}).get("/Title") if r.metadata else None
        title = str(meta).strip() if meta else title
    elif ext == ".docx":
        import docx
        d = docx.Document(str(path))
        sec, buf, n = None, [], 0
        for p in d.paragraphs:
            if (p.style.name or "").lower().startswith(("heading", "title")) and p.text.strip():
                if buf:
                    out += _split("\n\n".join(buf), None, sec)
                sec, buf = p.text.strip(), []
                n += 1
                if (p.style.name or "").lower() == "title" or (n == 1 and title == path.stem):
                    title = p.text.strip()
            elif p.text.strip():
                buf.append(p.text.strip())
        if buf:
            out += _split("\n\n".join(buf), None, sec)
    elif ext == ".pptx":
        from pptx import Presentation
        for i, s in enumerate(Presentation(str(path)).slides, 1):
            txt = "\n\n".join(sh.text_frame.text for sh in s.shapes if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip())
            out += _split(txt, i, None)
    elif ext in (".txt", ".md"):
        sec, buf = None, []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^#{1,6}\s+(.*)", line)
            if m:
                if buf:
                    out += _split("\n".join(buf), None, sec)
                sec, buf = m.group(1).strip(), []
                if title == path.stem.replace("_", " ").replace("-", " ").strip() and line.startswith("# "):
                    title = sec
            else:
                buf.append(line)
        if buf:
            out += _split("\n".join(buf), None, sec)
    else:
        raise ValueError(f"{path.name}: this kind of document is not read here")
    out = [p for p in out if len(p["text"]) >= 20]
    if not out:
        raise ValueError(f"{path.name}: no text could be read (a scanned PDF needs a text layer)")
    return title[:200], out


def fingerprint(passages: list[dict]) -> str:
    return hashlib.sha1("\n".join(p["text"] for p in passages).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ the index (one corpus = one set of rows)

def index(corpus: str, docs: list[dict]) -> int:
    """Replace a corpus's passages with these documents' ({"name", "title", "passages"})."""
    drop(corpus)
    now, n = time.time(), 0
    with db.transaction():
        for d in docs:
            for p in d["passages"]:
                cid = "ch-" + _secrets.token_hex(6)
                db.run("INSERT INTO assist_chunks (id, corpus, doc, title, page, section, text, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (cid, corpus, d["name"], d.get("title"), p.get("page"), p.get("section"), p["text"], now))
                if db.BACKEND == "sqlite":
                    db.run("INSERT INTO assist_chunks_fts (id, corpus, title, text) VALUES (?, ?, ?, ?)", (cid, corpus, d.get("title") or "", p["text"]))
                n += 1
    return n


def drop(corpus: str) -> None:
    db.run("DELETE FROM assist_chunks WHERE corpus = ?", (corpus,))
    if db.BACKEND == "sqlite":
        db.run("DELETE FROM assist_chunks_fts WHERE corpus = ?", (corpus,))


def count(corpus: str) -> int:
    return int((db.one("SELECT COUNT(*) AS n FROM assist_chunks WHERE corpus = ?", (corpus,)) or {}).get("n") or 0)


def terms(text: str) -> list[str]:
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}", (text or "").lower()):
        w = w.strip("-")
        if len(w) >= 3 and w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:16]


def search(corpus: str, question: str, k: int = 5) -> list[dict]:
    """The k passages that match the question best (full-text search, any of its words, best first)."""
    ts = terms(question)
    if not ts:
        return []
    if db.BACKEND == "sqlite":
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in ts)
        rows = db.q("SELECT c.* FROM assist_chunks_fts f JOIN assist_chunks c ON c.id = f.id WHERE assist_chunks_fts MATCH ? AND f.corpus = ? ORDER BY bm25(assist_chunks_fts) LIMIT ?",
                    (match, corpus, k))
    else:
        q = " | ".join(re.sub(r"[^a-z0-9]", "", t) for t in ts if re.sub(r"[^a-z0-9]", "", t))
        rows = db.q("SELECT c.*, ts_rank(to_tsvector('english', c.text), to_tsquery('english', ?)) AS rank FROM assist_chunks c "
                    "WHERE c.corpus = ? AND to_tsvector('english', c.text) @@ to_tsquery('english', ?) ORDER BY rank DESC, c.id LIMIT ?", (q, corpus, q, k)) if q else []
    return [{k_: r.get(k_) for k_ in ("id", "doc", "title", "page", "section", "text")} for r in rows]


def _stem(w: str) -> str:
    return w[:5]


def cite(p: dict) -> str:
    where = f"page {p['page']}" if p.get("page") else (f"“{p['section']}”" if p.get("section") else "")
    return f"{p.get('title') or p['doc']}" + (f", {where}" if where else "")


def answer(corpus: str, question: str, k: int = 5, need: float = 0.5) -> dict:
    """An extractive answer: the sentences of the passages found that share the most of the question's words, each
    with its citation; a refusal when no sentence covers enough of the question (`need`: the share of its words)."""
    ts = terms(question)
    passages = search(corpus, question, k)
    stems = {_stem(t) for t in ts}
    scored = []
    for p in passages:
        for s in re.split(r"(?<=[.!?])\s+|\n+", p["text"]):
            s = s.strip()
            if len(s) < 15:
                continue
            ws = {_stem(w) for w in terms(s)}
            hit = len(stems & ws)
            if hit:
                scored.append((hit, -len(s), s, p))
    scored.sort(key=lambda x: (-x[0], x[1]))
    if not scored or scored[0][0] < max(1, int(round(need * len(stems)))):
        return {"answered": False, "answer": "The documents in this assistant do not answer that question.", "citations": [], "passages": passages}
    pick, used = [], set()
    for hit, _, s, p in scored:
        if s in used or hit < max(1, scored[0][0] - 1):
            continue
        used.add(s)
        pick.append({"sentence": s, "passage": p["id"], "doc": p["doc"], "page": p.get("page"), "section": p.get("section"), "cite": cite(p)})
        if len(pick) == 2:
            break
    return {"answered": True, "answer": " ".join(f"{x['sentence']} [{i + 1}]" for i, x in enumerate(pick)), "citations": pick, "passages": passages}


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text or ""))


def grounded(answer_text: str, cited: list[dict]) -> list[str]:
    """What in an answer is not in the passages it cites: numbers first (the commonest invention)."""
    body = " ".join(p["text"] for p in cited)
    plain = re.sub(r"\[\d+\]", "", answer_text or "")                  # citation markers [1] are not claims
    return [f"the number {n} is not in the cited passages" for n in sorted(numbers(plain) - numbers(body))]


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
