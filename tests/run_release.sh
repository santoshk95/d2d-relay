#!/usr/bin/env bash
# A release check: a fresh test stack from TEST_IMAGE, then every suite (run_all.sh).
# TEST_IMAGE=d2d-relay:<tag> bash tests/run_release.sh [<output name>]
# Output: tests/out/<output name>/ (default <tag>): stack.log and one log per suite. Since item 56 there is one mode
# (no starting-credit review: PASDACS creates organisations); an old mode argument, 0 or 1, is ignored.
# The stack is left running; take it down afterwards (README.md).
set -u
cd "$(dirname "$0")"
case "${1:-}" in 0|1) shift ;; esac
: "${TEST_IMAGE:?set TEST_IMAGE to the image to test, e.g. d2d-relay:54f6ed7}"
NAME=${1:-${TEST_IMAGE##*:}}
mkdir -p "out/$NAME"
if ! bash stack/stack.sh > "out/$NAME/stack.log" 2>&1; then
  tail -15 "out/$NAME/stack.log"
  exit 1
fi
grep -E '^web=|^stand-in|^WARNING' "out/$NAME/stack.log"
bash run_all.sh "$NAME"
