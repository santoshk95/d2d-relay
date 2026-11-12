"""Mail-rule file drops - a mailbox folder read over IMAP (imaplib, standard library) or the mock lab's HTTP listing;
each rule you describe (folder, subject match, from / to systems) becomes an integration, each day's matching
messages one run whose volume is the number of attachments."""
from __future__ import annotations

import collections
import email
import email.utils
import imaplib
import json
import time

from . import base

KIND, LABEL, GROUP = "mail", "Mail file drops", "Files & mail"
AUTH = "mailbox user (IMAP, read-only)"
DOCS = "IMAP folder listing (imaplib) or the mock lab's HTTP listing; rules described in the source settings"
CONFIG = [{"name": "url", "label": "Mailbox", "hint": "imaps://host or the mock lab's http://... listing", "required": True},
          {"name": "rules", "label": "Mail rules (JSON)", "hint": '[{"name": "Supplier statements inbox -> finance share", "folder": "INBOX/Suppliers", "subject_match": "statement", "from_system": "Finance inbox", "to_system": "Finance share", "schedule": "Daily"}]', "required": True}]
SECRETS = [{"name": "username", "label": "User"}, {"name": "password", "label": "Password or app password"}]


def _messages(url: str, folder: str, secrets: dict, since: float) -> list[dict]:
    if url.startswith("http"):
        c = base.Client(url, base.Client.basic(secrets.get("username") or "", secrets.get("password") or "") if secrets.get("username") else None)
        return c.get("/messages", {"folder": folder}).get("messages") or []
    host = url.split("://", 1)[-1].split("/")[0]
    m = imaplib.IMAP4_SSL(host.split(":")[0], int(host.split(":")[1]) if ":" in host else 993)
    out = []
    try:
        m.login(secrets.get("username") or "", secrets.get("password") or "")
        m.select(folder, readonly=True)
        _, data = m.search(None, "SINCE", time.strftime("%d-%b-%Y", time.gmtime(since)))
        for num in (data[0].split() if data and data[0] else [])[-500:]:
            _, raw = m.fetch(num, "(BODY.PEEK[HEADER] BODYSTRUCTURE)")
            msg = email.message_from_bytes(raw[0][1]) if raw and raw[0] else None
            if msg is None:
                continue
            att = sum(1 for part in msg.walk() if part.get_filename()) if msg.is_multipart() else 0
            out.append({"subject": msg.get("Subject", ""), "from": msg.get("From", ""), "date": email.utils.parsedate_to_datetime(msg["Date"]).timestamp() if msg.get("Date") else None, "attachments": [{"name": "attachment"}] * att})
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    rules = cfg.get("rules") or []
    if isinstance(rules, str):
        rules = json.loads(rules or "[]")
    out = base.empty()
    systems = {}
    for r in rules:
        for s in (r.get("from_system"), r.get("to_system")):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        msgs = [x for x in _messages(cfg["url"], r.get("folder") or "INBOX", secrets, now - 42 * 86400) if (r.get("subject_match") or "").lower() in (x.get("subject") or "").lower()]
        rid = f"{r.get('folder')}:{r.get('subject_match')}"
        out["integrations"].append({"ext_id": rid, "name": r.get("name") or f"{r.get('from_system')} {r.get('to_system')}", "kind": "File", "via": "Mail rule", "from_system": r.get("from_system"), "to_system": r.get("to_system"),
                                    "schedule": r.get("schedule") or "On event", "owner": r.get("owner"), "properties": {"folder": r.get("folder"), "subject_match": r.get("subject_match"), "messages": len(msgs)}})
        per_day = collections.defaultdict(list)
        for x in msgs:
            t = base.ts(x.get("date"))
            if t:
                per_day[int(t // 86400)].append(x)
        for day, items in sorted(per_day.items()):
            out["runs"].append({"integration": rid, "ext_id": f"{rid}:{day}", "started": day * 86400 + 8 * 3600, "ended": day * 86400 + 8 * 3600, "status": "success", "duration_s": None,
                                "volume": sum(len(x.get("attachments") or []) for x in items), "error": None})
    out["systems"] = list(systems.values())
    return out
