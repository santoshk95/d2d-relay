"""Test stack only: item 64, large data (webapp/app/uploads.py, genbi_kit/sampling.py).
Uploads in parts (Cloudflare refuses a request over 100 MB): POST /api/uploads {name, size} -> {id, part_size, parts};
PUT /api/uploads/<id>/<n> (the part's bytes); POST /api/uploads/<id>/done; DELETE /api/uploads/<id>; a form then names
the upload in `uploads` ([{"field", "id"}]) instead of sending the file.
- starting: a size cap (10 GB a file, said in plain words), no empty file, a name; no session, no upload;
- a 9 MB CSV (one part of 32 MB) and a 33 MB file (two parts, sent out of order): each part's size checked, parts
  outside the file refused, "done" before every part has arrived refused, the parts joined byte for byte, done once;
- a new dashboard from the upload (POST /api/projects with `uploads` and data_policy): the file as if it had come with
  the form, its 25 credits, project.json data_policy; the upload removed once used; someone else's upload id (a
  colleague's, another organisation's) or an unfinished one refused before anything is charged;
- a DAWB hand-off (field "handoff") and a Semantic Review (field "files") from uploads;
- DELETE: the upload and its parts removed;
- sampling (worker.read_data in the test web container, with GENBI_SAMPLE_ROWS / GENBI_SAMPLE_OVER set small for that
  run only): a table over the threshold sampled (random, or the most recent rows by its date), the small one used in
  full, sample.json, data_sample/ (what the Power BI file loads), the Parquet sample, data_size, the semantic view and
  the activity log saying so; "all" samples nothing; the default threshold leaves a small table alone.
Its people sign in from 198.18.64.x.
python -I -X utf8 item64_check.py <public> <admin>"""
import hashlib
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402
from review_models import SALES as SALES_MODEL  # noqa: E402

c._ips = (f"198.18.64.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
PART = 32 * 1024 * 1024


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def put_part(p: c.Person, uid: str, n: int, data: bytes):
    req = urllib.request.Request(f"{p.base}/api/uploads/{uid}/{n}", data=data, method="PUT", headers={"Content-Type": "application/octet-stream"})
    try:
        with p.http.open(req, timeout=300) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw or b"null")
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def upload(p: c.Person, name: str, data: bytes) -> str | None:
    """A whole upload: start, every part, done. Returns its id (None when any step failed)."""
    s, r = p.post("/api/uploads", {"name": name, "size": len(data)})
    if s != 200:
        return None
    uid, size = r["id"], r["part_size"]
    for n in range(r["parts"]):
        if put_part(p, uid, n, data[n * size:(n + 1) * size])[0] != 200:
            return None
    return uid if p.post(f"/api/uploads/{uid}/done")[0] == 200 else None


