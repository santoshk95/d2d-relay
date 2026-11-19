"""Test stack only: item 81 (the user, 2026-11-19: "make the intial configuration and business/org context mandate ... it
must be a guided way"). An organisation's owners set it up once, step by step, before its first dashboard
(webapp/app/orgsetup.py, GET /api/org/profile and its steps; the screens in webapp/static/js/47-setup.js, #/setup):
- a new organisation: needed, Your business next, what the form offers (the 13 industries, currencies, the five
  calendars, audiences), 5 Relay Model runs a day, an empty dictionary; /api/me org.setup; no session 401;
- until it is finished New dashboard, a DAWB import and a new Semantic Review are refused (400, before the brand's rule,
  nothing made or charged) in the owner's words, or a member's; Finish is refused too; a member reads it and changes
  nothing (403 for every step);
- Your business: its rules (an unknown industry, a short or long description, a currency, the calendar); general
  applies no pack, a new industry applies its pack (the dictionary's counts grow) and drops an older proposal, the same
  industry again does not apply it again;
- Prepare with Relay Model: without the AI on the stack the run ends "error" in plain words within a minute (with a
  Claude sign-in or an API key in tests/stack/.env: its checked proposal within 10 minutes); the industry standard (no
  AI): the understanding in the context's own words, the pack's KPIs with the calendar in their time basis and the
  currency, the pack's terms with the naming conventions' abbreviations as synonyms;
- Understanding accepted as edited; KPI standard (added, kept, replaced, skipped with why: one name, one KPI);
  Ontology and dictionaries (the abbreviations reach the business terms and tag a column);
- Finish refused while a step or the brand is missing (400 naming it), then done: setup_done, audited, the people
  told; afterwards New dashboard, a DAWB import and a Semantic Review start; ontology.json and ontology.md of a
  dashboard carry the accepted understanding ("Your organisation");
- not blocked: an organisation from before (a dashboard of its own; or the old first-time setup and a brand), which
  can still add its business context; a personal workspace;
- every text the setup API returns is plain keyboard characters and never names Claude or Atlas;
- in Chromium: #/setup for an owner at 1280 and 375 px (the seven steps listed, one step on the screen, no script
  errors, no null or undefined, nothing wider than the screen) and a member's read-only view. Screenshots: item81-*.png.
Its people sign in from 198.18.81.x.
python -I -X utf8 item81_check.py <public> <admin>"""
import itertools
import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402
from review_models import SALES  # noqa: E402

c._ips = (f"198.18.81.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
TYPO = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190, 0x2194))
NEVER = ("claude", "anthropic", "atlas", "this pc")          # never in a text a person reads (the AI is "Relay Model")
STEPS = ["Your business", "Prepare", "Understanding", "KPI standard", "Ontology and dictionaries", "Theme", "Check and finish"]
WRITES = [("PUT", "/api/org/profile/context"), ("POST", "/api/org/profile/generate"), ("POST", "/api/org/profile/standard"),
          ("PUT", "/api/org/profile/understanding"), ("POST", "/api/org/profile/kpis"), ("POST", "/api/org/profile/terms"),
          ("POST", "/api/org/profile/done")]
OWNER_SAYS = "Finish setting up your organisation first"
ORG, DOM = f"Fresh Basket {S}", f"freshbasket{S}.com"
ABOUT = ("Fresh Basket runs 120 neighbourhood grocery stores and a home delivery service in the Netherlands and Belgium, "
         "with its own brands in every aisle.")
