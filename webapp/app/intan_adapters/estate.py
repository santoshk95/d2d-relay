"""The sample estate (build-plan v2, P13): a synthetic set of systems and integrations — the 17 of the signed-off
mockup's integration map plus one or two per other platform — with seeded failures, used by the "Sample estate"
adapter in the product and by the mock lab's simulators in tests (tests/mocklab/intan_sims.py translates it into
each vendor's own payload shape). Everything here is synthetic (DemoData), never client data; runs are generated
relative to "now" so baselines and trends work on any day.

Seeded risks: an API token expiring in 3 days (I-022), a pipeline 3× slower since 4 days ago (I-031), a bot that
fails because a screen changed (I-040) and the bot that waits on it (I-041), a file drop 18 % smaller than usual
(I-058), an announced portal schema change (I-063), OIC message-pack usage at 92 % (I-090), an SSIS package 2.6×
slower with 3 retries this week (I-095) and a job found only in logs that nobody owns (I-084).
"""
from __future__ import annotations

import hashlib
import time

SYSTEMS = {
    "tally": ("Tally", "ERP"), "zoho": ("Zoho Books", "Finance"), "fusion": ("Oracle Fusion", "ERP"), "sap": ("SAP S/4HANA", "ERP"),
    "sqlsrv": ("SQL Server", "Database"), "n8n": ("n8n", "Workflow tool"), "adf": ("Azure Data Factory", "Pipeline tool"),
    "oic": ("Oracle Integration Cloud", "Integration platform"), "uipath": ("UiPath", "RPA"), "ssis": ("SSIS", "ETL tool"),
    "gst": ("GST portal", "Portal"), "dwh": ("Snowflake", "Warehouse"), "crm": ("Salesforce", "CRM"), "sftp": ("Bank SFTP", "Files"),
    "jira": ("Jira / Freshservice", "ITSM"), "pbi": ("Power BI", "BI"),
    # the lab's extra systems
    "sharepoint": ("SharePoint", "Content"), "dynamics": ("Dynamics 365", "ERP"), "netsuite": ("NetSuite", "ERP"), "teams": ("Teams", "Collaboration"),
    "s3": ("Amazon S3", "Files"), "redshift": ("Redshift", "Warehouse"), "mail": ("Finance inbox", "Mail"), "share": ("Finance share", "Files"),
    "payroll": ("Payroll portal", "Portal"), "hr": ("HR system", "HR"), "webshop": ("Web shop", "Apps"), "erp": ("ERP", "ERP"),
}
RACI = [  # owners from the RACI table (pattern -> owner) for integrations whose tool does not expose an owner
    ("Power BI refresh", "BI team"), ("Bank statements", "Treasury"), ("Oracle Integration Cloud", "Oracle team"),
]

