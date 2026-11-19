"""Test stack only: item 70, deployment (python -I -X utf8 item70_check.py <public> <admin>).

A published dashboard sent to the Power BI service through the stand-in Imports API (fake_powerbi.py, 127.0.0.1:8106)
as the organisation's own Entra app, and its Power BI project pushed to GitHub through the stand-in GitHub API
(fake_github.py: started here inside the web container on port 9913 when it is not running; the stack points the app at
it with RELAY_GITHUB_API=http://d2d-relay-test-web:9913). The settings (owners change them, the token is never shown
again, Test), Publish to Power BI (the .pbix out of the download, the import polled, report and dataset ids and the
report's address recorded, one at a time, an overwrite keeping the report, a failed import, a workspace the app may not
publish to), Push to GitHub (the project only: no data, local settings, keys, links or other files; .platform files;
the model's DataFolder as the .pbix has it; the workflow once and never again; already up to date; a change after
someone else pushed; a removed page removed; two dashboards of one name; a token without Workflows on a new branch; a
read-only token; an empty repository), automatic publishing and pushing (deploy.after_pbix, as the worker calls it, and
what cannot start recorded), who may do what, a run cut off by a restart, plain keyboard characters, and the screens in
Chromium (screenshots item70-*.png). Its people sign in from 198.18.70.x.
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import quote

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

check = c.check
STAMP = str(int(time.time()))[-6:]
STANDIN = "http://127.0.0.1:8106"
CLIENT_ID, SECRET = "33333333-aaaa-4bbb-8ccc-000000000001", "stand-in-client-secret-not-real"
WS_SALES, WS_OPS = "11111111-aaaa-4bbb-8ccc-000000000001", "11111111-aaaa-4bbb-8ccc-000000000002"
GOOD = "github_pat_STANDIN_GOOD_000000000000000000"
READONLY = "github_pat_STANDIN_READONLY_00000000000000"
NOWORKFLOW = "github_pat_STANDIN_NOWORKFLOW_000000000000"
REPO, REPO2, EMPTY_REPO = "d2d-test/bi-dashboards", "d2d-test/second-repo", "d2d-test/empty-repo"
GITHUB_STANDIN = "http://d2d-relay-test-web:9913"
WORKFLOW = ".github/workflows/d2d-relay-deploy.yml"
BAD = "\u2014\u2013\u2018\u2019\u201c\u201d\u2192\u2022\u2026\u00b7"


# ---------------------------------------------------------------- helpers

def standin(path: str, body=None) -> dict:
    req = urllib.request.Request(STANDIN + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"null")


def gh(path: str, body=None) -> dict:
    """The stand-in GitHub API, asked from inside the web container (it has no port on this PC)."""
    code = ("import sys, urllib.request\n"
            "d = sys.stdin.read()\n"
            f"req = urllib.request.Request('http://127.0.0.1:9913{path}', data=d.encode() if d else None, "
            "method='POST' if d else 'GET', headers={'Content-Type': 'application/json'})\n"
            "print(urllib.request.urlopen(req, timeout=15).read().decode())")
    r = subprocess.run(["docker", "exec", "-i", c.WEB_C, "/usr/local/bin/python3", "-c", code], input=json.dumps(body) if body is not None else "",
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"_error": (r.stdout + r.stderr)[-400:]}


def repo_files(repo: str, branch: str = "main") -> dict:
    out = gh(f"/_test/files?repo={quote(repo, safe='')}&branch={quote(branch, safe='')}")
    return {p: base64.b64decode(v) for p, v in (out.get("files") or {}).items()}


def start_github_standin() -> bool:
    if "_error" not in gh("/_test/state"):
        return True
    subprocess.run(["docker", "cp", os.path.join(HERE, "fake_github.py"), f"{c.WEB_C}:/tmp/fake_github.py"], capture_output=True)
    subprocess.run(["docker", "exec", "-d", "-u", "relay", c.WEB_C, "/usr/local/bin/python3", "/tmp/fake_github.py"], capture_output=True)
    for _ in range(30):
        time.sleep(0.5)
        if "_error" not in gh("/_test/state"):
            return True
    return False


def last_line(out: str):
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def state(p, pid: str) -> dict:
    s, d = p.get(f"/api/projects/{pid}/deploys")
    return d if s == 200 and isinstance(d, dict) else {}


def wait_run(p, pid: str, rid: str, seconds: int = 120) -> dict:
    r = {}
    for _ in range(seconds):
        r = next((x for x in state(p, pid).get("runs") or [] if x.get("id") == rid), {})
        if r.get("status") in ("done", "error"):
            return r
        time.sleep(1)
    return r


def deploy(p, pid: str, kind: str, seconds: int = 120) -> tuple[int, dict]:
    s, d = p.post(f"/api/projects/{pid}/deploy/{kind}")
    if s != 200:
        return s, d if isinstance(d, dict) else {"detail": d}
    return s, wait_run(p, pid, d["started"]["id"], seconds)


def plain(obj) -> bool:
    text = json.dumps(obj, ensure_ascii=False)
    return not any(ch in text for ch in BAD) and "Power BI Desktop" not in text


PLANT = r'''
import base64, json, os, time, zipfile
from app import db, store
TID, PID, NAME, REPORT = __ARGS__
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))
with db.use(TID):
    d = store.project_dir(PID)
    pb = d / "powerbi"
    rep = pb / f"{REPORT}.Report"
    files = {
        f"{REPORT}.pbip": json.dumps({"version": "1.0", "artifacts": [{"report": {"path": f"{REPORT}.Report"}}], "settings": {"enableAutoRecovery": True}}, indent=2),
        f"{REPORT}.Report/definition.pbir": json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": f"../{REPORT}.SemanticModel"}}}, indent=2),
        f"{REPORT}.Report/definition/version.json": json.dumps({"version": "2.0.0"}),
        f"{REPORT}.Report/definition/report.json": json.dumps({"themeCollection": {}}),
        f"{REPORT}.Report/definition/pages/pages.json": json.dumps({"pageOrder": ["ReportSection1", "ReportSection2"]}),
        f"{REPORT}.Report/definition/pages/ReportSection1/page.json": json.dumps({"name": "ReportSection1", "displayName": "Ventes \u00e9t\u00e9"}, ensure_ascii=False),
        f"{REPORT}.Report/definition/pages/ReportSection2/page.json": json.dumps({"name": "ReportSection2", "displayName": "Detail"}),
        f"{REPORT}.Report/definition/pages/ReportSection1/visuals/v1/visual.json": json.dumps({"visual": {"visualType": "card"}}),
        f"{REPORT}.SemanticModel/definition.pbism": json.dumps({"version": "1.0", "settings": {}}),
        f"{REPORT}.SemanticModel/model.bim": json.dumps({"name": "SemanticModel", "compatibilityLevel": 1567, "model": {"tables": [], "expressions": [
            {"name": "DataFolder", "kind": "m", "expression": [f'"{d}/data/" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]']}]}}, indent=2),
        f"{REPORT}.Report/.pbi/localSettings.json": "{}",
        f"{REPORT}.SemanticModel/.pbi/cache.abf": "DATA" * 50,
        f"{REPORT}.Report/sales.csv": "month,sales\n2026-01,1\n",
        f"{REPORT}.SemanticModel/extract.parquet": "PAR1",
        f"{REPORT}.Report/keys.pem": "-----BEGIN PRIVATE KEY-----",
        "data.csv": "x\n1\n",
        "Other.pbip": "{}",
    }
    for rel, text in files.items():
        (pb / rel).parent.mkdir(parents=True, exist_ok=True)
        (pb / rel).write_text(text, encoding="utf-8")
    (rep / "StaticResources/RegisteredResources").mkdir(parents=True, exist_ok=True)
    (rep / "StaticResources/RegisteredResources/logo.png").write_bytes(PNG)
    if not (rep / "linked.json").is_symlink():
        os.symlink("/etc/hostname", rep / "linked.json")
    pbix = b"PK\x03\x04 item70 stand-in pbix " + REPORT.encode() + bytes(range(256)) * 8
    with zipfile.ZipFile(d / f"{REPORT}.zip", "w") as z:
        z.writestr(f"{REPORT}/{REPORT}.pbix", pbix, compress_type=zipfile.ZIP_STORED)
        z.writestr(f"{REPORT}/data/sales.csv", "month,sales\n2026-01,1\n")
    st = store.load(PID)
    st.update(name=NAME, status="done", approved=1, error=None, job=None, finished=time.time(),
              versions=st.get("versions") or [{"v": 1, "when": time.time(), "created": time.time(), "summary": "Planted by item70_check",
                                               "pages": ["Overview", "Detail"], "visuals": 1, "measures": 1, "gates": []}],   # as the worker makes one
              output={"report": REPORT, "pbix": f"{REPORT}.pbix", "zip": f"{REPORT}.zip", "pbix_mb": 0.1, "pages": 2, "visuals": 1,
                      "measures": 1, "data_folder": f"C:\\D2D Relay Data\\{REPORT}\\data\\", "refreshed": True, "data_in_zip": True})
    store.save(st)
print(json.dumps({"pbix": base64.b64encode(pbix).decode(), "folder": str(d)}))
'''


def plant(tid: str, pid: str, name: str, report: str) -> dict:
    """A published dashboard as the worker leaves it (the test stack has no AI and no Power BI file maker), and files in
    its powerbi/ folder that are not the project."""
    return last_line(g.app(PLANT.replace("__ARGS__", json.dumps([tid, pid, name, report])))) or {}


def edit_files(tid: str, pid: str, report: str) -> str:
    """A changed visual and a removed page, as a change request would leave them."""
    return g.app(f"""
