"""End-to-end API checks for D2D Relay against an isolated test container (never the live one).

python -I d2d_checks.py <public site> <admin portal> <group> [<group> ...]
    e.g. http://127.0.0.1:8103 http://127.0.0.1:8104 connectors portal

Signs people in the real way: it asks for a code and reads it from the test container's log (the test stack has no
mail, so RELAY_OTP_DEV_LOG=1 prints it there). Nothing is emailed. Nobody signs up (item 56): a person without an
account is first given one by PASDACS on the admin portal (provision_account), as PASDACS or an owner would. The code limits are real too: on the public site
each person comes from an address of their own (cf-connecting-ip, as Cloudflare would send it), and forget_codes()
clears a person's earlier codes in the test database before they sign in again within the minute.
Each group prints one line per check and a summary; the exit code is the number of failures.
"""
import http.cookiejar
import itertools
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/")
ADMIN_BASE = sys.argv[2].rstrip("/")
GROUPS = sys.argv[3:]
RESULTS = []
STAMP = str(int(time.time()))[-6:]
WEB_C = os.environ.get("D2D_TEST_WEB", "d2d-relay-test-web")
ADMIN_C = os.environ.get("D2D_TEST_ADMIN", "d2d-relay-test-admin")
DB_C = os.environ.get("D2D_TEST_DB", "d2d-relay-test-db")
TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the repository's tests/ folder
OUT = os.environ.get("D2D_TEST_OUT") or os.path.join(TESTS, "out")      # this run's logs and screenshots (git-ignored)
_ips = (f"198.51.100.{n}" for n in itertools.count(10))
# Item 40: every code a suite asks for carries a bot-check token (the stack's Cloudflare test keys pass any); a body
# that names "turnstile" itself (item40_check.py) is sent as it is
TURNSTILE_TOKEN = os.environ.get("D2D_TEST_TURNSTILE", "XXXX.DUMMY.TOKEN.XXXX")


def out_path(name: str) -> str:
    """Where a screenshot goes: the run's folder (D2D_TEST_OUT, set by run_all.sh), else tests/out."""
    os.makedirs(OUT, exist_ok=True)
    return os.path.join(OUT, name)


# New dashboard is a guided flow since 2026-11-19 (webapp/static/js/04-new.js): six steps, one on the screen at a time
# (0 Name, 1 Your data, 2 What to build, 3 Theme, 4 Visuals, 5 Check and start); each file goes up as soon as it is
# picked. Python for the browser scripts that run in the test web container: put it in front of a script
# (input=c.ND_FLOW + PLAY) and call nd_* with its Playwright page.
ND_FLOW = r'''
ND_SHOWN = "form.formcard.nd section.nd-step:not([hidden])"
ND_NOTE = {}                       # what the walk saw: "suggested" (Relay prefilled What to build from the data)


def nd_step(page, i, timeout=30000):
    """Wait until step i (0-5) is the one on the screen."""
    page.wait_for_selector(f"{ND_SHOWN} #nd-h{i}", timeout=timeout)


def nd_next(page, i=None):
    """Next (or, on the last step, Start); i: wait for that step to show."""
    page.click("form.formcard.nd .nd-nav button[type=submit]")
    if i is not None:
        nd_step(page, i)


def nd_open(page, base="http://127.0.0.1:8000"):
    page.goto(base + "/#/new")
    page.wait_for_selector("#nd-name", timeout=30000)
    if page.locator("button:has-text('Start again')").count():      # a draft left in this tab: start from nothing
        page.click("button:has-text('Start again')")
        page.wait_for_selector("#nd-name", timeout=30000)
    nd_step(page, 0)


def nd_upload(page, accept_prefix, path, name):
    """Pick a file in the shown step's drop zone (its input accepts accept_prefix ...) and wait until it is up."""
    page.set_input_files(f"{ND_SHOWN} input[type=file][accept^='{accept_prefix}']", path)
    page.wait_for_function("n => [...document.querySelectorAll('.nd-files .nd-fr')].some(r => r.textContent.includes(n) && r.textContent.includes('uploaded'))",
                           arg=name, timeout=60000)


def nd_to_visuals(page, name, csv_path=None, zip_path=None, prompt=None):
    """From the Name step to the Visuals step: the name, the data (a CSV, or a DAWB hand-off .zip), what to build (the
    suggested request, or `prompt`), the theme (the organisation's brand, set before)."""
    page.fill("#nd-name", name)
    nd_next(page, 1)
    if zip_path:
        page.click(".dmode button:has-text('From a DAWB hand-off')")
        nd_upload(page, ".zip", zip_path, zip_path.rsplit("/", 1)[-1])
    else:
        nd_upload(page, ".csv", csv_path, csv_path.rsplit("/", 1)[-1])
    nd_next(page, 2)
    if not zip_path:
        try:                                                                       # Relay's suggestion, from the data
            page.wait_for_function("() => (document.querySelector('#nd-prompt') || {}).value", timeout=30000)
            ND_NOTE["suggested"] = True
        except Exception:  # noqa: BLE001 - the walk goes on with words of its own; the suite may check ND_NOTE
            ND_NOTE["suggested"] = False
        if prompt or not ND_NOTE["suggested"]:
            page.fill("#nd-prompt", prompt or "Sales by region and month")
    nd_next(page, 3)
    page.wait_for_selector(f"{ND_SHOWN} .nd-theme", timeout=30000)                   # the brand, ready
    nd_next(page, 4)
'''


# A JavaScript function for Chromium (item 37): given a visual's box on a prototype page, its sunburst labels (the
# rotated lines that share one transform) that lie on another label or leave their own slice. Each label's corners come
# from its lines' boxes in their own coordinates, taken to the page by the text's screen matrix; two labels overlap
# unless an axis separates them (1 px allowed); a label is inside when every corner, 1 px in, is in the fill of the
# slice its centre is in. Returns {labels, over, outside}.
SUNBURST_JS = r"""(box) => {
  const by = {};
  box.querySelectorAll('svg text[transform^="rotate"]').forEach(t => { const k = t.getAttribute('transform'); (by[k] = by[k] || []).push(t); });
  const labels = Object.values(by).map(ts => {
    const bs = ts.map(t => t.getBBox()), x0 = Math.min(...bs.map(b => b.x)), y0 = Math.min(...bs.map(b => b.y));
    const x1 = Math.max(...bs.map(b => b.x + b.width)), y1 = Math.max(...bs.map(b => b.y + b.height)), m = ts[0].getScreenCTM();
    return {s: ts.map(t => t.textContent).join(' '), c: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => new DOMPoint(x, y).matrixTransform(m))};
  });
  const apart = (A, B) => [A, B].some(P => P.some((a, i) => {
    const b = P[(i + 1) % 4], nx = b.y - a.y, ny = a.x - b.x, len = Math.hypot(nx, ny) || 1, pr = Q => Q.map(p => (p.x * nx + p.y * ny) / len);
    const pa = pr(A), pb = pr(B);
    return Math.max(...pa) <= Math.min(...pb) + 1 || Math.max(...pb) <= Math.min(...pa) + 1;
  }));
  const centre = c => ({x: (c[0].x + c[2].x) / 2, y: (c[0].y + c[2].y) / 2});
  const inFill = (p, path) => path.isPointInFill(new DOMPoint(p.x, p.y).matrixTransform(path.getScreenCTM().inverse()));
  const shrink = c => { const m = centre(c); return c.map(p => { const dx = p.x - m.x, dy = p.y - m.y, d = Math.hypot(dx, dy) || 1; return {x: p.x - dx / d, y: p.y - dy / d}; }); };
  const slices = [...box.querySelectorAll('.grp > path:not([transform])')], over = [], outside = [];
  labels.forEach((a, i) => labels.slice(i + 1).forEach(b => { if (!apart(a.c, b.c)) over.push(a.s + ' | ' + b.s); }));
  labels.forEach(l => { const home = slices.find(p => inFill(centre(l.c), p)); if (!home || !shrink(l.c).every(p => inFill(p, home))) outside.push(l.s); });
  return {labels: labels.map(l => l.s), over, outside};
}"""


