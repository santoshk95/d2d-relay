# D2D Relay release tests

Every D2D Relay release is checked end to end on a throwaway Docker stack, `d2d-relay-test`, started from the release
image. The stack has its own containers, volumes and ports and never touches the live one: no live container, volume,
`.env` or `Downloads\D2D Relay` file is used, except live's Claude sign-in volume for the real-Claude test below, which
is mounted, never copied.

| Folder or file | What it holds |
|---|---|
| `stack/docker-compose.yml` | The test stack: `d2d-relay-test-db`, `-web`, `-admin` and `-runner`, as live is laid out |
| `stack/stack.sh` | Starts a fresh test stack from an image (and removes the earlier one) |
| `stack/helpers.ps1` | The test stack's own DAX checker and Power BI file maker on this PC, for the end-to-end run |
| `checks/` | The suites, the stand-in Razorpay API (`fake_razorpay.py`) and its checkout window (`rzp_stub.js`) |
| `audit/` | `routes.py` and `routes-public.txt`: the public site's API routes, which `sec_check.py` tries without a session |
| `run_release.sh` | A fresh stack, then every suite, in one review mode |
| `run_all.sh` | Every suite against the running stack |
| `out/` | Each run's logs and screenshots (git-ignored) |

Needs: Docker Desktop, Git Bash, Python 3.10 or later (Windows' own `python`, standard library only), and the image to
test, built on this PC (a release image is built from its clean commit and tagged `d2d-relay:<commit>`). The browser
checks run headless Chromium inside the test web container, so nothing else is installed here.

## Starting the stack

```bash
TEST_IMAGE=d2d-relay:54f6ed7 bash tests/stack/stack.sh 1
```

- `TEST_IMAGE` (required): the image to test.
- `TEST_DB_PASSWORD`: the test database's password. When it is not set, stack.sh makes one up at random.
- The argument is the starting-credit review: `1` (on, live's setting: PASDACS approves each new organisation's 50
  starting credits) or `0` (off, `RELAY_CREDITS_START_REVIEW=0`). A release is checked in both modes.

stack.sh removes any earlier test stack with its volumes, empties `stack/test-projects` (the projects folder, a bind as
on live), writes the settings to `stack/.env` (git-ignored), starts the stack, waits until web and admin are healthy and
starts the stand-in Razorpay inside the web container. Then:

- http://127.0.0.1:8103 is the public site, http://127.0.0.1:8104 the admin portal (info@pasdacs.com), and
  127.0.0.1:8105 the stand-in Razorpay.
- Nothing is emailed: sign-in codes are printed to the containers' logs (`docker logs d2d-relay-test-web`, lines
  `[otp] code for ...`).
- The stand-in's keys are made up and look it (`rzp_live_D2DTESTSTACK01`, `stand-in-key-secret-not-real`). The key id
  starts with `rzp_live_` so the live path runs: selling needs a platform admin to switch it on, as on live.
- The stack has no Claude sign-in: every AI run fails at once (and gives its credits back), which the suites expect.

stack.sh refuses to start while any container labelled `d2d-relay.job=1` exists on this PC. Until item 34 the job
runner removed every such container when it started (`docker/job_runner.py`, `sweep()`), live's dashboard builds
included; since item 34 each job carries its web container's name (`d2d-relay.web`) and a runner removes only its own
stack's. The refusal stays for images from before item 34 (and `upgrade_check.py` starts one). If it says so, wait
until the live build ends. A test stack's own leftovers can be removed with `docker rm -f <name>`.

## Running the suites

A release check, each mode on a fresh stack:

```bash
TEST_IMAGE=d2d-relay:54f6ed7 bash tests/run_release.sh 1
TEST_IMAGE=d2d-relay:54f6ed7 bash tests/run_release.sh 0
```

Each prints one line per suite and a total; the logs are in `tests/out/<tag>-review-on` (or `-off`). With the stack
already running, `bash tests/run_all.sh <output name>` runs the suites alone.

