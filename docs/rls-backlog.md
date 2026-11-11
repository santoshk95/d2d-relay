# Row-level security in D2D dashboards (backlog)

Status: **backlog, not started.** Raised on 2026-11-10, after an enterprise-size test of D2D's Power BI output.

## Why

Large organisations expect each person to see only their part of the data. A regional manager sees their region; a
store manager sees their stores. D2D can't set this up today, so anyone who opens a D2D report in Power BI sees every
row.

## What exists today

- **The plan has no roles.** The plan's schema (`genbi_kit/definition.py`) has no field for them.
- **Neither does the Power BI project.** `_model_bim` in `genbi_kit/report_builder.py` writes tables, relationships and
  measures, but never `roles`.
- **So there is nothing to check.** The review gates (`genbi_kit/gates.py`) and the DAX check (`genbi_kit/daxcheck.py`)
  have no roles to test.

The demo dashboard **Global Ports Enterprise (demo)** proves that D2D's output can carry RLS. It is
`global-ports-enterprise-demo-10c1` in the PASDACS workspace, loaded on 2026-11-10. Two roles were added by hand to its
`powerbi/Global Ports Enterprise.SemanticModel/model.bim`:

| Role | Filter |
|---|---|
| Region - Africa | `'Terminal'[Region] = "Africa"` |
| Regional managers (dynamic) | `'Terminal'[Region] IN CALCULATETABLE ( VALUES ( 'User Access'[Region] ), 'User Access'[email] = USERPRINCIPALNAME () )` on Terminal, and `'User Access'[email] = USERPRINCIPALNAME ()` on the hidden User Access table |

The `.pbix` made from it keeps both roles. It holds 10.2 million cargo rows and 30 pages. As Region - Africa, Power BI's
engine returns 3 terminals and 635,860 cargo rows. A change request on that dashboard would rebuild it without the roles.

## What to build

1. **Roles in the plan.** Support two kinds:
   - *Static:* a fixed filter per table, for example `'Terminal'[Region] = "Africa"`.
   - *Dynamic:* one role that filters by the signed-in person's email through a user-access table, which maps each email
     to a region, store or cost centre. The demo's "Regional managers" role works this way. The access table is
     hidden, and it comes from an uploaded CSV, a BigQuery table or generated demo data.
2. **Roles in the model.** `_model_bim` writes TMSL `roles`: a `name`, `modelPermission: "read"`, and `tablePermissions`
   with each table's `filterExpression`. It adds no members: people and groups are added to roles in the Power BI service
   after publishing.
3. **A review gate.** It checks that every filter's tables and columns exist, and the DAX check runs each filter in Power
   BI's engine. The gate also queries the engine as each role (connection-string property `Roles=<name>`) and records
   how many rows that role sees. It warns about a role that sees everything or nothing.
4. **Confirmation.** The plan review lists the roles in plain words, for example "Regional managers see only their own
   regions, from User Access". That way the client agrees who sees what before the build.
5. **Hand-over text.** The README in the download says:
   - which roles exist;
   - that people are added to roles in the Power BI service (the semantic model's **Security** page);
   - how to try the roles in Power BI Desktop (**Modeling → View as**).

## Done when

- A plan that declares a static role and a dynamic role produces a Power BI project whose model has both.
- The gates pass, and the review shows how many rows each role sees.
- A change request keeps the roles.
- On the Global Ports data, Region - Africa sees 3 terminals.

## Good to know

- **Testing dynamic roles from a script:** Power BI Desktop's local engine refuses a made-up email in `EffectiveUserName`
  ("not a properly formed account name"). Test the dynamic filter with a fixed email in place of `USERPRINCIPALNAME()`,
  or in Power BI Desktop with **Modeling → View as → Other user**.
- **Who RLS applies to:** in the Power BI service, RLS filters the data for people with Viewer access and for app users.
  Workspace Admins, Members and Contributors see every row.
- **BigQuery:** Power BI's RLS is separate from BigQuery's own row-level access policies. With Import, D2D's only
  storage mode, BigQuery's policies apply to the account that runs the refresh, not to the person viewing the report.
- **Not part of this item:** hiding tables or columns per role (object-level security), and adding people to roles
  automatically.
- **Open question:** whether adding roles in a change request costs credits, like any other change.