from app import db, store
with db.use({tid!r}):
    pb = store.project_dir({pid!r}) / "powerbi" / ({report!r} + ".Report") / "definition" / "pages"
    (pb / "ReportSection2" / "page.json").unlink()
    (pb / "ReportSection1" / "visuals" / "v1" / "visual.json").write_text('{{"visual": {{"visualType": "barChart"}}}}')
print("edited")
""")


def after_pbix(tid: str, pid: str, expect: int) -> list:
    """deploy.after_pbix as the worker calls it, in a process of its own inside the web container: it waits for the
    runs it started (their threads end with the process)."""
    out = g.app(f"""
import json, time
from app import db, deploy
with db.use({tid!r}):
    before = {{r["id"] for r in db.q("SELECT id FROM deploy_runs")}}
    deploy.after_pbix({pid!r})
    new = []
    for _ in range(150):
        new = [r for r in db.q("SELECT * FROM deploy_runs") if r["id"] not in before]
        if len(new) >= {expect} and all(r["status"] in ("done", "error") for r in new):
            break
        time.sleep(1)
    print(json.dumps([{{k: r[k] for k in ("kind", "via", "status", "error", "note", "url")}} for r in new]))
""")
    got = last_line(out)
    return got if isinstance(got, list) else [{"_out": out[-400:]}]


# ---------------------------------------------------------------- people

_ips = iter(f"198.18.70.{n}" for n in range(10, 60))


def person(email: str):
    p = c.Person(email)
    p.ip = next(_ips)
    return p


owner = person(f"opal.owner@deploy{STAMP}.com")
s, r = owner.sign_in("Deploy Test", "Opal Owner")
check("people: PASDACS creates an organisation; its owner signs in", s == 200, (s, r))
dev = person(f"dev.deploy@deploy{STAMP}.com")
s, r = dev.sign_in(person="Dev Deploy")
check("people: a colleague (a BI Dev) signs in", s == 200, (s, r))
other = person(f"oscar.owner@elsewhere{STAMP}.com")
s, r = other.sign_in("Elsewhere Deploy", "Oscar Owner")
check("people: another organisation's owner signs in", s == 200, (s, r))
tid = g.sql(f"SELECT tenant_id FROM relay.tn_orgs WHERE domain = 'deploy{STAMP}.com'")
schema = "t_" + tid.replace("-", "_")
anon = c.Person("nobody@example.com")

# ---------------------------------------------------------------- settings
s, _ = anon.get("/api/deploy/settings")
check("settings: the API needs a sign-in (401)", s == 401, s)
s, d = owner.get("/api/deploy/settings")
check("settings: an owner manages them; nothing set up yet", s == 200 and d.get("can_manage") is True and d["powerbi"]["connected"] is False
      and d["github"]["repo"] is None and d["github"]["has_token"] is False and d["github"]["folder"] == "d2d-relay"
      and d["github"]["secrets"] == ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "FABRIC_WORKSPACE_ID"], (s, d))
s, d = dev.get("/api/deploy/settings")
check("settings: a colleague reads them, cannot manage them", s == 200 and d.get("can_manage") is False, (s, d))
s, r = dev.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES}})
check("settings: only an owner changes them (403)", s == 403, (s, r))
s, r = owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES}})
check("powerbi: a workspace needs the Entra app first", s == 400 and "Connect Power BI first" in r.get("detail", ""), (s, r))
s, r = owner.get("/api/deploy/powerbi/workspaces")
check("powerbi: no workspaces to pick before the Entra app", s == 400, (s, r))
standin("/_test/reset", {})
s, r = owner.put("/api/semreview/pbi", {"tenant": "contoso.onmicrosoft.com", "client_id": CLIENT_ID, "client_secret": SECRET})
check("powerbi: the owner connects the Entra app (Semantic Review's)", s == 200 and r.get("configured"), (s, r))
s, ws = owner.get("/api/deploy/powerbi/workspaces")
check("powerbi: the app's workspaces to pick from", s == 200 and [w["name"] for w in ws.get("workspaces", [])] == ["Operations", "Sales BI"], (s, ws))
s, r = dev.get("/api/deploy/powerbi/workspaces")
check("powerbi: a colleague cannot list them (403)", s == 403, (s, r))
for body, word, what in (({"workspace_id": "not-a-guid"}, "not a workspace", "not a GUID"),
                         ({"workspace_id": "99999999-aaaa-4bbb-8ccc-000000000009"}, "does not see", "one the app does not see"),
                         ({"auto": True}, "Choose a workspace", "automatic without a workspace")):
    s, r = owner.put("/api/deploy/settings", {"powerbi": body})
    check(f"powerbi: refused: {what}", s == 400 and word in r.get("detail", ""), (s, r))
s, r = owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES, "auto": False}})
check("powerbi: the workspace is saved with its name", s == 200 and r["powerbi"]["workspace_name"] == "Sales BI" and r["powerbi"]["auto"] is False, (s, r))

# ---------------------------------------------------------------- a published dashboard (planted: the stack has no AI)
s, d = c.new_dashboard(owner)
pid = (d or {}).get("id")
check("dashboard: one is made", s == 200 and pid, (s, str(d)[:200]))
for _ in range(90):
    if (owner.get(f"/api/projects/{pid}")[1] or {}).get("status") == "error":
        break
    time.sleep(2)
s, r = owner.post(f"/api/projects/{pid}/deploy/powerbi")
check("dashboard: one not published yet is not deployed (409)", s == 409 and "published" in r.get("detail", ""), (s, r))
p1 = plant(tid, pid, "Deploy Sales", "Deploy Sales")
pbix1 = base64.b64decode(p1.get("pbix") or "")
check("dashboard: published, with its Power BI file and project (planted)", len(pbix1) > 2000, p1)
st = state(owner, pid)
check("dashboard: ready to publish, GitHub not set up yet", st.get("published") and st["powerbi"]["ready"] and not st["github"]["ready"]
      and "Set up the GitHub repository first" in (st["github"].get("why") or "") and st["can"] == {"deploy": True, "manage": True}, st)

# ---------------------------------------------------------------- Publish to Power BI
s, d = owner.post(f"/api/projects/{pid}/deploy/powerbi")
rid = (d or {}).get("started", {}).get("id")
check("publish: started", s == 200 and str(rid).startswith("dp-") and d["started"]["status"] in ("queued", "running"), (s, d))
s2, r2 = owner.post(f"/api/projects/{pid}/deploy/powerbi")
check("publish: one at a time (409)", s2 == 409 and "running already" in r2.get("detail", ""), (s2, r2))
run1 = wait_run(owner, pid, rid)
check("publish: done", run1.get("status") == "done", run1)
imps = standin("/_test/imports").get("imports", [])
imp = imps[0] if imps else {}
check("publish: the .pbix itself (out of the download zip) went to the Imports API, CreateOrOverwrite, named after the report",
      len(imps) == 1 and imp.get("name") == "Deploy Sales.pbix" and imp.get("nameConflict") == "CreateOrOverwrite"
      and imp.get("bytes") == len(pbix1) and base64.b64decode(imp.get("head") or "") == pbix1[:16], imps)
check("publish: report and dataset ids, the report's address, the workspace, who", run1.get("report_id") == imp.get("report")
      and run1.get("dataset_id") == imp.get("dataset") and run1.get("url") == f"https://app.powerbi.com/groups/{WS_SALES}/reports/{imp.get('report')}"
      and run1.get("target_name") == "Sales BI" and run1.get("by") == "Opal Owner" and run1.get("via") == "manual", run1)
check("publish: the import was polled until it succeeded", standin("/_test/state").get("import_poll", 0) >= 2)
left = g.sh(f"ls -A /data/projects/.tenants/{tid}/.deploy 2>/dev/null | wc -l")
check("publish: the .pbix taken out of the zip is gone", left.strip() in ("0", ""), left)
s, acts = owner.get(f"/api/projects/{pid}/activity")
acts = acts if isinstance(acts, list) else (acts or {}).get("events", acts)
texts = [e.get("text", "") for e in acts] if isinstance(acts, list) else []
check("publish: the dashboard's activity says so", any("Published to the Power BI service, workspace Sales BI" in t for t in texts), texts[-4:])
s, run2 = deploy(owner, pid, "powerbi")
check("publish again: the same report, overwritten", run2.get("status") == "done" and run2.get("report_id") == run1.get("report_id"), run2)
owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_OPS}})
s, run3 = deploy(owner, pid, "powerbi")
check("publish: a workspace the app may not publish to names Member or Contributor", run3.get("status") == "error"
      and "Member or Contributor" in (run3.get("error") or ""), run3)
owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES}})
n = g.sql(f"SELECT count(*) FROM {schema}.audit WHERE action IN ('deploy.powerbi', 'deploy.powerbi_done', 'deploy.powerbi_error')")
check("publish: audited (asked, done, failed)", n.isdigit() and int(n) >= 6, n)

# ---------------------------------------------------------------- GitHub
ghapi = (g.app("from app import deploy\nprint(deploy.GITHUB_API)").strip().splitlines() or [""])[-1]
github = check("github: the stack points the app at the stand-in (RELAY_GITHUB_API in tests/stack/docker-compose.yml)", ghapi == GITHUB_STANDIN, ghapi)
github = github and check("github: the stand-in GitHub API runs in the web container", start_github_standin())
pid2 = None
if not github:
    print("(the GitHub checks are skipped: they would reach the real GitHub)")
else:
    gh("/_test/reset", {})
    for body, word, what in (({"repo": "not a repo", "token": GOOD}, "owner and name", "a repository that is not owner/name"),
                             ({"repo": REPO, "token": "abc"}, "does not look like", "a token that is not one"),
                             ({"repo": REPO, "branch": "a..b", "token": GOOD}, "branch name", "a branch git cannot have"),
                             ({"repo": REPO, "folder": "../up", "token": GOOD}, "folder", "a folder outside the repository"),
                             ({"repo": REPO}, "Enter a token", "no token")):
        s, r = owner.put("/api/deploy/settings", {"github": body})
        check(f"github: refused: {what}", s == 400 and word in r.get("detail", ""), (s, r))
    s, r = dev.put("/api/deploy/settings", {"github": {"repo": REPO, "token": GOOD}})
    check("github: only an owner sets it up (403)", s == 403, (s, r))
    s, r = owner.put("/api/deploy/settings", {"github": {"repo": f"https://github.com/{REPO}.git", "branch": "main", "folder": "d2d-relay", "token": GOOD}})
    check("github: saved (a GitHub address is read as owner/name); the token is never sent back", s == 200 and r["github"]["repo"] == REPO
          and r["github"]["has_token"] and GOOD not in json.dumps(r), (s, r))
    s, r = dev.get("/api/deploy/settings")
    check("github: a colleague sees the repository, never the token", s == 200 and r["github"]["repo"] == REPO and GOOD not in json.dumps(r), r)
    enc = (g.app(f"from app import db, secrets_store\nwith db.use({tid!r}):\n    print(secrets_store._paths()[0])").strip().splitlines() or [""])[-1]
    kept = g.sh(f"grep -c {GOOD} '{enc}'; test -s '{enc}' && echo present")
    check("github: the token is kept encrypted", enc.endswith("secrets.enc") and kept.splitlines()[0].strip() == "0" and "present" in kept, (enc, kept))
    s, t = owner.post("/api/deploy/github/test", {})
    check("test: the saved settings reach the repository; the branch is there; no workflow yet", s == 200 and t.get("ok") and t.get("branch_exists")
          and t.get("workflow_exists") is False and t.get("repo") == REPO, (s, t))
    s, t = owner.post("/api/deploy/github/test", {"branch": "release/1"})
    check("test: a branch that the first push makes", s == 200 and t.get("branch_exists") is False and t.get("default_branch") == "main", (s, t))
    for body, word, what in (({"token": READONLY}, "Contents: Read and write", "a read-only token"),
                             ({"token": "github_pat_wrong_token_000000000000"}, "did not accept the token", "a wrong token"),
                             ({"repo": EMPTY_REPO}, "repository is empty", "an empty repository"),
                             ({"repo": "d2d-test/nope"}, "cannot find d2d-test/nope", "a repository the token cannot see")):
        s, r = owner.post("/api/deploy/github/test", body)
        check(f"test: {what} is named as such", s == 400 and word in r.get("detail", ""), (s, r))
    s, r = dev.post("/api/deploy/github/test", {})
    check("test: only an owner tests (403)", s == 403, (s, r))

    s, push1 = deploy(owner, pid, "github")
    files = repo_files(REPO)
    head = gh(f"/_test/files?repo={quote(REPO, safe='')}&branch=main").get("head")
    base = "d2d-relay/Deploy Sales/"
    check("push: done; the commit is the branch's head, with its address", push1.get("status") == "done" and push1.get("commit_sha") == head
          and push1.get("url") == f"https://github.com/{REPO}/commit/{head}" and push1.get("path") == "d2d-relay/Deploy Sales", push1)
    want = {base + x for x in ("Deploy Sales.pbip", ".gitignore", "Deploy Sales.Report/.platform", "Deploy Sales.SemanticModel/.platform",
                               "Deploy Sales.Report/definition.pbir", "Deploy Sales.Report/definition/report.json",
                               "Deploy Sales.Report/definition/pages/ReportSection2/page.json",
                               "Deploy Sales.Report/definition/pages/ReportSection1/visuals/v1/visual.json",
                               "Deploy Sales.Report/StaticResources/RegisteredResources/logo.png",
                               "Deploy Sales.SemanticModel/definition.pbism", "Deploy Sales.SemanticModel/model.bim")}
    check("push: the Power BI project is there", want <= set(files), sorted(want - set(files)))
    check("push: nothing that is not the project (data, local settings, keys, links, other files)",
          not any(x in p for p in files for x in (".pbi/", ".csv", ".parquet", ".pem", "linked.json", "Other.pbip")), sorted(files))
    check("push: the repository's own files stay (README)", "README.md" in files)
    check("push: a binary file as it is", files.get(base + "Deploy Sales.Report/StaticResources/RegisteredResources/logo.png") == b"\x89PNG\r\n\x1a\n" + bytes(range(64)))
    check("push: text in other scripts as it is", "Ventes \u00e9t\u00e9" in files.get(base + "Deploy Sales.Report/definition/pages/ReportSection1/page.json", b"").decode("utf-8", "replace"))
    plat = json.loads(files.get(base + "Deploy Sales.Report/.platform") or b"{}")
    check("push: .platform files in Fabric's Git format (so fabric-cicd finds the items)", plat.get("metadata") == {"type": "Report", "displayName": "Deploy Sales"}
          and plat.get("config", {}).get("version") == "2.0" and len(plat.get("config", {}).get("logicalId", "")) == 36, plat)
    bim = files.get(base + "Deploy Sales.SemanticModel/model.bim", b"")
    check("push: the model's DataFolder as the .pbix has it, never the server's folder", b"/data/projects" not in bim
          and b'C:\\\\D2D Relay Data\\\\Deploy Sales\\\\data\\\\' in bim, bim[:300])
    wf = files.get(WORKFLOW, b"").decode("utf-8", "replace")
    check("push: the workflow is added for this branch and folder, with fabric-cicd and the four secrets", 'branches: ["main"]' in wf and 'D2D_FOLDER: "d2d-relay"' in wf
          and "fabric-cicd==" in wf and all(f"secrets.{k}" in wf for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "FABRIC_WORKSPACE_ID")), wf[:300])
    check("push: the workflow in plain keyboard characters", wf and all(ord(ch) < 128 for ch in wf), [ch for ch in wf if ord(ch) >= 128][:5])
    check("push: the record says what was added and left out", "workflow was added" in (push1.get("note") or "") and "Left out" in (push1.get("note") or ""), push1.get("note"))
    before = gh("/_test/state")
    s, push2 = deploy(owner, pid, "github")
    after = gh("/_test/state")
    check("push again: already up to date, no new commit", push2.get("status") == "done" and push2.get("commit_sha") == push1.get("commit_sha")
          and "Already up to date" in (push2.get("note") or "") and after.get("POST /git/commits") == before.get("POST /git/commits"), (push2, before, after))
    gh("/_test/commit", {"repo": REPO, "files": {WORKFLOW: "# the BI team's own version\n"}})
    check("change: a page removed and a visual changed in the dashboard", edit_files(tid, pid, "Deploy Sales").endswith("edited"))
    gh("/_test/race", {"repo": REPO})
    s, push3 = deploy(owner, pid, "github")
    files = repo_files(REPO)
    check("push: someone else pushed meanwhile: started again on top of theirs (never forced)", push3.get("status") == "done" and "external.txt" in files, push3)
    check("push: the removed page is removed, the changed visual changed", base + "Deploy Sales.Report/definition/pages/ReportSection2/page.json" not in files
          and b"barChart" in files.get(base + "Deploy Sales.Report/definition/pages/ReportSection1/visuals/v1/visual.json", b""), sorted(files)[:12])
    check("push: the workflow is added once: the BI team's version stays", files.get(WORKFLOW) == b"# the BI team's own version\n")

    # a second dashboard of the same name (its report fails to import, below)
    s, d2 = c.new_dashboard(owner)
    pid2 = (d2 or {}).get("id")
    for _ in range(90):
        if (owner.get(f"/api/projects/{pid2}")[1] or {}).get("status") == "error":
            break
        time.sleep(2)
    plant(tid, pid2, "Deploy Sales", "Broken Sales")
    s, push4 = deploy(owner, pid2, "github")
    files = repo_files(REPO)
    check("push: a second dashboard of the same name gets a folder of its own", push4.get("status") == "done"
          and push4.get("path") == f"d2d-relay/Deploy Sales ({pid2})" and f"d2d-relay/Deploy Sales ({pid2})/Broken Sales.pbip" in files
          and base + "Deploy Sales.pbip" in files, push4)

    # a token without the Workflows permission, a new branch, a nested folder; then a token with it
    s, r = owner.put("/api/deploy/settings", {"github": {"repo": REPO2, "branch": "release/1", "folder": "bi/d2d", "token": NOWORKFLOW}})
    s, push5 = deploy(owner, pid, "github")
    files = repo_files(REPO2, "release/1")
    check("no Workflows permission: the dashboard is pushed to a new branch, the workflow is not, and the record says why",
          push5.get("status") == "done" and "bi/d2d/Deploy Sales/Deploy Sales.pbip" in files and WORKFLOW not in files
          and "workflow was not added" in (push5.get("note") or "") and "made from main" in (push5.get("note") or ""), push5)
    s, r = owner.put("/api/deploy/settings", {"github": {"repo": REPO2, "branch": "release/1", "folder": "bi/d2d", "token": GOOD}})
    s, push6 = deploy(owner, pid, "github")
    files = repo_files(REPO2, "release/1")
    check("then with Workflows: the workflow alone is added, for that branch and folder", push6.get("status") == "done" and WORKFLOW in files
          and 'branches: ["release/1"]' in files[WORKFLOW].decode() and 'D2D_FOLDER: "bi/d2d"' in files[WORKFLOW].decode()
          and "workflow was added" in (push6.get("note") or ""), push6)
    check("settings: the workflow is known to be in that repository", ((owner.get("/api/deploy/settings")[1] or {}).get("github") or {}).get("workflow_added") is True)
    edit = g.app(f"""