| Suite | Checks: review on / off |
|---|---|
| `d2d_checks.py` (groups `connectors portal credits people production`) | 119 / 119 |
| `gov_check.py` + `gov_ui_check.py` | 60 + 10 |
| `ask_credits_check.py`, `review_fixes_check.py` | 14, 13 |
| `pay_check.py` + `pay_ui_check.py` | 114 + 37 |
| `sec_check.py` | 132 / 115 |
| `item29_check.py` + `tour_ui_check.py` | 34 + 28 |
| `item30_check.py`, `rename_check.py` | 54, 8 |
| `jobs_check.py`, `accounts_check.py` | 18, 45 |
| `item34_check.py`: built-in visuals first, the model's name, each runner sweeping only its own stack | 32 |
| **All, for aa4531e** (685 / 668 for 54f6ed7, before item 34) | **718 / 701** |

One suite by hand, with the stack running:

```bash
cd tests/checks
python -I -X utf8 sec_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
```

Always `python -I -X utf8`: `-I` keeps the environment's `PYTHON*` settings and the current folder out, and `-X utf8`
is needed because the rupee sign breaks the Windows console otherwise (`-I` also ignores `PYTHONIOENCODING`). Each
suite prints a line per check and `N of M checks passed`; its exit code is the number of failures.

- `d2d_checks.py` runs only the groups it is given (none: nothing). Its `rehearsal` group passes only after a copy of
  live's database is loaded into the test stack; on a fresh stack its 2 checks fail by design.