def code_from_logs(container: str, email: str, since: float) -> str | None:
    """The sign-in code the app printed for this address (RELAY_OTP_DEV_LOG=1), the newest since `since`."""
    for _ in range(20):
        out = subprocess.run(["docker", "logs", "--since", str(int(since) - 2), container], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        found = re.findall(r"\[otp\] code for " + re.escape(email) + r": (\d{6})", out.stdout + out.stderr)
        if found:
            return found[-1]
        time.sleep(0.5)
    return None


def code_now(container: str, email: str, since: float, wait: float = 2.0) -> str | None:
    """The code the app printed for this address since `since`, looked for once after `wait` seconds (to show that none
    was sent, without code_from_logs' ten seconds of looking)."""
    time.sleep(wait)
    out = subprocess.run(["docker", "logs", "--since", str(int(since) - 2), container], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    found = re.findall(r"\[otp\] code for " + re.escape(email) + r": (\d{6})", out.stdout + out.stderr)
    return found[-1] if found else None


def has_account(email: str) -> bool:
    """Test database only: whether the address has an account (relay.tn_accounts)."""
    n = subprocess.run(["docker", "exec", "-u", "postgres", DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c",
                        "SELECT count(*) FROM relay.tn_accounts WHERE email = '" + email.lower().replace("'", "''") + "'"],
                       capture_output=True, text=True, check=True).stdout.strip()
    return n not in ("", "0")


def provision_account(email: str, org_name: str | None = None, person: str | None = None) -> None:
    """Item 56: nobody signs up, so a test person without an account gets one the way it is done now, by PASDACS on the
    admin portal: an address at an organisation's domain is added to it (Organisations, Person), and an address at a
    new domain gets a new organisation with it as the main owner (New organisation; named org_name, or after the
    domain). On an image from before item 56 the admin portal cannot do either; the old sign-up then happens in
    Person.sign_in."""
    if email.lower() == "info@pasdacs.com" or has_account(email):    # the platform admin always has one (and signs PASDACS in)
        return
    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    domain = email.rsplit("@", 1)[-1].lower()
    s, d = admin.get("/api/admin/orgs")
    # item 60: an organisation may have several email domains (its main one is "domain", all of them "domains")
    o = next((x for x in (d or {}).get("orgs", []) if domain in (x.get("domains") or [x.get("domain")])), None) if isinstance(d, dict) else None
    if o:
        s, r = admin.post(f"/api/admin/orgs/{o['id']}/people", {"email": email, "role": "member"})
    else:
        name = org_name or " ".join(w.capitalize() for w in re.split(r"[-_]+", domain.split(".")[0]) if w)
        s, r = admin.post("/api/admin/orgs", {"name": name, "email": email, "person": person or ""})
    if s != 200:
        print(f"(PASDACS could not give {email} an account: {s} {detail_of(r)})", flush=True)


def in_app(code: str, container: str | None = None, env: dict | None = None, timeout: int = 300) -> str:
    """Python inside the test web container (or `container`) with the app's settings, db.init() done first (as _db);
    env: extra variables for that one run, set before anything is imported (launch gives a part exactly its own
    environment, so `docker exec -e` would not reach it). Returns what it printed, stdout and stderr together."""
    head = f"import os\nos.environ.update({dict((str(k), str(v)) for k, v in (env or {}).items())!r})\n" if env else ""
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", container or WEB_C, "/opt/relay/bin/launch", "web",
                        "python", "-"], input=head + "from app import db as _db\n_db.init()\n" + code, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    return (r.stdout + r.stderr).strip()


def last_json(out: str):
    """The JSON a seeding script printed last ({} when there is none)."""
    for line in reversed((out or "").splitlines()):
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, (dict, list)):
            return v
    return {}


# Item 59: credits are no longer bought online, so a past payment is seeded straight into relay.tn_payments the way
# payments.py made them (amounts in paise or cents; a paid one's GST invoice issued by invoices.issue, which takes the
# next number of its series: D2D/<fy>/ for live keys, TEST/<fy>/ for test keys).
_SEED_PAYMENT = r'''
import json, secrets, time
from app import db, invoices, orgs
a = json.loads(ARGS_JSON)
o = orgs.row(a["tenant"])
with db.use(a["tenant"]):
    u = db.one("SELECT id, name, email FROM users WHERE lower(email) = ?", (a["email"].lower(),))
cur, credits = a.get("currency", "INR"), int(a.get("credits", 100))
price = int(a.get("price") or credits * (10000 if cur == "INR" else 100))
gst = int(a.get("gst") if a.get("gst") is not None else (price * 18 // 100 if cur == "INR" else 0))
now = time.time() - float(a.get("ago", 3600))
status, live = a.get("status", "paid"), 1 if a.get("live") else 0
bill = a.get("billing") or {"name": o["name"] + " Private Limited", "address": "1 Test Road, Indiranagar", "country": "India",
                             "state": "29", "pin": "560038", "gstin": ""}
r = {"id": "pay-" + secrets.token_hex(8), "tenant_id": o["tenant_id"], "org_name": o["name"], "user_id": u["id"], "user_name": u["name"],
     "email": u["email"], "credits": credits, "price": price, "gst": gst, "amount": price + gst, "currency": cur, "live": live,
     "status": status, "order_id": "order_" + secrets.token_hex(7).upper(),
     "payment_id": None if status == "failed" else "pay_" + secrets.token_hex(7).upper(), "method": "upi",
     "error": "The bank declined the payment" if status == "failed" else None, "refunded": int(a.get("refunded") or 0),
     "created": now - 60, "paid": now if status in ("paid", "refunded") else None, "updated": now, "billing": json.dumps(bill),
     "invoice_no": None, "invoice": None}
seller = {"gst": 18, "invoice": {"name": "PASDACS Stand-in Private Limited", "address": "2 Seller Street\nBengaluru", "state": "29",
                                 "pin": "560001", "gstin": "29ABCDE1234F1Z5", "sac": "998314", "prefix": "D2D", "lut": "",
                                 "description": "D2D Relay credits"}}
with db.use(db.PLATFORM):
    with db.transaction():
        if a.get("invoice", True) and status in ("paid", "refunded"):
            inv = invoices.issue({**r, "billing": bill}, seller, now, {"id": r["payment_id"], "method": "upi"})
            r["invoice"], r["invoice_no"] = json.dumps(inv), inv["no"]
        cols = list(r)
        db.run(f"INSERT INTO relay.tn_payments ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(r[k] for k in cols))
print(json.dumps({"id": r["id"], "invoice_no": r["invoice_no"], "amount": r["amount"], "user_id": u["id"], "fy": invoices.fiscal_year(now)}))
'''