ABOUT_SNIP = "neighbourhood grocery stores"
BRANDS, REGIONS = ["Fresh Basket", "Basket Express"], ["Netherlands", "Belgium"]
CALENDAR = {"kind": "4-4-5", "start_month": 2}
PRIORITIES = "Grow own brands sales. Cut shrink in the fresh departments. Keep every store in stock."
CONVENTIONS = "bnr = banner, dvsn = division, sls = sales"
ABBREVIATIONS = {"bnr": "banner", "dvsn": "division", "sls": "sales"}
SUMMARY_SNIP = "sells groceries in 120 stores"
SUMMARY = f"{ORG} {SUMMARY_SNIP} and online; the owner edited this line."
TEXTS: list[str] = []          # every answer of the setup API and every refusal (plain keyboard characters, none of NEVER)
MESSAGES: list[str] = []       # the refusals' and a failed run's own words (nor a queue)


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def api(p: c.Person, method: str, path: str, body=None) -> tuple[int, dict]:
    """A call whose answer is kept for the plain-words check: (status, the answer, or {"detail": it} when it is no dict)."""
    s, r = p.call(method, path, body if body is not None or method == "GET" else {})
    TEXTS.append(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
    if s >= 400:
        MESSAGES.append(str(detail(r)))
    return s, r if isinstance(r, dict) else {"detail": r}


def profile(p: c.Person) -> tuple[int, dict]:
    return api(p, "GET", "/api/org/profile")


def said(s: int, r) -> tuple[int, dict]:
    """A New dashboard's or an import's answer: a refusal's words are kept for the plain-words check."""
    if s >= 400:
        MESSAGES.append(str(detail(r)))
        TEXTS.append(str(detail(r)))
    return s, r if isinstance(r, dict) else {"detail": r}


def review(p: c.Person) -> tuple[int, dict]:
    """A new Semantic Review of one small model (item 55's model.bim)."""
    boundary = "----sr81" + str(time.time_ns())
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\nSetup check {S}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="sales.bim"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode() + json.dumps(SALES).encode() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(p.base + "/api/semreview/runs", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with p.http.open(req, timeout=120) as r:
            raw, s = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, s = e.read(), e.code
    try:
        out = json.loads(raw or b"null")
    except ValueError:
        out = raw.decode("utf-8", "replace")
    return said(s, out)


def org_of(p: c.Person) -> dict:
    me = p.get("/api/me")[1]
    return (me.get("org") or {}) if isinstance(me, dict) else {}


def steps_of(p: dict) -> dict:
    return p.get("steps") if isinstance(p.get("steps"), dict) else {}


def dic_of(p: dict) -> dict:
    return p.get("dictionary") if isinstance(p.get("dictionary"), dict) else {}


def me_setup(p: c.Person) -> dict:
    """/api/me org.setup: {"status", "done", "can_edit", "next"}."""
    s = org_of(p).get("setup")
    return s if isinstance(s, dict) else {}


def note_items(p: c.Person) -> list[dict]:
    s, n = p.get("/api/notifications")
    return [x for x in ((n or {}).get("items") or []) if isinstance(x, dict)] if isinstance(n, dict) else []


def audit_rows(tid: str) -> int:
    """The organisation's audit rows: its workspace's own and the platform's about it (-1: could not be read)."""
    a = g.sql(f'SELECT count(*) FROM "t_{tid.replace("-", "_")}".audit')
    b = g.sql(f"SELECT count(*) FROM relay.tn_audit WHERE tenant_id = '{tid}'")
    return int(a) + int(b) if a.isdigit() and b.isdigit() else -1


def unplain(text: str) -> list[str]:
    """Typographic characters, and names a person must never read, in a text."""
    low = text.lower()
    return sorted(set(ch for ch in text if ch in TYPO)) + [w for w in NEVER if w in low]


def where_unplain(texts: list[str]) -> list[str]:
    """Where the first few unplain texts are, for the failure's detail."""
    out = []
    for t in texts:
        low = t.lower()
        at = min([i for i in (t.find(ch) for ch in TYPO) if i >= 0] + [i for i in (low.find(w) for w in NEVER) if i >= 0] or [-1])
        if at >= 0:
            out.append(t[max(0, at - 80):at + 80])
        if len(out) >= 3:
            break
    return out


def stack_has_ai() -> bool | None:
    """Whether the test stack can reach the AI: tests/stack/.env (stack.sh) mounts a Claude sign-in (external volume) or
    sets an API key. None when there is no such file. Only those two settings are read."""
    try:
        with open(os.path.join(HERE, "..", "stack", ".env"), encoding="utf-8") as f:
            env = dict(x.strip().split("=", 1) for x in f if "=" in x and not x.lstrip().startswith("#"))
    except OSError:
        return None
    return env.get("TEST_CLAUDE_EXTERNAL", "").strip() == "true" or bool(env.get("TEST_ANTHROPIC_API_KEY", "").strip())


def wait_job(p: c.Person, seconds: int) -> dict:
    """The profile once Relay Model's run has ended (done or error), or after `seconds`."""
    end = time.time() + seconds
    while True:
        s, prof = p.get("/api/org/profile")
        prof = prof if isinstance(prof, dict) else {}
        if (prof.get("job") or {}).get("status") in ("done", "error") or time.time() > end:
            return profile(p)[1]
        time.sleep(2)


def shape(prop: dict) -> list[str]:
    """What is wrong with a Relay Model proposal's shape (nothing: [])."""
    bad = []
    und = prop.get("understanding")
    if not isinstance(und, dict) or not str(und.get("summary") or "").strip():
        bad.append("no understanding with a summary")
    kpis, terms = prop.get("kpis"), prop.get("terms")
    if not isinstance(kpis, list) or not 1 <= len(kpis) <= 60:
        bad.append(f"KPIs: {len(kpis) if isinstance(kpis, list) else kpis!r} (1 to 60)")
    else:
        if not all(isinstance(k, dict) and str(k.get("name") or "").strip() and str(k.get("why") or "").strip() for k in kpis):
            bad.append("a KPI without its name or why")
        if not all(isinstance(k.get("from_pack"), (str, type(None))) for k in kpis if isinstance(k, dict)):
            bad.append("a KPI's from_pack is neither a pack KPI's name nor null")
        names = [str(k.get("name")).strip().lower() for k in kpis if isinstance(k, dict)]
        if len(set(names)) != len(names):
            bad.append("a KPI name twice")
    if not isinstance(terms, list) or len(terms) > 80:
        bad.append(f"terms: {len(terms) if isinstance(terms, list) else terms!r} (at most 80)")
    elif not all(isinstance(t, dict) and str(t.get("name") or "").strip() and t.get("kind") in ("measure", "key", "date", "attribute") for t in terms):
        bad.append("a term without its name or kind")
    if not isinstance(prop.get("abbreviations"), dict):
        bad.append("no abbreviations")
    return bad


def tags(p: c.Person, cols: list[tuple[str, str]]) -> dict:
    s, r = p.post("/api/ontology/match", {"columns": [{"name": n, "type": t} for n, t in cols]})
    return {x.get("name"): (x.get("tag") or {}).get("term") for x in (r or {}).get("columns", [])} if s == 200 and isinstance(r, dict) else {"status": s}


def browser(container: str, script: str, *args: str) -> dict:
    try:
        res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=480)
    except subprocess.TimeoutExpired:
        return {"run": "no answer in 8 minutes"}
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


# Chromium in the test web container: the owner on #/setup at 1280 and 375 px, then #/setup?step=context, kpis and terms
# (each step its own content only: the context's description in a field, the proposal's KPI names, its term names), and
# a member's #/setup at 1280 px (read only). Screenshots in /tmp, copied out by the suite.
PLAY = r"""
import json, re, sys
from playwright.sync_api import sync_playwright
owner, member, typo = sys.argv[1:4]
STEPS, KPI_MARKS, TERM_MARKS, SNIPS = (json.loads(x) for x in sys.argv[4:8])
URL = "http://127.0.0.1:8000/"
MAIN = "(document.querySelector('#main') || document.querySelector('main') || document.body)"
LISTED = ("(names) => { const m = " + MAIN + "; const t = (m.textContent + ' ' + [...m.querySelectorAll('[aria-label]')]"
          ".map(e => e.getAttribute('aria-label')).join(' ')).toLowerCase(); return names.filter(n => t.includes(n.toLowerCase())); }")
TEXT = "() => " + MAIN + ".innerText"
ANY = "(marks) => { const t = " + MAIN + ".innerText; return marks.some(x => t.includes(x)); }"
FIELD = ("(snip) => [...document.querySelectorAll('textarea, input')].some(e => (e.value || '').includes(snip)"
         " && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden')")
WIDE = "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
EDITABLE = ("() => { const m = " + MAIN + ", vis = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';"
            " return {fields: [...m.querySelectorAll('textarea, select, input:not([type=hidden])')].filter(e => vis(e) && !e.disabled && !e.readOnly).length,"
            " buttons: [...m.querySelectorAll('button')].filter(e => vis(e) && !e.disabled && /^(finish|accept|save|use the industry standard)/i.test(e.innerText.trim()))"
            ".map(e => e.innerText.trim())}; }")
STRAY = re.compile(r"\b(?:null|undefined|NaN)\b|\[object Object\]")
out = {}


def opened(b, cookie, w):
    ctx = b.new_context(viewport={"width": w, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:300]))
    page.on("response", lambda r: errs.append(f"{r.status} {r.url[-90:]}") if r.status >= 500 else None)
    return ctx, page, errs


def wait(page, js, arg, timeout=20000):
    try:
        page.wait_for_function(js, arg=arg, timeout=timeout)
        return True
    except Exception as e:  # noqa: BLE001 - the suite says what it saw
        return "no: " + str(e).splitlines()[0][:160]


with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    for w in (1280, 375):
        ctx, page, errs = opened(b, owner, w)
        res, texts = {"wide": {}}, []
        page.goto(URL + "#/setup")
        res["waited"] = wait(page, "(names) => (" + LISTED + ")(names).length === names.length", STEPS, 30000)
        page.wait_for_timeout(1500)
        res["listed"] = page.evaluate(LISTED, STEPS)
        t = page.evaluate(TEXT)
        res["shown"] = [n for n in STEPS if n.lower() in t.lower()]
        res["hash"] = page.evaluate("location.hash")
        res["text"] = t[:1500]
        texts.append(t)
        res["wide"]["setup"] = page.evaluate(WIDE)
        page.screenshot(path=f"/tmp/item81-setup-{w}.png", full_page=True)
        for step in ("context", "kpis", "terms"):
            page.goto(URL + "#/setup?step=" + step)
            res["waited_" + step] = (wait(page, "(snip) => (" + FIELD + ")(snip) || " + MAIN + ".innerText.includes(snip)", SNIPS[0])
                                     if step == "context" else wait(page, ANY, KPI_MARKS if step == "kpis" else TERM_MARKS))
            page.wait_for_timeout(800)
            t = page.evaluate(TEXT)
            texts.append(t)
            res[step] = {"field": page.evaluate(FIELD, SNIPS[0]), "about": SNIPS[0] in t, "kpis": [x for x in KPI_MARKS if x in t],
                         "terms": [x for x in TERM_MARKS if x in t], "hash": page.evaluate("location.hash"), "text": t[:600]}
            res["wide"][step] = page.evaluate(WIDE)
            if step == "kpis":
                page.screenshot(path=f"/tmp/item81-kpis-{w}.png", full_page=True)
        every = "\n".join(texts)
        res["stray"] = sorted(set(STRAY.findall(every)))
        res["typo"] = "".join(sorted(set(ch for ch in every if ch in typo)))
        res["errors"] = errs
        out[str(w)] = res
        ctx.close()
    ctx, page, errs = opened(b, member, 1280)
    page.goto(URL + "#/setup")
    m = {"waited": wait(page, "(s) => { const t = " + MAIN + ".innerText; return s.some(x => t.includes(x)) || /setting it up/i.test(t); }", SNIPS, 30000)}
    page.wait_for_timeout(1500)
    t = page.evaluate(TEXT)
    m.update({"text": t[:1500], "said": [x for x in SNIPS if x in t] + (["setting it up"] if re.search("setting it up", t, re.I) else []),
              "editable": page.evaluate(EDITABLE), "wide": page.evaluate(WIDE), "typo": "".join(sorted(set(ch for ch in t if ch in typo))),
              "stray": sorted(set(STRAY.findall(t))), "errors": errs})
    page.screenshot(path="/tmp/item81-member-1280.png", full_page=True)
    out["member"] = m
    ctx.close()
    b.close()
print(json.dumps(out))
"""


def main() -> None:
    admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
    owner, mem = c.Person(f"fay.owner@{DOM}"), c.Person(f"mo.member@{DOM}")
    s, r = owner.sign_in(ORG, "Fay Owner", brand=False)         # no brand and nothing set up: this suite walks both itself
    check("people: PASDACS creates a new organisation; its owner signs in (no brand yet)", s == 200, (s, r))
    s2, r2 = mem.sign_in(person="Mo Member")
    tid = org_of(owner).get("id")
    mo = org_of(mem)
    check("people: a colleague signs in, a member (not an owner)", s2 == 200 and tid and mo.get("id") == tid and mo.get("is_owner") is False,
          (s2, r2, mo.get("id"), tid))
    tid = str(tid)

    # ---------------------------------------------------------------- a new organisation
    section("a new organisation")
    s, p0 = profile(owner)
    check("new: needed, Your business next; nothing set yet, not from before, no brand; the owner may change it",
          s == 200 and p0.get("status") == "needed" and p0.get("next") == "context" and p0.get("can_edit") is True
          and p0.get("legacy") is False and not p0.get("context") and not p0.get("proposal") and not p0.get("job")
          and not p0.get("understanding") and not any(steps_of(p0).values()) and not p0.get("done") and p0.get("theme_ready") is False,
          (s, {k: p0.get(k) for k in ("status", "next", "can_edit", "legacy", "context", "proposal", "job", "understanding", "steps", "done",
                                      "theme_ready")}, detail(p0)))
    s, onto = owner.get("/api/ontology")
    packs = {x.get("id") for x in (onto.get("packs") or [])} if isinstance(onto, dict) else set()
    inds = [x for x in p0.get("industries") or [] if isinstance(x, dict)]
    cals = [x for x in p0.get("calendars") or [] if isinstance(x, dict)]
    dic = dic_of(p0)
    codes = re.findall(r'"([A-Z]{3})"', json.dumps(p0.get("currencies")))
    cur = "EUR" if "EUR" in codes or not codes else next((x for x in codes if x != "USD"), "USD")    # the context's currency
    check("new: the form offers the 13 industries (the packs), currencies (USD among them), the five calendars and audiences; 5 Relay "
          "Model runs a day; an empty dictionary",
          len(inds) == 13 and {x.get("id") for x in inds} == packs and all(x.get("name") and "description" in x for x in inds)
          and "USD" in codes and {x.get("kind") for x in cals} == {"calendar", "fiscal", "4-4-5", "4-5-4", "5-4-4"} and all(x.get("label") for x in cals)
          and len(p0.get("audiences") or []) >= 1 and p0.get("generations_left") == 5 and dic.get("kpis") == 0 and dic.get("terms") == 0,
          {"industries": [x.get("id") for x in inds], "packs": sorted(packs), "currencies": str(p0.get("currencies"))[:200], "calendars": cals,
           "audiences": p0.get("audiences"), "generations_left": p0.get("generations_left"), "dictionary": dic})
    audiences = [a for a in p0.get("audiences") or [] if isinstance(a, str)][:2] or ["Executives"]
    in_cur = re.compile(rf"\b{cur}\b" + ("|euro" if cur == "EUR" else ""), re.I)       # a text naming that currency

    def context(**kw) -> dict:
        """Fresh Basket's business context (grocery-retail, in `cur`), with `kw` in place of its fields."""
        return {"industry": "grocery-retail", "about": ABOUT, "brands": BRANDS, "regions": REGIONS, "currency": cur,
                "calendar": dict(CALENDAR), "audiences": audiences, "priorities": PRIORITIES, "conventions": CONVENTIONS, **kw}

    so, sm = me_setup(owner), me_setup(mem)
    check("new: /api/me says so (org.setup): needed, not done; the owner may change it, a member not",
          so.get("status") == "needed" and so.get("done") is False and so.get("can_edit") is True and so.get("next") == "context"
          and sm.get("status") == "needed" and sm.get("done") is False and sm.get("can_edit") is False, (so, sm))
    anon = c.Person(f"nobody.{S}@example.com")
    got = {f"{m} {path}": anon.call(m, path, None if m == "GET" else {})[0] for m, path in [("GET", "/api/org/profile")] + WRITES}
    check("new: nobody without a session (401, every setup route)", set(got.values()) == {401}, got)

    # ---------------------------------------------------------------- blocked until it is set up
    section("blocked until it is set up")
    b0 = org_of(owner).get("credits")
    s1, r1 = said(*c.new_dashboard(owner))
    s2, r2 = said(*c.import_handoff(owner, f"Setup Mini {S}"))
    s3, r3 = review(owner)
    check(f"blocked: an owner's New dashboard is refused (400, '{OWNER_SAYS}': before the brand's own rule)",
          s1 == 400 and OWNER_SAYS in str(detail(r1)), (s1, detail(r1)))
    check("blocked: ... and a DAWB import (400, the same words)", s2 == 400 and OWNER_SAYS in str(detail(r2)), (s2, detail(r2)))
    check("blocked: ... and a new Semantic Review (400, the same words)", s3 == 400 and OWNER_SAYS in str(detail(r3)), (s3, detail(r3)))
    s4, r4 = said(*c.new_dashboard(mem))
    s5, r5 = review(mem)
    check(f"blocked: a member is told an owner finishes it (400, '{ORG} is still being set up'): New dashboard and Semantic Review",
          s4 == 400 and s5 == 400 and all(f"{ORG} is still being set up" in str(detail(x)) and "owner" in str(detail(x)) for x in (r4, r5)),
          (s4, detail(r4), s5, detail(r5)))
    s, lst = owner.get("/api/projects")
    s6, ov = owner.get("/api/semreview")
    check("blocked: nothing was made or charged (no dashboard, no review, the credits as they were)",
          b0 is not None and org_of(owner).get("credits") == b0 and lst == [] and isinstance(ov, dict) and ov.get("runs") == [],
          (b0, org_of(owner).get("credits"), lst, (ov or {}).get("runs") if isinstance(ov, dict) else ov))
    s1, r1 = api(owner, "POST", "/api/org/profile/done")
    s2, r2 = api(owner, "POST", "/api/org/profile/generate")
    s3, r3 = api(owner, "POST", "/api/org/profile/standard")
    check("blocked: Finish is refused before anything is set up (400); Relay Model and the industry standard need a saved context (400)",
          s1 == 400 and s2 == 400 and s3 in (400, 409), (s1, detail(r1), s2, detail(r2), s3, detail(r3)))

    # ---------------------------------------------------------------- Your business
    section("Your business")
    for body, why in ((context(industry="no-such-industry"), "an industry that is none of the packs"),
                      (context(about="Too short."), "what the business does in under 20 characters"),
                      (context(about="A" + "b" * 3000), "what the business does in over 3,000 characters"),
                      (context(currency="Euro"), "a currency that is not a 3-letter code"),
                      (context(calendar={"kind": "lunar", "start_month": 1}), "a calendar that is none of the five"),
                      (context(calendar={"kind": "fiscal", "start_month": 13}), "a fiscal year starting in month 13")):
        s, r = api(owner, "PUT", "/api/org/profile/context", body)
        check(f"context: refused (400, saying why): {why}", s == 400 and isinstance(detail(r), str) and len(detail(r).strip()) > 5, (s, detail(r)))
    s, p = profile(owner)
    check("context: a refused one saves nothing (still needed, no context)", p.get("status") == "needed" and not p.get("context"),
          {k: p.get(k) for k in ("status", "context")})
    s, p = api(owner, "PUT", "/api/org/profile/context", context(industry="general"))
    s2, onto = owner.get("/api/ontology")
    onto = onto if isinstance(onto, dict) else {}
    check("context: saved with industry general: draft, Prepare next; general applies no pack (no terms, no KPIs, no industry)",
          s == 200 and p.get("status") == "draft" and p.get("next") == "prepare" and bool(steps_of(p).get("context"))
          and (p.get("context") or {}).get("industry") == "general" and (p.get("context") or {}).get("about") == ABOUT
          and dic_of(p).get("kpis") == 0 and dic_of(p).get("terms") == 0 and onto.get("industry") == {} and onto.get("terms") == [],
          (s, detail(p), {k: p.get(k) for k in ("status", "next", "steps", "dictionary")}, onto.get("industry")))
    s, p = api(owner, "POST", "/api/org/profile/standard")
    prop = p.get("proposal") or {}
    check("standard: the general standard's proposal at once, no AI (Understanding next)",
          s == 200 and prop.get("source") == "standard" and isinstance(prop.get("understanding"), dict) and bool(prop.get("kpis"))
          and p.get("next") == "understanding", (s, detail(p), prop.get("source"), p.get("next")))

    # ---------------------------------------------------------------- a member reads, never changes
    section("a member reads it and changes nothing")
    s, pm = profile(mem)
    check("member: reads the setup (200, the context the owner saved) and may not change it",
          s == 200 and pm.get("can_edit") is False and pm.get("status") == "draft" and (pm.get("context") or {}).get("about") == ABOUT,
          (s, {k: pm.get(k) for k in ("can_edit", "status")}))
    got = {}
    for m, path in WRITES:
        body = (context(industry="general") if path.endswith("/context") else {"summary": "A member's own words for the business."}
                if path.endswith("/understanding") else {"accept": []} if path.endswith(("/kpis", "/terms")) else {})
        got[f"{m} {path}"] = api(mem, m, path, body)[0]
    check("member: every change is refused (403): context, Relay Model, the standard, understanding, KPIs, terms, Finish",
          set(got.values()) == {403}, got)

    # ---------------------------------------------------------------- a new industry
    section("a new industry")
    s, p = api(owner, "PUT", "/api/org/profile/context", context())
    s2, onto = owner.get("/api/ontology")
    onto = onto if isinstance(onto, dict) else {}
    s3, pk = owner.get("/api/ontology/packs/grocery-retail")
    pk = pk if isinstance(pk, dict) else {}
    pack_kpis = [k.get("name") for k in pk.get("kpis") or []]
    pack_terms = [t.get("name") for t in pk.get("terms") or []]
    d = dic_of(p)
    check("industry: saving grocery-retail applies its pack: the dictionary grows to its 80 terms and its KPIs (as the Ontology page "
          "counts them)", s == 200 and len(pack_terms) == 80 and d.get("terms") == 80 and 0 < (d.get("kpis") or 0) <= len(pack_kpis)
          and d.get("kpis") == onto.get("kpis") and d.get("terms") == len(onto.get("terms") or [])
          and (onto.get("industry") or {}).get("packs") == ["grocery-retail"],
          (s, detail(p), d, onto.get("kpis"), len(onto.get("terms") or []), onto.get("industry")))
    ctx = p.get("context") or {}
    cal = ctx.get("calendar") if isinstance(ctx.get("calendar"), dict) else {}
    check(f"industry: the context is kept as given ({cur}, the 4-4-5 calendar from February, brands, regions, audiences, conventions); "
          "the older proposal is dropped (Prepare next again)",
          ctx.get("currency") == cur and {k: cal.get(k) for k in CALENDAR} == CALENDAR and ctx.get("brands") == BRANDS and ctx.get("regions") == REGIONS
          and ctx.get("audiences") == audiences and ctx.get("conventions") == CONVENTIONS and not p.get("proposal")
          and p.get("next") == "prepare" and p.get("status") == "draft", (ctx, p.get("proposal") and "a proposal", p.get("next")))
    applied = (onto.get("industry") or {}).get("applied")
    s, p = api(owner, "PUT", "/api/org/profile/context", context(about=ABOUT + " Two new stores opened this year."))
    s2, onto2 = owner.get("/api/ontology")
    onto2 = onto2 if isinstance(onto2, dict) else {}
    check("industry: saving the same industry again does not apply its pack again (the dictionary as it was)",
          s == 200 and applied and (onto2.get("industry") or {}).get("applied") == applied and dic_of(p) == d,
          (s, detail(p), applied, (onto2.get("industry") or {}).get("applied"), p.get("dictionary"), d))

    # ---------------------------------------------------------------- Prepare: Relay Model
    section("Prepare: Relay Model")
    has_ai = stack_has_ai()
    print(f"(tests/stack/.env: the stack {'can reach' if has_ai else 'cannot reach' if has_ai is False else 'may reach'} the AI)", flush=True)
    s, p = api(owner, "POST", "/api/org/profile/generate")
    job = p.get("job") or {}
    check("generate: Relay Model starts drafting in the background (job running)",
          s == 200 and job.get("status") in ("running", "error", "done") and bool(job.get("started")), (s, job, detail(p)))
    s2 = None
    if has_ai:
        s2 = api(owner, "POST", "/api/org/profile/generate")[0]       # while the first one runs
    p = wait_job(owner, 600 if has_ai else 60)
    job = p.get("job") or {}
    if has_ai is None and job.get("status") != "error":              # no tests/stack/.env: what the run did tells
        has_ai = True
        if job.get("status") == "running":                          # still running after a minute: the stack reaches the AI
            s2 = api(owner, "POST", "/api/org/profile/generate")[0]
            p = wait_job(owner, 540)
            job = p.get("job") or {}
    prop = p.get("proposal") or {}
    if has_ai:
        check("generate: a second run while one runs is refused (409); Relay Model's proposal is ready within 10 minutes",
              s2 in (409, None) and job.get("status") == "done" and prop.get("source") == "relay", (s2, job))
        bad = shape(prop)
        check("generate: its proposal is checked: an understanding with a summary, 1 to 60 KPIs each with why, at most 80 terms, "
              "abbreviations", not bad, bad)
    else:
        err = str(job.get("error") or "")
        MESSAGES.append(err)
        check("generate: without the AI on the stack the run ends 'error' within a minute, in plain words (no Claude, no queue)",
              job.get("status") == "error" and len(err.strip()) > 10 and not unplain(err) and "queue" not in err.lower(), job)
        check("generate: a failed run leaves no proposal: Prepare is next again (the industry standard stays open)",
              not prop and p.get("next") == "prepare" and p.get("status") == "draft", (p.get("proposal") and "a proposal", p.get("next")))

    # ---------------------------------------------------------------- Prepare: the industry standard
    section("Prepare: the industry standard")
    s, p = api(owner, "POST", "/api/org/profile/standard")
    prop = p.get("proposal") or {}
    und = prop.get("understanding") if isinstance(prop.get("understanding"), dict) else {}
    kpis = [k for k in prop.get("kpis") or [] if isinstance(k, dict)]
    terms = [t for t in prop.get("terms") or [] if isinstance(t, dict)]
    check("standard: the industry standard as it is, no AI: a proposal at once (Understanding next)",
          s == 200 and prop.get("source") == "standard" and bool(prop.get("made")) and p.get("next") == "understanding" and p.get("status") == "draft",
          (s, detail(p), prop.get("source"), p.get("next")))
    pri = und.get("priorities")
    pri = " ".join(map(str, pri)) if isinstance(pri, list) else str(pri or "")
    check(f"standard: the understanding in the context's own words: what it does, brands, regions, {cur}, the 4-4-5 calendar, audiences, "
          "priorities", ABOUT_SNIP in json.dumps(und) and und.get("brands") == BRANDS and und.get("regions") == REGIONS
          and cur in str(und.get("currency")) and "4-4-5" in str(und.get("calendar")) and und.get("audiences") == audiences
          and "own brands" in pri.lower(), und)
    names = [k.get("name") for k in kpis]
    check(f"standard: its KPIs are the grocery-retail pack's ({len(pack_kpis)}), each from the pack and with why",
          len(pack_kpis) > 50 and sorted(map(str, names)) == sorted(map(str, pack_kpis))
          and all(k.get("from_pack") == k.get("name") and str(k.get("why") or "").strip() for k in kpis),
          {"missing": sorted(set(pack_kpis) - set(names))[:8], "more": sorted(set(map(str, names)) - set(pack_kpis))[:8],
           "no why or other from_pack": [k.get("name") for k in kpis if k.get("from_pack") != k.get("name") or not str(k.get("why") or "").strip()][:8]})
    cal = [k.get("name") for k in kpis if "4-4-5" in str(k.get("time") or "")]
    check("standard: their time basis is worded for the 4-4-5 calendar (every KPI but at most the 2 with a time basis of their own)",
          len(kpis) > 50 and len(cal) >= len(kpis) - 2, {"not": [(k.get("name"), k.get("time")) for k in kpis if k.get("name") not in cal][:6]})
    money = [k for k in kpis if k.get("unit") == "currency"]
    check(f"standard: its KPIs in money name the currency ({cur})", bool(money) and all(in_cur.search(json.dumps(k)) for k in money),
          [k.get("name") for k in money if not in_cur.search(json.dumps(k))][:8] or "no KPI in money")
    syn = {t.get("name"): [str(x).lower() for x in t.get("synonyms") or []] for t in terms}
    ab = prop.get("abbreviations") if isinstance(prop.get("abbreviations"), dict) else {}
    ab = {str(k).lower(): str(v).lower() for k, v in ab.items()}
    try:                                             # the kit's own rules, in the web container: each one a term, no clash
        conf = c.last_json(c.in_app(f"""
import json
from genbi_kit import ontology as O
print(json.dumps({{"conflicts": O.conflicts(O.clean_terms(json.loads({json.dumps(json.dumps(terms))})))}}))
"""))
    except subprocess.TimeoutExpired:
        conf = {}
    check("standard: its terms are the pack's 80 with the naming conventions' abbreviations as other names of the terms they name "
          "(bnr Banner, dvsn Division, sls Sales), each a term, no name two terms of one kind share",
          set(pack_terms) <= set(syn) and len(syn) == len(terms) and "bnr" in syn.get("Banner", []) and "dvsn" in syn.get("Division", [])
          and "sls" in syn.get("Sales", []) and all(ab.get(k) == v for k, v in ABBREVIATIONS.items()) and conf.get("conflicts") == [],
          {"missing": sorted(set(pack_terms) - set(syn))[:8], "Banner": syn.get("Banner"), "Division": syn.get("Division"),
           "abbreviations": ab, "conflicts": conf or "could not be checked"})

    # ---------------------------------------------------------------- Understanding
    section("Understanding")
    s, p = api(owner, "PUT", "/api/org/profile/understanding", {**und, "summary": SUMMARY})
    u2 = p.get("understanding") or {}
    check("understanding: the owner's edit is accepted as it is (KPI standard next)",
          s == 200 and u2.get("summary") == SUMMARY and u2.get("brands") == BRANDS and bool(steps_of(p).get("understanding"))
          and p.get("next") == "kpis", (s, detail(p), u2.get("summary"), p.get("next")))
    s, r = api(owner, "POST", "/api/org/profile/done")
    check("finish: refused while a step is missing (400 naming the KPI standard)", s == 400 and "kpi" in str(detail(r)).lower(), (s, detail(r)))

    # ---------------------------------------------------------------- KPI standard
    section("KPI standard")
    s, kd = owner.get("/api/semreview/kpis")
    ids = {k.get("name"): k.get("id") for k in (kd.get("kpis") or [])} if isinstance(kd, dict) else {}
    gone = [owner.delete(f"/api/semreview/kpis/{ids.get(n)}")[0] for n in ("Units Sold", "Gross Sales", "Net Sales")]
    own = [owner.post("/api/semreview/kpis", body)[0] for body in (
        {"name": "Sales Before Discounts", "synonyms": ["Gross Sales"], "definition": "Sales at full price, before any discount."},
        {"name": "Takings", "synonyms": ["Net Revenue"], "definition": "Money taken at the tills and online."})]
    check("kpis: for the check, Units Sold, Gross Sales and Net Sales are taken out of the dictionary; two KPIs of the organisation's own "
          "go by Gross Sales and Net Revenue", gone == [200, 200, 200] and own == [200, 200], (gone, own))
    accept = ["Units Sold", "Gross Sales", "Net Sales", "Transactions", "Average Basket Value", "Shrink %"]
    s, r = api(owner, "POST", "/api/org/profile/kpis", {"accept": accept, "replace": False})
    sk = r.get("skipped") if isinstance(r.get("skipped"), list) else []
    check("kpis: accepted: one taken out is added back, those the dictionary has are kept, one whose name or other name another KPI "
          "holds is skipped with why (one name, one KPI)",
          s == 200 and isinstance(r.get("added"), int) and r["added"] >= 1 and isinstance(r.get("kept"), int) and r["kept"] >= 3
          and r.get("replaced") == 0 and 1 <= len(sk) <= 2
          and all(isinstance(x, dict) and x.get("name") in ("Gross Sales", "Net Sales") and str(x.get("why") or "").strip() for x in sk)
          and r["added"] + r["kept"] + len(sk) == len(accept),
          (s, {k: r.get(k) for k in ("added", "kept", "replaced", "skipped")}, detail(r)))
    s, kd = owner.get("/api/semreview/kpis")
    entries = [k for k in (kd.get("kpis") or []) if isinstance(k, dict)] if isinstance(kd, dict) else []
    by = {k.get("name"): k for k in entries}
    seen, twice = set(), []
    for k in entries:
        for nm in [k.get("name")] + list(k.get("synonyms") or []):
            key = " ".join(str(nm).lower().split())
            twice += [nm] if key in seen else []
            seen.add(key)
    check("kpis: in the dictionary Units Sold is back on the 4-4-5 calendar, the organisation's own two are as they were, still one "
          "name one KPI", "4-4-5" in str((by.get("Units Sold") or {}).get("time"))
          and (by.get("Sales Before Discounts") or {}).get("synonyms") == ["Gross Sales"] and (by.get("Takings") or {}).get("synonyms") == ["Net Revenue"]
          and not twice, {"Units Sold": by.get("Units Sold"), "own": [by.get("Sales Before Discounts"), by.get("Takings")], "twice": twice[:6]})
    s, r = api(owner, "POST", "/api/org/profile/kpis", {"accept": ["Transactions"], "replace": True})
    s2, kd = owner.get("/api/semreview/kpis")
    tr = next((k for k in (kd.get("kpis") or []) if k.get("name") == "Transactions"), {}) if isinstance(kd, dict) else {}
    s3, p = profile(owner)
    check("kpis: with replace the proposal's version wins (Transactions replaced, now on the 4-4-5 calendar); the step is done, terms next",
          s == 200 and r.get("replaced") == 1 and "4-4-5" in str(tr.get("time")) and bool(steps_of(p).get("kpis"))
          and p.get("next") == "terms", (s, {k: r.get(k) for k in ("added", "kept", "replaced", "skipped")}, tr.get("time"), p.get("next")))

    # ---------------------------------------------------------------- Ontology and dictionaries
    section("Ontology and dictionaries")
    s, o = owner.get("/api/ontology")
    tids = {t.get("name"): t.get("id") for t in (o.get("terms") or [])} if isinstance(o, dict) else {}
    gone = [owner.delete(f"/api/ontology/terms/{tids.get(n)}")[0] for n in ("Banner", "Division")]
    accept = ["Banner", "Division", "Store", "Sales", "Tender Type"]
    s, r = api(owner, "POST", "/api/org/profile/terms", {"accept": accept})
    nsk = len(r["skipped"]) if isinstance(r.get("skipped"), list) else int(r.get("skipped") or 0)
    check("terms: accepted: Banner and Division (taken out first) are added from the proposal, the rest kept",
          gone == [200, 200] and s == 200 and isinstance(r.get("added"), int) and r["added"] >= 2 and isinstance(r.get("kept"), int)
          and r["kept"] >= 3 and r["added"] + r["kept"] + (r.get("replaced") or 0) + nsk == len(accept),
          (gone, s, {k: r.get(k) for k in ("added", "kept", "replaced", "skipped")}, detail(r)))
    s, o = owner.get("/api/ontology")
    o = o if isinstance(o, dict) else {}
    ts = {t.get("name"): [str(x).lower() for x in t.get("synonyms") or []] for t in o.get("terms") or []}
    tg = tags(owner, [("bnr", "string"), ("dvsn", "string")])
    s2, p = profile(owner)
    check("terms: the naming conventions reached the business terms (a column bnr is tagged Banner, dvsn Division), no clash; Theme next "
          "(no brand yet)", "bnr" in ts.get("Banner", []) and "dvsn" in ts.get("Division", []) and o.get("conflicts") == [] and len(ts) == 80
          and tg == {"bnr": "Banner", "dvsn": "Division"} and bool(steps_of(p).get("terms")) and p.get("next") == "theme"
          and p.get("theme_ready") is False and dic_of(p).get("terms") == 80,
          {"Banner": ts.get("Banner"), "Division": ts.get("Division"), "conflicts": o.get("conflicts"), "terms": len(ts), "tags": tg,
           "next": p.get("next"), "theme_ready": p.get("theme_ready")})

    # ---------------------------------------------------------------- the screens
    section("the screens")
    kblob, tblob = json.dumps(kpis).lower(), json.dumps(terms).lower()
    kpi_marks = [str(k.get("name")) for k in kpis if len(str(k.get("name"))) > 12 and str(k.get("name")).lower() not in tblob][:12]
    term_marks = [str(t.get("name")) for t in terms if len(str(t.get("name"))) > 9 and str(t.get("name")).lower() not in kblob][:12]
    ui = browser(c.WEB_C, PLAY, c.cookie(owner, "d2d_session") or "", c.cookie(mem, "d2d_session") or "", TYPO, json.dumps(STEPS),
                 json.dumps(kpi_marks), json.dumps(term_marks), json.dumps([ABOUT_SNIP, SUMMARY_SNIP]))
    for w in ("1280", "375"):
        x = ui.get(w) or {}
        cx, kx, tx = x.get("context") or {}, x.get("kpis") or {}, x.get("terms") or {}
        check(f"screen {w} px: #/setup lists the seven steps, Your business to Check and finish",
              x.get("listed") == STEPS and (w != "1280" or x.get("shown") == STEPS),
              {k: x.get(k) for k in ("listed", "shown", "waited", "hash", "text")} if x else ui)
        check(f"screen {w} px: one step on the screen at a time (#/setup?step=context, kpis and terms each show their own only)",
              (cx.get("field") is True or cx.get("about") is True) and not cx.get("kpis") and not cx.get("terms") and bool(kx.get("kpis"))
              and kx.get("field") is False and not kx.get("terms") and bool(tx.get("terms")) and tx.get("field") is False and not tx.get("kpis"),
              {s_: {k: (x.get(s_) or {}).get(k) for k in ("field", "about", "kpis", "terms", "hash")} | {"waited": x.get("waited_" + s_)}
               for s_ in ("context", "kpis", "terms")} if x else ui)
        check(f"screen {w} px: no script errors, no null or undefined, plain characters",
              bool(x) and x.get("errors") == [] and x.get("stray") == [] and x.get("typo") == "",
              {k: x.get(k) for k in ("errors", "stray", "typo")} if x else ui)
        check(f"screen {w} px: nothing wider than the screen", len(x.get("wide") or {}) == 4 and not any((x.get("wide") or {}).values()),
              x.get("wide") if x else ui)
    m = ui.get("member") or {}
    ed = m.get("editable") or {}
    check("screen: a member sees the read-only view (what the owners set, or that an owner is setting it up; nothing to change), no errors",
          bool(m.get("said")) and ed.get("fields") == 0 and ed.get("buttons") == [] and m.get("errors") == [] and m.get("wide") is False
          and m.get("stray") == [] and m.get("typo") == "", {k: m.get(k) for k in ("said", "editable", "errors", "wide", "stray", "typo", "waited", "text")}
          if m else ui)
    for f in ("item81-setup-1280.png", "item81-kpis-1280.png", "item81-setup-375.png", "item81-kpis-375.png", "item81-member-1280.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)

    # ---------------------------------------------------------------- Theme, Check and finish
    section("Theme, Check and finish")
    s, r = api(owner, "POST", "/api/org/profile/done")
    check("finish: refused without the brand, every step done (400 naming it)", s == 400 and bool(re.search(r"brand|theme", str(detail(r)), re.I)),
          (s, detail(r)))
    owner.ensure_brand()
    s, p = profile(owner)
    check("theme: the brand set under Branding: theme ready, Check and finish next", p.get("theme_ready") is True and p.get("next") == "finish"
          and p.get("status") == "draft", {k: p.get(k) for k in ("theme_ready", "next", "status")})
    before = {x.get("id") for x in note_items(mem)}
    rows0 = audit_rows(tid)
    s, p = api(owner, "POST", "/api/org/profile/done")
    check("finish: done: status done, when, nothing next", s == 200 and p.get("status") == "done" and bool(p.get("done")) and p.get("next") is None,
          (s, detail(p), {k: p.get(k) for k in ("status", "done", "next")}))
    flag, rows1 = g.sql(f"SELECT setup_done FROM relay.tn_orgs WHERE tenant_id = '{tid}'"), audit_rows(tid)
    check("finish: the organisation is marked set up (relay.tn_orgs.setup_done) and it is audited", flag == "1" and 0 <= rows0 < rows1,
          (flag, rows0, rows1))
    new = [x for x in note_items(mem) if x.get("id") not in before]
    TEXTS.extend(json.dumps(x, ensure_ascii=False) for x in new)
    told = [x for x in new if re.search(r"ready|set up|" + re.escape(ORG), f"{x.get('title')} {x.get('body')}", re.I)]
    check("finish: its people are told it is ready (a member's notices)", bool(told), new or note_items(mem)[:3])
    so, sm = me_setup(owner), me_setup(mem)
    check("finish: /api/me says it is done, to the owner and to a member", so.get("status") == "done" and so.get("done") is True
          and sm.get("status") == "done" and sm.get("done") is True and sm.get("can_edit") is False, (so, sm))

    # ---------------------------------------------------------------- afterwards
    section("afterwards")
    admin.post(f"/api/admin/orgs/{tid}/credits", {"credits": 100, "note": "item 81 check"})
    s1, r1 = said(*c.new_dashboard(owner))
    s2, r2 = said(*c.import_handoff(owner, f"Setup Mini {S}"))
    s3, r3 = review(owner)
    check("after: New dashboard starts (200)", s1 == 200 and bool(r1.get("id")), (s1, str(detail(r1))[:200]))
    check("after: so does a DAWB import (waiting at Confirm KPIs)", s2 == 200 and r2.get("status") == "awaiting_kpis", (s2, str(detail(r2))[:200]))
    check("after: and a new Semantic Review", s3 == 200 and str(r3.get("id", "")).startswith("sr-"), (s3, detail(r3)))
    seed = c.seed_project(tid, owner.email, f"Setup files {S}", {
        "sales.csv": "sale_date,store_id,banner,net_sales\n2026-11-01,1,Fresh Basket,100.50\n2026-11-02,2,Basket Express,80.00\n"})
    folder = f"/data/projects/.tenants/{tid}/{seed.get('id')}"
    oj, md = g.sh(f"cat {folder}/ontology.json"), g.sh(f"cat {folder}/ontology.md")
    try:
        org = json.loads(oj).get("organisation")
    except (ValueError, AttributeError):
        org = None
    check("files: a dashboard's ontology.json carries the accepted understanding (organisation, with the owner's edit)",
          bool(seed.get("id")) and isinstance(org, dict) and org.get("summary") == SUMMARY and org.get("brands") == BRANDS,
          org if org is not None else oj[-300:])
    i, j = md.find("Your organisation"), md.find("## KPI dictionary")
    part = md[i:j] if 0 <= i < j else ""
    check("files: its ontology.md opens with Your organisation (brands, regions, the currency, the 4-4-5 calendar), before the KPI dictionary",
          all(x in part for x in ("Basket Express", "Belgium", cur, "4-4-5")), part[:700] or md[:700])

    # ---------------------------------------------------------------- not blocked
    section("not blocked: organisations from before, a personal workspace")
    plain = {"industry": "general", "about": "Old Shop sells hardware and garden tools in three towns.", "brands": [], "regions": [],
             "currency": "USD", "calendar": {"kind": "calendar", "start_month": 1}, "audiences": audiences[:1], "priorities": "", "conventions": ""}
    lee = c.Person(f"lee.owner@oldshop{S}.com")
    s, r = lee.sign_in(f"Old Shop {S}", "Lee Owner", brand=False)
    t1 = str(org_of(lee).get("id"))
    s0, q0 = profile(lee)
    seed = c.seed_project(t1, lee.email, f"Old dashboard {S}", {"sales.csv": "month,sales\n2026-01,10\n2026-02,12\n"}, read=False)
    s1, q1 = profile(lee)
    check("legacy: an organisation with a dashboard from before is not blocked (done, legacy), its owner may still open the setup; "
          "it reads only its own", s == 200 and q0.get("status") == "needed" and not q0.get("context") and bool(seed.get("id"))
          and q1.get("status") == "done" and q1.get("legacy") is True and q1.get("can_edit") is True,
          (s, {k: q0.get(k) for k in ("status", "legacy")}, seed, {k: q1.get(k) for k in ("status", "legacy", "can_edit")}))
    s2, r2 = said(*c.import_handoff(lee, f"Old Mini {S}"))       # a new dashboard's gate, without a plan by the AI
    lee.ensure_brand()
    s3, r3 = said(*c.import_handoff(lee, f"Old Mini {S}"))
    check("legacy: a new dashboard (a DAWB import) meets only the brand's rule (400, Set your brand first), then starts (200)",
          s2 == 400 and "Set your brand first" in str(detail(r2)) and OWNER_SAYS not in str(detail(r2)) and s3 == 200,
          (s2, detail(r2), s3, str(detail(r3))[:200]))
    s4, q4 = api(lee, "PUT", "/api/org/profile/context", plain)
    check("legacy: it can still add its business context, and stays done", s4 == 200 and q4.get("status") == "done"
          and (q4.get("context") or {}).get("about") == plain["about"], (s4, detail(q4), q4.get("status")))
    liv = c.Person(f"liv.owner@oldtour{S}.com")
    s, r = liv.sign_in(f"Old Tour {S}", "Liv Owner", brand=False)
    liv.post("/api/org/setup")                       # the old first-time setup, done before item 81 ...
    s0, q0 = profile(liv)
    liv.ensure_brand()                               # ... and a brand
    s1, q1 = profile(liv)
    s2, r2 = review(liv)
    check("legacy: the old first-time setup alone is not enough (needed); with a brand it is from before (done, legacy): a Semantic "
          "Review starts", s == 200 and q0.get("status") == "needed" and q0.get("legacy") is False and q1.get("status") == "done"
          and q1.get("legacy") is True and s2 == 200, (s, {k: q0.get(k) for k in ("status", "legacy")}, {k: q1.get(k) for k in ("status", "legacy")},
                                                         s2, detail(r2)))
    gm, work = f"pat.{S}@gmail.com", f"pat@patws81x{S}.com"
    s, r = admin.post("/api/admin/orgs", {"name": f"Pat {S}", "email": work, "person": "Pat Personal", "credits": 0})
    ptid = (((r or {}).get("created") or {}) if isinstance(r, dict) else {}).get("id")
    schema = "t_" + str(ptid).replace("-", "_")
    g.sql(f"UPDATE relay.tn_orgs SET personal = 1, domain = '{gm}' WHERE tenant_id = '{ptid}'")     # as item 39 made them (no new ones)
    g.sql(f"UPDATE relay.tn_accounts SET email = '{gm}' WHERE email = '{work}'")
    g.sql(f"UPDATE {schema}.users SET email = '{gm}' WHERE email = '{work}'")
    pat = c.Person(gm)
    s1, r1 = pat.sign_in(provision=False)            # item 83: a personal workspace signs nobody in any more
    check("personal: a personal workspace is not asked for a setup: since item 83 it cannot sign in at all (no session)",
          s == 200 and s1 != 200, (s, s1, str(r1)[:200]))

    # ---------------------------------------------------------------- plain words
    section("plain words")
    s, js = owner.call("GET", "/js/47-setup.js")
    js = js if isinstance(js, str) else json.dumps(js)
    check("plain: the setup screen's script (/js/47-setup.js) has no long dashes, curly quotes, arrows or bullets",
          s == 200 and len(js) > 1000 and not [ch for ch in js if ch in TYPO], (s, "".join(sorted(set(ch for ch in js if ch in TYPO)))))
    bad = [t for t in TEXTS if unplain(t)]
    queue = [m_ for m_ in MESSAGES if "queue" in m_.lower()]
    check("plain: every answer of the setup API and every refusal is plain keyboard characters and names no Claude, Anthropic or Atlas "
          "(nor this PC); no message speaks of a queue", bool(TEXTS) and not bad and not queue,
          {"answers": len(TEXTS), "where": where_unplain(bad), "queue": queue[:3]})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - a crash is a failure; the summary line is still printed
        traceback.print_exc()
        check("item 81: the suite ran to the end", False, repr(e))
    bad_ = [n for n, ok in c.RESULTS if not ok]
    print(f"\n{len(c.RESULTS) - len(bad_)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad_}" if bad_ else ""))
    sys.exit(len(bad_))