- Screenshots of the browser suites go to `tests/out`, or to the folder `D2D_TEST_OUT` names (run_all.sh sets it to the
  run's folder).
- With the review on, set `D2D_TEST_APPROVE_START=1` when running a suite by hand, so new organisations get their
  starting credits approved the way PASDACS does (`run_all.sh` reads the stack's mode itself).
- In Git Bash, `docker exec` paths need `MSYS_NO_PATHCONV=1`. Python with the app's context runs inside the web
  container: `docker exec -i -u relay -w /srv d2d-relay-test-web /opt/relay/bin/launch web python -`, calling
  `db.init()` first.
- `pay_ui_check.py` waits up to 15 seconds for each dialog; on a busy PC it can time out. Rerun it before calling it a
  failure.
- `jobs_check.py` counts only this stack's job containers (labelled with its web container; before item 34, in its
  web container's network), so a live build running at the same time does not count.
- Docker Desktop's port forwarding can stall a connection to 127.0.0.1 for about 20 seconds; the suite then stops with
  `WinError 10060` and no summary line (seen once in `sec_check.py`, with nothing in the app's log). Run the release
  check again on a fresh stack.

## Tearing down

```bash
cd tests/stack
docker compose -p d2d-relay-test down -v
```

Run it in `tests/stack`: compose reads the `.env` stack.sh wrote there, so it sees the same image, password and Claude
volume settings. Never run it from the repository root: the `docker-compose.yml` there is live's, and its volumes
carry live's names. Logs stay in `tests/out` and the projects folder in `tests/stack/test-projects` until the next
stack.sh.

## Real Claude (on demand)

The test stack can mount live's Claude sign-in, the volume `claude-api-auth`, for real builds. **Always set both
`TEST_CLAUDE_VOLUME=claude-api-auth` and `TEST_CLAUDE_EXTERNAL=true`, never external false**: as external, compose
never deletes the volume, not even with `down -v`. stack.sh refuses any other volume that is not external, and writes
both settings to `stack/.env`, so the teardown in `tests/stack` keeps them. Set both on every command that names the
stack anywhere else. Never copy the sign-in (`.credentials.json`): a refresh in a copy could rotate the token live uses.

End to end, as a customer would, needs this PC's DAX checker and Power BI file maker too: `stack/helpers.ps1` starts
the repository's copies on the test stack's own queues (and a data folder of their own, `C:\D2D Relay Test`), never
live's; live's keep running beside them.

```bash
TEST_CLAUDE_VOLUME=claude-api-auth TEST_CLAUDE_EXTERNAL=true TEST_IMAGE=d2d-relay:<tag> bash tests/stack/stack.sh 1
powershell -NoProfile -ExecutionPolicy Bypass -File tests/stack/helpers.ps1 start
cd tests/checks
python -I -X utf8 visuals_e2e_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
python -I -X utf8 real_build_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
cd ../..
powershell -NoProfile -ExecutionPolicy Bypass -File tests/stack/helpers.ps1 stop
```

- `visuals_e2e_check.py`: one dashboard in each Visuals mode, in the order the form offers them (Power BI's built-in
  visuals, built-in first with custom where needed, Relay custom visuals), each planned and built by real Claude,
  approved, published through Power BI's engine (the DAX check) and made into a .pbix; then what each report is made
  of, in its definition and inside the .pbix (built-in: no custom visual embedded; Relay: its custom visuals embedded).
- `real_build_check.py`: one real build, with each job container looked at from outside while it runs (only this
  stack's job containers, never live's): its mounts, network, rights, and no other organisation's folder.

A plan takes one to two minutes, a build a few more, publishing with the .pbix about one. Afterwards take the stack
down (as above) and delete the test runs' transcripts from the volume (each check prints its organisation; the folder
names start with a dash, hence `--`):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v claude-api-auth:/c --entrypoint /bin/sh d2d-relay:<tag> -c 'cd /c/projects && rm -rf -- ./-data-projects--tenants-<test organisation>-*'
```

## Other checks (on demand)

| Script | What it checks | How |
|---|---|---|
| `upgrade_check.py` | The image live runs today, then the release candidate on the same database and folders (23 checks) | `python -I -X utf8 upgrade_check.py <public> <admin> <old image> <new image>`, after stack.sh (it restarts the stack itself, review on, so the job-container rule applies). `OLD_HAS_PURPOSE=1` when the old image reviews new organisations (72b71a1 and later). Leave `D2D_TEST_APPROVE_START` unset: the suite approves what it needs itself |
| `proto_sandbox_check.py` | A hostile prototype cannot act for the person viewing it, alone or framed in the app (23 checks) | `python -I -X utf8 proto_sandbox_check.py <public> <admin>` (with `D2D_TEST_APPROVE_START=1` on a stack with the review on) |
| `access_check.py` | Cloudflare Access tokens on the admin portal, with a key made up here (10 checks) | Inside the admin container: `docker exec -i -u relay -w /srv d2d-relay-test-admin /opt/relay/bin/launch web python - < tests/checks/access_check.py` |
| `guard_cases.py` | The AI engine's shell guard: 64 cases | On this PC, no stack: `python -I tests/checks/guard_cases.py agent/bash_guard.py` |
| `rzp_real_check.py`, `rzp_real_ui.py` | Razorpay's real TEST mode (test keys move no money) | Razorpay TEST keys only, never live ones, in `tests/stack/.env.real` (git-ignored: `TEST_RZP_KEY_ID=rzp_test_...` and `TEST_RZP_SECRET=...`); start the stack with them: `set -a; . tests/stack/.env.real; set +a; TEST_RZP_API=https://api.razorpay.com/v1 TEST_IMAGE=d2d-relay:<tag> bash tests/stack/stack.sh 1`, then `python -I -X utf8 rzp_real_check.py <public> <admin>` and `rzp_real_ui.py <public> <admin> explore\|pay\|pay-usd\|fail\|closed-tab` |

## Keeping the suite current

- A release that adds or removes API routes: take the route list again from the candidate image, so `sec_check.py`
  tries every reachable route without a session:

  ```bash
  MSYS_NO_PATHCONV=1 docker run --rm --network none --entrypoint /usr/local/bin/python -v "$(pwd -W)/tests/audit:/audit:ro" d2d-relay:<tag> -X utf8 /audit/routes.py "" > tests/audit/routes-public.txt
  ```

- A new item's checks go in `checks/<name>_check.py`: `import d2d_checks as c`, `c.check(...)` per check, end with the
  `N of M checks passed` line and exit with the number of failures. Add it to `run_all.sh` and the table above.
- When an expectation changes because the app changed on purpose, change the check and say so in `docs/LOG.md`.