# ---- the map: [id, source adapter, name, from, to, via, kind, schedule text, cadence, owner (None = not exposed by the tool), baseline seconds, success rate, volume, seeded plan]
ESTATE = [
    {"id": "I-014", "source": "n8n", "name": "Tally vouchers → warehouse", "from": "tally", "to": "n8n", "via": "n8n", "kind": "Flow", "schedule": "Every 30 min", "every_min": 30, "owner": "Finance IT", "duration_s": 42, "success": .996, "volume": 1200},
    {"id": "I-015", "source": "n8n", "name": "n8n → Snowflake vouchers load", "from": "n8n", "to": "dwh", "via": "n8n", "kind": "Flow", "schedule": "Every 30 min", "every_min": 30, "owner": "Finance IT", "duration_s": 18, "success": .996, "volume": 1200, "writes": ["snowflake:FINANCE.VOUCHERS"]},
    {"id": "I-022", "source": "adf", "name": "Zoho Books invoices → ADF", "from": "zoho", "to": "adf", "via": "ADF", "kind": "API pull", "schedule": "Hourly", "every_min": 60, "owner": "Data team", "duration_s": 180, "success": .979, "volume": 850,
     "plan": {"kind": "credential", "name": "ZohoBooks-OAuth", "expires_days": 3}},
    {"id": "I-023", "source": "adf", "name": "ADF → Snowflake finance mart", "from": "adf", "to": "dwh", "via": "ADF", "kind": "Pipeline", "schedule": "Hourly", "every_min": 60, "owner": "Data team", "duration_s": 360, "success": 1.0, "volume": 850, "writes": ["snowflake:FINANCE.FACT_INVOICES"]},
    {"id": "I-031", "source": "adf", "name": "SAP GL extract → ADF", "from": "sap", "to": "adf", "via": "ADF", "kind": "Pipeline", "schedule": "Daily 02:00", "daily_at": 2, "owner": "SAP team", "duration_s": 780, "success": .933, "volume": 410000,
     "plan": {"kind": "slow", "factor": 3.15, "since_days": 4}},
    {"id": "I-040", "source": "uipath", "name": "SAP vendor master → UiPath", "from": "sap", "to": "uipath", "via": "UiPath", "kind": "Bot", "schedule": "Daily 06:00", "daily_at": 6, "owner": "Procurement", "duration_s": 720, "success": .867, "volume": 320,
     "plan": {"kind": "screen_change", "last_n": 4, "error": "Selector not found: 'Vendor master' screen — element 'Save' (the screen gained a field on 3 Nov)"}},
    {"id": "I-041", "source": "uipath", "name": "UiPath → Salesforce accounts", "from": "uipath", "to": "crm", "via": "UiPath", "kind": "Bot", "schedule": "Daily 06:30", "daily_at": 6.5, "owner": "Sales ops", "duration_s": 300, "success": .867, "volume": 320, "depends_on": ["I-040"],
     "plan": {"kind": "dependency", "on": "I-040", "last_n": 4}},
    {"id": "I-052", "source": "logs", "name": "Snowflake → Power BI refresh", "from": "dwh", "to": "pbi", "via": "Power BI", "kind": "Refresh", "schedule": "8×/day", "every_min": 180, "owner": None, "duration_s": 540, "success": .988, "volume": None, "feeds": ["Board Pack"]},
    {"id": "I-058", "source": "sftp", "name": "Bank statements SFTP → ADF", "from": "sftp", "to": "adf", "via": "ADF", "kind": "File", "schedule": "Daily 07:00", "daily_at": 7, "owner": None, "duration_s": 60, "success": 1.0, "volume": 3500000,
     "plan": {"kind": "volume_drop", "pct": 18}},
    {"id": "I-063", "source": "apigw", "name": "GST returns ← Zoho Books", "from": "zoho", "to": "gst", "via": "ClearTax", "kind": "API push", "schedule": "Monthly", "monthly_day": 20, "owner": "Tax", "duration_s": 240, "success": 1.0, "volume": 1,
     "plan": {"kind": "schema_change", "text": "Portal schema change announced for Dec: GSTR-1 v2 fields", "due_days": 26}},
    {"id": "I-071", "source": "n8n", "name": "Power BI alerts → Jira", "from": "pbi", "to": "jira", "via": "n8n", "kind": "Webhook", "schedule": "On event", "events_per_day": 9, "owner": "BI team", "duration_s": 2, "success": 1.0, "volume": 1},
    {"id": "I-077", "source": "airflow", "name": "Salesforce → Snowflake", "from": "crm", "to": "dwh", "via": "Airflow", "kind": "Pipeline", "schedule": "Every 15 min", "every_min": 15, "owner": "Data team", "duration_s": 40, "success": .999, "volume": 230, "writes": ["snowflake:SALES.ACCOUNTS"]},
    {"id": "I-090", "source": "oic", "name": "Oracle Fusion AP invoices → OIC", "from": "fusion", "to": "oic", "via": "OIC", "kind": "Integration", "schedule": "Every 15 min", "every_min": 15, "owner": None, "duration_s": 25, "success": .992, "volume": 140,
     "plan": {"kind": "usage", "value": 920000, "limit": 1000000, "text": "OIC message usage at 92 % of the monthly pack"}},
    {"id": "I-091", "source": "oic", "name": "OIC → Snowflake AP mart", "from": "oic", "to": "dwh", "via": "OIC", "kind": "Integration", "schedule": "Every 15 min", "every_min": 15, "owner": None, "duration_s": 12, "success": .998, "volume": 140, "writes": ["snowflake:FINANCE.AP_INVOICES"]},
    {"id": "I-095", "source": "ssis", "name": "SQL Server sales → SSIS package", "from": "sqlsrv", "to": "ssis", "via": "SSIS", "kind": "Package", "schedule": "Nightly 01:00", "daily_at": 1, "owner": "Data team", "duration_s": 1200, "success": .90, "volume": 2100000,
     "plan": {"kind": "slow", "factor": 2.6, "since_days": 6, "retries": 3}},
    {"id": "I-096", "source": "ssis", "name": "SSIS → Snowflake sales mart", "from": "ssis", "to": "dwh", "via": "SSIS", "kind": "Package", "schedule": "Nightly 02:00", "daily_at": 2, "owner": "Data team", "duration_s": 1080, "success": .967, "volume": 2100000, "writes": ["snowflake:SALES.FACT_SALES"]},
    {"id": "I-084", "source": "logs", "name": "SAP S/4HANA → Bank SFTP export", "from": "sap", "to": "sftp", "via": None, "kind": "File", "schedule": "Unknown", "daily_at": 5.97, "owner": None, "duration_s": 90, "success": 1.0, "volume": 18000,
     "plan": {"kind": "orphan", "text": "SAP logs"}},
]

