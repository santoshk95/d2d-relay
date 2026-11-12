"""The module registry (build-plan v2, P9): one catalogue of everything RELAY by PASDACS does, grouped under the six
PASDACS pillars, with platforms, work types, journeys, checkpoints and links to the screens that exist today. The
menu, Home, All modules, search and every module page read it. Ported from the signed-off mockup
(mockup-a2z/core.js, screens-home.js, screens-start.js, v0.12) - keep the two in step until the mockup retires.

Also the brand settings (Admin > Branding): the install's name, mark, colours and partner mode, with the fixed
"Powered by PASDACS Relay" line for white-labelled partners.

P17: the brand and the edition follow the tenant. A service partner white-labels its workspace and its clients'
(a client may save its own); direct clients and the platform show RELAY by PASDACS. The edition is the tenant's
(Branding's edition setting stays for the platform's own workspace); a module switched off for the tenant is "off".
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db

router = APIRouter()

PILLARS = [
    ("process", "Process", "Requirements, process documents, controls and who does what"),
    ("automation", "Automation", "RPA, workflows, documents and jobs - the chasing and re-keying, gone"),
    ("systems", "Systems", "ERP, finance, CRM, HR, ITSM, apps and cloud - connected, built and shipped"),
    ("data", "Data & Analytics", "Warehouse, pipelines, BI, ontology, metrics, quality and governance"),
    ("ai", "Artificial Intelligence", "Conversational, predictive, recommending and assisting - with the working shown"),
    ("consulting", "Consulting services", "Strategy, architecture, proposals, estimates, delivery, run and value"),
]
WORK = [("assess", "Assess"), ("develop", "Develop"), ("change", "Fix / change"), ("migrate", "Migrate"), ("run", "Run & support")]
ALLW = [w for w, _ in WORK]

# Routes of the screens that exist in the app today (the mockup's names on the left).
LIVE = {"d2d": "#/d2d", "askd": "#/askd", "schedule": "#/schedules", "semantics": "#/metrics", "metrics": "#/metrics",
        "brd": "#/m/brd", "processdocs": "#/m/processdocs", "raci": "#/m/raci", "mining": "#/m/mining", "controls": "#/m/controls", "testdocs": "#/m/testdocs",  # W4 Process (workbench packs)
        "demodata": "#/new", "visuals": "#/library", "connections": "#/connections", "gates": "#/d2d", "publish": "#/pages",
        "runners": "#/admin/ai", "ops": "#/admin/monitoring", "govern": "#/admin/people", "settings": "#/settings",
        "knowledge": "#/graph", "observe": "#/observability", "intan": "#/integrations", "servicedesk": "#/servicedesk", "migbi": "#/migrate-bi",
        "studio": "#/studio", "rfp": "#/rfp", "heal": "#/heal", "sdlc": "#/sdlc", "quality": "#/m/quality",
        "delivery": "#/m/delivery", "assess": "#/m/assess", "strategy": "#/m/strategy", "selection": "#/m/selection",
        "managed": "#/m/managed", "finops": "#/m/finops", "enable": "#/m/enable",
        "architecture": "#/m/architecture",
        "predict": "#/m/predict", "anomaly": "#/m/anomaly", "recommend": "#/m/recommend", "assist": "#/m/assist", "agents": "#/m/agents", "aigov": "#/m/aigov"}          # W5 AI modules
LIVE.update({"pipelines": "#/m/pipelines", "dwh": "#/m/dwh", "governance": "#/m/governance", "mdm": "#/m/mdm", "excel": "#/m/excel"})          # W1 Data & Analytics modules on the workbench
LIVE.update({"erp": "#/m/erp", "integrate": "#/m/integrate", "crm": "#/m/crm", "hr": "#/m/hr", "iam": "#/m/iam", "plm": "#/m/plm", "collab": "#/m/collab", "apis": "#/m/apis", "ship": "#/m/ship", "apps": "#/m/apps", "connect": "#/m/connect"})          # W3 Systems modules on the workbench
LIVE.update({"n8n": "#/m/n8n", "rpa": "#/m/rpa", "idp": "#/m/idp", "jobs": "#/m/jobs"})          # W2 Automation modules on the workbench


def M(id, name, sub, text, pl, icon, platforms, work, **kw):  # noqa: A002
    return {"id": id, "name": name, "short": kw.pop("short", name), "sub": sub, "text": text, "pl": pl, "icon": icon,
            "platforms": platforms, "work": work, **kw}


MODULES = [
    # ---- Process
    M("brd", "BRD & requirements", "From workshops to an approved BRD and backlog", "Notes, call recordings and whiteboards turned into a BRD, user stories and acceptance criteria you approve.", "process", "file", ["Word", "Confluence", "SharePoint", "Jira", "Azure Boards", "Miro"], ["develop", "change", "migrate"], status="available", route="#/m/brd", links={"develop": "brd", "change": "brd", "migrate": "brd"}, stat="BRDs, sign-offs, backlogs and traceability live", api=["/api/m/brd"]),
    M("processdocs", "Business process documents", "Process maps and SOPs", "From interviews or a screen recording to BPMN maps and step-by-step procedures, kept current.", "process", "route", ["BPMN 2.0", "Visio", "Signavio", "ARIS", "Bizagi", "Lucidchart"], ["assess", "develop", "change", "migrate"], short="Process documents", status="available", route="#/m/processdocs", links={"assess": "processdocs", "develop": "processdocs", "change": "processdocs", "migrate": "processdocs"}, stat="BPMN maps, SOPs and migration from Visio live", api=["/api/m/processdocs"]),
    M("raci", "RACI & operating model", "Who does, approves and is told", "Roles, responsibilities and approvals per process and system - agents included as roles.", "process", "users", ["Excel", "SharePoint", "Entra ID groups", "Org charts"], ["assess", "develop", "change"], status="available", route="#/m/raci", links={"assess": "raci", "develop": "raci", "change": "raci"}, stat="RACI with conflicts checked and owners' agreement live", api=["/api/m/raci"]),
    M("mining", "Process mining & discovery", "How the work really runs", "Event logs from ERP and ticketing turned into the real process - variants, delays, rework and what to automate first.", "process", "search", ["Celonis", "UiPath Process Mining", "Power Automate Process Mining", "Signavio PI", "SAP / Oracle event logs"], ["assess", "develop", "run"], short="Process mining", status="available", route="#/m/mining", links={"assess": "mining", "develop": "mining", "run": "mining"}, stat="Variants, delays, rework, event logs from SAP and KPIs watched live", api=["/api/m/mining"]),
    M("controls", "Controls & compliance", "Internal controls with evidence", "Controls mapped to processes and systems; evidence collected automatically for audits and statutory returns.", "process", "shield", ["SOX / ICFR", "SAP GRC", "AuditBoard", "GST - TRACES - MCA", "Excel trackers"], ["assess", "develop", "change", "run"], status="available", route="#/m/controls", links={"assess": "controls", "develop": "controls", "change": "controls", "run": "controls"}, stat="Controls mapped to processes and owners, evidence collected by rules live", api=["/api/m/controls"]),
    M("testdocs", "Test plans & UAT scripts", "From requirements to signed-off tests", "Test cases and UAT scripts generated from the BRD, run on synthetic data, signed off by business users.", "process", "check", ["Jira Xray", "Zephyr", "TestRail", "Azure Test Plans", "Excel"], ["develop", "change", "migrate"], short="Test plans & UAT",
      status="available", route="#/m/testdocs", links={"develop": "testdocs", "change": "testdocs", "migrate": "testdocs"}, stat="Test cases from the acceptance criteria, coverage proven, business sign-off live", api=["/api/m/testdocs"]),
    # ---- Automation
    M("rpa", "RPA", "Bots built, fixed, moved and run", "New bots where no API exists; broken bots fixed; bots moved between platforms - APIs instead of screens where possible.", "automation", "cpu", ["UiPath", "Blue Prism", "Automation Anywhere", "Power Automate Desktop", "SS&C Blue Prism Cloud", "Python (Playwright)"], ALLW, status="available", route="#/m/rpa", links={w: "rpa" for w in ("assess", "change", "migrate", "run")}, api=["/api/m/rpa"]),
    M("n8n", "Workflows & iPaaS", "Flows between apps, from plain words", "Describe the flow or start from a process map - built, tested and deployed to the platform you run.", "automation", "route", ["n8n", "Power Automate", "Zapier", "Make", "Workato", "Boomi", "MuleSoft"], ALLW, status="available", route="#/m/n8n", links={"assess": "n8n", "develop": "n8n", "change": "n8n", "migrate": "n8n", "run": "n8n"}, stat="n8n flows designed, tested and deployed; moves from Power Automate, Zapier, Make, Workato, Boomi and MuleSoft proven side by side", api=["/api/m/n8n"]),
    M("idp", "Document processing", "Invoices, POs, KYC and forms read for you", "Fields and tables pulled from scans, PDFs and emails with confidence scores; low-confidence items go to a person.", "automation", "file", ["Azure AI Document Intelligence", "AWS Textract", "Google Document AI", "UiPath Document Understanding", "ABBYY"], ALLW, status="available", route="#/m/idp", links={w: "idp" for w in ("assess", "develop", "change", "run")}, api=["/api/m/idp"]),
    M("jobs", "Job scheduling & orchestration", "Batch and pipeline schedules", "Schedules and dependencies for jobs, pipelines and bots - calendars, retries and SLAs in one place.", "automation", "clock", ["Control-M", "AutoSys", "Apache Airflow", "ADF triggers", "Windows Task Scheduler", "cron"], ALLW, short="Jobs & orchestration", status="available", route="#/m/jobs", links={w: "jobs" for w in ("assess", "develop", "change", "migrate", "run")}, api=["/api/m/jobs"]),
    M("schedule", "Reports & alerts", "Scheduled delivery, drafted from plain words", "PDF reports and measure alerts by mail or Teams, on your time zone.", "automation", "bell", ["Email (Microsoft, Gmail)", "Teams", "Slack", "Power BI subscriptions", "Cognos schedules"], ["develop", "change", "migrate", "run"], status="available", route="#/schedules", roles=["admin", "dev", "viewer"], links={"develop": "schedule", "change": "schedule", "run": "schedule"}, api=["/api/schedules"]),
    M("heal", "Self-healing", "Failures fixed with approval", "Refreshes, pipelines, flows and bots watched; a fix tested in a copy; applied when a person approves.", "automation", "heart", ["Power BI", "ADF", "Airflow", "n8n", "UiPath", "Logs & alerts"], ["assess", "develop", "run"], status="available", route="#/heal", links={"run": "heal", "change": "heal"}, api=["/api/heal"]),
    # ---- Systems
    M("erp", "ERP", "Core ERP - integrated, extended, moved", "Extracts, integrations, reports and moves between ERPs - mapping agreed with you, proven record by record.", "systems", "db", ["SAP S/4HANA", "SAP ECC", "Oracle Fusion (ERP, SCM)", "Oracle Retail MFCS", "Oracle E-Business Suite", "Dynamics 365 F&O", "Oracle NetSuite", "Odoo"], ALLW, status="available", route="#/m/erp", links={w: "erp" for w in ALLW}, api=["/api/m/erp"]),
    M("plm", "PLM", "Products, parts, BOMs and engineering changes", "Parts, BOMs and engineering changes kept in step with ERP (eBOM -> mBOM), cleaned, reported and moved between PLM systems - every record reconciled.", "systems", "layers", ["Siemens Teamcenter", "PTC Windchill", "Dassault 3DEXPERIENCE / ENOVIA", "Oracle Agile PLM", "SAP PLM", "Aras Innovator", "Arena PLM"], ALLW, status="available", route="#/m/plm", links={w: "plm" for w in ALLW}, api=["/api/m/plm"]),
    M("integrate", "Finance & accounting", "Books, tax and statutory portals", "Tally, Zoho Books and others connected to your warehouse and ERP; GST and statutory filings prepared with evidence.", "systems", "book", ["Oracle Fusion Financials", "Tally", "Zoho Books", "QuickBooks", "Xero", "Busy", "ClearTax", "GST - TRACES - MCA portals"], ALLW, status="available", route="#/m/integrate", links={w: "integrate" for w in ALLW}, api=["/api/m/integrate"]),
    M("crm", "CRM & sales", "Customers, pipeline and service", "CRM data cleaned, integrated and reported; workflows automated; moves between CRMs proven.", "systems", "users", ["Salesforce", "Dynamics 365 CE", "Zoho CRM", "HubSpot", "Freshsales"], ALLW, status="available", route="#/m/crm", links={w: "crm" for w in ALLW}, api=["/api/m/crm"]),
    M("hr", "HR & payroll", "People data, joiners and payroll inputs", "Joiner-mover-leaver flows, payroll inputs and HR reporting - personal data handled by policy.", "systems", "users", ["Oracle Fusion HCM", "SAP SuccessFactors", "Workday", "Zoho People", "Darwinbox", "Keka"], ALLW, status="available", route="#/m/hr", links={w: "hr" for w in ALLW}, api=["/api/m/hr"]),
    M("servicedesk", "ITSM & service desk", "Tickets summarised, grouped and routed", "Every ticket summarised, duplicates grouped, priority by business impact - routed to an agent or a person.", "systems", "bell", ["Jira Service Management", "Freshservice", "ServiceNow", "Zendesk", "ManageEngine"], ALLW, short="ITSM - service desk", designed=True, status="available", route="#/servicedesk", roles=["admin", "dev", "viewer"], links={"run": "servicedesk", "change": "servicedesk"}, api=["/api/servicedesk"]),
    M("collab", "Collaboration & content", "Sites, files and knowledge", "SharePoint, Teams and Google Workspace content organised, permissioned and moved - and searchable by agents.", "systems", "folder", ["SharePoint", "Teams", "OneDrive", "Google Workspace", "Confluence"], ALLW, status="available", route="#/m/collab", links={w: "collab" for w in ALLW}, api=["/api/m/collab"]),
    M("intan", "Integration analytics", "Every integration, mapped and watched", "Discovers the APIs, flows, bots, jobs and file transfers running between your systems; shows their health and risks, and raises fixes before anyone notices.", "systems", "pulse", ["Oracle Integration Cloud (OIC)", "SSIS", "Azure Data Factory", "SAP CPI - PI/PO", "MuleSoft", "Boomi", "Informatica", "Azure Logic Apps", "AWS Glue", "Airflow", "n8n - Power Automate", "UiPath - Blue Prism - AA", "API gateways", "SFTP - email file drops", "System logs & ITSM"], ["assess", "change", "run"], status="available", route="#/integrations", links={"assess": "intan", "run": "intan"}, api=["/api/intan"]),
    M("apis", "Integration & APIs", "APIs, events and middleware", "APIs designed and documented, events and queues wired, middleware built or moved - with contract tests.", "systems", "swap", ["REST / SOAP", "OpenAPI", "Oracle Integration Cloud (OIC)", "SAP CPI - PI/PO", "MuleSoft", "Boomi", "Azure Logic Apps", "Azure API Management", "Kafka", "Azure Service Bus"], ALLW, status="available", route="#/m/apis", links={w: "apis" for w in ("assess", "change", "run")}, api=["/api/m/apis"]),
    M("apps", "Apps & products", "From idea to working product", "Web, mobile and low-code apps or services - spec agreed first, built in a repository you own.", "systems", "layers", ["Web (React, Angular)", "Android", "iOS", "Power Apps", "AppSheet", "Zoho Creator", "Python - Java - Node.js"], ALLW, status="available", route="#/m/apps", links={w: "apps" for w in ("assess", "change", "run")}, api=["/api/m/apps"]),
    M("sdlc", "AI SDLC", "Change requests by governed agents", "Bring your Git repository: plan, develop, test, UAT on synthetic data and release - approved and audited, team-wide.", "systems", "code", ["GitHub", "Azure DevOps", "GitLab", "Bitbucket", "Jira", "Azure Boards"], ["assess", "develop", "change", "run"], status="available", route="#/sdlc", links={"develop": "sdlc", "change": "sdlc"}, api=["/api/sdlc"]),
    M("ship", "Cloud & CI/CD", "Deploy with the right connections", "Environments, identity, infrastructure as code and pipelines - every release gated and reversible.", "systems", "send", ["Microsoft Azure", "AWS", "Google Cloud", "GitHub Actions", "Azure DevOps", "Terraform", "Kubernetes"], ALLW, status="available", route="#/m/ship", links={w: "ship" for w in ("assess", "change", "run")}, api=["/api/m/ship"]),
    M("iam", "Identity & access", "Who can see and do what", "Single sign-on, groups and access reviews across the systems you run - joiners and leavers handled.", "systems", "lock", ["Entra ID", "Okta", "Google Workspace", "AWS IAM", "SAP roles"], ALLW, status="available", route="#/m/iam", links={w: "iam" for w in ALLW}, api=["/api/m/iam"]),
    M("connect", "Connections", "Warehouses and files, signed in as you", "Your sources with your own sign-in; extract or live.", "systems", "plug", ["ERP & PLM", "Finance & HR", "CRM & ITSM", "Warehouses", "Integration & RPA", "BI tools", "Files", "Code & cloud"], ["assess", "change", "run"], status="available", route="#/connections", links={w: "connect" for w in ("assess", "change", "run")}, api=["/api/m/connect"]),
    # ---- Data & Analytics
    M("dwh", "Data warehouse & lakehouse", "Designed, built, tuned or migrated", "Models on the platform you choose - or legacy warehouses such as Oracle / Exadata, Teradata and Netezza moved to the cloud, with reconciliation.", "data", "db", ["Snowflake", "BigQuery", "Databricks", "Microsoft Fabric", "Redshift", "Synapse", "Oracle Autonomous DW", "Oracle Exadata", "Oracle DW (on-premises)", "Teradata", "Netezza", "Greenplum", "IBM Db2", "SQL Server", "Hadoop / Hive"], ALLW, short="Warehouse & lakehouse", status="available", route="#/m/dwh", links={"assess": "dwh", "develop": "dwh", "change": "dwh", "migrate": "dwh", "run": "dwh"}, stat="Warehouse migration proven table by table", api=["/api/m/dwh"]),
    M("pipelines", "Data pipelines & ETL", "Ingest, transform, test", "Pipelines written, fixed and moved between tools - rules first, AI where none fits, every load tested.", "data", "route", ["SSIS", "Azure Data Factory", "dbt", "Informatica", "Talend", "DataStage", "Airflow", "AWS Glue", "Fivetran", "Oracle Data Integrator"], ALLW, short="Pipelines & ETL", status="available", route="#/m/pipelines", links={"assess": "pipelines", "develop": "pipelines", "change": "pipelines", "migrate": "pipelines", "run": "pipelines"}, stat="Assess, build, fix, migrate and run ETL estates", api=["/api/m/pipelines"]),
    M("bi", "BI & dashboards", "New dashboards, fixes, or the whole estate moved", "Describe a dashboard and get a proven Power BI file (.pbix) - or fix, rationalise and migrate an existing estate, every number proven.", "data", "chart", ["Power BI", "Tableau", "Looker", "Metabase", "Qlik Sense", "QlikView", "IBM Cognos", "MicroStrategy", "SAP BusinessObjects", "SSRS"], ALLW, status="available", route="#/d2d", roles=["admin", "dev"], links={"develop": "d2d", "change": "d2d", "assess": "migbi", "migrate": "migbi", "run": "schedule"}),
    M("semantics", "Ontology & semantic models", "How your data fits together", "Entities, keys and relationships across sources; semantic models with business descriptions people can read.", "data", "graph", ["Power BI semantic models", "dbt semantic layer", "LookML", "AtScale", "Fabric"], ["assess", "develop", "change", "migrate"], short="Ontology & semantics", status="available", route="#/metrics", links={"develop": "semantics", "change": "semantics"}, stat="Industry packs: entities, metrics, KPIs and sample data", api=["/api/semantic", "/api/m/semantics"]),
    M("metrics", "Formulas & metrics", "One definition per number", "Certified metrics with versions and four-eyes review; formulas translated between DAX, SQL, Excel and BI tools.", "data", "book", ["DAX", "SQL", "Excel", "LookML", "Tableau calcs", "Cognos expressions"], ["assess", "develop", "change", "migrate"], status="available", route="#/metrics", links={"develop": "metrics", "change": "metrics", "migrate": "migbi"}, api=["/api/semantic"]),
    M("observe", "Data observability", "Data health across every layer", "Freshness, volume, schema, distribution and reconciliation watched from source to report, agent and person - impact traced, fixes routed with approval.", "data", "gauge", ["Relay checks & lineage", "Monte Carlo", "Bigeye", "Acceldata", "Metaplane", "Elementary (dbt)", "Soda", "Great Expectations", "OpenLineage", "Datadog"], ALLW, designed=True, status="available", route="#/observability", links={"assess": "observe", "run": "observe"}, api=["/api/observe"]),
    M("quality", "Data quality & reconciliation", "Numbers that agree everywhere", "Quality rules, thresholds and source-to-report reconciliation; breaks raised in ITSM with the evidence.", "data", "scale", ["dbt tests", "Great Expectations", "Soda", "Power BI DAX checks", "Excel tie-outs"], ["assess", "develop", "change", "run"], short="Quality & reconciliation", status="available", route="#/m/quality", links={"assess": "quality", "develop": "quality", "change": "quality", "run": "quality"}, stat="Rules, reconciliation and scheduled checks live", api=["/api/m/quality"]),
    M("governance", "Data governance & catalogue", "Ownership, lineage and policy", "Who owns what, where it comes from and whether it can be trusted - synced with your catalogue.", "data", "shield", ["Microsoft Purview", "Collibra", "Alation", "Unity Catalog", "Atlan"], ALLW, short="Governance & catalogue", status="available", route="#/m/governance", links={"assess": "governance", "develop": "governance", "change": "governance", "migrate": "governance", "run": "governance"}, stat="Owners, classifications and terms fixed with approval", api=["/api/m/governance"]),
    M("mdm", "Master data", "One customer, supplier and product", "Golden records with match rules people confirm; duplicates and gaps fixed at the source.", "data", "target", ["SAP MDG", "Informatica MDM", "Reltio", "Profisee", "Excel masters"], ALLW, status="available", route="#/m/mdm", links={"assess": "mdm", "develop": "mdm", "change": "mdm", "migrate": "mdm", "run": "mdm"}, stat="Match rules proven; merges written with approval", api=["/api/m/mdm"]),
    M("excel", "Excel & spreadsheet models", "From fragile workbooks to governed models", "Finance and planning workbooks read, explained and rebuilt as governed models - or kept, with checks.", "data", "grid", ["Excel", "Google Sheets", "Power Query", "VBA macros"], ALLW, short="Excel models", status="available", route="#/m/excel", links={"assess": "excel", "develop": "excel", "change": "excel", "migrate": "excel", "run": "excel"}, stat="Workbooks evaluated again, fixed and rebuilt as proven models", api=["/api/m/excel"]),
    M("demodata", "Sample & synthetic data", "For demos, UAT and tests", "Realistic tables with stories planted in them - never real personal data.", "data", "dice", ["CSV", "Parquet", "SQL inserts", "Industry packs"], ["develop", "change"], short="Sample data", status="available", route="#/new", links={"develop": "demodata", "change": "demodata"}),
    M("visuals", "Visuals", "Library & factory", "Sixty chart types, or a new custom visual generated and tested for you.", "data", "layers", ["Power BI custom visuals", "Deneb / Vega", "D3"], ["develop", "change"], status="available", route="#/library", links={"develop": "visuals", "change": "visuals"}),
    # ---- Artificial Intelligence
    M("askd", "Conversational analytics", "Ask Relay - ask your data", "Plain questions answered with your own access, the SQL and the agreed metric - in the app, Teams or Slack.", "ai", "spark", ["Ask Relay", "Teams", "Slack", "Power BI Q&A", "Copilot"], ["assess", "develop", "change", "run"], status="available", route="#/askd", roles=["admin", "dev", "viewer"], links={"develop": "askd", "run": "askd"}, api=["/api/askd"]),
    M("predict", "Predictive analytics & forecasting", "Forecasts with their accuracy shown", "Demand, cash, churn and late-delivery forecasts, back-tested in plain words before anyone relies on them.", "ai", "pulse", ["Azure ML", "Databricks ML", "Vertex AI", "SageMaker", "Prophet", "Python"], ALLW, short="Predictive analytics", roles=["admin", "dev", "viewer"], status="available", route="#/m/predict", links={"assess": "predict", "develop": "predict", "change": "predict", "migrate": "predict", "run": "predict"}, stat="Back-tested forecasts, a person chooses the model", api=["/api/m/predict"]),
    M("anomaly", "Anomaly & risk detection", "Unusual numbers caught early", "Unusual postings, spend, delays and data drift flagged with the reason - before month-end, not after.", "ai", "alert", ["Power BI anomaly detection", "Azure AI", "Python", "Rules + ML"], ["assess", "develop", "change", "run"], short="Anomalies & risk", status="available", route="#/m/anomaly", links={"assess": "anomaly", "develop": "anomaly", "change": "anomaly", "run": "anomaly"}, stat="Rules and statistics; a person reviews every finding", api=["/api/m/anomaly"]),
    M("recommend", "Suggestions & recommendations", "What to do next, with reasons", "Business suggestions from your numbers - each with evidence, expected impact and who should act.", "ai", "target", ["Ask Relay", "Teams", "Jira / Freshservice", "Email"], ["develop", "change", "run"], short="Recommendations", status="available", route="#/m/recommend", roles=["admin", "dev", "viewer"], links={"develop": "recommend", "change": "recommend", "run": "recommend"}, stat="Next-best actions with their evidence, tracked; Ask Relay's suggestions included", api=["/api/m/recommend"]),
    M("assist", "Document & knowledge assistants", "Answers from your documents", "Assistants over SharePoint, Confluence and policies - answers cite the page they came from, access respected.", "ai", "book", ["Azure OpenAI", "Claude", "Copilot Studio", "Ollama", "Hugging Face", "SharePoint", "Confluence"], ALLW, short="Knowledge assistants", status="available", route="#/m/assist", links={"assess": "assist", "develop": "assist", "change": "assist", "migrate": "assist", "run": "assist"}, stat="Cited answers from your documents; golden questions scored", api=["/api/m/assist"]),
    M("agents", "AI agents & copilots", "Your own agents, governed", "Agents for your processes - tools, approvals and audit built in, running on the model you choose.", "ai", "cpu", ["Claude", "Azure OpenAI", "Copilot Studio", "n8n AI", "Ollama", "Hugging Face"], ALLW, short="AI agents", status="available", route="#/m/agents", links={"assess": "agents", "develop": "agents", "change": "agents", "migrate": "agents", "run": "agents"}, stat="Defined by a person, tested before it is on; every write approved", api=["/api/m/agents"]),
    M("aigov", "AI governance & evaluation", "Safe, measured, explainable", "Model and prompt evaluations, usage policies, cost and risk registers - for every agent in Relay and your own.", "ai", "shield", ["Relay runners & audit", "Azure AI Content Safety", "Evaluation sets", "EU AI Act / DPDP checklists"], ["assess", "develop", "run"], short="AI governance", status="available", route="#/m/aigov", links={"assess": "aigov", "develop": "aigov", "run": "aigov"}, stat="Inventory and policy checks, evaluation suites scored over time, a risk register", api=["/api/m/aigov"]),
    M("knowledge", "Knowledge map", "Lineage, rules & learning", "Reports, pipelines, bots, flows and APIs on one map - and the rules learned on the way.", "ai", "graph", ["Relay graph", "Purview / Collibra lineage", "OpenLineage"], ["assess", "run"], status="available", route="#/graph", links={"assess": "knowledge", "run": "knowledge"}, stat="Lineage and knowledge map live", api=["/api/lineage"]),
    # ---- Consulting services (engagements)
    M("strategy", "Strategy & roadmap", "Data, automation and AI strategy", "Maturity, target state, business case and a roadmap in waves - built from what the platform finds, presented as a deck.", "consulting", "target", ["Maturity models", "Business case", "Roadmap", "Strategy deck"], [], status="available", route="#/m/strategy", stat="Maturity, business case maths and roadmap live", links={"engage": "strategy"}, api=["/api/m/strategy", "/api/studio"]),
    M("architecture", "Architecture & technical design", "Target architecture, chosen with reasons", "Options compared on cost, security and fit; target, integration and security design; decision records - presented as an architecture deck and design pack.", "consulting", "layers", ["Reference architectures", "ADRs", "Security design", "Architecture deck", "HLD / LLD", "C4 / ArchiMate diagrams", "draw.io / Visio"], [], short="Architecture & design", status="available", route="#/m/architecture", stat="Options compared, design, ADRs and the Present step live", links={"engage": "architecture"}, api=["/api/m/architecture", "/api/studio"]),
    M("selection", "Tool & vendor selection", "The right platform, for the right reasons", "Requirements, shortlists, proofs of concept and licence costs compared - decision written down. (Issuing an RFP to vendors; answering one is RFP & bid response.)", "consulting", "scale", ["RFP / RFI", "Proof of concept", "Licence comparison"], [], status="available", route="#/m/selection", stat="Requirements, RFPs issued, weighted scores and proofs of concept live", links={"engage": "selection"}, api=["/api/m/selection"]),
    M("rfp", "RFP & bid response", "From RFP to a submitted response", "An RFP, RFI or tender read in full; go / no-go with reasons; a compliance matrix; answers drafted from your past responses and Relay's own module facts; priced from Assess & estimate; reviewed and submitted as a pack.", "consulting", "send", ["RFP / RFI / tender packs (PDF, Word, Excel)", "SAP Ariba", "Coupa", "Jaggaer", "GeM (India)", "Buyer portals & e-mail", "Loopio", "Responsive", "SharePoint"], [], status="available", route="#/rfp", links={"engage": "rfp"}, api=["/api/rfp"]),
    M("proposals", "Proposals, decks & documents", "Every consulting deliverable, in your house style", "Proposal and submission decks, architecture decks, business cases, SoWs, steering and hand-over packs - drafted from Relay's facts in your house template (white-labelled for partners), checked, reviewed and versioned.", "consulting", "file", ["PowerPoint", "Word", "PDF", "Google Slides / Docs", "Excel (pricing)", "SharePoint / OneDrive / Drive", "Mermaid / draw.io diagrams"], [], short="Proposals & decks", status="available", route="#/studio", links={"engage": "studio"}, api=["/api/studio"]),
    M("assess", "Assess & estimate", "Size it and price it", "Read the estate, size it, estimate effort and cost per wave - export the proposal pack and deck.", "consulting", "search", ["Estimates", "Proposal pack"], [], ed="partner", status="available", route="#/m/assess", stat="Estate readers, estimation model and rate cards live", links={"engage": "assess"}, api=["/api/m/assess", "/api/studio"]),
    M("delivery", "Programme & delivery", "Every client, wave and proof", "Process, automation, systems, data and AI work in one plan, with proof and hours saved.", "consulting", "grid", ["Waves", "Steering packs", "Hand-over packs"], [], short="Programme view", ed="partner", designed=True, status="available", route="#/m/delivery", links={"engage": "delivery"}, stat="Programmes, RAID and weekly status reports live", api=["/api/m/delivery"]),
    M("managed", "Managed services & support", "Run it for you, with SLAs", "L1-L3 support across the modules you use - agents first, people for decisions, monthly service reviews.", "consulting", "heart", ["SLAs", "ITSM", "Service reviews"], [], short="Managed services", status="available", route="#/m/managed", stat="Service catalogue, SLAs and monthly service reports live", links={"engage": "managed"}, api=["/api/m/managed"]),
    M("finops", "Cost & licence optimisation", "Pay for what you use", "Cloud, warehouse and BI licence spend analysed; unused reports, capacity and seats found and cut.", "consulting", "gauge", ["Power BI capacity", "Snowflake credits", "Azure / AWS / GCP", "RPA licences"], [], short="Cost & licences", status="available", route="#/m/finops", stat="Licence and cloud-cost exports, findings and approved savings plans live", links={"engage": "finops"}, api=["/api/m/finops"]),
    M("enable", "Adoption & enablement", "People ready for the new way", "Learning paths, playbooks and adoption tracking so validating agent work becomes the team's habit.", "consulting", "users", ["Learning paths", "Playbooks", "Adoption tracking"], [], status="available", route="#/m/enable", stat="Learning paths, guides, playbook and adoption scorecard live", links={"engage": "enable"}, api=["/api/m/enable"]),
    # ---- screens reached through links and the Platform group (not shown as cards)
    M("d2d", "D2D", "Data to Decision", "Describe the dashboard you need - D2D plans it with you, builds a prototype, proves every number and hands you a Power BI file (.pbix).", "hidden", "chart", [], [], status="available", route="#/d2d", roles=["admin", "dev"], ed="ent"),
    M("migbi", "BI migration", "Reports to Power BI, proven", "Discover -> Decide -> Convert -> Prove -> Hand over -> Run for a whole BI estate.", "hidden", "swap", [], [], status="available", route="#/migrate-bi", roles=["admin", "dev"], ed="partner", api=["/api/migrate-bi"]),
    M("gates", "Proof & gates", "Nothing ships unproven", "Twelve review gates and Power BI's own engine check every version before it is approved or published.", "hidden", "shield", [], [], status="available", route="#/d2d", roles=["admin", "dev"]),
    M("publish", "Pages & publishing", "Pages, exports & GitHub", "Insight pages, reviews, GitHub push, Slack / Teams, PDF and PNG exports.", "hidden", "send", [], [], status="available", route="#/pages", roles=["admin", "dev", "viewer"], ed="ent", api=["/api/pages", "/api/reviews"]),
    M("runners", "Runners", "AI providers & agents", "Claude, LiteLLM (Bedrock, Azure, Vertex), Codex, Gemini, Antigravity, backup provider.", "platform", "cpu", [], [], status="available", route="#/admin/ai", roles=["admin"]),
    M("ops", "Ops", "Monitoring & cost", "Health, metrics, watchdog, cost report, quotas, backups.", "platform", "pulse", [], [], status="available", route="#/admin/monitoring", roles=["admin"]),
    M("govern", "Govern", "Identity, tenants & audit", "SSO, roles, teams, shares, audit log.", "platform", "lock", [], [], status="available", route="#/admin/people", roles=["admin"]),
]
for _m in MODULES:
    _m.setdefault("ed", "shared")
    _m.setdefault("status", "planned")
    _m.setdefault("route", "#/m/" + _m["id"])
    _m.setdefault("roles", ["admin", "dev"])
    _m.setdefault("links", {})
    _m.setdefault("designed", False)
BY_ID = {m["id"]: m for m in MODULES}
LOCKED = {"enterprise": ["delivery", "assess", "migbi"], "partner": ["askd", "schedule"], "both": []}

# Each module's own journey (Develop, or the engagement for consulting modules) with an optional Migrate variant;
# otherwise the standard way Relay does that kind of work (GENERIC).
PLAN = {
    "brd": {"journey": ["Gather", "Draft", "Review", "Approve", "Backlog", "Trace"], "steps": ["Upload workshop notes, call recordings, emails or whiteboard photos; or invite the agent to the meeting", "The agent drafts the BRD in your template: scope, stakeholders, current vs future process, requirements, rules, data, risks", "Business owners comment in place; open questions are listed, not guessed", "Approval with names and dates; every version kept", "User stories and acceptance criteria pushed to Jira or Azure Boards", "Each requirement traced to the build, the tests and the sign-off"], "builds": ["Process documents", "AI SDLC", "ITSM"],
            "migrate": {"journey": ["Collect", "Read", "Standardise", "Gaps", "Approve", "Backlog"], "steps": ["Bring old specs in Word, PDF, Confluence or SharePoint", "The agent reads them and maps every requirement to your BRD template", "Duplicates and contradictions listed with where they came from", "Gaps against how the system really behaves (from the knowledge map) flagged", "Owners approve the standard version"]}},
    "processdocs": {"journey": ["Capture", "Map", "Correct", "Publish", "Automate", "Keep current"], "steps": ["Interviews, a screen recording of someone doing the task, or system logs", "BPMN map and step-by-step SOP: screens, fields, decisions, rules, hand-offs", "The process owner corrects it; changes are tracked", "Published to SharePoint or Confluence in your house style", "One click to Workflows, RPA or AI SDLC for the steps worth automating", "When the system or bot changes, the document is flagged for review"], "builds": ["RPA", "Workflows", "RACI"],
                    "migrate": {"journey": ["Collect", "Convert", "Check", "Publish"], "steps": ["Bring Visio, Word or slide-based process documents", "Converted to BPMN and the standard SOP template", "Checked against how the work is really done (recordings, logs)", "Published and linked to the systems and people involved"]}},
    "raci": {"journey": ["Processes", "Roles", "Draft", "Agree", "Publish", "Use"], "steps": ["Start from the process documents or a list of activities", "Roles from your org chart and Entra ID groups - agents included as roles", "The agent drafts Responsible, Accountable, Consulted, Informed per step", "Owners agree; conflicts (two Accountables, no one Responsible) flagged", "Published with the operating model", "Approvals in Relay (validation queue, releases) follow the RACI automatically"], "builds": ["Process documents", "Govern", "Validation queue"]},
    "dwh": {"journey": ["Sources", "Model", "Build", "Prove", "Ship", "Run"], "steps": ["Connect sources: ERP, finance, CRM, files, APIs", "Design the model (star schemas, data vault or lakehouse layers) with the ontology", "Pipelines in dbt, ADF, Fabric or Databricks - rules first, AI where none fits", "Row counts, checksums and business totals proven", "Deployed through Cloud & CI/CD", "Monitored; Self-healing proposes fixes"], "builds": ["Connections", "Ontology", "Cloud & CI/CD"],
            "migrate": {"journey": ["Discover", "Decide", "Convert", "Prove", "Hand over", "Run"], "steps": ["Read the source warehouse - Oracle DW or Exadata (schemas, PL/SQL packages, materialised views, partitions), Teradata (BTEQ, macros), Netezza, Db2 or SQL Server - and the ETL feeding it (Informatica, ODI, SSIS, DataStage)", "Decide what to keep, merge or retire, using query history, lineage and usage", "Convert schemas, PL/SQL and BTEQ to Snowflake, BigQuery, Databricks, Fabric or Redshift SQL and dbt - rules first, AI where none fits; data moved in waves with change capture", "Prove it: row counts, checksums, business totals and the same queries run on both sides, then performance and cost compared", "Cut over report by report with owner sign-off; old warehouse kept read-only until retired"]}},
    "governance": {"journey": ["Catalogue", "Own", "Lineage", "Quality", "Policy", "Prove"], "live": "Lineage, metric certification and the proof gates work today; the catalogue, ownership and quality rules are planned.", "steps": ["Catalogue every table, report, metric, bot and flow - with business descriptions", "Owners and stewards per domain (from the RACI)", "Lineage from source to report across all modules (live today)", "Quality rules with thresholds; breaks raised in ITSM", "Policies: access, retention, personal-data tags; sync with Collibra or Purview", "Nothing ships without passing the gates (live today)"], "builds": ["Knowledge map", "Proof & gates", "RACI"]},
    "predict": {"journey": ["Question", "Data", "Model", "Prove", "Share", "Watch"], "steps": ["Start from a business question: demand next quarter, cash in 13 weeks, churn, late deliveries", "The agent picks the data with the ontology and shows what it will use", "Models trained and compared; the simplest one that is accurate enough wins", "Back-tested accuracy shown in plain words before anyone relies on it", "Forecasts into Power BI, Ask Relay and scheduled reports", "Accuracy watched; retrained when it drifts"], "builds": ["Data warehouse", "Conversational analytics", "Reports & alerts"]},
    "recommend": {"journey": ["Signals", "Explain", "Suggest", "Assign", "Track"], "live": "Ask Relay already suggests next questions and actions with each answer; dedicated recommendation feeds are planned.", "steps": ["Signals from metrics, forecasts and anomalies", "Why it matters: the numbers behind it, in plain words", "A suggestion with expected impact and who should act (from the RACI)", "Sent to the owner, or raised in Jira / Freshservice", "Outcome tracked so the next suggestion is better"], "builds": ["Predictive analytics", "Formulas & metrics", "ITSM"]},
    "strategy": {"journey": ["Listen", "Assess", "Target", "Case", "Roadmap", "Deck"], "steps": ["Stakeholder interviews and the platform's own discovery of systems, data and reports", "Maturity across process, automation, systems, data and AI", "Target state and the capabilities to get there", "Business case: hours saved, accuracy, risk, cost - from real numbers, not guesses", "Roadmap in waves that Relay can then run", "Strategy and business-case deck for the steering committee, produced through Proposals & decks"], "builds": ["Assess & estimate", "Programme view", "Architecture"]},
    "architecture": {"journey": ["Needs", "Options", "Compare", "Design", "Approve", "Present"], "steps": ["Requirements and constraints from the BRD and strategy", "Technology options for warehouse, BI, integration, automation and AI", "Compared on cost, security, skills and fit - with the reasons written down", "Target architecture, integration and security design, diagrams kept current from the knowledge map", "Architecture decision records approved by named owners", "Architecture deck and design pack (HLD / LLD, C4 or ArchiMate diagrams kept current from the knowledge map, ADRs) produced through Proposals & decks and filed as approved versions"], "builds": ["Strategy", "Cloud & CI/CD", "Proposals & decks"]},
    "rfp": {"journey": ["Qualify", "Understand", "Answer", "Price", "Review", "Submit", "Learn"], "steps": ["Drop in the RFP pack - PDF, Word, Excel or a portal export; the agent lists every requirement, deadline, format rule and evaluation criterion, and you confirm the list", "Go / no-go: fit against your modules and past wins, risks, effort and the deadline - recommended with reasons; a named person decides", "Compliance matrix: each requirement marked Comply, Partial, Not or Alternative with its evidence (module, case study, reference); answers drafted from your past-responses library and Relay's module facts - never an invented reference", "Price from Assess & estimate - effort per wave, licences, run & support - in the buyer's currency; commercial terms from your templates", "Technical, commercial and legal reviews plus an agent red-team read; comments resolved in place; every version kept", "Submission pack in the buyer's required format (Word, PDF, Excel or portal fields) and the proposal deck from Proposals & decks; a named person submits", "Win / loss and buyer feedback recorded; answers that won become reusable, so the next response starts further ahead"], "builds": ["Proposals & decks", "Assess & estimate", "Architecture"]},
    "proposals": {"journey": ["Brief", "Outline", "Draft", "Check", "Review", "Final"], "steps": ["Brief: what, for whom, by when; the template (yours, or your partner's white-label) and the sources - an Assess run, an architecture, a programme, an RFP", "An outline, section by section, with the story line - you reorder, cut and add before a word is written", "Deck or document drafted with charts, tables and diagrams generated from the platform's own numbers; every figure links back to its evidence", "Checks: numbers against their source, references real, nothing crosses tenants, contrast and alt text in the deck, house-style rules", "Review in place: comments, tracked versions, approval by a named owner", "Final as PowerPoint, Word or PDF (and Google formats), filed to SharePoint or Drive with a one-page summary; later edits re-run the checks"], "builds": ["RFP & bid response", "Architecture", "Programme view"]},
    "enable": {"journey": ["Roles", "Learn", "Practise", "Adopt", "Measure"], "steps": ["Who needs what: builders, validators, business users, leads", "Short learning paths in the platform itself", "Practise on sample data, not production", "Playbooks for validating agent work", "Adoption and time-to-validate tracked in Team & agents"], "builds": ["Sample data", "Team & agents", "Validation queue"]},
    "n8n": {"journey": ["Describe", "Design", "Build", "Prove", "Deploy", "Run"], "steps": ["Describe the flow in plain words, or start from a process map or video", "The agent proposes nodes, triggers and credentials (by name only) - you agree the design", "Workflow JSON is written and deployed to your own n8n (self-hosted or cloud) through its API", "Test executions with sample payloads; failures go to Heal"], "builds": ["Integrate", "Heal", "Ship"]},
    "rpa": {"journey": ["Find", "Design", "Build", "Prove", "Ship", "Run"], "steps": ["Find the tasks worth a bot: from process documents, recordings or the validation queue", "Design the bot with APIs first, screen steps only where no API exists", "Built in Power Automate, n8n, Python or UiPath - your choice, with test cases", "Tests on sample data; a person approves before it runs live", "Deployed with credentials by name from the secrets store", "Watched by Self-healing"], "builds": ["Workflows", "Integrate", "Proof & gates"],
            "migrate": {"journey": ["Discover", "Decide", "Convert", "Prove", "Hand over", "Run"], "steps": ["Read packages, releases, queues, run history and exceptions (credentials by name only)", "Decide which bots to retire, merge or move - with usage and failure rates", "Each bot becomes a neutral process model, then Power Automate, n8n or Python; screen steps become API calls where an API exists", "The same test cases run on old and new; outputs and exception paths compared"]}},
    "integrate": {"journey": ["Discover", "Map", "Build", "Prove", "Ship", "Run"], "steps": ["Read API specs, sample payloads and field lists - Tally, Zoho Books, SAP, Dynamics 365, NetSuite, portals and more", "Agree the field mapping and rules with the agent, side by side", "Built as n8n, Power Automate or code, with retries, logging and alerts", "Contract tests and record-by-record reconciliation of what moved"], "builds": ["Workflows", "Ship", "Knowledge map"]},
    "apps": {"journey": ["Idea", "Shape", "Build", "Prove", "Ship", "Run"], "steps": ["Describe the idea; the agent asks what matters and drafts the spec, screens and data model", "Pick the platform: web, Android, Power Apps, or a Python / Java / Node service - or let the agent recommend one with reasons", "The agent builds in a repository you own, in small reviewed steps, with tests from the start", "Automated tests, accessibility and security checks; a person approves each release", "Ship deploys it; Ops and Heal watch it in production"], "builds": ["Ship", "Integrate", "Proof & gates"]},
    "sdlc": {"journey": ["Request", "Plan", "Develop", "QA", "UAT", "Release", "Run"], "steps": ["Connect your Git repository (GitHub, Azure DevOps, GitLab) and tracker (Jira, Azure Boards); the agent indexes the code, tests and conventions - code stays in your tenant", "A change request comes in from the tracker or in plain words; the agent writes the plan: files touched, risks, tests to add - a tech lead approves it", "Agents develop on a branch in small commits, following your coding standards; every AI call and file change is logged against the request", "QA: unit, integration and regression tests generated and run; security and dependency scans; a reviewer agent and a named human review the pull request", "UAT on synthetic data that mirrors production shape (no real personal data) in an isolated environment; business users sign off in the app", "Release through Ship: pipeline, approvals, change record, one-click roll back", "Enterprise controls: one governed AI setup for the whole team instead of each developer's own tools - policies, budgets, model choice, audit trail per request"], "builds": ["Ship", "Sample data", "Proof & gates", "Govern"]},
    "ship": {"journey": ["Connect", "Plan", "Pipeline", "Prove", "Release", "Run"], "steps": ["Connect your cloud - Azure, AWS or Google Cloud - with your own identity (Entra ID, IAM, Workspace); secrets stay in the secrets store", "Plan environments (dev, test, production) and the services each app or workflow needs", "Pipelines written for GitHub Actions or Azure DevOps, with infrastructure as code", "Every release passes the gates; production needs a named approver; one-click roll back", "Costs and health per environment in Ops"], "builds": ["Build - Apps", "Workflows", "Ops"]},
    "heal": {"journey": ["Watch", "Diagnose", "Fix", "Prove", "Approve", "Learn"], "steps": ["Watch refreshes, pipelines, workflows and deployments", "Diagnose with the logs and the knowledge map", "Propose a fix and test it in a copy", "Apply when a person approves; keep the rule for next time"], "builds": ["Ops", "Knowledge map", "Workflows"]},
    "assess": {"journey": ["Discover", "Size", "Estimate", "Propose"], "steps": ["Read the estate - BI, ETL, RPA, databases - or upload exports", "Size it in each tool's own terms, with usage and complexity", "Estimate effort, duration and cost per wave, with what converts automatically and why", "Proposal pack and deck produced through Proposals & decks in your house style - or fed into an RFP & bid response"], "builds": ["Migrate - BI", "Migrate - RPA", "Programme view"]},
}
GENERIC = {
    "assess": {"journey": ["Connect", "Inventory", "Health", "Findings", "Estimate"], "steps": ["Connect to, or upload exports from, {pf} - read-only", "Inventory everything in the tool's own terms, with usage and owners", "Health check: failures, risks, duplicates, unused items, cost", "Findings and quick wins shown in the right view - you confirm them", "Effort and cost per wave for what you want to do next"]},
    "develop": {"journey": ["Describe", "Shape", "Build", "Prove", "Ship", "Run"], "steps": ["Describe what you need and attach anything - recordings, screenshots, documents", "The agent shapes it on {pf} - you confirm the design in the view that fits", "Built in small, reviewed steps; every step logged", "Proven with tests and, for numbers, against the source", "Shipped with a named approver; roll back ready"]},
    "change": {"journey": ["Request", "Diagnose", "Fix", "Prove", "Approve", "Learn"], "steps": ["A ticket from Jira or Freshservice, or a request in plain words", "The agent reproduces the problem and finds the cause - you confirm the diagnosis", "The fix or change is made on a copy or branch, with tests", "Proven against the expected result", "You approve; it is released and the ticket updated", "The fix becomes a rule, so the next one is faster"]},
    "migrate": {"journey": ["Discover", "Decide", "Convert", "Prove", "Hand over", "Run"], "steps": ["Discover what runs today on {pf} - read-only", "Decide what to keep, merge or retire, with usage and reasons", "Convert to the target platform - rules first, AI where none fits", "Prove old and new side by side", "Hand over with the evidence pack and owner sign-off", "Run and watch after go-live"]},
    "run": {"journey": ["Watch", "Alert", "Fix", "Approve", "Report"], "steps": ["Runs, failures, SLAs and cost watched on {pf}", "Alerts with the likely cause, grouped - not one per failure", "Self-healing proposes a fix and tests it in a copy", "A person approves before it is applied", "Monthly service report: health, changes, hours saved"]},
    "engage": {"journey": ["Listen", "Analyse", "Recommend", "Agree", "Deliver"], "steps": ["Workshops and interviews with your leads", "Analysis from what Relay discovers in your systems, data and processes - facts, not guesses", "Options with costs, risks and reasons", "You agree the direction; decisions recorded", "Delivered as waves that run on Relay, with progress in Programme view"]},
}
CONFIRM = {
    "rfp": [["Requirements", "the list the agent read from the RFP pack"], ["Go / no-go", "the decision, with reasons, by a named person"], ["Matrix", "the compliance matrix and every drafted answer"], ["Price", "effort, licences and terms before they go in"], ["Submit", "the final pack - a person submits it"]],
    "proposals": [["Outline", "the story line before drafting"], ["Draft", "every figure with its evidence"], ["Final", "approval by a named owner before it is filed or sent"]],
    "architecture": [["Options", "the shortlist and how it was compared"], ["Design", "target, integration and security design"], ["Present", "the deck and design pack before they go out"]],
    "brd": [["Draft", "the BRD in your template, comments in place"], ["Approve", "sign-off by each business owner"], ["Backlog", "user stories before they go to Jira"]],
    "processdocs": [["Map", "the BPMN process map, step by step"], ["Correct", "the SOP next to the recording it came from"], ["Publish", "final version before SharePoint / Confluence"]],
    "raci": [["Draft", "the RACI matrix, conflicts highlighted"], ["Agree", "each owner confirms their row"]],
    "rpa": [["Design", "the bot flow: API steps vs screen steps"], ["Prove", "test runs side by side with the recording"], ["Ship", "go-live approval by the process owner"]],
    "n8n": [["Design", "the workflow diagram and credentials by name"], ["Prove", "test executions with sample payloads"], ["Deploy", "approval before it touches a live system"]],
    "observe": [["Checks", "which assets are watched and the thresholds"], ["Warn", "the banner and message to report users"], ["Fix", "the fix plan from Self-healing or AI SDLC"]],
    "intan": [["Map", "the discovered integration map - what talks to what"], ["Ticket", "each proposed ticket and its priority before it is raised"], ["Fix", "the fix plan from Self-healing or AI SDLC before anything changes"]],
    "integrate": [["Map", "field mapping side by side, with sample records"], ["Prove", "record-by-record reconciliation"], ["Ship", "cut-over approval"]],
    "servicedesk": [["Groups", "each ticket group and its summary"], ["Priority", "priority with the reason"], ["Write back", "approval before anything is written to Jira or Freshservice"]],
    "apps": [["Shape", "wireframes, spec and data model"], ["Build", "each pull request"], ["Ship", "release approval"]],
    "sdlc": [["Plan", "the change plan: files, risks, tests"], ["QA", "the pull request with test results"], ["UAT", "business sign-off on synthetic data"], ["Release", "named approver"]],
    "ship": [["Plan", "environments and services diagram"], ["Release", "production approval and roll-back plan"]],
    "dwh": [["Model", "the data model (entities and keys)"], ["Prove", "row counts and business totals"], ["Ship", "go-live approval"]],
    "governance": [["Own", "owners per domain"], ["Policy", "access and retention rules"]],
    "predict": [["Data", "the data the model will use"], ["Prove", "back-test chart in plain words"], ["Share", "before forecasts reach reports"]],
    "recommend": [["Suggest", "each suggestion with its evidence"], ["Assign", "before it is sent to an owner"]],
    "strategy": [["Assess", "maturity scores with the evidence"], ["Roadmap", "waves and business case"], ["Deck", "the steering-committee deck before it goes out"]],
    "assess": [["Size", "the inventory in the tool's own terms"], ["Estimate", "effort and cost per wave"]],
    "enable": [["Learn", "learning paths per role"]],
    "bi": [["Plan", "the data model, KPIs with their formulas and the pages"], ["Review", "the clickable prototype, version by version"], ["Approve", "the review gates, then the Power BI file (.pbix)"]],
}
CONFIRM_BY_WORK = {
    "assess": [["Inventory", "what was found, in the tool's own terms"], ["Findings", "health, risks and quick wins"], ["Estimate", "effort and cost per wave"]],
    "develop": [["Design", "the design in the view that fits"], ["Prove", "test results and, for numbers, the comparison with the source"], ["Ship", "named approval before go-live"]],
    "change": [["Diagnosis", "the cause, before anything changes"], ["Fix", "the change with its tests"], ["Release", "approval; the ticket is updated"]],
    "migrate": [["Decide", "keep, merge or retire - with reasons"], ["Prove", "old and new side by side"], ["Hand over", "owner sign-off on the evidence pack"]],
    "run": [["Fix", "each proposed fix before it is applied"], ["Report", "the monthly service report"]],
    "engage": [["Findings", "facts from your systems, before recommendations"], ["Direction", "the option you choose, recorded"], ["Plan", "the waves and who owns them"]],
}


def plan_for(m: dict, work: str) -> dict:
    """The journey and steps a module page shows for a work type (or the engagement for consulting modules)."""
    base = PLAN.get(m["id"])
    if work in ("develop", "engage") and base:
        return {k: v for k, v in base.items() if k != "migrate"}
    if work == "migrate" and base and base.get("migrate"):
        return {**{k: v for k, v in base.items() if k != "migrate"}, **base["migrate"]}
    g = GENERIC.get(work) or GENERIC["engage"]
    pf = ", ".join((m.get("platforms") or [])[:3]) or "your platforms"
    return {"journey": g["journey"], "steps": [s.replace("{pf}", pf) for s in g["steps"]]}


def confirm_for(m: dict, work: str) -> list:
    if m["id"] in CONFIRM and work in ("develop", "engage"):
        return CONFIRM[m["id"]]
    return CONFIRM_BY_WORK.get(work) or CONFIRM_BY_WORK["engage"]


# ------------------------------------------------------------------ brand settings (Admin > Branding)

DEFAULT_BRAND = {"name": "D2D Relay", "full": "D2D Relay", "tagline": "Data to Decision", "partner": False, "mark": "R",
                 "color": "#111111", "accent": "signal", "logo_light": "", "logo_dark": "", "sender": "Relay", "contact": "info@pasdacs.com",
                 "edition": "both", "hourly_rate": 0, "currency": "₹", "usd_rate": 1.0, "powered": "Powered by PASDACS Relay"}
ACCENTS = ("signal", "gold", "teal", "ink")
# P11: the tenant's document templates and house style (Admin > Branding -> the studio); kept in the same secrets-free
# `branding` meta but never returned with the brand itself (a data URL of up to 2 MB each).
TEMPLATE_KEYS = {"template_pptx": "The PowerPoint template", "template_docx": "The Word template"}
TEMPLATE_MAX = 2 * 1024 * 1024


def templates() -> dict:
    """{"pptx": bytes | None, "docx": bytes | None, "house_style": str, "names": {...}} - decoded from the saved data URLs."""
    import base64
    try:
        saved = json.loads(db.meta("branding") or "{}")
    except ValueError:
        saved = {}
    out = {"pptx": None, "docx": None, "house_style": (saved.get("house_style") or "").strip(), "names": {}}
    for key, slot in (("template_pptx", "pptx"), ("template_docx", "docx")):
        v = saved.get(key) or ""
        if v.startswith("data:") and ";base64," in v:
            try:
                out[slot] = base64.b64decode(v.split(";base64,", 1)[1])
                out["names"][slot] = saved.get(key + "_name") or f"template.{slot}"
            except ValueError:
                pass
    return out


def _saved_brand(tid: str | None = None) -> dict:
    """What Admin > Branding saved in a tenant (the current one by default)."""
    try:
        if tid and tid != db.tenant():
            with db.use(tid):
                raw = db.meta("branding")
        else:
            raw = db.meta("branding")
        return json.loads(raw or "{}")
    except (ValueError, LookupError):
        return {}


def _tenant() -> dict | None:
    try:
        return db.one("SELECT * FROM relay.tn_tenants WHERE id = ?", (db.tenant(),))
    except Exception:  # noqa: BLE001 - before the control plane exists (old tests): the platform as it was
        return None


BRAND_LOOK = ("name", "full", "mark", "color", "logo_light", "logo_dark", "tagline", "accent", "partner")


def brand() -> dict:
    """The effective brand of the current tenant: the defaults with whatever Admin > Branding saved - a partner's
    client wears its partner's white label unless it saved its own. The powered-by line never changes."""
    t = _tenant()
    saved = _saved_brand()
    look = saved
    parent = None
    if t and t["kind"] == "client" and t["parent_id"] and t["parent_id"] != db.PLATFORM:
        parent = db.one("SELECT * FROM relay.tn_tenants WHERE id = ?", (t["parent_id"],))
        if parent and parent["kind"] == "partner" and not saved.get("partner"):
            inherited = _saved_brand(parent["id"])
            look = {**saved, **{k: v for k, v in inherited.items() if k in BRAND_LOOK}}
    b = {**DEFAULT_BRAND, **{k: v for k, v in look.items() if k in DEFAULT_BRAND}}
    b["powered"] = DEFAULT_BRAND["powered"]
    if t and t["kind"] == "client" and not (parent and parent["kind"] == "partner"):
        b["partner"] = False                                   # direct clients show RELAY by PASDACS
    if not b["partner"]:                                       # the platform's own look cannot be renamed
        b.update({k: DEFAULT_BRAND[k] for k in ("name", "full", "mark", "color", "logo_light", "logo_dark")})
    if t and t["kind"] != "platform":
        b["edition"] = t["edition"]
    b["tenant"] = {"id": t["id"], "name": t["name"], "kind": t["kind"]} if t else {"id": db.tenant(), "name": None, "kind": "platform"}
    b["inherited"] = bool(parent and parent["kind"] == "partner" and not saved.get("partner"))
    return b