def uploads_field(*refs: tuple[str, str]) -> str:
    return json.dumps([{"field": f, "id": i} for f, i in refs])


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_json(path: str) -> dict:
    """A JSON file in the test web container ({} when there is none)."""
    try:
        v = json.loads(g.sh(f"cat '{path}' 2>/dev/null") or "{}")
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
dom = f"bigdata{S}.com"
owner, mia = c.Person(f"bea.owner@{dom}"), c.Person(f"mia.dev@{dom}")
s, r = owner.sign_in(f"Big Data Co {S}", "Bea Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
s, r = mia.sign_in(person="Mia Dev")
other = c.Person(f"oto.owner@elsewhere{S}.com")
s2, r2 = other.sign_in(f"Elsewhere {S}", "Oto Owner")
check("setup: a colleague and another organisation's owner sign in", s == 200 and s2 == 200, (s, s2))
for p in (owner, mia, other):
    p.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
other.post("/api/org/setup")
tid = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("id")
UPLOADS = f"/data/projects/.tenants/{tid}/.uploads"


def balance() -> int:
    return ((owner.get("/api/me")[1] or {}).get("org") or {}).get("credits") or 0


admin.post(f"/api/admin/orgs/{tid}/credits", {"credits": 200 - balance(), "note": "item 64 check"})

# ---------------------------------------------------------------- starting an upload
section("starting an upload")
s, r = c.Person("x").post("/api/uploads", {"name": "a.csv", "size": 10})
check("start: nobody without a session (401)", s == 401, (s, r))
s, r = owner.post("/api/uploads", {"name": "huge.csv", "size": 11 * 1024 ** 3})
check("start: a file over 10 GB is refused at once, saying so in plain words (413)", s == 413
      and "larger than D2D Relay takes (10 GB a file)" in str(detail(r)), (s, detail(r)))
s, r = owner.post("/api/uploads", {"name": "empty.csv", "size": 0})
check("start: an empty file is refused (400)", s == 400 and "empty" in str(detail(r)), (s, detail(r)))
s, r = owner.post("/api/uploads", {"name": "  ", "size": 10})
check("start: a file needs a name (400)", s == 400, (s, detail(r)))

# ---------------------------------------------------------------- a 9 MB CSV in parts
section("a 9 MB CSV")
rows = ["sale_date,store_code,region,net_sales,units"] + [f"2026-{1 + i % 12:02d}-{1 + i % 28:02d},S{i % 40:03d},{('North', 'South', 'East', 'West')[i % 4]},"
                                                        f"{(i * 7919) % 100000 / 100:.2f},{1 + i % 9}" for i in range(296000)]
big = ("\n".join(rows) + "\n").encode()
check("data: the CSV is about 9 MB", 8.5e6 < len(big) < 9.9e6, len(big))
s, r = owner.post("/api/uploads", {"name": "../../store sales.csv", "size": len(big)})
uid = (r or {}).get("id") if isinstance(r, dict) else None
check("start: one part of 32 MB for 9 MB (the part size the browser uses)", s == 200 and str(uid).startswith("up-") and r.get("parts") == 1
      and r.get("part_size") == PART, (s, r))
s, r = owner.post(f"/api/uploads/{uid}/done")
check("done: before its part has arrived, refused (409, naming the part)", s == 409 and "Parts 1 of" in str(detail(r)), (s, detail(r)))
s, r = put_part(owner, uid, 1, b"x")
check("part: a part outside the file is refused (400)", s == 400, (s, detail(r)))
s, r = put_part(owner, uid, 0, big[:1000])
check("part: a part with the wrong number of bytes is refused, saying how many came and how many were due (400)", s == 400
      and f"arrived with 1,000 bytes, not {len(big):,}" in str(detail(r)), (s, detail(r)))
s, r = put_part(mia, uid, 0, big)
check("part: a colleague cannot send parts of someone else's upload (404)", s == 404, (s, detail(r)))
s, r = put_part(other, uid, 0, big)
check("part: nor can another organisation (404)", s == 404, (s, detail(r)))
s, r = put_part(owner, uid, 0, big)
check("part: the part arrives whole", s == 200 and r == {"part": 0, "bytes": len(big)}, (s, r))
s, r = owner.post(f"/api/uploads/{uid}/done")
check("done: joined, named without its folders (store sales.csv), its size checked", s == 200 and r.get("name") == "store sales.csv"
      and r.get("bytes") == len(big), (s, r))
s2, r2 = owner.post(f"/api/uploads/{uid}/done")
s3, r3 = put_part(owner, uid, 0, big)
check("done: once (done again says the same; another part is refused, 409)", s2 == 200 and r2 == r and s3 == 409, (s2, s3, detail(r3)))
kept = g.sh(f"sha256sum {UPLOADS}/{uid}/file | cut -c1-64; ls {UPLOADS}/{uid}")
check("done: the file is kept byte for byte, its part gone", sha(big) in kept and ".part" not in kept, kept)

section("a new dashboard from the upload")
b0 = balance()
s, r = mia.form("/api/projects", {"prompt": "Sales by store", "data_mode": "upload", "uploads": uploads_field(("files", uid))})
check("use: a colleague cannot use someone else's upload (404), nothing charged", s == 404 and balance() == b0, (s, detail(r), balance()))
s, r = other.form("/api/projects", {"prompt": "Sales by store", "data_mode": "upload", "uploads": uploads_field(("files", uid))})
check("use: nor another organisation (404)", s == 404, (s, detail(r)))
s, r = owner.post("/api/uploads", {"name": "half.csv", "size": 100})
half = (r or {}).get("id")
s, r = owner.form("/api/projects", {"prompt": "Sales by store", "data_mode": "upload", "uploads": uploads_field(("files", half))})
check("use: an upload that has not finished is refused (409), nothing charged", s == 409 and "has not finished uploading" in str(detail(r))
      and balance() == b0, (s, detail(r)))
s, r = owner.form("/api/projects", {"prompt": "Sales by store", "data_mode": "upload", "uploads": "not json"})
check("use: an uploads list that cannot be read is refused (400)", s == 400, (s, detail(r)))
s, r = owner.form("/api/projects", {"prompt": "Sales by store and region", "data_mode": "upload", "name": f"Big sales {S}",
                                    "uploads": uploads_field(("files", uid)), "data_policy": json.dumps({"mode": "sample", "method": "recent"})})
pid = (r or {}).get("id") if isinstance(r, dict) else None
files = (r or {}).get("files") if isinstance(r, dict) else None
check("use: a new dashboard from the upload, the file as if it came with the form", s == 200 and files == [{"name": "store sales.csv", "bytes": len(big)}],
      (s, detail(r), files))
check("use: it uses the new dashboard's 25 credits", b0 - balance() == 25, (b0, balance()))
check("use: project.json keeps the person's choice for big data (sample, the most recent rows)",
      (r or {}).get("data_policy") == {"mode": "sample", "method": "recent"}, (r or {}).get("data_policy"))
on_disk = g.sh(f"sha256sum /data/projects/.tenants/{tid}/{pid}/data/'store sales.csv' | cut -c1-64; ls -A {UPLOADS}")
check("use: the data file is the upload byte for byte, and the upload is removed once used", sha(big) in on_disk and uid not in on_disk, on_disk)
s, r = owner.form("/api/projects", {"prompt": "Sales again", "data_mode": "upload", "uploads": uploads_field(("files", uid))})
check("use: the same upload cannot be used twice (404)", s == 404, (s, detail(r)))
s, r = owner.form("/api/projects", {"prompt": "Sales by region", "data_mode": "upload", "data_policy": "bogus"},
                  {"files": ("small.csv", b"region,sales\nNorth,1\nSouth,2\n")})
check("use: an unknown data_policy is left out (the default, auto, applies)", s == 200 and "data_policy" not in (r or {}), (s, (r or {}).get("data_policy")))

# ---------------------------------------------------------------- two parts, out of order
section("a 33 MB file in two parts")
two = (b"id,value\n" + b"".join(b"%08d,%d\n" % (i, i % 97) for i in range(3_200_000)))[:PART + 4321]
s, r = owner.post("/api/uploads", {"name": "two parts.csv", "size": len(two)})
uid2 = (r or {}).get("id") if isinstance(r, dict) else None
check("start: two parts for 32 MB and a bit", s == 200 and r.get("parts") == 2, (s, r))
s1, r1 = put_part(owner, uid2, 1, two[PART:])
s, r = owner.post(f"/api/uploads/{uid2}/done")
check("parts: the last part first; done then names the missing first part (409)", s1 == 200 and s == 409 and "Parts 1 of" in str(detail(r)), (s1, s, detail(r)))
s0, r0 = put_part(owner, uid2, 0, two[:PART])
s, r = owner.post(f"/api/uploads/{uid2}/done")
check("parts: joined in order, byte for byte", s0 == 200 and s == 200 and r.get("bytes") == len(two)
      and sha(two) in g.sh(f"sha256sum {UPLOADS}/{uid2}/file"), (s0, s, r))
s, r = mia.delete(f"/api/uploads/{uid2}")
check("delete: not by a colleague (404)", s == 404, (s, detail(r)))
s, r = owner.delete(f"/api/uploads/{uid2}")
left = g.sh(f"ls -A {UPLOADS}")
check("delete: the upload and its file are removed", s == 200 and r == {"deleted": uid2} and uid2 not in left, (s, r, left))
s, r = owner.post(f"/api/uploads/{uid2}/done")
check("delete: then it is not found (404)", s == 404, (s, detail(r)))
s, r = owner.delete("/api/uploads/up-nothere")
check("delete: an id that is not one (404)", s == 404, (s, detail(r)))

# ---------------------------------------------------------------- the other forms that take uploads
section("a DAWB hand-off and a Semantic Review from uploads")
hz = upload(owner, "mini.zip", c.mini_handoff(f"Mini Parts {S}"))
s, r = owner.form("/api/projects/import", {"visuals_mode": "builtin", "uploads": uploads_field(("handoff", hz))})
check("import: a DAWB hand-off that came in parts waits at Confirm KPIs", bool(hz) and s == 200 and (r or {}).get("status") == "awaiting_kpis",
      (hz, s, detail(r)))
s, r = owner.form("/api/projects/import", {"visuals_mode": "builtin"})
check("import: neither a file nor an upload is refused (400)", s == 400 and ".zip" in str(detail(r)), (s, detail(r)))
mz = upload(owner, "Sales model.bim", json.dumps(SALES_MODEL).encode())
s, r = owner.form("/api/semreview/runs", {"name": f"From parts {S}", "uploads": uploads_field(("files", mz))})
rid = (r or {}).get("id") if isinstance(r, dict) else None
run = {}
for _ in range(120):
    s2, run = owner.get(f"/api/semreview/runs/{rid}")
    if s2 == 200 and run.get("status") in ("done", "error"):
        break
    time.sleep(1)
check("review: a Semantic Review of a model that came in parts finishes", bool(mz) and s == 200 and run.get("status") == "done"
      and ((run.get("result") or {}).get("summary") or {}).get("models") == 1, (s, detail(r), run.get("status"), run.get("error")))
check("uploads: every upload used is gone (the one never finished stays until a day has passed)", g.sh(f"ls -A {UPLOADS}").split() == [half],
      g.sh(f"ls -A {UPLOADS}"))

# ---------------------------------------------------------------- sampling big tables
section("sampling big tables (worker.read_data, a small threshold for this run only)")
SMALL = {"GENBI_SAMPLE_ROWS": "10000", "GENBI_SAMPLE_OVER": "20000"}
sales = "txn_date,store_id,net_sales\n" + "".join(f"2026-{1 + (i // 3000) % 10:02d}-{1 + (i // 100) % 28:02d},{1 + i % 5},{(i * 37) % 1000}.25\n"
                                                    for i in range(30000))
stores = "store_id,store_name\n1,North\n2,South\n3,East\n4,West\n5,Harbour\n"
seed = c.seed_project(tid, owner.email, f"Sampled {S}", {"sales.csv": sales, "stores.csv": stores}, env=SMALL, announce=True)
spid = seed.get("id")
folder = f"/data/projects/.tenants/{tid}/{spid}"
spec = file_json(f"{folder}/sample.json") if spid else {}
check("sample: a table over the threshold (30,000 rows over 20,000) is sampled at random to 10,000 rows; the small one is not",
      bool(spid) and spec.get("method") == "random" and spec.get("files", {}).get("sales.csv", {}).get("of") == 30000
      and spec["files"]["sales.csv"].get("rows") == 10000 and "stores.csv" not in spec.get("files", {}), spec or seed)
lines = g.sh(f"wc -l < {folder}/data_sample/sales.csv; wc -l < {folder}/data_sample/stores.csv; ls {folder}/.genbi/cache/ | grep -c sample.parquet; "
             f"wc -l < {folder}/data/sales.csv").split()
check("sample: data_sample/ holds the sample and the small table in full (what the Power BI file loads); the Parquet sample; data/ untouched",
      lines == ["10001", "6", "1", "30001"], lines)
pj = c.last_json(c.in_app(f"""
import json
from app import store
with _db.use({tid!r}):
    print(json.dumps(store.load({spid!r}).get("data_size")))
"""))
check("sample: project.json's data_size: 30,005 rows, 10,005 of them used", pj.get("total_rows") == 30005 and pj.get("used_rows") == 10005
      and "sales.csv" in (pj.get("sampled") or {}), pj)
s, sem = owner.get(f"/api/projects/{spid}/semantic")
view = (sem or {}).get("view") or {}
st_ = next((t for t in view.get("tables") or [] if t.get("file") == "sales.csv"), {})
check("sample: the semantic view says what is a sample (random, sales.csv: 10,000 of 30,000 rows)",
      (view.get("sample") or {}).get("method") == "random" and "sales.csv" in ((view.get("sample") or {}).get("files") or {})
      and st_.get("sample_of") == 30000, (view.get("sample"), {k: st_.get(k) for k in ("rows", "sample_of")}))
act = owner.get(f"/api/projects/{spid}/activity")[1] or []
check("sample: the activity log says Relay plans and builds on a sample, every other table in full",
      any("Large data: " in (e.get("text") or "") and "plans and builds on a sample of sales.csv (10,000 of 30,000 rows)" in (e.get("text") or "")
          for e in act if isinstance(e, dict)),
      [e.get("text") for e in act[-3:] if isinstance(e, dict)])
recent = c.seed_project(tid, owner.email, f"Recent {S}", {"sales.csv": sales, "stores.csv": stores}, env=SMALL,
                        policy={"mode": "sample", "method": "recent"})
rfolder = f"/data/projects/.tenants/{tid}/{recent.get('id')}"
rspec = file_json(f"{rfolder}/sample.json")
span = g.sh(f"tail -n +2 {rfolder}/data_sample/sales.csv | cut -d, -f1 | sort | sed -n '1p;$p'").split()
# the data: 3,000 rows a month from January to October, 100 a day: the newest 10,000 are August to October and 19 to 28 July
check("sample: 'recent' keeps the 10,000 most recent rows by the table's date (txn_date): 2026-07-19 to 2026-10-28",
      (rspec.get("files", {}).get("sales.csv") or {}).get("method") == "recent" and rspec["files"]["sales.csv"].get("date") == "txn_date"
      and span == ["2026-07-19", "2026-10-28"], (rspec, span))
alls = c.seed_project(tid, owner.email, f"All rows {S}", {"sales.csv": sales, "stores.csv": stores}, env=SMALL, policy={"mode": "all", "method": "random"})
afolder = f"/data/projects/.tenants/{tid}/{alls.get('id')}"
check("sample: 'all' samples nothing (no sample.json, no data_sample/)", g.sh(f"ls {afolder}").split().count("sample.json") == 0
      and "data_sample" not in g.sh(f"ls {afolder}") and bool(alls.get("id")), g.sh(f"ls {afolder}"))
dflt = c.seed_project(tid, owner.email, f"Default {S}", {"sales.csv": sales, "stores.csv": stores})
dfolder = f"/data/projects/.tenants/{tid}/{dflt.get('id')}"
check("sample: with the default threshold (2,000,000 rows) a 30,000-row table is used in full", bool(dflt.get("id"))
      and "sample.json" not in g.sh(f"ls {dfolder}"), g.sh(f"ls {dfolder}"))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
