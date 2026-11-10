#!/usr/bin/env bash
# RELAY by PASDACS on Linux or macOS: start, stop and look after Relay (one container). On Windows use relay.cmd.
#   ./relay.sh start | stop | restart | status | logs | backup | export | import <file> | login | open | load <file>
set -euo pipefail
cd "$(dirname "$0")"
val() { [ -f .env ] && sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"\{0,1\}\([^\"]*\)\"\{0,1\}[[:space:]]*$/\1/p" .env | tail -1 || true; }
PORT="$(val RELAY_PORT)"; PORT="${PORT:-8000}"
URL="http://127.0.0.1:$PORT"

files() {
  local lan; lan="$(val RELAY_LAN_IP)"
  echo "-f docker-compose.yml"
  if [ -n "$lan" ] && [ -f docker-compose.lan.yml ]; then
    if (ip -o addr 2>/dev/null || ifconfig 2>/dev/null) | grep -q "[^0-9]$lan[^0-9]"; then echo "-f docker-compose.lan.yml"
    else echo "The address $lan is not on this machine right now: Relay starts on $URL only." >&2; fi
  fi
}

volumes() {
  for pair in "RELAY_CLAUDE_EXTERNAL RELAY_CLAUDE_VOLUME" "RELAY_AGY_EXTERNAL RELAY_AGY_VOLUME"; do
    set -- $pair
    if [ "$(val "$1")" = true ] && [ -n "$(val "$2")" ]; then docker volume inspect "$(val "$2")" >/dev/null 2>&1 || docker volume create "$(val "$2")" >/dev/null; fi
  done
}

start() {
  volumes
  # the projects and library folders as full paths (shown in the app), unless .env sets them
  p="$(val RELAY_PROJECTS)"; l="$(val RELAY_LIBRARY)"; mkdir -p "${p:-./data/projects}" "${l:-./data/library}" "$(val RELAY_BACKUPS || true)" 2>/dev/null || true
  [ -n "$(val HOST_PROJECTS_DIR)" ] || export HOST_PROJECTS_DIR="$(cd "${p:-./data/projects}" && pwd)"
  [ -n "$(val HOST_LIBRARY_DIR)" ] || export HOST_LIBRARY_DIR="$(cd "${l:-./data/library}" && pwd)"
  # shellcheck disable=SC2046
  docker compose $(files) up -d --no-build --pull never || { echo "Relay did not start. Load the image first: ./relay.sh load relay-<version>.tar.gz"; exit 1; }
  printf "Waiting for Relay to be ready"
  for _ in $(seq 1 100); do
    s="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' relay 2>/dev/null || true)"
    case "$s" in
      healthy) echo " - ready."; echo "Relay: $URL"; return 0 ;;
      unhealthy|exited) echo " - $s. See: ./relay.sh logs"; exit 1 ;;
    esac
    printf "."; sleep 3
  done
  echo " - still starting after 5 minutes. See: ./relay.sh logs"; exit 1
}

case "${1:-status}" in
  start) start ;;
  stop) docker compose -f docker-compose.yml stop ;;
  restart) docker compose -f docker-compose.yml stop; start ;;
  status) docker exec relay relay-ctl status ;;
  logs) docker logs --follow --tail 200 relay ;;
  backup) docker exec relay relay-ctl db-dump ;;
  export) docker exec relay relay-ctl export ;;
  import)
    f="${2:?./relay.sh import <file from relay export>}"; d="$(cd "$(dirname "$f")" && pwd)"
    volumes
    docker compose -f docker-compose.yml run --rm --no-deps -v "$d:/import:ro" relay relay-ctl import "/import/$(basename "$f")" ;;
  login) docker exec -it relay relay-ctl login ;;
  open) (command -v xdg-open >/dev/null && xdg-open "$URL") || (command -v open >/dev/null && open "$URL") || echo "$URL" ;;
  load) docker load --input "${2:?./relay.sh load relay-<version>.tar.gz}" ;;
  *) echo "./relay.sh start | stop | restart | status | logs | backup | export | import <file> | login | open | load <file>"; exit 2 ;;
esac