from app import db, store
with db.use({tid!r}):
    (store.project_dir({pid!r}) / "powerbi" / "Deploy Sales.Report" / "definition" / "report.json").write_text('{{"changed": true}}')
print("edited")
""")
    owner.put("/api/deploy/settings", {"github": {"repo": REPO2, "branch": "release/1", "folder": "bi/d2d", "token": READONLY}})
    s, push7 = deploy(owner, pid, "github")
    check("push: a read-only token says what it needs", edit.endswith("edited") and push7.get("status") == "error"
          and "Contents: Read and write" in (push7.get("error") or ""), push7)
    owner.put("/api/deploy/settings", {"github": {"repo": EMPTY_REPO, "token": GOOD}})
    s, push8 = deploy(owner, pid, "github")
    check("push: an empty repository says what to do", push8.get("status") == "error" and "repository is empty" in (push8.get("error") or ""), push8)
    owner.put("/api/deploy/settings", {"github": {"repo": REPO, "branch": "main", "folder": "d2d-relay", "token": GOOD}})

# ---------------------------------------------------------------- a failed import
if pid2:
    s, run4 = deploy(owner, pid2, "powerbi")
    check("publish: an import the service refuses says why", run4.get("status") == "error" and "PackageNotSupported" in (run4.get("error") or ""), run4)

# ---------------------------------------------------------------- automatic (deploy.after_pbix, as the worker calls it)
s, r = owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES, "auto": True}})
if github:
    s2, r2 = owner.put("/api/deploy/settings", {"github": {"repo": REPO, "branch": "main", "folder": "d2d-relay", "auto": True}})
    check("auto: switched on for both", s == 200 and s2 == 200 and r2["powerbi"]["auto"] and r2["github"]["auto"], (s, r, s2, r2))
autos = after_pbix(tid, pid, 2 if github else 1)
check("auto: the Power BI file made: published" + (" and pushed" if github else ""), len(autos) == (2 if github else 1)
      and all(a.get("via") == "auto" and a.get("status") == "done" for a in autos), autos)
st = state(owner, pid)
check("auto: shown on the dashboard as automatic", any(x["via"] == "auto" and x["by"] is None for x in st.get("runs", [])), st.get("runs", [])[:3])
owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES, "auto": False}})
if github:
    owner.put("/api/deploy/settings", {"github": {"repo": REPO, "branch": "main", "folder": "d2d-relay", "auto": False}})
check("auto off: nothing happens", after_pbix(tid, pid, 0) == [])
owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES, "auto": True}})
owner.delete("/api/semreview/pbi")
refused = after_pbix(tid, pid, 1)
check("auto: what cannot start is recorded on the dashboard (no Entra app)", len(refused) == 1 and refused[0].get("status") == "error"
      and "Connect Power BI first" in (refused[0].get("error") or ""), refused)
owner.put("/api/semreview/pbi", {"tenant": "contoso.onmicrosoft.com", "client_id": CLIENT_ID, "client_secret": SECRET})
owner.put("/api/deploy/settings", {"powerbi": {"workspace_id": WS_SALES, "auto": False}})

# ---------------------------------------------------------------- who may do what
s, r = dev.get(f"/api/projects/{pid}/deploys")
check("access: a colleague the dashboard is not shared with does not see it (404)", s == 404, (s, r))
s, org = owner.get("/api/org")
dev_id = next((x["id"] for x in org.get("people", []) if x["email"] == dev.email), None)
owner.put(f"/api/projects/{pid}/shares", {"visibility": "private", "shares": [{"principal_type": "user", "principal_id": dev_id, "permission": "view"}]})
st = state(dev, pid)
check("access: shared to view: the colleague sees the deployments, may not run them", st.get("runs") and st["can"] == {"deploy": False, "manage": False}, st.get("can"))
s, r = dev.post(f"/api/projects/{pid}/deploy/powerbi")
check("access: ... and Publish is refused (403)", s == 403, (s, r))
owner.put(f"/api/projects/{pid}/shares", {"visibility": "private", "shares": [{"principal_type": "user", "principal_id": dev_id, "permission": "edit"}]})
s, run5 = deploy(dev, pid, "powerbi")
check("access: shared to edit: a BI Dev publishes it", run5.get("status") == "done" and run5.get("by") == "Dev Deploy", run5)
s, r = other.get(f"/api/projects/{pid}/deploys")
check("access: another organisation does not see it (404)", s == 404, (s, r))
s, r = other.get("/api/deploy/settings")
check("access: another organisation has settings of its own", s == 200 and r["powerbi"]["workspace_id"] is None and r["github"]["repo"] is None, r)
s, r = anon.post(f"/api/projects/{pid}/deploy/github")
check("access: nobody signed in deploys nothing (401)", s == 401, (s, r))

# ---------------------------------------------------------------- a run cut off by a restart
g.sql(f"INSERT INTO {schema}.deploy_runs (id, project_id, kind, via, status, step, created) VALUES "
      f"('dp-cutoff70000', '{pid}', 'github', 'manual', 'running', 'Pushing to GitHub', {time.time() - 4 * 3600})")
cut = next((x for x in state(owner, pid).get("runs", []) if x["id"] == "dp-cutoff70000"), {})
check("restart: a run from before the restart is shown as stopped", cut.get("status") == "error" and "restarted" in (cut.get("error") or ""), cut)

# ---------------------------------------------------------------- texts
st = state(owner, pid)
check("texts: plain keyboard characters, never Power BI Desktop (runs, settings)", plain(st) and plain(owner.get("/api/deploy/settings")[1]), "")
js = open(os.path.join(os.path.dirname(os.path.dirname(HERE)), "webapp", "static", "js", "44-deploy.js"), encoding="utf-8").read()
check("texts: the screens' file is plain keyboard characters and never says Power BI Desktop", all(ord(ch) < 128 for ch in js) and "Power BI Desktop" not in js)

# ---------------------------------------------------------------- the screens in Chromium
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
owner_cookie, dev_cookie, pid = sys.argv[1], sys.argv[2], sys.argv[3]
BAD = "\u2014\u2013\u2018\u2019\u201c\u201d\u2192\u2022\u2026\u00b7"
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    for who, cookie, width in (("owner", owner_cookie, 1280), ("owner", owner_cookie, 360), ("dev", dev_cookie, 1280)):
        ctx = b.new_context(viewport={"width": width, "height": 900})
        ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        tag, r = f"{who}-{width}", {}
        pg.goto(f"http://127.0.0.1:8000/#/p/{pid}")
        pg.wait_for_timeout(5000)
        r["loaded"] = pg.evaluate("typeof deployCard === 'function' && typeof deploySettings === 'function'")
        r["on_overview"] = pg.locator(".depcard").count() > 0
        if r["on_overview"]:
            pg.screenshot(path=f"/tmp/item70-overview-{tag}.png", full_page=True)
        if r["loaded"]:
            pg.goto("http://127.0.0.1:8000/#/org")
            pg.wait_for_timeout(3000)
            errors.clear()
            pg.evaluate("(pid) => document.querySelector('#main').replaceChildren(h('div', {class: 'page', id: 'deptest'}, deployCard({id: pid, status: 'done'}), deploySettings()))", pid)
            pg.wait_for_selector("#deptest .depgrid", timeout=15000)
            pg.wait_for_selector("#deptest .depset h3:has-text('CI/CD with GitHub')", timeout=15000)
            pg.wait_for_timeout(2000)
            text = pg.inner_text("#deptest")
            r.update(text=text, inputs=pg.locator("#deptest .depset input").count(),
                     buttons=[x.strip() for x in pg.locator("#deptest .depcard button").all_inner_texts()],
                     css=pg.evaluate("getComputedStyle(document.querySelector('#deptest .depgrid')).display"),
                     wide=pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
                     bad=[ch for ch in text if ch in BAD], errors=list(errors))
            pg.screenshot(path=f"/tmp/item70-{tag}.png", full_page=True)
        out[tag] = r
        ctx.close()
    b.close()
print(json.dumps(out))
"""
cookie_of = lambda p: next((k.value for k in p.jar if k.name == "d2d_session"), "")   # noqa: E731
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie_of(owner), cookie_of(dev), pid], input=PLAY, capture_output=True,
                     text=True, encoding="utf-8", errors="replace", timeout=300)