def seed_payment(tenant: str, email: str, **kw) -> dict:
    """Item 59: a payment made before buying online was removed, as relay.tn_payments holds it: paid by `email` in the
    organisation `tenant`, in rupees (Rs 100 a credit and 18% GST) unless currency="USD"; live=True for live keys (else
    test keys), invoice=False for one paid before invoices, status "failed" for a checkout never completed, credits,
    ago (seconds). Returns {"id", "invoice_no", "amount", "user_id", "fy"} ({} when it could not be seeded)."""
    out = in_app(_SEED_PAYMENT.replace("ARGS_JSON", repr(json.dumps({"tenant": tenant, "email": email, **kw}))))
    got = last_json(out)
    if not got.get("id"):
        print(f"(could not seed a payment: {out[-400:]})", flush=True)
    return got


# A dashboard's folder seeded straight into an organisation's projects folder (items 62 and 64): its CSVs, project.json
# (by default waiting at Confirm KPIs, with no plan: nothing runs it) and its row in the database, then the data read as
# the worker reads it before Relay plans (worker.read_data: the organisation's ontology into ontology.json and
# ontology.md, a sample of big tables by data_policy, the profile with every column's business term).
_SEED_PROJECT = r'''
import json, time
from app import db, store, worker
a = json.loads(ARGS_JSON)
with db.use(a["tenant"]):
    uid = db.one("SELECT id FROM users WHERE lower(email) = ?", (a["email"].lower(),))["id"]
    pid = store.new_id(a["name"])
    d = store.ROOT / pid
    (d / "data").mkdir(parents=True)
    for name, text in a["files"].items():
        (d / "data" / name).write_text(text, encoding="utf-8")
    worker.refresh_guide(d)
    (d / "request.md").write_text("# " + a["name"] + "\n\n## What the user asked for\n\n" + a["prompt"] + "\n", encoding="utf-8")
    st = {"id": pid, "name": a["name"], "prompt": a["prompt"], "model": "", "style": {}, "created": time.time(),
          "custom_visuals": "never", "visuals_mode": "builtin", "custom_paid": False, "status": a.get("status") or "awaiting_kpis",
          "files": [{"name": n, "bytes": len(t.encode())} for n, t in a["files"].items()], "images": [], "versions": [],
          "runs": [], "job": None, "error": None}
    if a.get("policy"):
        st["data_policy"] = a["policy"]
    store.save(st)
    db.add_project(pid, uid)
    out = {"id": pid}
    if a.get("read", True):
        view = worker.read_data(pid, bool(a.get("announce")))
        out["tables"] = len((view or {}).get("tables") or [])
print(json.dumps(out))
'''


def seed_project(tenant: str, email: str, name: str, files: dict[str, str], prompt: str = "Sales by store and week",
                 env: dict | None = None, **kw) -> dict:
    """A dashboard of `email` in `tenant` from CSV texts {file name: text}, its data read (read=False: not; announce=True:
    the activity log says what was read; policy={"mode", "method"}: project.json data_policy). env: variables for that
    run only (GENBI_SAMPLE_ROWS, GENBI_SAMPLE_OVER ...). Returns {"id", "tables"} ({} when it could not be seeded)."""
    args = {"tenant": tenant, "email": email, "name": name, "files": files, "prompt": prompt, **kw}
    out = in_app(_SEED_PROJECT.replace("ARGS_JSON", repr(json.dumps(args))), env=env)
    got = last_json(out)
    if not got.get("id"):
        print(f"(could not seed a dashboard: {out[-600:]})", flush=True)
    return got


def read_data(tenant: str, pid: str, env: dict | None = None, announce: bool = False) -> str:
    """worker.read_data again for a seeded dashboard (its data read as before planning); what it printed."""
    return in_app(f"""
import json
from app import db, worker
with db.use({tenant!r}):
    v = worker.read_data({pid!r}, {announce!r})
print(json.dumps({{"tables": len((v or {{}}).get("tables") or [])}}))
""", env=env)


# A small DAWB hand-off (item 58's format 1): a new dashboard from it waits at Confirm KPIs with its plan at once, no
# Claude needed, which items 62 to 73 use to get a dashboard whose plan waits for the person.
MINI_DATA = {"dim_store": "store_id,store_name,region_name\n1,North Main,East\n2,South Side,East\n3,West End,West\n",
             "sales_daily": "sale_date,store_id,channel,orders,net_sales\n2026-11-01,1,store,10,100.50\n2026-11-01,2,online,4,80.00\n"
                            "2026-11-02,1,store,12,130.25\n2026-11-02,3,store,7,70.00\n2026-11-03,2,online,5,95.75\n"
                            "2026-11-03,3,store,9,88.10\n"}
MINI_COLS = {"dim_store": [("store_id", "whole number", "Store number"), ("store_name", "text", "Store name"), ("region_name", "text", "Region")],
             "sales_daily": [("sale_date", "date", "Trading day"), ("store_id", "whole number", "Store; joins to dim_store"),
                             ("channel", "text", "store or online"), ("orders", "whole number", "Orders placed"),
                             ("net_sales", "decimal", "Sales after discounts, USD")]}
MINI_KPIS = [{"name": "Net sales", "dax": "SUM(sales_daily[net_sales])", "description": "Sales after discounts, USD", "format": "currency"},
             {"name": "Order count", "dax": "SUM(sales_daily[orders])", "description": "Orders placed", "format": "whole number"},
             {"name": "Average order", "dax": "DIVIDE([Net sales], [Order count])", "description": "Net sales per order, USD", "format": "currency"}]


def mini_handoff(name: str) -> bytes:
    """A DAWB hand-off folder as one .zip (POST /api/projects/import, field "handoff"), named `name`."""
    import hashlib
    import io
    import zipfile
    sha = lambda b: hashlib.sha256(b).hexdigest()                       # noqa: E731
    rows = {t: len([x for x in text.splitlines()[1:] if x.strip()]) for t, text in MINI_DATA.items()}
    project = {"kind": "d2d-project", "format": 1, "name": name, "made_by": {"product": "DAWB", "release": "T-1", "at": "2026-11-19 06:00 UTC"},
               "description": "How the stores sell, by channel.", "audience": "Store leaders",
               "inputs": [{"file": f"data/{t}.csv", "table": t, "description": f"The {t} table", "rows": rows[t],
                           "columns": [{"name": n, "type": ty, "description": d} for n, ty, d in MINI_COLS[t]]} for t in MINI_DATA],
               "plan": {"model": {"tables": [{"name": "dim_store", "role": "dimension", "grain": "one row per store"},
                                             {"name": "sales_daily", "role": "fact", "grain": "one row per day, store and channel"}],
                                  "relationships": ["sales_daily[store_id] -> dim_store[store_id]"]},
                        "kpis": json.loads(json.dumps(MINI_KPIS)),
                        "pages": [{"name": "Overview", "purpose": "How the stores sell", "visuals": [
                            {"title": "Net sales", "visual": "card", "query": "SELECT SUM(net_sales) FROM sales_daily", "x": 0, "y": 0, "w": 6, "h": 4}]}],
                        "grid": {"columns": 24}}}
    files = {f"data/{t}.csv": text.encode() for t, text in MINI_DATA.items()}
    files["README.md"] = b"# A test hand-off\n"
    files["project.json"] = json.dumps(project, indent=2).encode()
    listed = {p: ({"rows": rows[p[5:-4]], "sha256": sha(b), "columns": {n: ty for n, ty, _ in MINI_COLS[p[5:-4]]}} if p.startswith("data/")
                  else {"sha256": sha(b)}) for p, b in files.items()}
    files["manifest.json"] = json.dumps({"run": "2026-11-19T060000Z", "release": "T-1", "files": listed, "rows": sum(rows.values())}).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p, b in files.items():
            z.writestr(f"mini/{p}", b)
    return buf.getvalue()