# ---- one or two per other platform, each with a seeded failure, for the mock lab (not part of the 17-map)
LAB = {
    "cpi": [{"id": "L-CPI-1", "name": "S/4 → Salesforce orders", "from": "sap", "to": "crm", "via": "SAP CPI", "kind": "Integration", "schedule": "Every 10 min", "every_min": 10, "owner": "Integration CoE", "duration_s": 8, "success": .99, "volume": 60},
            {"id": "L-CPI-2", "name": "Salesforce → S/4 customers", "from": "crm", "to": "sap", "via": "SAP CPI", "kind": "Integration", "schedule": "Hourly", "every_min": 60, "owner": "Integration CoE", "duration_s": 30, "success": .95, "volume": 20,
             "plan": {"kind": "credential_expired", "name": "SFDC_OAuth", "last_n": 5, "error": "401 Unauthorized from Salesforce: OAuth token expired"}}],
    "mulesoft": [{"id": "L-MULE-1", "name": "Order API → NetSuite", "from": "webshop", "to": "netsuite", "via": "MuleSoft", "kind": "API", "schedule": "On event", "events_per_day": 400, "owner": "Integration CoE", "duration_s": 1, "success": .999, "volume": 1},
                 {"id": "L-MULE-2", "name": "NetSuite → Web shop inventory", "from": "netsuite", "to": "webshop", "via": "MuleSoft", "kind": "Integration", "schedule": "Every 5 min", "every_min": 5, "owner": "Integration CoE", "duration_s": 6, "success": .97, "volume": 900,
                  "plan": {"kind": "failing", "last_n": 6, "error": "HTTP 502 from NetSuite SuiteTalk endpoint"}}],
    "boomi": [{"id": "L-BOOMI-1", "name": "NetSuite → Zoho Books invoices", "from": "netsuite", "to": "zoho", "via": "Boomi", "kind": "Integration", "schedule": "Hourly", "every_min": 60, "owner": "Finance IT", "duration_s": 95, "success": .99, "volume": 400,
               "plan": {"kind": "volume_drop", "pct": 31}}],
    "logicapps": [{"id": "L-LA-1", "name": "Teams approvals → SharePoint", "from": "teams", "to": "sharepoint", "via": "Logic Apps", "kind": "Flow", "schedule": "On event", "events_per_day": 25, "owner": "Workplace IT", "duration_s": 3, "success": 1.0, "volume": 1},
                  {"id": "L-LA-2", "name": "Invoice OCR → Dynamics 365", "from": "sharepoint", "to": "dynamics", "via": "Logic Apps", "kind": "Flow", "schedule": "Every 15 min", "every_min": 15, "owner": "Finance IT", "duration_s": 20, "success": .99, "volume": 30,
                   "plan": {"kind": "slow", "factor": 3.4, "since_days": 3}}],
    "glue": [{"id": "L-GLUE-1", "name": "S3 clickstream → Redshift", "from": "s3", "to": "redshift", "via": "AWS Glue", "kind": "Pipeline", "schedule": "Hourly", "every_min": 60, "owner": "Data platform", "duration_s": 600, "success": .96, "volume": 5000000,
              "plan": {"kind": "failing", "last_n": 3, "error": "An error occurred while calling o123.pyWriteDynamicFrame: S3 access denied"}}],
    "powerautomate": [{"id": "L-PA-1", "name": "Email attachments → SharePoint", "from": "mail", "to": "sharepoint", "via": "Power Automate", "kind": "Flow", "schedule": "On event", "events_per_day": 40, "owner": "Finance IT", "duration_s": 4, "success": .98, "volume": 1,
                       "plan": {"kind": "credential_expired", "name": "Office 365 Outlook (finance-bot)", "last_n": 8, "error": "Connection 'Office 365 Outlook' is in error: token expired"}}],
    "blueprism": [{"id": "L-BP-1", "name": "Payroll portal → HR system", "from": "payroll", "to": "hr", "via": "Blue Prism", "kind": "Bot", "schedule": "Daily 05:00", "daily_at": 5, "owner": "HR ops", "duration_s": 900, "success": .9, "volume": 150,
                   "plan": {"kind": "screen_change", "last_n": 3, "error": "Element not found: 'Submit timesheet' button (application screen changed)"}}],
    "aa": [{"id": "L-AA-1", "name": "AP matching bot", "from": "mail", "to": "erp", "via": "Automation Anywhere", "kind": "Bot", "schedule": "Daily 04:00", "daily_at": 4, "owner": "Finance ops", "duration_s": 1500, "success": .9, "volume": 200,
            "plan": {"kind": "screen_change", "last_n": 3, "error": "UI element not found: object 'Invoice number' (screen changed)"}}],
    "mail": [{"id": "L-MAIL-1", "name": "Supplier statements inbox → finance share", "from": "mail", "to": "share", "via": "Mail rule", "kind": "File", "schedule": "Daily", "daily_at": 8, "owner": None, "duration_s": 5, "success": 1.0, "volume": 24,
              "plan": {"kind": "volume_drop", "pct": 50}}],
    "kong": [{"id": "L-KONG-1", "name": "orders-api", "from": "webshop", "to": "erp", "via": "Kong", "kind": "API", "schedule": "On event", "events_per_day": 2000, "owner": "Platform team", "duration_s": 0.2, "success": .995, "volume": 1},
             {"id": "L-KONG-2", "name": "stock-api", "from": "erp", "to": "webshop", "via": "Kong", "kind": "API", "schedule": "On event", "events_per_day": 800, "owner": "Platform team", "duration_s": 0.3, "success": .72, "volume": 1,
              "plan": {"kind": "failing", "last_n": 40, "error": "HTTP 500 from upstream stock service"}}],
}
LAB_SIGNALS = {"cpi": [], "mulesoft": [{"kind": "licence", "text": "vCore usage at 88 % of the subscription", "value": .88, "limit": 1.0}]}


