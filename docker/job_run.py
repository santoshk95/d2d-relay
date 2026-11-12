#!/usr/local/bin/python3
"""Inside a job container (docker/job_runner.py): `job-run <prompt file> claude <args...>` gives claude the prompt on its
standard input, from the file the job runner put in the container, and deletes the file first."""
import os
import sys


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[2] != "claude":
        sys.exit("usage: job-run <prompt file> claude <args...>")
    # what the AI writes stays group-writable for the web app (relaydata), as the AI engine's own umask (supervisord, 002)
    os.umask(0o002)
    fd = os.open(sys.argv[1], os.O_RDONLY)
    os.unlink(sys.argv[1])
    os.dup2(fd, 0)
    os.close(fd)
    os.execvp("claude", sys.argv[2:])


if __name__ == "__main__":
    main()