def import_handoff(p: "Person", name: str, **fields):
    """A new dashboard from mini_handoff(name): (status, answer); it waits at Confirm KPIs (25 credits, built-in visuals)."""
    boundary = "----d2dimport" + str(time.time_ns())
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in {"visuals_mode": "builtin", **fields}.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="handoff"; filename="mini.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode()
                 + mini_handoff(name) + b"\r\n")
    req = urllib.request.Request(p.base + "/api/projects/import", data=b"".join(parts) + f"--{boundary}--\r\n".encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with p.http.open(req, timeout=180) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw or b"null")
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def forget_codes(email: str) -> None:
    """Test database only: forget this address's earlier codes, so it may ask again within the minute."""
    subprocess.run(["docker", "exec", "-u", "postgres", DB_C, "psql", "-q", "-h", "/run/postgresql", "-d", "relay", "-c",
                    "DELETE FROM otp_codes WHERE email = '" + email.replace("'", "''") + "'"], capture_output=True, check=True)


def setup_flag(email: str, reset: bool = False) -> str:
    """Test database only: the old first-time setup flag (relay.tn_orgs.setup_done: /api/me setup_needed, the tour) of
    the address's organisation, "0" or "1" ("" when it has none); reset: set it back to 0."""
    org = "(SELECT home_tenant FROM relay.tn_accounts WHERE email = '" + email.lower().replace("'", "''") + "')"
    q = f"UPDATE relay.tn_orgs SET setup_done = 0 WHERE tenant_id = {org}" if reset else f"SELECT setup_done FROM relay.tn_orgs WHERE tenant_id = {org}"
    return subprocess.run(["docker", "exec", "-u", "postgres", DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                          capture_output=True, text=True).stdout.strip()


class Person:
    def __init__(self, email: str, base: str = BASE):
        self.email, self.base = email, base
        self.container = ADMIN_C if base == ADMIN_BASE else WEB_C
        self.ip = None if base == ADMIN_BASE else next(_ips)      # the admin portal refuses Cloudflare's header without Access
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body=None, headers=None):
        if path == "/auth/otp/start" and isinstance(body, dict) and "turnstile" not in body:
            body = {**body, "turnstile": TURNSTILE_TOKEN}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
        try:
            with self.http.open(req, timeout=60) as r:
                raw = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            out = json.loads(raw or b"null")
        except ValueError:
            out = raw.decode("utf-8", "replace")
        return status, out

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)

    def put(self, path, body=None, **kw):
        return self.call("PUT", path, body if body is not None else {}, **kw)

    def patch(self, path, body=None, **kw):
        return self.call("PATCH", path, body if body is not None else {}, **kw)

    def delete(self, path, **kw):
        return self.call("DELETE", path, **kw)

    def form(self, path: str, fields: dict, files: dict | None = None):
        """A multipart POST (fields, and files as name -> (filename, bytes))."""
        boundary = "----d2dcheck" + str(time.time_ns())
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (fn, data) in (files or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: text/csv\r\n\r\n'.encode()
                         + data + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with self.http.open(req, timeout=120) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, raw.decode("utf-8", "replace")

    def sign_in(self, org_name: str | None = None, person: str | None = None, again: bool = False, provision: bool = True,
                brand: bool = True):
        """Ask for a code, read it from the container's log and sign in. provision (item 56): an address without an
        account is first given one by PASDACS (provision_account: org_name and person name a new organisation and its
        main owner); without it, an address without an account gets no code. An image from before item 56 still names
        a new organisation after the code (upgrade_check.py). brand: an owner gives an organisation without a brand a
        standard palette (ensure_brand) and finishes its setup the plain way (ensure_setup, item 81); False leaves both
        to the suite."""
        if provision:
            provision_account(self.email, org_name, person)
        if again:
            forget_codes(self.email)
        hdr = {"cf-connecting-ip": self.ip} if self.ip else {}
        t0 = time.time()
        s, r = self.post("/auth/otp/start", {"email": self.email}, headers=hdr)
        if s != 200:
            return s, r
        code = code_from_logs(self.container, self.email, t0)
        if not code:
            return 0, "no code in the container log"
        s, r = self.post("/auth/otp/verify", {"email": self.email, "code": code, "next": "#/d2d"})
        if s == 200 and isinstance(r, dict) and r.get("organisation"):      # an image from before item 56: the sign-up step
            s, r = self.post("/auth/otp/organisation", {"name": org_name or r["organisation"]["suggested"], "person": person or ""})
        if s == 200 and brand and self.base == BASE:
            self.ensure_brand()
            self.ensure_setup()
        return s, r

    def ensure_brand(self) -> None:
        """Since 2026-11-19 a new dashboard needs its organisation's brand (branding.require_style: a 400 until an owner
        sets one under Branding). An owner signing in to an organisation with no brand yet picks the first standard
        palette, as an owner would before starting dashboards. A member (who may not change it), an organisation that
        has one, or an image without the rule ("ready" not in GET /api/branding) is left as it is."""
        s, b = self.get("/api/branding")
        if s == 200 and isinstance(b, dict) and b.get("may_edit") and b.get("ready") is False:
            s, r = self.post("/api/branding/choose", {"index": 0, "standard": True})
            if s != 200:
                print(f"({self.email} could not set the organisation's brand: {s} {detail_of(r)})", flush=True)

    def ensure_setup(self) -> None:
        """Since item 81 a new organisation's owners finish a guided setup (GET /api/org/profile) before its first
        dashboard, DAWB import or Semantic Review (each a 400 until then). An owner signing in to an organisation whose
        setup is not done finishes it the plain way, without any AI, so the organisation stays as it was before item 81:
        industry general (it applies no pack), the industry standard's proposal, its understanding accepted as it is, no
        KPIs and no business terms taken (an empty accept), then Finish (the brand is ensure_brand's, called first).
        Finish also marks the old first-time setup done (relay.tn_orgs.setup_done: /api/me setup_needed, the tour); that
        flag is put back as it was, as the owner had not done the tour. A member (can_edit false), an organisation that
        is done (finished, from before item 81, or a personal workspace) or an image without the setup (404) is left as
        it is (item81_check.py signs in with brand=False and walks the setup itself)."""
        s, p = self.get("/api/org/profile")
        if s == 404 or (s == 200 and isinstance(p, dict) and (p.get("status") == "done" or not p.get("can_edit"))):
            return
        if s != 200 or not isinstance(p, dict):
            print(f"({self.email} could not read the organisation's setup: {s} {detail_of(p)})", flush=True)
            return
        was = setup_flag(self.email)
        context = {"industry": "general", "about": "An organisation of the D2D Relay release checks, set up the plain way.",
                   "brands": [], "regions": [], "currency": "USD", "calendar": {"kind": "calendar", "start_month": 1},
                   "audiences": [a for a in p.get("audiences") or [] if isinstance(a, str)][:1], "priorities": "", "conventions": ""}
        s, r = self.put("/api/org/profile/context", context)
        if s == 200:
            s, r = self.post("/api/org/profile/standard")
        if s == 200:
            proposal = (r.get("proposal") if isinstance(r, dict) else None) or {}
            s, r = self.put("/api/org/profile/understanding", proposal.get("understanding") or {"summary": context["about"]})
        for path, body in (("kpis", {"accept": []}), ("terms", {"accept": []}), ("done", {})):
            if s == 200:
                s, r = self.post(f"/api/org/profile/{path}", body)
        if s != 200:
            print(f"({self.email} could not finish the organisation's setup: {s} {detail_of(r)})", flush=True)
        elif was == "0":
            setup_flag(self.email, reset=True)


_signed: dict[tuple[str, str], "Person"] = {}


def signed_in(email: str, base: str) -> "Person":
    """One signed-in session per address and site for the whole run (an address may ask for one code a minute)."""
    key = (base, email)
    if key not in _signed:
        p = Person(email, base)
        s, r = p.sign_in(again=True)          # the same address may have asked for a code on the other site just now
        check(f"sign-in: {email} on {'the admin portal' if base == ADMIN_BASE else 'the public site'}", s == 200, (s, r))
        _signed[key] = p
    return _signed[key]


def check(name: str, ok: bool, detail=None) -> bool:
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok or detail is None else f"   -> {str(detail)[:400]}"), flush=True)
    return bool(ok)


