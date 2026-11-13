#!/usr/bin/env bash
# A fresh D2D Relay test stack, never the live one: bash tests/stack/stack.sh <starting-credit review: 0|1>
#   TEST_IMAGE        the image to test (required), e.g. d2d-relay:54f6ed7
#   TEST_DB_PASSWORD  the test database's password (made up at random when not set)
#   TEST_CLAUDE_VOLUME / TEST_CLAUDE_EXTERNAL   only for a real-Claude test: claude-api-auth and true, always together
# Containers d2d-relay-test-db/-web/-admin/-runner; 127.0.0.1:8103 public site, 8104 admin portal, 8105 stand-in
# Razorpay. Any earlier test stack is removed first, with its volumes. The settings are written to .env here
# (git-ignored), so `docker compose -p d2d-relay-test ...` run in this folder later (down -v included) sees them too.
set -euo pipefail
cd "$(dirname "$0")"
REVIEW=${1:-}
case "$REVIEW" in 0|1) ;; *) echo "usage: TEST_IMAGE=d2d-relay:<tag> bash stack.sh <starting-credit review: 0|1>" >&2; exit 2 ;; esac
: "${TEST_IMAGE:?set TEST_IMAGE to the image to test, e.g. d2d-relay:54f6ed7}"
docker image inspect "$TEST_IMAGE" >/dev/null 2>&1 || { echo "stack.sh: no image $TEST_IMAGE on this PC" >&2; exit 2; }

# The real-Claude rule: a volume other than the stack's own is only ever mounted as external, so `down -v` never deletes it.
TEST_CLAUDE_VOLUME=${TEST_CLAUDE_VOLUME:-d2d-relay-test-claude}
TEST_CLAUDE_EXTERNAL=${TEST_CLAUDE_EXTERNAL:-false}
if [ "$TEST_CLAUDE_VOLUME" != d2d-relay-test-claude ] && [ "$TEST_CLAUDE_EXTERNAL" != true ]; then
  echo "stack.sh: TEST_CLAUDE_VOLUME=$TEST_CLAUDE_VOLUME needs TEST_CLAUDE_EXTERNAL=true (else down -v would delete it)" >&2
  exit 2
fi
if [ "$TEST_CLAUDE_EXTERNAL" = true ] && ! docker volume inspect "$TEST_CLAUDE_VOLUME" >/dev/null 2>&1; then
  echo "stack.sh: no volume $TEST_CLAUDE_VOLUME" >&2
  exit 2
fi

# The job runner removes every job container on this PC when it starts (live's too): never while one exists.
jobs=$(docker ps -aq --filter label=d2d-relay.job=1)
if [ -n "$jobs" ]; then
  echo "stack.sh: job containers exist (label d2d-relay.job=1). The test stack's job runner removes every one when it" >&2
  echo "starts, a live dashboard build's included. Wait until they are gone (a test stack's leftovers: docker rm -f):" >&2
  for j in $jobs; do
    net=$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$j")
    web=$(docker inspect -f '{{.Name}}' "${net#container:}" 2>/dev/null || echo "${net#container:}")
    echo "  $(docker inspect -f '{{.Name}} {{.State.Status}}' "$j"), in the network of $web" >&2
  done
  exit 3
fi

export TEST_IMAGE TEST_CLAUDE_VOLUME TEST_CLAUDE_EXTERNAL
export TEST_DB_PASSWORD=${TEST_DB_PASSWORD:-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')}
export TEST_START_REVIEW=$REVIEW
# The stand-in Razorpay's keys: made up, and look it. The key id looks live so the live path runs.
export TEST_RZP_KEY_ID=${TEST_RZP_KEY_ID:-rzp_live_D2DTESTSTACK01}
export TEST_RZP_SECRET=${TEST_RZP_SECRET:-stand-in-key-secret-not-real}
export TEST_RZP_WEBHOOK=${TEST_RZP_WEBHOOK:-stand-in-webhook-secret-not-real}
export TEST_RZP_API=${TEST_RZP_API:-http://d2d-relay-test-web:9911/v1}
# Item 40: the bot check on, with Cloudflare's published test keys (always pass); TEST_TURNSTILE_SECRET= turns it off
export TEST_TURNSTILE_SITE_KEY=${TEST_TURNSTILE_SITE_KEY-1x00000000000000000000AA}
export TEST_TURNSTILE_SECRET=${TEST_TURNSTILE_SECRET-1x0000000000000000000000000000000AA}
export CODE_APP= CODE_APP_AT= CODE_STATIC= CODE_STATIC_AT=     # test the image itself, not the working tree

docker compose -p d2d-relay-test down -v >/dev/null 2>&1 || true
rm -rf ./test-projects && mkdir -p ./test-projects ./empty-app ./empty-static   # item 31: the projects folder is a bind, as on live
{
  echo "# Written by stack.sh for the running test stack (git-ignored); docker compose reads it in this folder"
  for v in TEST_IMAGE TEST_DB_PASSWORD TEST_START_REVIEW TEST_RZP_KEY_ID TEST_RZP_SECRET TEST_RZP_WEBHOOK TEST_RZP_API \
           TEST_CLAUDE_VOLUME TEST_CLAUDE_EXTERNAL TEST_TURNSTILE_SITE_KEY TEST_TURNSTILE_SECRET; do
    echo "$v=${!v}"
  done
} > .env
docker compose -p d2d-relay-test up -d 2>&1 | tail -3

w= a=
for _ in $(seq 1 90); do
  w=$(docker inspect -f '{{.State.Health.Status}}' d2d-relay-test-web 2>/dev/null || true)
  a=$(docker inspect -f '{{.State.Health.Status}}' d2d-relay-test-admin 2>/dev/null || true)
  [ "$w" = healthy ] && [ "$a" = healthy ] && break
  sleep 5
done
echo "web=$w admin=$a image=$(docker inspect -f '{{.Config.Image}}' d2d-relay-test-web) review=$(MSYS_NO_PATHCONV=1 docker exec d2d-relay-test-web printenv RELAY_CREDITS_START_REVIEW)"
swept=$(docker logs d2d-relay-test-runner 2>&1 | grep 'removed a job left from before' || true)
if [ -n "$swept" ]; then
  echo "WARNING: the test runner removed job containers when it started (a live build may have been stopped):" >&2
  echo "$swept" >&2
fi
[ "$w" = healthy ] && [ "$a" = healthy ] || { echo "stack.sh: the stack did not become healthy" >&2; exit 1; }

MSYS_NO_PATHCONV=1 docker cp ../checks/fake_razorpay.py d2d-relay-test-web:/tmp/fake_razorpay.py
MSYS_NO_PATHCONV=1 docker exec -d -u relay -e FAKE_RZP_KEY_ID="$TEST_RZP_KEY_ID" -e FAKE_RZP_SECRET="$TEST_RZP_SECRET" \
  d2d-relay-test-web /usr/local/bin/python3 /tmp/fake_razorpay.py
sleep 2
echo "stand-in Razorpay: $(curl -s http://127.0.0.1:8105/_test/state)"
