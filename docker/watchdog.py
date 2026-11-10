#!/usr/local/bin/python3
"""Relay's watchdog: a supervisor event listener (stdout is the supervisor's protocol channel; messages go to stderr).

- A part that cannot start (FATAL: it exited again and again right after starting) stops the whole container, so
  Docker's restart policy starts everything fresh instead of leaving Relay half up.
- Every minute the web app and the AI engine must answer their health checks. A part that is running but has not
  answered for 5 minutes in a row is restarted: a process that hangs does not exit by itself.
"""
import configparser
import os
import sys
import time
import urllib.request

from supervisor import childutils

CONF = os.environ.get("RELAY_SUPERVISOR_CONF", "/run/relay/supervisord.conf")
PROBES = {"web": "http://127.0.0.1:8000/healthz", "agent": "http://127.0.0.1:8090/health"}
CRITICAL = {"web", "agent", "database"}
MISSES = 5          # minutes without an answer before a restart
GRACE_S = 240       # a part that started less than this long ago is not judged yet


def say(msg: str) -> None:
    print(f"watchdog: {msg}", file=sys.stderr, flush=True)


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001 - any failure is a missed answer
        return False


def control_env() -> dict:
    """The supervisor tells an event listener where its control socket is, but not the socket's user and password
    (relay-init writes a new one into the running config at every start): read them from there."""
    env = dict(os.environ)
    conf = configparser.RawConfigParser()
    try:
        conf.read(CONF, encoding="utf-8")
        env.setdefault("SUPERVISOR_USERNAME", conf.get("supervisorctl", "username", fallback=""))
        env.setdefault("SUPERVISOR_PASSWORD", conf.get("supervisorctl", "password", fallback=""))
        env.setdefault("SUPERVISOR_SERVER_URL", conf.get("supervisorctl", "serverurl", fallback="unix:///run/relay/supervisor.sock"))
    except (OSError, configparser.Error) as e:
        say(f"could not read the control socket's sign-in from {CONF}: {e}")
    return env


def main() -> None:
    rpc = childutils.getRPCInterface(control_env())
    missed = {name: 0 for name in PROBES}
    while True:
        headers, payload = childutils.listener.wait(sys.stdin, sys.stdout)
        try:
            event = headers.get("eventname", "")
            if event == "PROCESS_STATE_FATAL":
                info, _ = childutils.eventdata(payload + "\n")
                name = info.get("processname")
                if name in CRITICAL:
                    say(f"{name} could not start after several tries: stopping the container so Docker starts it fresh")
                    rpc.supervisor.shutdown()
            elif event.startswith("TICK"):
                for name, url in PROBES.items():
                    p = rpc.supervisor.getProcessInfo(name)
                    if p.get("statename") != "RUNNING" or time.time() - p.get("start", 0) < GRACE_S:
                        missed[name] = 0
                        continue
                    missed[name] = 0 if answers(url) else missed[name] + 1
                    if missed[name] >= MISSES:
                        say(f"{name} has not answered its health check for {MISSES} minutes: restarting it")
                        rpc.supervisor.stopProcess(name, True)
                        rpc.supervisor.startProcess(name, False)
                        missed[name] = 0
        except Exception as e:  # noqa: BLE001 - the watchdog must keep listening
            say(f"could not handle {headers.get('eventname')}: {e.__class__.__name__}: {e}")
        childutils.listener.ok(sys.stdout)


if __name__ == "__main__":
    main()