def detail_of(r):
    return r.get("detail") if isinstance(r, dict) else r


# ---------------------------------------------------------------------------------------------------- connectors

def connectors():
    stamp = str(int(time.time()))[-6:]
    owner = Person(f"olive.owner@acme{stamp}.com")
    s, r = owner.sign_in("Acme Test", "Olive Owner")
    check("connectors: a new organisation's owner signs in", s == 200, (s, r))
    s, me = owner.get("/api/me")
    org = (me or {}).get("org") or {}
    check("connectors: a new organisation has none switched on (CSV only)", s == 200 and org.get("connectors") == [], (s, org))
    s, cat = owner.get("/api/org/connectors")
    kinds = [c["kind"] for c in (cat or {}).get("connectors", [])]
    check("connectors: every connector is listed, all on request", s == 200 and len(kinds) == 6 and not any(c["on"] for c in cat["connectors"]), (s, cat))
    check("connectors: the list says what each one reads", all(c.get("note") and c.get("label") for c in cat.get("connectors", [])), cat)
    s, r = owner.get("/api/connectors")
    check("connectors: the wizard offers no connector", s == 200 and r.get("kinds") == {}, (s, r))
    s, r = owner.post("/api/connections", {"kind": "bigquery", "name": "BQ", "auth_mode": "service_account",
                                           "config": {"project": "p"}, "secrets": {"service_account_json": "{}"}})
    check("connectors: adding a BigQuery connection is refused (403)", s == 403 and "PASDACS" in str(detail_of(r)), (s, r))
    s, r = owner.post("/api/org/connector-request", {"kinds": ["bigquery", "snowflake"], "message": "Sales tables, 2M rows"})
    check("connectors: asking PASDACS is recorded (not emailed here: no mail set up)", s == 200 and r.get("sent") is False, (s, r))
    s, r = owner.post("/api/org/connector-request", {"kinds": ["nope"]})
    check("connectors: an unknown connector cannot be asked for (400)", s == 400, (s, r))
    s, r = owner.post("/api/org/connector-request", {"kinds": []})
    check("connectors: a request names at least one connector (400)", s == 400, (s, r))
    s, r = owner.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": ["bigquery"]})
    check("connectors: an owner cannot switch connectors on (no admin API on the public site)", s in (403, 404), (s, r))

    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/orgs")
    mine = next((o for o in (d or {}).get("orgs", []) if o["id"] == org.get("id")), {})
    plat = next((o for o in (d or {}).get("orgs", []) if o.get("platform")), {})
    check("connectors: Organisations shows the new organisation as CSV only", s == 200 and mine.get("connectors") == [], (s, mine))
    check("connectors: PASDACS's own workspace has every connector", len(plat.get("connectors") or []) == 6, plat)
    s, rq = admin.get("/api/admin/requests")
    req = next((x for x in (rq or {}).get("connectors", []) if x.get("org") == org.get("id")), {})
    check("connectors: the request is listed for the platform admin (Requests)", req.get("kinds") == ["bigquery", "snowflake"] and req.get("message"), rq)
    s, r = admin.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": ["bigquery", "warp-drive"]})
    check("connectors: an unknown connector cannot be switched on (400)", s == 400, (s, r))
    s, r = admin.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": ["bigquery"]})
    mine = next((o for o in (r or {}).get("orgs", []) if o["id"] == org.get("id")), {})
    check("connectors: the platform admin switches BigQuery on", s == 200 and mine.get("connectors") == ["bigquery"], (s, mine))

    s, me = owner.get("/api/me")
    check("connectors: the owner's organisation now has BigQuery", (me.get("org") or {}).get("connectors") == ["bigquery"], me.get("org"))
    s, r = owner.get("/api/connectors")
    check("connectors: the wizard offers BigQuery only", s == 200 and list(r.get("kinds", {})) == ["bigquery"], (s, list((r or {}).get("kinds", {}))))
    s, r = owner.post("/api/connections", {"kind": "snowflake", "name": "SF", "auth_mode": "password",
                                           "config": {"account": "a", "warehouse": "w", "database": "d", "user": "u"}, "secrets": {"password": "x"}})
    check("connectors: Snowflake is still refused (403)", s == 403, (s, r))
    s, c = owner.post("/api/connections", {"kind": "bigquery", "name": "BQ test", "auth_mode": "service_account",
                                           "config": {"project": "demo-project"}, "secrets": {"service_account_json": '{"type": "service_account"}'}})
    check("connectors: a BigQuery connection can be added now", s == 200 and (c or {}).get("id"), (s, c))
    cid = (c or {}).get("id")
    s, n = owner.get("/api/notifications") if cid else (0, None)
    texts = json.dumps(n)
    check("connectors: the owner was told BigQuery is switched on", "Connectors for Acme Test" in texts, texts[:300])

    s, r = admin.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": []})
    check("connectors: the platform admin switches it off again", s == 200, (s, r))
    s, r = owner.get("/api/connections")
    conn = next((x for x in (r or {}).get("connections", []) if x["id"] == cid), {})
    check("connectors: the connection stays, marked switched off", conn.get("allowed") is False, conn)
    s, r = owner.post(f"/api/connections/{cid}/test")
    check("connectors: a switched-off connection cannot be tested (403)", s == 403, (s, r))
    s, r = owner.get(f"/api/connections/{cid}/browse?q=")
    check("connectors: ... nor browsed (403)", s == 403, (s, r))
    s, r = owner.post(f"/api/connections/{cid}/query", {"sql": "SELECT 1"})
    check("connectors: ... nor queried (403)", s == 403, (s, r))
    s, r = owner.put(f"/api/connections/{cid}/tables", {"objects": ["a.b"]})
    check("connectors: ... nor given tables (403)", s == 403, (s, r))
    s, r = owner.delete(f"/api/connections/{cid}")
    check("connectors: but it can be removed", s == 200 and not any(x["id"] == cid for x in r.get("connections", [])), (s, r))


