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
| `checks/` | The suites, the stand-in Microsoft APIs (`fake_powerbi.py`) and the stand-in GitHub API (`fake_github.py`, item 70) |
| `audit/` | `routes.py` and `routes-public.txt`: the public site's API routes, which `sec_check.py` tries without a session |
| `run_release.sh` | A fresh stack, then every suite |
| `run_all.sh` | Every suite against the running stack |
| `out/` | Each run's logs and screenshots (git-ignored) |

Needs: Docker Desktop, Git Bash, Python 3.10 or later (Windows' own `python`, standard library only), and the image to
test, built on this PC. A release image is built from its clean commit and tagged `d2d-relay:<commit>`, in a folder with
a short path (Visual Atlas's test paths pass Windows' 260 characters in the session scratchpad):

```bash
docker build -t d2d-relay:<sha> --build-arg RELAY_COMMIT=<sha> --build-arg RELAY_VERSION=1.0.0 --build-arg AGY_IMAGE=d2d-relay-agy:pinned .
```

To try suites against a working tree that is not committed yet, copy its files (`git ls-files -co --exclude-standard`,
through tar) to a folder such as `Downloads\d2d-tests-snap`, build there with a tag of your own, and remove the folder
afterwards. The browser checks run headless Chromium inside the test web container, so nothing else is installed here.

## Starting the stack

```bash
TEST_IMAGE=d2d-relay:54f6ed7 bash tests/stack/stack.sh
```

- `TEST_IMAGE` (required): the image to test.
- `TEST_DB_PASSWORD`: the test database's password. When it is not set, stack.sh makes one up at random.
- Since item 56 there is one mode: nobody signs up, and a new organisation gets its starting credits when PASDACS
  creates it. (Until then a release was checked twice, with the starting-credit review on and off.)

stack.sh removes any earlier test stack with its volumes, empties `stack/test-projects` (the projects folder, a bind as
on live), writes the settings to `stack/.env` (git-ignored), starts the stack, waits until web and admin are healthy and
starts the stand-in Microsoft APIs inside the web container. Then:

- http://127.0.0.1:8103 is the public site, http://127.0.0.1:8104 the admin portal (info@pasdacs.com), and
  127.0.0.1:8106 the stand-in Microsoft sign-in, Fabric and Power BI APIs for Semantic Review and publishing (items 55
  and 70, `checks/fake_powerbi.py`, started by stack.sh). The stand-in GitHub API (`checks/fake_github.py`, item 70)
  answers on port 9913 inside the web container only; item70_check.py starts it, and the stack points the app at it
  (`RELAY_GITHUB_API`).
- Credits are bought online again since item 85 (beside Request credits): the stack runs a stand-in Razorpay on
  127.0.0.1:8105 (`fake_razorpay.py`, started in the web container by stack.sh) with made-up keys; `pay_check.py`
  (server) and `pay_ui_check.py` (screens) cover it.
- A new dashboard needs its organisation's brand since 2026-11-19 (a 400 naming Branding without one): when an owner
  signs in (`Person.sign_in`) to an organisation without a brand, the first standard palette is picked for it
  (`Person.ensure_brand`); `sign_in(brand=False)` leaves it unset (tour_ui_check.py picks it in the tour's brand step).
- Since item 81 a new organisation's owners finish a guided setup before its first dashboard, DAWB import or Semantic
  Review (a 400 until then): an owner signing in (`Person.sign_in`) to an organisation whose setup is not done finishes
  it the plain way, without AI (`Person.ensure_setup`: industry general, so no pack, the industry standard's
  understanding, no KPIs or terms taken), so it stays as before; the old first-time setup flag (`setup_needed`, the
  tour) is put back as it was. A member, an organisation from before item 81, a personal workspace or an image without
  the setup is left as it is; `sign_in(brand=False)` leaves both brand and setup to the suite (item81_check.py).
- Nothing is emailed: sign-in codes are printed to the containers' logs (`docker logs d2d-relay-test-web`, lines
  `[otp] code for ...`). The admin portal also shows an account's code on its sign-in page (item 57,
  `TEST_OTP_ON_SCREEN=1` by default; set it empty to test the admin portal without it). For a person trying the stack
  in a browser on this PC, `TEST_WEB_OTP_ON_SCREEN=1` shows the public site's codes on its sign-in page too (off for
  the suites, which read the log). Only addresses with an account get one (item 56): the suites have PASDACS create their
  organisations and people on the admin portal first (`d2d_checks.provision_account`, called by `Person.sign_in`).
