#!/usr/local/bin/python3
"""Start one part of Relay with exactly its own environment.

    launch <part> <command> [args...]

The supervisor runs this as the part's own user. The environment comes from /run/relay/env/<part>.json, written by
relay-init at start-up and readable only by that user. The web app first waits for the database to accept connections.
"""
import json
import os
import subprocess
import sys
import time

PG_READY = "/usr/lib/postgresql/17/bin/pg_isready"


def wait_for_database(env: dict, limit_s: int = 180) -> None:
    if env.get("RELAY_DB") != "embedded":
        return
    end = time.time() + limit_s
    while time.time() < end:
        r = subprocess.run([PG_READY, "-q", "-h", "/run/postgresql", "-d", "relay", "-U", "relay_app"], env=env)
        if r.returncode == 0:
            return
        time.sleep(1)
    print(f"launch: the database did not accept connections within {limit_s} s; starting anyway", file=sys.stderr, flush=True)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: launch <part> <command> [args...]")
    part, cmd = sys.argv[1], sys.argv[2:]
    try:
        with open(f"/run/relay/env/{part}.json", encoding="utf-8") as f:
            env = json.load(f)
    except OSError as e:
        sys.exit(f"launch: no settings for {part} ({e.strerror}); relay-init writes them at start-up")
    if part == "web":
        wait_for_database(env)
    os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