# ---------------------------------------------------------------------------------------------------- the admin portal

def cookie(p: Person, name: str):
    return next((c.value for c in p.jar if c.name == name), None)


def admin_portal():
    s, js = Person("x", BASE).get("/portal.js")
    check("portal: the public site says it is public", s == 200 and '"portal": "public"' in str(js), js)
    s, js = Person("x", ADMIN_BASE).get("/portal.js")
    check("portal: the admin portal says it is the admin portal", s == 200 and '"portal": "admin"' in str(js), js)
    s, h = Person("x", ADMIN_BASE).get("/healthz")
    check("portal: the admin portal is up on the shared database", s == 200 and h.get("portal") == "admin" and h.get("database") == "postgres", h)

    outsider = Person(f"pat@acme{STAMP}.com", ADMIN_BASE)
    s, r = outsider.post("/auth/otp/start", {"email": outsider.email})
    check("portal: a non-PASDACS address cannot ask for a code (403)", s == 403 and "PASDACS" in str(detail_of(r)), (s, r))
    s, r = outsider.post("/auth/otp/verify", {"email": outsider.email, "code": "123456"})
    check("portal: ... nor sign in with any code", s in (400, 403), (s, r))

    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    check("portal: info@pasdacs.com signs in to the admin portal with its own cookie", cookie(admin, "d2d_admin") and not cookie(admin, "d2d_session"),
          [c.name for c in admin.jar])
    s, me = admin.get("/api/me")
    check("portal: ... as a platform admin on the admin portal", s == 200 and me.get("portal") == "admin" and (me.get("org") or {}).get("platform_admin") is True, me)
    staff = Person(f"ops{STAMP}@pasdacs.com", ADMIN_BASE)
    t0 = time.time()
    s, r = staff.post("/auth/otp/start", {"email": staff.email})
    check("portal: a @pasdacs.com address without an account gets the usual answer, but no code (item 56)",
          s == 200 and "If " in str(r) and not code_now(ADMIN_C, staff.email, t0), (s, r))
    s, r = staff.sign_in(again=True)          # PASDACS adds them to its own workspace first (provision_account)
    s2, me2 = staff.get("/api/me")
    check("portal: once added to PASDACS's workspace, a @pasdacs.com colleague signs in and is an admin",
          s == 200 and (me2.get("org") or {}).get("platform_admin") is True, (s, r, me2))
    for path, want in (("/api/admin/orgs", 200), ("/api/admin/requests", 200), ("/api/notifications", 200), ("/api/projects", 404),
                       ("/api/connections", 404), ("/api/admin/audit", 404), ("/api/admin/backups", 404), ("/api/health", 404),
                       ("/api/org", 404), ("/api/askd/threads", 404)):
        s, r = admin.get(path)
        check(f"portal: admin portal GET {path} -> {want}", s == want, (s, detail_of(r)))
    s, r = admin.post("/auth/otp/organisation", {"name": "X", "person": "Y"})
    check("portal: there is no sign-up step, not even on the admin portal (404 or 405: no such route)", s in (404, 405), (s, r))

    owner = Person(f"olga.owner@bravo{STAMP}.com")
    s, r = owner.sign_in("Bravo Test", "Olga Owner")
    check("portal: the owner of an organisation PASDACS created signs in on the public site", s == 200 and cookie(owner, "d2d_session"), (s, r))
    s, r = owner.get("/api/admin/orgs")
    check("portal: the public site has no admin APIs (404)", s == 404, (s, r))
    pub_admin = signed_in("info@pasdacs.com", BASE)
    s, r = pub_admin.get("/api/admin/orgs")
    check("portal: ... not even for info@pasdacs.com there (404)", s == 404, (s, r))
    s, me = pub_admin.get("/api/me")
    check("portal: on the public site info@pasdacs.com is no platform admin", s == 200 and (me.get("org") or {}).get("platform_admin") is False, me.get("org"))

    swap = Person("x", ADMIN_BASE)       # a public session's cookie, offered to the admin portal under its cookie name
    swap.jar.set_cookie(http.cookiejar.Cookie(0, "d2d_admin", cookie(owner, "d2d_session"), None, False, "127.0.0.1", False, False, "/", True,
                                              False, None, False, None, None, {}))
    s, r = swap.get("/api/me")
    check("portal: a public-site session is refused by the admin portal (401)", s == 401, (s, r))
    swap2 = Person("x", BASE)
    swap2.jar.set_cookie(http.cookiejar.Cookie(0, "d2d_session", cookie(admin, "d2d_admin"), None, False, "127.0.0.1", False, False, "/", True,
                                               False, None, False, None, None, {}))
    s, r = swap2.get("/api/me")
    check("portal: an admin-portal session is refused by the public site (401)", s == 401, (s, r))

    cf = {"cf-connecting-ip": "203.0.113.7"}
    s, r = admin.get("/api/me", headers=cf)
    check("portal: through Cloudflare without Access set up, the admin portal refuses (403)", s == 403 and "Cloudflare Access" in str(detail_of(r)), (s, r))
    s, r = Person("x", ADMIN_BASE).get("/login.html", headers=cf)
    check("portal: ... its pages too", s == 403 and "Cloudflare Access" in str(r), (s, str(r)[:200]))
    s, r = owner.get("/api/me", headers=cf)
    check("portal: the public site is not affected by that", s == 200, (s, r))


# ---------------------------------------------------------------------------------------------------- credits by approval

CSV = b"month,region,sales\n2026-01,North,120\n2026-02,North,135\n2026-01,South,98\n2026-02,South,101\n"


def new_dashboard(p: Person):
    return p.form("/api/projects", {"prompt": "Sales by region and month", "data_mode": "upload", "name": "Credit check"},
                  {"files": ("sales.csv", CSV)})


