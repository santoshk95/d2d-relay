"""Test stack only: items 46 and 47 (2026-11-14).
Item 46, the user: "Add parallel builds" (and "power bi pbix file will be sequence only as it run in the same windows
machine"):
- the worker runs up to PARALLEL (3) jobs at once, never two of one dashboard, oldest first;
- publishing (pbi, pbix: Power BI on this PC) runs one at a time, outside the three AI slots;
- the AI engine takes 3 runs in the build lane and 1 in the chat lane, and says so on /health.
Item 47, the user: "in API use opus 5.5 as default and same in personal as well dont use any other model for Relay
Model powered by claude":
- the web app's default model and Ask Relay's are the Relay Model; the AI engine's default too;
- the Relay Model is served by claude-opus-5-5; the catalog's own default is claude-opus-5-5.
The worker is driven with stand-in jobs (no AI): each sleeps, and the check records what ran at once.
python -I -X utf8 item46_check.py <public> <admin>"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

check = c.check

# ---------------------------------------------------------------- item 46: the worker's slots
out = g.app("""
import asyncio, json, time
from app import worker

T0 = time.time()
queue = [  # (job id, project, kind): oldest first; a2 is a second job of project a
    ("j-a1", "a", "plan"), ("j-b", "b", "plan"), ("j-c", "c", "build"), ("j-a2", "a", "revise"),
    ("j-d", "d", "plan"), ("j-e", "e", "pbix"), ("j-f", "f", "pbi")]
rows = [{"id": j, "pid": p, "kind": k, "model": "relay", "owner_id": "u-t", "created": i, "args": "{}", "tenant": _db.PLATFORM}
        for i, (j, p, k) in enumerate(queue)]
began, spans, now_ai, now_serial, peak = set(), [], [0], [0], {"ai": 0, "serial": 0, "all": 0}


def waiting():                                  # what is still queued: a job leaves the queue when it starts
    return [r for r in rows if r["id"] not in began]


async def fake_run(pid, kind, args):
    jid = next(r["id"] for r in rows if r["pid"] == pid and r["kind"] == kind)
    began.add(jid)
    serial = kind in worker.SERIAL
    (now_serial if serial else now_ai)[0] += 1
    peak["ai"], peak["serial"] = max(peak["ai"], now_ai[0]), max(peak["serial"], now_serial[0])
    peak["all"] = max(peak["all"], now_ai[0] + now_serial[0])
    start = time.time() - T0
    await asyncio.sleep(0.6)
    (now_serial if serial else now_ai)[0] -= 1
    spans.append([jid, pid, kind, round(start, 2), round(time.time() - T0, 2)])


worker._waiting_rows = waiting
worker._run = fake_run
worker._finish = lambda jid, pid: None


async def main():
    loop_task = asyncio.create_task(worker.worker_loop())
    for _ in range(80):
        await asyncio.sleep(0.1)
        if len(spans) == len(rows):
            break
    loop_task.cancel()
    await asyncio.sleep(0.2)


asyncio.run(main())
print(json.dumps({"parallel": worker.PARALLEL, "spans": sorted(spans, key=lambda s: s[3]), "peak": peak,
                  "took": round(time.time() - T0, 2), "left": len(worker.RUNNING)}))
""")
try:
    r = json.loads(out.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {}
spans = r.get("spans") or []
check("slots: the stand-in queue ran, all seven jobs", len(spans) == 7, out[-800:])
check("slots: three builds at once (PARALLEL 3), never more", r.get("parallel") == 3 and (r.get("peak") or {}).get("ai") == 3, r.get("peak"))
check("slots: publishing ran one at a time, beside the builds", (r.get("peak") or {}).get("serial") == 1 and (r.get("peak") or {}).get("all") == 4,
      r.get("peak"))


def overlap(a, b):
    return a[3] < b[4] - 0.01 and b[3] < a[4] - 0.01


same_pid = [(a[0], b[0]) for i, a in enumerate(spans) for b in spans[i + 1:] if a[1] == b[1] and overlap(a, b)]
check("slots: never two jobs of one dashboard at once (a's change waits for its plan)", not same_pid and len([s for s in spans if s[1] == "a"]) == 2,
      same_pid)
by = {s[0]: s for s in spans}
first = {s[0] for s in spans if s[3] < 0.3}
check("slots: the oldest builds start at once (a1, b, c), and publishing e beside them", first == {"j-a1", "j-b", "j-c", "j-e"}, sorted(first))
check("slots: d waits for a free build slot, a2 for a1, publishing f for e", len(by) == 7
      and by["j-d"][3] >= min(by[j][4] for j in ("j-a1", "j-b", "j-c")) - 0.01 and by["j-a2"][3] >= by["j-a1"][4] - 0.01
      and by["j-f"][3] >= by["j-e"][4] - 0.01, spans)
check("slots: side by side it took far less than one at a time (7 x 0.6 s)", 0 < (r.get("took") or 99) < 2.6 and r.get("left") == 0,
      (r.get("took"), r.get("left")))

# ---------------------------------------------------------------- item 46: the AI engine's lanes
eng = subprocess.run(["docker", "exec", c.WEB_C, "curl", "-s", "--max-time", "10", "http://127.0.0.1:8090/health"], capture_output=True, text=True)
try:
    h = json.loads(eng.stdout)
except ValueError:
    h = {}
check("engine: the build lane takes 3 runs at once, the chat lane 1", h.get("capacity") == {"build": 3, "chat": 1}, h.get("capacity"))
check("engine: it says how many run now (none here) and is not busy", h.get("runs") == {"build": 0, "chat": 0} and h.get("busy") is False,
      (h.get("runs"), h.get("busy")))

# ---------------------------------------------------------------- item 47: one model, Claude Opus 5.5
check("model: the AI engine's default is the Relay Model", h.get("model") == "relay", h.get("model"))
out = g.app("""
import json
from app import worker, askd
house = json.loads(worker.CATALOG.with_name("house-models.json").read_text(encoding="utf-8"))["models"]
cat = json.loads(worker.CATALOG.read_text(encoding="utf-8"))
print(json.dumps({"default": worker.DEFAULT_MODEL, "ask": askd.models_for("u-item46")["default"],
                  "targets": {m["id"]: m.get("target") for m in house}, "catalog": cat.get("default"),
                  "fallback": worker.FALLBACK["default"]}))
""")
try:
    m = json.loads(out.strip().splitlines()[-1])
except (ValueError, IndexError):
    m = {}
check("model: new dashboards and Ask Relay both use the Relay Model", m.get("default") == "relay" and m.get("ask") == "relay", m or out[-400:])
check("model: the Relay Model is served by claude-opus-5-5, and it is the only house model", m.get("targets") == {"relay": "claude-opus-5-5"},
      m.get("targets"))
check("model: the catalog's own default and the last fallback are claude-opus-5-5", m.get("catalog") == "claude-opus-5-5"
      and m.get("fallback") == "claude-opus-5-5", (m.get("catalog"), m.get("fallback")))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
