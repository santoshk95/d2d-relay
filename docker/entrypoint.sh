#!/bin/bash
# RELAY by PASDACS: the container's entrypoint (under tini).
#   start (default)   prepare /data and the database (relay-init), then run every part under the supervisor
#   anything else     run that command instead, e.g. `relay-ctl status` or `relay-ctl stage-import <dump>`
set -euo pipefail

if [ "${1:-start}" != "start" ]; then
  exec "$@"
fi

if [ "$(id -u)" != "0" ]; then
  echo "relay: the container must start as root; each part then runs as its own user. Remove the --user option." >&2
  exit 1
fi

/opt/relay/bin/relay-init

# The supervisor starts with a clean environment: each part gets only its own settings from /run/relay/env
# (docker/launch.py), never the whole container environment.
exec env -i PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONUNBUFFERED=1 TZ="${TZ:-UTC}" \
  /usr/local/bin/supervisord --nodaemon --configuration /run/relay/supervisord.conf