ui = last_line(res.stdout) or {}
for name in ("owner-1280", "owner-360", "dev-1280"):
    for shot in (f"item70-{name}.png", f"item70-overview-{name}.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{shot}", c.out_path(shot)], capture_output=True)
o, n, m = ui.get("owner-1280") or {}, ui.get("owner-360") or {}, ui.get("dev-1280") or {}
check("ui: 44-deploy.js and deploy.css are in the app (index.html)", o.get("loaded") is True and o.get("css") == "grid", (o.get("loaded"), o.get("css"), res.stderr[-300:]))
check("ui: a published dashboard's Overview shows the Deploy card (06-project.js)", o.get("on_overview") is True, o.get("on_overview"))
check("ui: the owner's card offers both, with the workspace and the repository", "Publish to Power BI" in (o.get("buttons") or [])
      and "Push to GitHub" in (o.get("buttons") or []) and "Workspace: Sales BI" in (o.get("text") or "") and REPO in (o.get("text") or ""), o.get("buttons"))
check("ui: the owner's settings have their fields (repository, branch, folder, token, both switches)", (o.get("inputs") or 0) >= 6, o.get("inputs"))
check("ui: a colleague reads the settings (no fields)", m.get("inputs") == 0 and "An owner of your organisation changes these." in (m.get("text") or ""), m.get("inputs"))
check("ui: at 360 px nothing is wider than the screen", n.get("wide") is True, n.get("wide"))
check("ui: no script errors; plain keyboard characters; never Power BI Desktop, null or undefined",
      all(x and not x.get("errors") and not x.get("bad") and not any(w in (x.get("text") or "") for w in ("Power BI Desktop", "null", "undefined"))
          for x in (o, n, m)), [(k, (v or {}).get("errors"), (v or {}).get("bad")) for k, v in ui.items()])

bad = [nm for nm, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