class BrandIn(BaseModel):
    name: str | None = None
    full: str | None = None
    tagline: str | None = None
    partner: bool | None = None
    mark: str | None = None
    color: str | None = None
    accent: str | None = None
    logo_light: str | None = None
    logo_dark: str | None = None
    sender: str | None = None
    contact: str | None = None                # the address people write to (sign-in page); PASDACS: info@pasdacs.com
    edition: str | None = None
    hourly_rate: float | None = None
    currency: str | None = None
    usd_rate: float | None = None
    template_pptx: str | None = None          # P11: data URL of the tenant's .pptx / .potx ("" removes it)
    template_pptx_name: str | None = None
    template_docx: str | None = None          # P11: data URL of the tenant's .docx / .dotx
    template_docx_name: str | None = None
    house_style: str | None = None            # P11: free-text house-style notes the studio's checks show


def _check_logo(v: str | None, what: str) -> None:
    if v and not (v.startswith("data:image/svg+xml") or v.startswith("data:image/png")):
        raise HTTPException(400, f"{what} must be an SVG or PNG data URL.")
    if v and len(v) > 200_000:
        raise HTTPException(400, f"{what} is too big (keep it under 200 KB).")


def _check_template(v: str | None, what: str) -> None:
    if not v:
        return
    if not (v.startswith("data:application/") and ";base64," in v):
        raise HTTPException(400, f"{what} must be a PowerPoint (.pptx / .potx) or Word (.docx / .dotx) file.")
    if len(v) > TEMPLATE_MAX * 4 // 3 + 1024:
        raise HTTPException(400, f"{what} is too big (keep it under 2 MB).")


