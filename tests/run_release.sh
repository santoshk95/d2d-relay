#!/usr/bin/env bash
# A release check in one review mode: a fresh test stack from TEST_IMAGE, then every suite (run_all.sh).
# TEST_IMAGE=d2d-relay:<tag> bash tests/run_release.sh <starting-credit review: 0|1> [<output name>]
# Output: tests/out/<output name>/ (default <tag>-review-on or -off): stack.log and one log per suite.
# Run it once with 1 and once with 0. The stack is left running; take it down afterwards (README.md).
set -u
cd "$(dirname "$0")"
REV=${1:-}
case "$REV" in 0|1) ;; *) echo "usage: TEST_IMAGE=d2d-relay:<tag> bash run_release.sh <starting-credit review: 0|1> [<output name>]" >&2; exit 2 ;; esac
: "${TEST_IMAGE:?set TEST_IMAGE to the image to test, e.g. d2d-relay:54f6ed7}"
NAME=${2:-${TEST_IMAGE##*:}-review-$([ "$REV" = 1 ] && echo on || echo off)}
mkdir -p "out/$NAME"
if ! bash stack/stack.sh "$REV" > "out/$NAME/stack.log" 2>&1; then
  tail -15 "out/$NAME/stack.log"
  exit 1
fi
grep -E '^web=|^stand-in|^WARNING' "out/$NAME/stack.log"
D2D_TEST_APPROVE_START=$REV bash run_all.sh "$NAME"