- The stack has no Claude sign-in: every AI run fails at once (and gives its credits back), which the suites expect.

stack.sh refuses to start while any container labelled `d2d-relay.job=1` exists on this PC. Until item 34 the job
runner removed every such container when it started (`docker/job_runner.py`, `sweep()`), live's dashboard builds
included; since item 34 each job carries its web container's name (`d2d-relay.web`) and a runner removes only its own
stack's. The refusal stays for images from before item 34 (and `upgrade_check.py` starts one). If it says so, wait
until the live build ends. A test stack's own leftovers can be removed with `docker rm -f <name>`.

## Running the suites

A release check, on a fresh stack:

```bash
TEST_IMAGE=d2d-relay:54f6ed7 bash tests/run_release.sh
```

It prints one line per suite and a total; the logs are in `tests/out/<tag>`. With the stack already running,
`bash tests/run_all.sh <output name>` runs the suites alone.

| Suite | Checks |
|---|---|
| `d2d_checks.py` (groups `connectors portal credits people production`) | 121 |
| `gov_check.py` + `gov_ui_check.py` | 61 + 11 |
| `ask_credits_check.py`, `review_fixes_check.py` | 14, 14 |
| `sec_check.py` | 117 |
| `item29_check.py` + `tour_ui_check.py` (the tour's brand step cannot be skipped by an owner without a brand, 2026-11-19) | 34 + 32 |
| `item30_check.py`, `rename_check.py` | 55, 9 |
| `jobs_check.py`, `accounts_check.py` | 19, 48 |
| `item34_check.py`: built-in visuals first (the guided New dashboard's two choices since 2026-11-19), the model's name ("Relay Model" since item 70), each runner sweeping only its own stack | 33 |
| `item35_check.py`: labels in the prototype of the built-in visuals gallery and in the rebuilt Atlas visuals | 9 |
| `item36_check.py`: KPI names clear of their values in low tiles; measure titles in the prototype | 10 |
| `item37_check.py`: a sunburst's labels on thin slices: none on another, each inside its own slice | 10 |
| `item38_check.py`: share tags and image, robots.txt, no `./` or `../` past the sign-in check | 41 |
| `item40_check.py`: the Turnstile bot check before a code (the stack runs Cloudflare's test keys; every suite sends a token), Resend code since item 41 | 23 |
| `item42_check.py`: since item 67 the installation's Claude sign-in first and its API key as the backup (`RELAY_AI_PRIMARY=api`: item 42's order, the key first), Ask Relay's fallback both ways, no key in the AI engine | 14 |
| `item44_check.py`: a dashboard's credits by its visuals (25 built-in, 50 custom), the difference once when moving to custom, Retry's charge, the screens | 37 |
| `item45_check.py`: the queue shows an organisation its own jobs only (positions, /api/health), "Starting shortly" (item 70's wording; it said "In the queue"), no Stop (button or API) | 16 |
| `item46_check.py`: up to 3 jobs at once with stand-in jobs (never two of one dashboard, publishing one at a time), the AI engine's lanes (item 68's review lane too), the Opus 5.5 defaults (and item 68's hidden reviewer model) | 13 |
| `item48_check.py`: a started build's credits and its free Retry, planning still refunded, nothing on screen or in the terms about credits coming back | 12 |
| `item49_check.py`: the job runner's two-minute tidy of its own finished jobs, with stand-in containers (never a running job, never another stack's) | 8 |
| `item50_check.py`: the admin portal's Overview (online now, everyone with an account newest first, totals; not on the public site; its first page) | 20 |
| `item51_check.py`: the sign-in code email in D2D's look (mail stubbed in the web and admin containers: who gets it, the code, plain characters, nothing fetched; in Chromium: 320 to 1280 px, dark mode) | 25 |
| `item52_check.py`: the prototype's matrix per row header (first level, Auto expand, ROLLUP totals, no summed ratio), cut card text and the Display check, the DAX check's levels, Ask Relay's percentages and plurals (a seeded answer in Chromium, the snapshot) | 38 |
| `item55_check.py`: Semantic Review: the KPI dictionary (one name one KPI, readable DAX, import preview and merge, CSV without formulas), reviews of model.bim, .pbit, a TMDL project, a live and a broken .pbix and the real .pbix of `TEST_REVIEW_PBIX` (skipped when it is not on the PC), what they find, credits and refunds, the meaning check's retry, Review again, who may do what, Power BI through the stand-in Microsoft APIs (`fake_powerbi.py`, 127.0.0.1:8106), a review cut off by a restart; its people sign in from 203.0.113.x (codes are limited per address); the cases of the independent review of 2026-11-18 (a YAML alias bomb, dictionary DAX using model measures, Table[Measure], dt"..." literals, 31 levels of doubling references, a non-Latin review name) | 91 |
| `item55_ui_check.py`: Semantic Review in Chromium: the menu, the guided start (your KPIs, your models from the file picker, check and start), the report's stages, the dictionary and its Add dialog, phone width, dark mode, no failed requests (screenshots `sr-*.png`) | 20 |
| `item56_check.py`: nobody signs up: an address without an account gets the usual answer and no code (and any code for it is wrong; the limits count it), the sign-up step gone, PASDACS creating an organisation (its rules, the owner's first sign-in and starting credits), owners adding and removing people, PASDACS adding someone (the owners told), the admin portal for PASDACS people with an account, the sign-in alert; in Chromium the sign-in page, New organisation and Add someone, the Overview, the Organisation page and the tour (screenshots `item56-*.png`); its people sign in from 192.0.2.x | 62 |
| `item57_check.py`: the code on the screen (`RELAY_OTP_ON_SCREEN`, on for the stack's admin portal only): an account's code in the answer that signs in once, the limits, no code for an address without an account or through a proxy, the public site unchanged, who counts as this PC, the admin sign-in page in Chromium (screenshot `item57-admin-signin.png`); and the start page "/" listing a dashboard when the dashboard list arrives late (held back 1.5 s in Chromium; the owner's first-time tour and organisation set-up done first, or the app opens `#/welcome`) | 23 |
| `item58_check.py`: a new dashboard from a DAWB hand-off (one .zip on New dashboard). Refused before anything is saved or charged, each saying what is wrong: not a zip, no project.json, two hand-offs, a file outside the folder, another format or kind, no manifest, a CSV changed after the manifest, a listed file missing, columns or rows that differ, a relationship to a missing column, a repeated key, two filter paths, two types, DAX that does not read, a format DAWB does not have, too many files, too few credits. A good one at Confirm KPIs: DAWB's KPIs (formats mapped, a format_string kept, a KPI named like a column renamed with the KPIs using it), pages, tables, relationships, notes, profile, request.md, `handoff/`, the audit; files at the zip's top with Windows backslashes; 25 / 50 credits; Confirm KPIs starting the build on the import's charge; the build's instructions; column descriptions in the model; the real hand-off of `TEST_HANDOFF_DIR` (default `Downloads\DAWB\handoff\d2d\pinecrest` in the home folder, skipped when it is not there); in Chromium the guided New dashboard's hand-off option and an import through its steps, the plan at 1280 and 360 px (screenshots `item58-*.png`); its people sign in from 198.18.58.x | 77 |
| `item59_check.py`: buying credits online is gone (item 59): the selling routes answer 404 or 405 signed in and 401 without a session (the webhook too), also on the admin portal, and nothing says "pay"; payments seeded as payments.py made them (`seed_payment`) still open for the right people only (a tax invoice, a test invoice, a receipt from before invoices; none for a checkout never completed) and are in Download my data; the admin portal's past payments, totals of real ones, financial years, invoice and CSV (test invoices when asked); a personal workspace's Request credits; in Chromium the Organisation page's Past payments and the admin portal's Payments page (screenshots `item59-*.png`); 198.18.59.x | 60 |
| `item60_check.py`: several email domains per organisation: created with them (cleaned, refused for free mail, throw-away, malformed or another organisation's), listed main first, people added at any of them (by owners and PASDACS), added and taken away by PASDACS (never the main one, the owners told, audited), a personal workspace has none; in Chromium New organisation and the Email domains dialog (screenshots `item60-*.png`); 198.18.60.x | 41 |
| `item61_check.py`: the ontology: the general pack until terms of one's own, the 13 packs, applying grocery-retail (terms and dictionary KPIs; again kept; replace), column matching (sls_amt Sales, str_nbr Store, last year's Sales, Gross Margin %), terms add, edit, remove and their rules, teaching a column name, export and import into another organisation, viewers read only, an organisation created with an industry; in Chromium Ontology at 1280 and 360 px (screenshots `item61-*.png`); 198.18.61.x | 68 |
| `item62_check.py`: a dashboard's semantic model (GET and PUT `/api/projects/<id>/semantic`) on a dashboard seeded into its folder and read by worker.read_data in the web container (`seed_project`): tables, columns, types, business terms, the Store key under two names, the relationship, counts, industry, ontology.json and ontology.md, data_size; the person's own tags (kept on the next read, refused for unknown columns or terms, and once the plan is confirmed); who may; a DAWB hand-off read at the import, its KPIs matched to the dictionary; in Chromium the plan screen's Semantic model card (screenshots `item62-*.png`); 198.18.62.x | 37 |
| `item63_check.py`: a KPI changed in words, 1 credit, a plan's KPI and a dictionary entry: refused before any charge (too short, not there, a viewer, another organisation, confirmed, no credits); without Claude 503 and the credit back, the plan and the entry unchanged; in Chromium the plan screen's "Change it in words" (screenshot `item63-plan.png`); 198.18.63.x | 30 |
| `item64_check.py`: uploads in parts (the 10 GB cap, a 9 MB CSV, a 33 MB file in two parts sent out of order, each part's size, done once, delete) and the forms that take them (a new dashboard with data_policy, a DAWB hand-off, a Semantic Review; someone else's upload refused before any charge); sampling by worker.read_data with a small threshold for that run only (random, recent, all, the default threshold): sample.json, data_sample/, the Parquet sample, data_size, the semantic view, the activity log; 198.18.64.x | 47 |
| `item65_check.py`: Semantic Review fixes on item 55's review of three models: the estimate before any charge, the refusals, the rules' own fixes made without AI and checked against each model, Relay's failing without Claude with their credits back, the TMDL, Tabular Editor and CSV downloads; 198.18.65.x | 33 |
| `item66_check.py`: Ask Relay: renaming a conversation (one's own only), and the options' KPIs (the dictionary's, then the dashboards') and the industry's example questions; 198.18.66.x | 23 |
| `item70_check.py`: deployment (written with item 70): publishing to the Power BI service through the stand-in Imports API and pushing the Power BI project to GitHub through the stand-in GitHub API (`fake_github.py`, started by the suite in the web container); 198.18.70.x | 95 |
| `item73_check.py`: every gap, assumption and difference from the KPI dictionary approved before Confirm KPIs: approval_items with stable ids (the analyst review seeded into project.json), Confirm refused until all are approved, the approvals kept and noted for the build; in Chromium Review and approve (screenshot `item73-approve.png`); 198.18.73.x | 19 |
| `item81_check.py`: the guided organisation setup (item 81, GET /api/org/profile and its steps): a new organisation needed, what the form offers, /api/me; New dashboard, a DAWB import and a new Semantic Review refused (400, the owner's or a member's words, before the brand's rule, nothing charged) until it is finished; a member reads only (403 for every step); the context's rules; general applies no pack, a new industry its pack (once) and drops an older proposal; Relay Model's run (no AI on the stack: "error" in plain words within a minute; with a Claude sign-in or key in `stack/.env`: its checked proposal within 10 minutes); the industry standard (the understanding in the context's words, the pack's KPIs on the 4-4-5 calendar and in the currency, the naming conventions as synonyms); understanding, KPIs (added, kept, replaced, skipped with why) and terms accepted; Finish refused while a step or the brand is missing, then done (setup_done, audited, the people told); afterwards the three start; ontology.json and ontology.md's "Your organisation"; organisations from before (a dashboard, or the old setup and a brand) and a personal workspace not blocked; plain words; in Chromium #/setup at 1280 and 375 px and a member's read-only view (screenshots `item81-*.png`); 198.18.81.x | 71 |
| **All, for items 59 to 73** (a working-tree snapshot of 2026-11-19 15:23 IST, d2d-relay:tests-snap3: 1564 passed; the 6 failing checks are app defects), one mode (before it: 1259 for item 58, 1183 for item 57, 1160 for item 56; review on / off: 1132 / 1115 for item 55; 1024 / not run for item 52; 987 for 8029415; 962 for 22c7464; 943 for 1c841da; 935 for 777f30c; 858 for 01559b6 and a871751; 847 for baf70e5 and 2686fc4; 846 / 829 for d1882f7, 825 / 808 for 96ea48a, 788 / 771 for 189ccac, 747 / 730 for 334b493, 685 / 668 for 54f6ed7) | **1570** |

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
- In Git Bash, `docker exec` paths need `MSYS_NO_PATHCONV=1`. Python with the app's context runs inside the web
  container: `docker exec -i -u relay -w /srv d2d-relay-test-web /opt/relay/bin/launch web python -`, calling
  `db.init()` first (`d2d_checks.in_app` does it). `launch` gives each part exactly its own environment, so
  `docker exec -e` never reaches the app: `in_app(code, env={...})` sets the variables inside, before anything is
  imported (item64_check.py's small sampling threshold, GENBI_SAMPLE_ROWS and GENBI_SAMPLE_OVER, both needed: the
  threshold is never below the sample size).
- Seeding instead of what the stack cannot do: `d2d_checks.seed_payment` (a payment from before item 59),
  `seed_project` and `read_data` (a dashboard's folder and worker.read_data, items 62 and 64), `mini_handoff` and
  `import_handoff` (a dashboard waiting at Confirm KPIs with its plan, no Claude needed: items 62 to 73); item 73's
  analyst review is seeded into project.json (plan_review), item 66's conversations into askd_threads.
- New dashboard is a guided flow since 2026-11-19 (six steps, files uploaded as they are picked): browser scripts put
  `d2d_checks.ND_FLOW` in front of theirs and walk it with `nd_open`, `nd_to_visuals`, `nd_next`, `nd_upload`.
- A dialog made by `modal()` focuses its first field 30 ms after it opens: before typing into one, wait for its fields
  and then 100 ms (item56_check.py does).
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

An Anthropic API key first (item 42): `TEST_ANTHROPIC_API_KEY=<key>` gives the stack's web and admin
`RELAY_ANTHROPIC_API_KEY`, so runs go to the key and fall back to the mounted sign-in. stack.sh writes it to
`stack/.env` with the other settings (ignored by git): delete that file after the teardown. Run the suites without
it: `item42_check.py` checks the no-key default and sets a fake key of its own.

End to end, as a customer would, needs this PC's DAX checker and Power BI file maker too: `stack/helpers.ps1` starts
the repository's copies on the test stack's own queues (and a data folder of their own, `C:\D2D Relay Test`), never
live's; live's keep running beside them.

```bash
TEST_CLAUDE_VOLUME=claude-api-auth TEST_CLAUDE_EXTERNAL=true TEST_IMAGE=d2d-relay:<tag> bash tests/stack/stack.sh
powershell -NoProfile -ExecutionPolicy Bypass -File tests/stack/helpers.ps1 start
cd tests/checks
python -I -X utf8 visuals_e2e_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
python -I -X utf8 real_build_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
cd ../..
powershell -NoProfile -ExecutionPolicy Bypass -File tests/stack/helpers.ps1 stop
```

- `visuals_e2e_check.py`: one dashboard in each Visuals choice New dashboard offers (since 2026-11-19 two: Power BI's
  built-in visuals, and built-in plus custom; `relay`, all custom, can still be named), each planned and built by real Claude,
  approved, published through Power BI's engine (the DAX check) and made into a .pbix; then what each report is made
  of, in its definition and inside the .pbix (built-in: no custom visual embedded; Relay: its custom visuals embedded);
  then every page of each report's prototype in Chromium: no label past its visual's edge, no Relay data label reading
  $0M (item 35), no name on top of a value in a Relay Gauges visual, every visual titled by a measure showing its
  sentence (item 36), and no sunburst label on another or outside its slice (item 37). Since items 62, 68, 73 and 76
  also: the plan screen had the semantic model, the analyst reviewed the plan on its own, each gap, assumption and
  deviation was approved at Confirm, the UI/UX, story and accuracy reviewers each checked the version without changing
  it, and each slicer moved to another value redraws what it filters (no error, NaN or Infinity).
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
| `upgrade_check.py` | The image live runs today, then the release candidate on the same database and folders (30 checks from d2d-relay:f754035; with an old image from before item 56, 31) | `python -I -X utf8 upgrade_check.py <public> <admin> <old image> <new image>`, after stack.sh (it restarts the stack itself, so the job-container rule applies). `OLD_HAS_PURPOSE=1` when the old image reviews new organisations (72b71a1 and later): the suite approves what it needs on the old image itself, and leaves one organisation's starting credits waiting, to approve after the upgrade. An old image from item 56 on (f754035, live's last) has no sign-up: PASDACS creates the organisation on its admin portal and nothing waits. Since item 59 a payment seeded as the old image's payments.py wrote it must still open after the upgrade |
| `proto_sandbox_check.py` | A hostile prototype cannot act for the person viewing it, alone or framed in the app (23 checks) | `python -I -X utf8 proto_sandbox_check.py <public> <admin>` |
| `access_check.py` | Cloudflare Access tokens on the admin portal, with a key made up here (10 checks) | Inside the admin container: `docker exec -i -u relay -w /srv d2d-relay-test-admin /opt/relay/bin/launch web python - < tests/checks/access_check.py` |
| `guard_cases.py` | The AI engine's shell guard: 64 cases | On this PC, no stack: `python -I tests/checks/guard_cases.py agent/bash_guard.py` |

## Keeping the suite current

- A release that adds or removes API routes: take the route list again from the candidate image, so `sec_check.py`
  tries every reachable route without a session (taken last on 2026-11-19 from a snapshot of the working tree at 15:23
  IST, items 59 to 73: the selling routes gone, the ontology, uploads, fixes, deploy, suggest and branding fonts routes
  in; take it again from the release image):

  ```bash
  MSYS_NO_PATHCONV=1 docker run --rm --network none --entrypoint /usr/local/bin/python -v "$(pwd -W)/tests/audit:/audit:ro" d2d-relay:<tag> -X utf8 /audit/routes.py "" > tests/audit/routes-public.txt
  ```

- A new item's checks go in `checks/<name>_check.py`: `import d2d_checks as c`, `c.check(...)` per check, end with the
  `N of M checks passed` line and exit with the number of failures. Add it to `run_all.sh` and the table above.
- When an expectation changes because the app changed on purpose, change the check and say so in `docs/LOG.md`.
