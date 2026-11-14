"""Test stack only: item 49 (2026-11-14). A finished live job container (exited 0) had been left behind after its
stream went away; the runner removed leftovers only when it started, and the leftover kept a test stack from starting.
Now the runner also removes, every two minutes, its own job containers that ended more than five minutes before.
- tidy_once removes this stack's ended job containers (and one created but never started);
- it leaves a running job of this stack alone, and another stack's ended job alone;
- with the five-minute grace, a job that has just ended is left for its stream to remove.
Stand-in containers (the stack's own image, /bin/true or sleep) carry the job labels; no AI.
python -I -X utf8 item49_check.py <public> <admin>"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check
RUNNER = os.environ.get("D2D_TEST_RUNNER", "d2d-relay-test-runner")


def docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


img = docker("inspect", "-f", "{{.Config.Image}}", c.WEB_C).stdout.strip()
web = docker("inspect", "-f", "{{.Name}}", c.WEB_C).stdout.strip().lstrip("/")
names = {k: f"d2d-relay-test-tidy-{k}-{c.STAMP}" for k in ("ended", "created", "running", "other", "fresh")}


def job(name: str, web_label: str, *, start: bool, cmd: str = "/bin/true") -> None:
    docker("create", "--name", name, "--label", "d2d-relay.job=1", "--label", f"d2d-relay.web={web_label}",
           "--label", "d2d-relay.cwd=/data/projects/tidy-x1", "--entrypoint", cmd, img, *(["3600"] if cmd == "sleep" else []))
    if start:
        docker("start", name)


def tidy(max_age: float) -> list[str]:
    code = ("import asyncio, importlib.machinery, json, sys; "
            "jr = importlib.machinery.SourceFileLoader('jr', '/opt/relay/bin/job-runner').load_module(); "
            f"print(json.dumps(asyncio.run(jr.tidy_once({max_age}))))")
    r = docker("exec", RUNNER, "/usr/local/bin/python3", "-c", code)
    try:
        return json.loads((r.stdout.strip().splitlines() or ["null"])[-1]) or []
    except ValueError:
        print(r.stdout[-500:], r.stderr[-800:], flush=True)
        return []


def exists(name: str) -> bool:
    return bool(docker("ps", "-aq", "--filter", f"name=^{name}$").stdout.strip())


try:
    job(names["ended"], web, start=True)                       # this stack's job that ended
    job(names["created"], web, start=False)                    # this stack's job created but never started
    job(names["running"], web, start=True, cmd="sleep")        # this stack's job still running
    job(names["other"], "d2d-relay-test-other-web", start=True)  # another stack's job that ended
    docker("wait", names["ended"])
    docker("wait", names["other"])
    check("setup: five stand-in job containers (this stack's ended, never started, running; another stack's)",
          all(exists(n) for n in (names["ended"], names["created"], names["running"], names["other"])), names)
    gone = tidy(300)
    check("grace: within five minutes of ending nothing is removed (its stream may still be reading)", gone == []
          and exists(names["ended"]), gone)
    gone = tidy(0)
    check("tidy: this stack's ended job is removed", names["ended"] in gone and not exists(names["ended"]), gone)
    check("tidy: so is one created but never started", names["created"] in gone and not exists(names["created"]), gone)
    check("tidy: a running job of this stack is left alone", names["running"] not in gone and exists(names["running"]), gone)
    check("tidy: another stack's ended job is left alone", names["other"] not in gone and exists(names["other"]), gone)
    check("tidy: the runner's code holds the two-minute tidy (item 49)", "tidy_once" in docker("exec", RUNNER, "cat", "/opt/relay/bin/job-runner").stdout,
          "no tidy_once in the runner")
finally:
    docker("rm", "-f", *names.values())
check("cleanup: no stand-in is left", not docker("ps", "-aq", "--filter", "name=d2d-relay-test-tidy-").stdout.strip(),
      docker("ps", "-a", "--filter", "name=d2d-relay-test-tidy-", "--format", "{{.Names}}").stdout)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