@router.get("/api/brand")
def get_brand():
    return brand()


@router.get("/auth/brand")
def get_brand_open():
    """For the sign-in page (no session yet): name, logos and colours only - of the tenant the page is for (?t= or
    its host name, set by auth.middleware)."""
    b = brand()
    out = {k: b[k] for k in ("name", "full", "tagline", "partner", "mark", "color", "accent", "logo_light", "logo_dark", "powered")}
    out["contact"] = b.get("contact") or ""
    out["workspace"] = (b.get("tenant") or {}).get("name") if (b.get("tenant") or {}).get("kind") != "platform" else None
    return out


@router.get("/api/admin/branding")
def admin_branding():
    try:
        saved = json.loads(db.meta("branding") or "{}")
    except ValueError:
        saved = {}
    tpl = {k: {"set": bool(saved.get(k)), "name": saved.get(k + "_name") or "", "chars": len(saved.get(k) or "")} for k in TEMPLATE_KEYS}
    tpl["house_style"] = saved.get("house_style") or ""
    return {"brand": brand(), "saved": {k: v for k, v in saved.items() if k not in TEMPLATE_KEYS}, "defaults": DEFAULT_BRAND, "accents": list(ACCENTS), "templates": tpl}


@router.put("/api/admin/branding")
def admin_set_branding(body: BrandIn):
    new = {k: v for k, v in body.model_dump().items() if v is not None}
    if "accent" in new and new["accent"] not in ACCENTS:
        raise HTTPException(400, f"Accent must be one of {', '.join(ACCENTS)}.")
    if "edition" in new and new["edition"] not in LOCKED:
        raise HTTPException(400, "Edition must be enterprise, partner or both.")
    if "edition" in new and db.tenant() != db.PLATFORM:
        raise HTTPException(400, "A workspace's edition is set by the platform (Platform > Tenants).")
    t = _tenant()
    if new.get("partner") and t and t["kind"] == "client" and not (t["parent_id"] and t["parent_id"] != db.PLATFORM):
        raise HTTPException(400, "A direct client shows RELAY by PASDACS; white-labelling is for service partners and their clients.")
    if "color" in new and not re.fullmatch(r"#[0-9A-Fa-f]{6}", new["color"]):
        raise HTTPException(400, "Colour must be a hex value like #111111.")
    if "contact" in new:
        new["contact"] = new["contact"].strip()[:120]
        if new["contact"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", new["contact"]):
            raise HTTPException(400, "The contact address must be an e-mail address like info@pasdacs.com.")
    if "hourly_rate" in new and new["hourly_rate"] < 0:
        raise HTTPException(400, "The hourly rate cannot be negative.")
    if "usd_rate" in new and new["usd_rate"] <= 0:
        raise HTTPException(400, "The exchange rate must be above zero.")
    for k in ("name", "full", "tagline", "sender", "mark", "currency"):
        if k in new:
            new[k] = new[k].strip()[:80]
    if "mark" in new:
        new["mark"] = new["mark"][:3] or "R"
    _check_logo(new.get("logo_light"), "The light logo")
    _check_logo(new.get("logo_dark"), "The dark logo")
    for k, what in TEMPLATE_KEYS.items():
        _check_template(new.get(k), what)
    if "house_style" in new:
        new["house_style"] = new["house_style"].strip()[:4000]
    for k in ("template_pptx_name", "template_docx_name"):
        if k in new:
            new[k] = re.sub(r"[^\w.\- ]+", "_", new[k])[:80]
    try:
        saved = json.loads(db.meta("branding") or "{}")
    except ValueError:
        saved = {}
    saved.update(new)
    db.set_meta("branding", json.dumps(saved))
    db.audit("branding.set", None, {k: (v if k not in ("logo_light", "logo_dark", *TEMPLATE_KEYS) else f"{len(v)} chars") for k, v in new.items()}, auth.who())
    return admin_branding()


# ------------------------------------------------------------------ the registry API

def role_of(u: dict | None) -> str:
    if not u:
        return "viewer"
    return "admin" if auth.is_admin(u) else "dev" if auth.is_dev(u) else "viewer"


def switched_on() -> set[str] | None:
    """The modules switched on for the current tenant (P17), or None before the control plane exists."""
    try:
        from . import tenancy
        return tenancy.effective(db.tenant())
    except Exception:  # noqa: BLE001
        return None




def module_state(mid: str) -> str | None:
    """A module's state in the current workspace: 'locked' (not in its edition), 'off' (switched off for it, P17),
    else the registry's own (available, partly, preview, planned); None for an unknown id."""
    m = BY_ID.get(mid)
    if not m:
        return None
    try:
        return state_of(m, brand()["edition"], switched_on())
    except Exception:  # noqa: BLE001 - before the control plane exists: the registry's status
        return m.get("status")


def state_of(m: dict, edition: str, on: set[str] | None = None) -> str:
    if m["id"] in LOCKED.get(edition, []):
        return "locked"
    if on is not None and m["id"] not in on:
        return "off"                                           # switched off for this workspace (P17)
    return "preview" if m["status"] == "planned" and m.get("designed") else m["status"]


def public(m: dict, edition: str, on: set[str] | None = None) -> dict:
    out = {k: v for k, v in m.items() if k not in ("designed",)}
    out["state"] = state_of(m, edition, on)
    out["route"] = m["route"]
    # links to live screens by work type (names from the mockup -> routes in this app)
    out["live"] = {w: LIVE.get(target) for w, target in (m.get("links") or {}).items() if LIVE.get(target)}
    return out


def catalogue(u: dict | None) -> dict:
    b = brand()
    edition = b["edition"]
    role = role_of(u)
    on = switched_on()
    mods = [public(m, edition, on) for m in MODULES if role in m["roles"]]
    return {"pillars": [{"id": i, "name": n, "line": l} for i, n, l in PILLARS],
            "work": [{"id": i, "name": n} for i, n in WORK], "modules": mods, "edition": edition, "role": role, "brand": b}


@router.get("/api/registry")
def get_registry():
    return catalogue(auth.current.get())


@router.post("/api/registry/{mid}/interest")
def module_interest(mid: str):
    """"I need this" on a planned module: recorded in the audit log and told to the admins, so demand decides the order."""
    m = BY_ID.get(mid)
    if not m:
        raise HTTPException(404, "No such module.")
    u = auth.current.get()
    db.audit("module.interest", mid, {"name": m["name"], "state": m["status"]}, auth.who())
    try:
        from . import notify
        admins = [r["id"] for r in db.q("SELECT id FROM users WHERE org_role = 'admin' AND active = 1")]
        notify.add_many(admins, "share", f"{(u or {}).get('name') or 'Someone'} needs {m['name']}", m["sub"], "#/m/" + mid, skip=(u or {}).get("id"))
    except Exception:  # noqa: BLE001 - the audit row is the record; a notification is a courtesy
        pass
    return {"ok": True, "module": mid}


@router.get("/api/registry/{mid}")
def get_module(mid: str, work: str | None = None):
    m = BY_ID.get(mid)
    u = auth.current.get()
    if not m or role_of(u) not in m["roles"]:
        raise HTTPException(404, "No such module.")
    edition = brand()["edition"]
    w = work if work in ALLW else ("develop" if "develop" in m["work"] else (m["work"][0] if m["work"] else "engage"))
    return {**public(m, edition, switched_on()), "work_type": w, "plan": plan_for(m, w), "confirm": confirm_for(m, w),
            "rules": ["One AI job at a time, every step logged", "Nothing reaches a live system without a named approval",
                      "Credentials by name only, kept in the secrets store", "Proven before it ships"]}