def credits_by_approval():
    dom = f"credit{STAMP}.com"
    owner, colleague = Person(f"cara.owner@{dom}"), Person(f"colin.colleague@{dom}")
    s, r = owner.sign_in("Credit Test", "Cara Owner")
    check("credits: PASDACS creates a new organisation and its owner signs in", s == 200, (s, r))
    s, me = owner.get("/api/me")
    org = me.get("org") or {}
    check("credits: it starts with 50 credits", org.get("credits") == 50 and org.get("pending_request") is None, org)
    s, o = owner.get("/api/org")
    check("credits: ... with a 'starting credits' line of 50 in its history",
          s == 200 and any(x["kind"] == "start" and x["delta"] == 50 for x in o.get("ledger", [])), o.get("ledger"))
    check("credits: the prices: 25 a dashboard (50 with custom visuals, item 44), 10 a change, 10 for up to 5 Ask Relay questions, "
          "10 a Semantic Review (item 55), 1 a KPI changed in words (item 63), 1 a review finding fixed (item 65)",
          (org.get("costs") or {}) == {"dashboard": 25, "dashboard_custom": 50, "change": 10, "ask": 10, "ask_questions": 5, "review": 10,
                                       "kpi": 1, "fix": 1},
          org.get("costs"))
    admin0 = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, r = admin0.post(f"/api/admin/orgs/{org.get('id')}/credits", {"credits": -50, "note": "Test: back to none"})
    check("credits: PASDACS takes the 50 back (to test running out)", s == 200, (s, r))
    s, r = new_dashboard(owner)
    check("credits: a new dashboard is refused without credits (402)", s == 402 and "PASDACS" in str(detail_of(r)), (s, r))
    s, r = owner.post("/api/org/credit-request", {"credits": 100, "message": "First pilot"})
    check("credits: the owner asks PASDACS for 100 credits", s == 200 and (r.get("request") or {}).get("credits") == 100, (s, r))
    s, r = owner.post("/api/org/credit-request", {"credits": 50})
    check("credits: a second request while one is waiting is refused (409)", s == 409, (s, r))
    s, r = colleague.sign_in()
    s, me2 = colleague.get("/api/me")
    pend = (me2.get("org") or {}).get("pending_request") or {}
    check("credits: a colleague sees the waiting request", pend.get("credits") == 100, me2.get("org"))
    s, r = colleague.post(f"/api/org/credit-request/{pend.get('id')}/withdraw")
    check("credits: ... but cannot withdraw someone else's (403)", s == 403, (s, r))
    s, r = owner.post(f"/api/org/credit-request/{pend.get('id')}/withdraw")
    check("credits: the owner withdraws it", s == 200 and r.get("pending_request") is None, (s, r))
    s, r = owner.post("/api/org/credit-request", {"credits": 150, "message": "Pilot, 5 dashboards"})
    rid = (r.get("request") or {}).get("id")
    check("credits: ... and asks for 150 instead", s == 200 and rid, (s, r))
    s, r = owner.post(f"/api/admin/requests/{rid}/approve", {"credits": 150})
    check("credits: nobody approves on the public site (404)", s == 404, (s, r))

    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/requests")
    mine = next((x for x in d.get("credits", []) if x["id"] == rid), {})
    check("credits: the admin portal lists it as waiting", mine.get("status") == "pending" and mine.get("org_name") == "Credit Test" and d.get("pending", 0) >= 1, mine)
    s, d2 = admin.get("/api/admin/orgs")
    org_row = next((x for x in d2.get("orgs", []) if x["id"] == org.get("id")), {})
    check("credits: Organisations shows what it asks for", (org_row.get("pending") or {}).get("credits") == 150, org_row)
    s, r = admin.post(f"/api/admin/requests/{rid}/approve", {"credits": 0})
    check("credits: approving 0 credits is refused (400)", s == 400, (s, r))
    s, r = admin.post(f"/api/admin/requests/{rid}/approve", {"credits": 120, "note": "Pilot agreed"})
    check("credits: the admin approves 120 (another amount than asked)", s == 200, (s, r))
    s, r = admin.post(f"/api/admin/requests/{rid}/approve", {"credits": 120})
    check("credits: ... once only (409)", s == 409, (s, r))
    s, me = owner.get("/api/me")
    check("credits: the organisation has the 120 credits at once", (me.get("org") or {}).get("credits") == 120 and not (me.get("org") or {}).get("pending_request"), me.get("org"))
    s, o = owner.get("/api/org")
    led = next((x for x in o.get("ledger", []) if x["kind"] == "adjust"), {})
    req = next((x for x in o.get("requests", []) if x["id"] == rid), {})
    check("credits: its history says PASDACS added them for the approved request", led.get("delta") == 120 and "Request approved" in (led.get("note") or ""), led)
    check("credits: its requests say approved, +120", req.get("status") == "approved" and req.get("granted") == 120, req)
    s, n = owner.get("/api/notifications")
    check("credits: the owner was told", "+120 credits for Credit Test" in json.dumps(n), json.dumps(n)[:300])

    s, r = owner.post("/api/org/credit-request", {"credits": 5000, "message": "Big project"})
    rid2 = (r.get("request") or {}).get("id")
    s, r = admin.post(f"/api/admin/requests/{rid2}/decline", {"note": ""})
    check("credits: declining needs a reason (400)", s == 400, (s, r))
    s, r = admin.post(f"/api/admin/requests/{rid2}/decline", {"note": "Please talk to us about a plan first"})
    check("credits: the admin declines with a reason", s == 200, (s, r))
    s, o = owner.get("/api/org")
    req2 = next((x for x in o.get("requests", []) if x["id"] == rid2), {})
    check("credits: the organisation sees it declined, with the reason, and no credits added",
          req2.get("status") == "declined" and "plan first" in (req2.get("note") or "") and o.get("credits") == 120, (req2, o.get("credits")))
    s, r = admin.post(f"/api/admin/requests/{rid2}/approve", {"credits": 10})
    check("credits: a declined request cannot be approved later (409)", s == 409, (s, r))
    s, r = new_dashboard(owner)
    check("credits: with credits, a new dashboard starts", s == 200 and (r or {}).get("id"), (s, str(r)[:200]))
    s, o = owner.get("/api/org")
    check("credits: ... and its 25 credits are charged", any(x["kind"] == "charge" and x["delta"] == -25 for x in o.get("ledger", [])), o.get("ledger"))


# ---------------------------------------------------------------------------------------------------- people management

def person(o: dict, email: str) -> dict:
    return next((p for p in o.get("people", []) if p["email"] == email), {})


