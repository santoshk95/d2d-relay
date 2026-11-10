"""`genbi read <path>` — what an attachment says, as text the agent can reason over (build-plan v2, P10: Start from an
idea or a plan; P11 reuses the same readers for RFP packs).

One reader per kind of file, every one standard library or a small pure-Python package (python-docx, openpyxl,
python-pptx, pypdf); video frames need ffmpeg in the image (the agent image has it; without it the note says so).

  docx        -> Markdown: headings, paragraphs, lists, tables
  xlsx / csv  -> a column profile per sheet (type, blanks, distinct, examples) + sample rows
  pptx        -> the texts of every slide (title, body, notes)
  pdf         -> the text of every page (the agent also Reads the file itself for the visual)
  png / jpg / webp -> size and dimensions (the agent Reads the image to look at it)
  mp4 / webm / mov -> key frames (ffmpeg) as JPEGs the agent can Read, plus the duration (ffprobe)
  mp3 / wav / m4a  -> metadata only; transcripts need a speech model (planned)
  txt / md / json / yaml -> the text as it is

`read(path)` returns a dict and writes it next to the file in `.read/<name>.json`, so the web app can show the same
extraction (text, frames, profile) on the Start page without running anything twice. `report(info)` is the text the
CLI prints for the agent.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path

KINDS = {"video": {".mp4", ".webm", ".mov"}, "audio": {".mp3", ".wav", ".m4a"}, "image": {".png", ".jpg", ".jpeg", ".webp"},
         "pdf": {".pdf"}, "doc": {".docx"}, "sheet": {".xlsx", ".csv"}, "deck": {".pptx"}, "text": {".txt", ".md", ".json", ".yaml", ".yml"}}
EXTENSIONS = {e for s in KINDS.values() for e in s}
MAX_FRAMES = 12
MAX_TEXT = 60_000            # characters kept in the cache and printed (the rest is counted, not lost: the file stays)
SAMPLE_ROWS = 5
CACHE_DIR = ".read"


class ReadError(Exception):
    pass


def kind_of(path: Path | str) -> str | None:
    ext = Path(path).suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), None)


def cache_path(path: Path) -> Path:
    return path.parent / CACHE_DIR / (path.name + ".json")


def cached(path: Path) -> dict | None:
    p = cache_path(Path(path))
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read(path: Path | str, write_cache: bool = True) -> dict:
    """Read one attachment; the dict has kind, name, bytes, text (what the agent reasons over), plus kind-specific
    parts (pages, sheets, slides, frames, meta) and a `note` where something could not be done."""
    path = Path(path)
    if not path.is_file():
        raise ReadError(f"{path} is not a file")
    kind = kind_of(path)
    if not kind:
        raise ReadError(f"{path.name}: not a kind of file Relay reads ({', '.join(sorted(EXTENSIONS))})")
    info = {"kind": kind, "name": path.name, "bytes": path.stat().st_size, "read_at": time.time(), "text": "", "note": ""}
    try:
        info.update(_READERS[kind](path))
    except ReadError:
        raise
    except Exception as e:  # noqa: BLE001 - a broken file is reported, never a crash in the agent's shell
        info["note"] = f"could not be read: {str(e).splitlines()[0][:300]}"
        info["error"] = True
    if len(info.get("text") or "") > MAX_TEXT:
        info["truncated"] = len(info["text"])
        info["text"] = info["text"][:MAX_TEXT] + f"\n\n… ({len(info['text']) - MAX_TEXT:,} more characters not shown)"
    if write_cache:
        try:
            cp = cache_path(path)
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return info


# ---------------------------------------------------------------- documents

def _docx(path: Path) -> dict:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(path))
    lines, headings, tables = [], [], 0
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            t = p.text.strip()
            if not t:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"Heading (\d)", style)
            if m or style == "Title":
                level = int(m.group(1)) + 1 if m else 1          # the Title is "#", Heading 1 is "##", …
                headings.append(t)
                lines.append("#" * min(level, 5) + " " + t)
            elif "List" in style:
                lines.append("- " + t)
            else:
                lines.append(t)
        elif tag == "tbl":
            tables += 1
            rows = [[c.text.strip().replace("\n", " ") for c in r.cells] for r in Table(child, d).rows]
            if rows:
                lines.append("")
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("|" + "---|" * len(rows[0]))
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                lines.append("")
    text = "\n".join(lines)
    return {"text": text, "headings": headings, "tables": tables, "paragraphs": sum(1 for l in lines if l and not l.startswith(("|", "#"))),
            "pages": None, "meta": {"words": len(text.split())}}


def _pdf(path: Path) -> dict:
    from pypdf import PdfReader
    r = PdfReader(str(path))
    pages = []
    for i, p in enumerate(r.pages, 1):
        try:
            t = (p.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            t = ""
        pages.append({"page": i, "text": t})
    text = "\n\n".join(f"--- page {p['page']} ---\n{p['text']}" for p in pages)
    scanned = sum(1 for p in pages if not p["text"])
    note = (f"{scanned} of {len(pages)} page(s) have no text layer (scanned): Read the PDF itself to look at them" if scanned else
            "also Read the file itself for layout, tables and figures")
    return {"text": text, "pages": len(pages), "page_texts": pages, "note": note, "meta": {"words": len(text.split())}}


def _pptx(path: Path) -> dict:
    from pptx import Presentation
    prs = Presentation(str(path))
    slides = []
    for i, s in enumerate(prs.slides, 1):
        title = s.shapes.title.text.strip() if s.shapes.title is not None and s.shapes.title.has_text_frame else ""
        texts = []
        for sh in s.shapes:
            if sh.has_text_frame:
                t = sh.text_frame.text.strip()
                if t and t != title:
                    texts.append(t)
            if getattr(sh, "has_table", False) and sh.has_table:
                for r in sh.table.rows:
                    texts.append(" | ".join(c.text.strip() for c in r.cells))
        notes = s.notes_slide.notes_text_frame.text.strip() if s.has_notes_slide and s.notes_slide.notes_text_frame is not None else ""
        slides.append({"slide": i, "title": title, "text": "\n".join(texts), "notes": notes})
    text = "\n\n".join(f"--- slide {x['slide']}: {x['title']} ---\n{x['text']}" + (f"\n[notes] {x['notes']}" if x["notes"] else "") for x in slides)
    return {"text": text, "slides": slides, "pages": len(slides), "meta": {"words": len(text.split())}}


# ---------------------------------------------------------------- sheets

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
NUM_RE = re.compile(r"^-?[\d,]+(\.\d+)?$|^-?\d+(\.\d+)?e-?\d+$", re.I)


def _guess(v) -> str:
    if v is None or v == "":
        return "blank"
    if isinstance(v, bool):
        return "text"
    if isinstance(v, (int, float)):
        return "number"
    if hasattr(v, "isoformat"):
        return "date"
    s = str(v).strip()
    if NUM_RE.match(s.replace(" ", "")):
        return "number"
    if DATE_RE.match(s):
        return "date"
    return "text"


def _profile(name: str, header: list, rows: list[list]) -> dict:
    cols = []
    for i, h in enumerate(header):
        vals = [r[i] if i < len(r) else None for r in rows]
        kinds = {}
        for v in vals:
            kinds[_guess(v)] = kinds.get(_guess(v), 0) + 1
        blanks = kinds.pop("blank", 0)
        typ = max(kinds, key=kinds.get) if kinds else "blank"
        present = [v for v in vals if v is not None and v != ""]
        distinct = {str(v) for v in present}
        examples = []
        for v in present:
            s = str(v)[:60]
            if s not in examples:
                examples.append(s)
            if len(examples) >= 3:
                break
        cols.append({"column": str(h), "type": typ, "blanks": blanks, "distinct": len(distinct), "examples": examples})
    return {"sheet": name, "rows": len(rows), "columns": cols,
            "sample": [[("" if v is None else str(v))[:80] for v in r[:len(header)]] for r in rows[:SAMPLE_ROWS]]}


def _sheet_text(p: dict) -> str:
    head = f"Sheet {p['sheet']}: {p['rows']:,} rows × {len(p['columns'])} columns"
    cols = "\n".join(f"- {c['column']} ({c['type']}; {c['distinct']:,} distinct, {c['blanks']:,} blank)"
                     + (f": e.g. {', '.join(c['examples'])}" if c["examples"] else "") for c in p["columns"])
    sample = "\n".join("| " + " | ".join(r) + " |" for r in p["sample"])
    return f"{head}\n{cols}\n\nFirst rows:\n| " + " | ".join(c["column"] for c in p["columns"]) + " |\n" + sample


def _xlsx(path: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            sheets.append({"sheet": ws.title, "rows": 0, "columns": [], "sample": []})
            continue
        header = [str(h) if h is not None else f"column_{i + 1}" for i, h in enumerate(header)]
        data = [list(r) for r in rows if any(v is not None and v != "" for v in r)]
        sheets.append(_profile(ws.title, header, data))
    wb.close()
    return {"text": "\n\n".join(_sheet_text(s) for s in sheets), "sheets": sheets, "rows": sum(s["rows"] for s in sheets)}


def _csv(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
        rd = csv.reader(fh)
        header = next(rd, None) or []
        data = [r for r in rd if any(v.strip() for v in r)]
    p = _profile(path.stem, [h or f"column_{i + 1}" for i, h in enumerate(header)], data)
    return {"text": _sheet_text(p), "sheets": [p], "rows": p["rows"]}


def _sheet(path: Path) -> dict:
    return _csv(path) if path.suffix.lower() == ".csv" else _xlsx(path)


# ---------------------------------------------------------------- images, video, audio

def image_size(path: Path) -> tuple[int, int] | None:
    """Width × height from the file header (PNG, JPEG, WebP) without an imaging library."""
    with path.open("rb") as f:
        head = f.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return w, h
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            f.seek(12)
            chunk = f.read(18)
            if chunk[:4] == b"VP8X":
                return 1 + int.from_bytes(chunk[12:15], "little"), 1 + int.from_bytes(chunk[15:18], "little")
            if chunk[:4] == b"VP8L":
                b = chunk[9:13]
                return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            if chunk[:4] == b"VP8 ":
                return int.from_bytes(chunk[14:16], "little") & 0x3FFF, int.from_bytes(chunk[16:18], "little") & 0x3FFF
            return None
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                if marker[1] in (0xC0, 0xC1, 0xC2):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return w, h
                size = struct.unpack(">H", f.read(2))[0]
                f.seek(size - 2, 1)
    return None


def _image(path: Path) -> dict:
    size = image_size(path)
    dims = f"{size[0]} × {size[1]} px" if size else "size unknown"
    return {"text": f"Image {path.name}: {dims}. Look at it with Read to read what it shows (fields, tables, screens).",
            "width": size[0] if size else None, "height": size[1] if size else None,
            "note": "Read the image to see it; this command only reports its size"}


def ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _probe(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    try:
        out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=60).stdout
        j = json.loads(out or "{}")
        meta = {"duration_s": round(float(j.get("format", {}).get("duration") or 0), 1)}
        for s in j.get("streams") or []:
            if s.get("codec_type") == "video" and s.get("width"):
                meta.update(width=s["width"], height=s["height"])
        return meta
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _video(path: Path) -> dict:
    meta = _probe(path)
    exe = ffmpeg()
    if not exe:
        return {"text": f"Video {path.name} ({path.stat().st_size:,} bytes). Frames could not be extracted here: ffmpeg is not installed in "
                        "this image, so the agent reads it when it runs.", "frames": [], "meta": meta,
                "note": "frames are extracted when the agent reads it (ffmpeg is in the agent image)"}
    out_dir = path.parent / CACHE_DIR / (path.name + ".frames")
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = meta.get("duration_s") or 0
    every = max(1.0, dur / MAX_FRAMES) if dur else 2.0
    try:
        subprocess.run([exe, "-v", "error", "-i", str(path), "-vf", f"fps=1/{every:g},scale='min(1280,iw)':-2", "-frames:v", str(MAX_FRAMES),
                        "-q:v", "4", str(out_dir / "frame-%02d.jpg")], capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return {"text": f"Video {path.name}: frames could not be extracted ({e.__class__.__name__}).", "frames": [], "meta": meta,
                "note": "frame extraction failed"}
    frames = sorted(f.name for f in out_dir.glob("frame-*.jpg"))
    rel = [f"{CACHE_DIR}/{path.name}.frames/{f}" for f in frames]
    text = (f"Video {path.name}: {dur:g} s" + (f", {meta.get('width')} × {meta.get('height')} px" if meta.get("width") else "")
            + f". {len(frames)} key frame(s), one every {every:g} s, saved as JPEG next to it — Read each to see the screens and clicks:\n"
            + "\n".join(f"- {path.parent / r}" for r in rel))
    return {"text": text, "frames": rel, "every_s": every, "meta": meta,
            "note": "" if frames else "no frames were produced (empty or unreadable video)"}


def _audio(path: Path) -> dict:
    meta = _probe(path)
    return {"text": f"Audio {path.name} ({path.stat().st_size:,} bytes" + (f", {meta['duration_s']:g} s" if meta.get("duration_s") else "")
                    + "). No transcript: transcripts need a speech model (planned). Use the brief and the other attachments for what was said.",
            "meta": meta, "note": "transcripts need a speech model (planned)"}


def _text(path: Path) -> dict:
    t = path.read_text(encoding="utf-8", errors="replace")
    return {"text": t, "meta": {"words": len(t.split()), "lines": t.count("\n") + 1}}


_READERS = {"doc": _docx, "pdf": _pdf, "deck": _pptx, "sheet": _sheet, "image": _image, "video": _video, "audio": _audio, "text": _text}


# ---------------------------------------------------------------- the text for the agent

def report(info: dict) -> str:
    head = f"{info['name']} — {info['kind']}, {info['bytes']:,} bytes"
    if info.get("pages"):
        head += f", {info['pages']} page(s)" if info["kind"] != "deck" else f", {info['pages']} slide(s)"
    if info.get("rows") is not None and info["kind"] == "sheet":
        head += f", {info['rows']:,} rows in {len(info.get('sheets') or [])} sheet(s)"
    out = [head]
    if info.get("note"):
        out.append(f"note: {info['note']}")
    out.append("")
    out.append(info.get("text") or "(no text)")
    return "\n".join(out)


def read_all(folder: Path | str) -> list[dict]:
    """Every attachment in a folder (sorted), each read and cached."""
    folder = Path(folder)
    out = []
    for f in sorted(p for p in folder.iterdir() if p.is_file() and kind_of(p)):
        try:
            out.append(read(f))
        except ReadError as e:
            out.append({"kind": kind_of(f), "name": f.name, "bytes": f.stat().st_size, "text": "", "note": str(e), "error": True})
    return out


def as_markdown(infos: list[dict]) -> str:
    return "\n\n".join(f"## {i['name']}\n\n{report(i)}" for i in infos)


if __name__ == "__main__":
    import sys
    for a in sys.argv[1:]:
        print(report(read(a)))
