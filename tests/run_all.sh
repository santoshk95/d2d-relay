#!/usr/bin/env bash
# Every release suite against the running test stack (stack/stack.sh), one after another; the payment suites switch
# selling on, so the older suites run first. bash tests/run_all.sh [<output name>]
# Logs and screenshots go to tests/out/<output name>/ (git-ignored). The suites approve new organisations' starting
# credits when the stack reviews them (D2D_TEST_APPROVE_START, read from the stack unless set).
set -u
cd "$(dirname "$0")/checks"
OUT=../out/${1:-latest}
mkdir -p "$OUT"
D2D_TEST_OUT=$(cd "$OUT" && { pwd -W 2>/dev/null || pwd; })     # a Windows path for Windows' Python under Git Bash
export D2D_TEST_OUT
if [ -z "${D2D_TEST_APPROVE_START:-}" ]; then
  D2D_TEST_APPROVE_START=$(MSYS_NO_PATHCONV=1 docker exec d2d-relay-test-web printenv RELAY_CREDITS_START_REVIEW 2>/dev/null || echo 1)
fi
export D2D_TEST_APPROVE_START
B=http://127.0.0.1:8103
A=http://127.0.0.1:8104
passed=0 total=0 failed=()

suite() {   # <suite> [<arguments after the two addresses>]
  local s=$1 line counts
  shift
  python -I -X utf8 "$s.py" "$B" "$A" "$@" > "$OUT/$s.log" 2>&1
  local rc=$?
  line=$(grep -E 'checks passed' "$OUT/$s.log" | tail -1)
  echo "$s: ${line:-no summary, exit code $rc (see $OUT/$s.log)}"
  counts=$(echo "$line" | sed -nE 's#^([0-9]+)( of |/)([0-9]+) checks passed.*#\1 \3#p')
  if [ -n "$counts" ]; then
    passed=$((passed + ${counts% *})) total=$((total + ${counts#* }))
  fi
  [ "$rc" = 0 ] && [ -n "$counts" ] || failed+=("$s")
}

suite d2d_checks connectors portal credits people production
for s in gov_check gov_ui_check ask_credits_check review_fixes_check pay_check pay_ui_check \
         sec_check item29_check tour_ui_check item30_check rename_check jobs_check accounts_check item34_check item35_check item36_check item37_check item38_check item39_check item40_check item42_check item44_check item45_check item46_check item48_check; do
  suite "$s"
done
echo "all suites: $passed of $total checks passed${failed[*]:+; suites with failures: ${failed[*]}}"
[ ${#failed[@]} = 0 ]