def people_management():
    dom = f"people{STAMP}.com"
    olivia, mark, nina = Person(f"olivia@{dom}"), Person(f"mark@{dom}"), Person(f"nina@{dom}")
    s, r = olivia.sign_in("People Test", "Olivia Owner")
    check("people: PASDACS creates an organisation with Olivia as its main owner; she signs in", s == 200, (s, r))
    s, me = olivia.get("/api/me")
    check("people: ... an owner, and the main one", (me.get("org") or {}).get("is_owner") and (me.get("org") or {}).get("is_primary"), me.get("org"))
    s, r = olivia.post("/api/org/people", {"email": f"mark@{dom}", "role": "member"})
    check("people: an owner adds Mark as a member (not emailed here: no mail set up)", s == 200 and (r.get("added") or {}).get("invited") is False
          and person(r, f"mark@{dom}").get("owner") is False, (s, r.get("added") if isinstance(r, dict) else r))
    s, r = olivia.post("/api/org/people", {"email": "someone@other-company.com"})
    check("people: only the organisation's own domain can be added (400)", s == 400 and dom in str(detail_of(r)), (s, r))
    s, r = olivia.post("/api/org/people", {"email": f"mark@{dom}"})
    check("people: adding someone twice is refused (409)", s == 409, (s, r))
    s, r = olivia.post("/api/org/people", {"email": "info@pasdacs.com"})
    check("people: an address of another organisation cannot be added (400/409)", s in (400, 409), (s, r))
    s, r = mark.sign_in()
    s, me = mark.get("/api/me")
    check("people: Mark signs in to People Test (added before he ever signed in)", (me.get("org") or {}).get("name") == "People Test"
          and (me.get("org") or {}).get("is_owner") is False, me.get("org"))
    s, r = mark.post("/api/org/people", {"email": f"nina@{dom}"})
    check("people: a member cannot add people (403)", s == 403, (s, r))
    s, o = mark.get("/api/org")
    olivia_id = person(o, f"olivia@{dom}").get("id")
    s, r = mark.patch(f"/api/org/people/{olivia_id}", {"role": "member"})
    check("people: a member cannot change roles (403)", s == 403, (s, r))
    mark_id = person(o, f"mark@{dom}").get("id")
    s, r = olivia.patch(f"/api/org/people/{mark_id}", {"role": "owner"})
    check("people: Olivia makes Mark an owner (several owners)", s == 200 and person(r, f"mark@{dom}").get("owner") is True, (s, r))
    s, me = mark.get("/api/me")
    check("people: Mark is now an owner", (me.get("org") or {}).get("is_owner") is True and (me.get("org") or {}).get("is_primary") is False, me.get("org"))
    s, r = mark.patch(f"/api/org/people/{olivia_id}", {"role": "member"})
    check("people: the main owner cannot be made a member (409)", s == 409, (s, r))
    s, r = mark.delete(f"/api/org/people/{olivia_id}")
    check("people: ... nor removed (409)", s == 409, (s, r))
    s, r = mark.post("/api/org/transfer", {"uid": mark_id})
    check("people: only the main owner hands over the main ownership (403)", s == 403, (s, r))
    s, r = mark.post("/api/org/people", {"email": f"nina@{dom}", "role": "member"})
    check("people: an owner other than the main one adds Nina", s == 200, (s, r))
    s, r = nina.sign_in()
    s, o = olivia.get("/api/org")
    nina_id = person(o, f"nina@{dom}").get("id")
    s, r = olivia.delete(f"/api/org/people/{nina_id}")
    # item 31 (the user, 2026-11-12): removing someone deletes their account at once; the address can come back as a new person
    check("people: Olivia removes Nina: her account is deleted at once, not kept as removed", s == 200 and not person(r, f"nina@{dom}")
          and not any(p.get("email") == f"nina@{dom}" for p in r.get("removed", [])), (s, r))
    s, r = nina.get("/api/me")
    check("people: Nina's session ends at once (401)", s == 401, (s, r))
    s, r = olivia.post("/api/org/people", {"email": f"nina@{dom}", "role": "member"})
    check("people: an owner can add her address back, as a new person", s == 200 and person(r, f"nina@{dom}")
          and person(r, f"nina@{dom}").get("id") != nina_id, (s, r))
    s, r = nina.sign_in(again=True)
    check("people: and she signs in again", s == 200, (s, r))
    s, o = olivia.get("/api/org")
    nina_id = person(o, f"nina@{dom}").get("id")              # her new account
    s, r = olivia.post("/api/org/transfer", {"uid": olivia_id})
    check("people: the main owner cannot hand it to herself (400)", s == 400, (s, r))
    s, r = olivia.post("/api/org/transfer", {"uid": nina_id, "stay_owner": False})
    check("people: Olivia hands the main ownership to Nina and becomes a member", s == 200, (s, r))
    s, me = nina.get("/api/me")
    check("people: Nina is the main owner now", (me.get("org") or {}).get("is_primary") is True and (me.get("org") or {}).get("is_owner") is True, me.get("org"))
    s, me = olivia.get("/api/me")
    check("people: Olivia is a member", (me.get("org") or {}).get("is_owner") is False and (me.get("org") or {}).get("is_primary") is False, me.get("org"))
    s, n = nina.get("/api/notifications")
    check("people: Nina was told", "main owner of People Test" in json.dumps(n), json.dumps(n)[:300])
    s, r = mark.delete(f"/api/org/people/{mark_id}")
    check("people: an owner can leave (signed out)", s == 200 and r.get("signed_out") is True, (s, r))
    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/orgs")
    po = next((x for x in d.get("orgs", []) if x["name"] == "People Test"), {})
    check("people: the admin portal shows the new main owner and 2 people", (po.get("owner") or {}).get("email") == f"nina@{dom}" and po.get("people") == 2, po)


# ---------------------------------------------------------------------------------------------------- production clean-up

def production():
    for base, where in ((BASE, "public site"), (ADMIN_BASE, "admin portal")):
        s, r = Person("x", base).get("/auth/otp/test-login")
        check(f"production: the temporary test login is gone ({where}: 404)", s == 404, (s, str(r)[:120]))
        s, page = Person("x", base).get("/login.html")
        check(f"production: the sign-in page has no testing mode ({where})", s == 200 and "testbanner" not in str(page) and "test_code" not in str(page),
              str(page)[:120])
    p = Person(f"limit.one@limits{STAMP}.com")
    provision_account(p.email, f"Limits {STAMP}")             # an account, so its codes are really sent (item 56)
    s, r = p.post("/auth/otp/start", {"email": p.email}, headers={"cf-connecting-ip": p.ip})
    s2, r2 = p.post("/auth/otp/start", {"email": p.email}, headers={"cf-connecting-ip": p.ip})
    check("production: one code a minute per address (429)", s == 200 and s2 == 429, (s, s2, r2))
    s, r = p.post("/auth/otp/verify", {"email": p.email, "code": "000000"})
    tries = [p.post("/auth/otp/verify", {"email": p.email, "code": "000000"})[0] for _ in range(5)]
    code = code_from_logs(WEB_C, p.email, time.time() - 120)
    s, r = p.post("/auth/otp/verify", {"email": p.email, "code": code or "", "next": ""})
    check("production: after 5 wrong tries even the right code is refused", s == 400 and all(t == 400 for t in tries), (s, tries))
    ip = f"203.0.113.{int(STAMP) % 200 + 20}"      # a network of its own each run
    codes = [Person(f"net{i}.{STAMP}@limits{STAMP}.com").post("/auth/otp/start", {"email": f"net{i}.{STAMP}@limits{STAMP}.com"},
                                                               headers={"cf-connecting-ip": ip})[0] for i in range(21)]
    check("production: 20 codes an hour per network, then 429", codes[:20] == [200] * 20 and codes[20] == 429, codes)
    for addr in (f"someone.{STAMP}@mailinator.com", f"someone.{STAMP}@gmail.com"):
        t0 = time.time()
        s, r = Person("x").post("/auth/otp/start", {"email": addr})
        check(f"production: @{addr.split('@')[1]} (no account) gets the usual answer and no code (item 56: nobody signs up)",
              s == 200 and not code_now(WEB_C, addr, t0, wait=1), (s, r))


def rehearsal():
    """After loading a copy of the live database into the test stack: the live data is there and works."""
    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/orgs")
    plat = next((o for o in (d or {}).get("orgs", []) if o.get("platform")), {})
    check("rehearsal: the PASDACS organisation came across with its 70 credits and 4 dashboards",
          plat.get("domain") == "pasdacs.com" and plat.get("credits") == 70 and plat.get("dashboards") == 4, plat)
    check("rehearsal: ... and every connector switched on for it", len(plat.get("connectors") or []) == 6, plat)
    pub = signed_in("info@pasdacs.com", BASE)
    s, me = pub.get("/api/me")
    org = me.get("org") or {}
    check("rehearsal: info@pasdacs.com is its main owner on the public site", org.get("is_owner") and org.get("is_primary") and org.get("credits") == 70, org)


GROUP_FUNCS = {"connectors": connectors, "portal": admin_portal, "credits": credits_by_approval, "people": people_management,
               "production": production, "rehearsal": rehearsal}

if __name__ == "__main__":
    for g in GROUPS:
        print(f"--- {g}", flush=True)
        try:
            GROUP_FUNCS[g]()
        except Exception as e:  # noqa: BLE001
            check(f"{g}: ran to the end", False, repr(e))
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
    sys.exit(len(bad))