def by_source(kind: str) -> list[dict]:
    return [i for i in ESTATE if i["source"] == kind]


def _r(seed: str) -> float:
    return int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def slots(spec: dict, now: float, days: int = 42) -> list[float]:
    """When this integration ran in the last `days` days, newest last."""
    out, start = [], now - days * 86400
    if spec.get("every_min"):
        step = spec["every_min"] * 60
        t = now - (now % step)
        while t > start:
            out.append(t); t -= step
    elif spec.get("daily_at") is not None:
        day = now - (now % 86400)
        t = day + spec["daily_at"] * 3600
        if t > now:
            t -= 86400
        while t > start:
            out.append(t); t -= 86400
    elif spec.get("monthly_day"):
        day = now - (now % 86400)
        t = day - ((int(day // 86400) - spec["monthly_day"]) % 30) * 86400 + 9 * 3600
        if t > now:
            t -= 30 * 86400
        while t > start:
            out.append(t); t -= 30 * 86400
    elif spec.get("events_per_day"):
        n = int(spec["events_per_day"] * days)
        for i in range(min(n, 600)):
            out.append(now - (i * days * 86400 / max(1, min(n, 600))) - _r(f"{spec['id']}-{i}") * 600)
    out.reverse()
    return out[-600:]


def runs(spec: dict, now: float | None = None, days: int = 42) -> list[dict]:
    """Deterministic run history with the seeded failure applied to the newest runs."""
    now = now or time.time()
    plan = spec.get("plan") or {}
    times = slots(spec, now, days)
    out = []
    n = len(times)
    for i, t in enumerate(times):
        age_days = (now - t) / 86400
        seed = f"{spec['id']}-{i}"
        base = spec["duration_s"] * (1 + (_r(seed + "d") - .5) * .24)
        vol = spec.get("volume")
        if vol is not None:
            vol = vol * (1 + (_r(seed + "v") - .5) * .06)
        status, error = ("success", None) if _r(seed + "s") <= spec["success"] else ("failed", "Timeout after 600 s" if _r(seed + "e") < .5 else "HTTP 502 from endpoint")
        if plan.get("kind") == "slow" and age_days <= plan["since_days"]:
            base *= plan["factor"]
        last = n - i
        if plan.get("kind") in ("failing", "screen_change", "credential_expired") and last <= plan.get("last_n", 3):
            status, error = "failed", plan["error"]
        if plan.get("kind") == "dependency" and last <= plan.get("last_n", 3):
            status, error, base, vol = "skipped", f"Skipped: waits on {plan['on']}", 0, 0
        if plan.get("kind") == "volume_drop" and last == 1 and vol is not None:
            vol = spec["volume"] * (1 - plan["pct"] / 100)
        out.append({"integration": spec["id"], "ext_id": f"{spec['id']}-{i:04d}", "started": t, "ended": t + base, "status": status,
                    "duration_s": round(base, 1), "volume": round(vol) if vol is not None else None, "error": error})
    if plan.get("retries"):                                                  # a failed run followed by a successful re-run
        for k in range(plan["retries"]):
            t = now - (1 + 2 * k) * 86400 + 3600
            out.append({"integration": spec["id"], "ext_id": f"{spec['id']}-retry{k}", "started": t, "ended": t + 300, "status": "failed", "duration_s": 300, "volume": 0, "error": "Deadlock on source table; retried"})
            out.append({"integration": spec["id"], "ext_id": f"{spec['id']}-retry{k}b", "started": t + 600, "ended": t + 600 + spec["duration_s"] * plan.get("factor", 1), "status": "success", "duration_s": spec["duration_s"] * plan.get("factor", 1), "volume": spec.get("volume"), "error": None})
        out.sort(key=lambda r: r["started"])
    return out


def credentials(specs: list[dict], now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for s in specs:
        p = s.get("plan") or {}
        if p.get("kind") == "credential":
            out.append({"name": p["name"], "kind": "oauth", "integration": s["id"], "expires": now + p["expires_days"] * 86400, "status": "valid"})
        elif p.get("kind") == "credential_expired":
            out.append({"name": p["name"], "kind": "oauth", "integration": s["id"], "expires": now - 86400, "status": "expired"})
    return out


def signals(specs: list[dict], now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for s in specs:
        p = s.get("plan") or {}
        if p.get("kind") == "usage":
            out.append({"kind": "usage", "integration": s["id"], "text": p["text"], "value": p["value"], "limit": p["limit"], "due": None})
        elif p.get("kind") == "schema_change":
            out.append({"kind": "schema_change", "integration": s["id"], "text": p["text"], "value": None, "limit": None, "due": now + p["due_days"] * 86400})
    return out


def discovery(specs: list[dict], now: float | None = None, owners: bool = True) -> dict:
    """The estate as an adapter would report it (the Sample estate adapter returns exactly this)."""
    now = now or time.time()
    systems = {}
    for s in specs:
        for key in (s["from"], s["to"]):
            name, kind = SYSTEMS[key]
            systems[name] = {"name": name, "kind": kind}
    integrations = [{"ext_id": s["id"], "name": s["name"], "kind": s["kind"], "via": s["via"], "from_system": SYSTEMS[s["from"]][0], "to_system": SYSTEMS[s["to"]][0],
                     "schedule": s["schedule"], "owner": s["owner"] if owners else None, "depends_on": s.get("depends_on") or [], "writes": s.get("writes") or [], "reads": [], "feeds": s.get("feeds") or [],
                     "properties": {"found_in": (s.get("plan") or {}).get("text") if (s.get("plan") or {}).get("kind") == "orphan" else None}} for s in specs]
    return {"systems": list(systems.values()), "integrations": integrations, "runs": [r for s in specs for r in runs(s, now)],
            "credentials": credentials(specs, now), "signals": signals(specs, now)}


def mockup_map() -> list[tuple[str, str, str]]:
    """(id, from system, to system) of the 17 integrations the mockup shows — what the tests reproduce."""
    return [(s["id"], SYSTEMS[s["from"]][0], SYSTEMS[s["to"]][0]) for s in ESTATE]


def expected_risks() -> dict[str, str]:
    """integration id -> the risk kind its seeded failure must raise."""
    out = {}
    for s in ESTATE + [x for v in LAB.values() for x in v]:
        p = s.get("plan") or {}
        if p.get("kind") == "credential":
            out[s["id"]] = "credential_expiring"
        elif p.get("kind") == "credential_expired":
            out[s["id"]] = "credential_expired"
        elif p.get("kind") == "slow":
            out[s["id"]] = "slow" if p["factor"] >= 3 else "slowing"
        elif p.get("kind") == "screen_change":
            out[s["id"]] = "screen_change"
        elif p.get("kind") == "dependency":
            out[s["id"]] = "dependency"
        elif p.get("kind") == "volume_drop":
            out[s["id"]] = "volume_drop"
        elif p.get("kind") == "usage":
            out[s["id"]] = "usage"
        elif p.get("kind") == "schema_change":
            out[s["id"]] = "schema_change"
        elif p.get("kind") == "orphan":
            out[s["id"]] = "no_owner"
        elif p.get("kind") == "failing":
            out[s["id"]] = "failing"
    return out
