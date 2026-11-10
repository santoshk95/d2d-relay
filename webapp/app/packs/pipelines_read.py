"""Data pipelines & ETL — readers: each tool's API or export into one neutral model, so the rules (health, decide,
diagnose, convert) work the same on every platform.

A job:  {"id", "tool", "tool_label", "kind" (pipeline | package | mapping | DAG | job | task | model | connection),
         "name", "folder", "description", "owner", "schedule", "enabled", "sources" [table], "target" table,
         "secrets" [where a password sits in the definition], "fingerprint" (the definition without its name),
         "steps" (number of transformations), "where" (connection id or upload file), "native" (the tool's id),
         "logic" (the structured definition for rules-first conversion, when the tool's format has one)}
A run:  {"job", "tool", "start", "end", "status" (succeeded | failed | running), "error", "rows"}

Exports are uploaded as the tool writes them (a .zip of the project folder, or the files): SSIS (.dtsx in a project
folder or .ispac, the SSISDB catalog extracts), Informatica PowerCenter (repository XML + parameter files), Azure Data
Factory (ARM template), dbt (target/manifest.json + run_results.json), Airflow (DAG files), Talend (.item), DataStage
(.dsx + dsjob logs), ODI (Smart Export XML), AWS Glue (job scripts) and Fivetran (the Platform Connector log tables).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .. import connectors
from . import _w1

TOOLS = {"adf": "Azure Data Factory", "dbt": "dbt", "airflow": "Apache Airflow", "iics": "Informatica Cloud", "powercenter": "Informatica PowerCenter",
         "talend": "Talend", "fivetran": "Fivetran", "ssis": "SSIS", "datastage": "IBM DataStage", "odi": "Oracle Data Integrator", "glue": "AWS Glue"}
SECRET_RX = re.compile(r"(?i)(password|pwd|passwd|secret)\s*[=:]\s*([^;\"'<>\s&]{4,})")
TABLE_RX = re.compile(r"(?i)\b(?:FROM|JOIN|INTO|MERGE\s+INTO|UPDATE|TRUNCATE\s+TABLE)\s+([A-Za-z_][\w$]*\.[A-Za-z_][\w$]*)")


def fingerprint(text: str, name: str = "") -> str:
    t = re.sub(r"\s+", " ", text or "")
    if name:
        t = re.sub(re.escape(name), "@", t, flags=re.I)
    t = re.sub(r"(?i)(v2|_v\d|copy|\(copy\))", "", t)
    return hashlib.sha1(t.encode()).hexdigest()[:16]


def job(tool: str, kind: str, name: str, **kw) -> dict:
    j = {"id": f"{tool}:{name}", "tool": tool, "tool_label": TOOLS.get(tool, tool), "kind": kind, "name": name, "folder": "", "description": "", "owner": None,
         "schedule": "", "enabled": True, "sources": [], "target": "", "secrets": [], "fingerprint": "", "steps": 0, "where": "", "native": name, "logic": None}
    j.update(kw)
    j["sources"] = sorted({s.upper() for s in j["sources"] if s and s.upper() != (j["target"] or "").upper()})
    j["target"] = (j["target"] or "").upper()
    return j


def run(job_name: str, tool: str, start, end, status: str, error: str | None = None, rows=None) -> dict:
    return {"job": job_name, "tool": tool, "start": _w1.ts(start), "end": _w1.ts(end), "status": status, "error": (error or None) and str(error)[:600], "rows": rows}


def tables_in(sql: str) -> list[str]:
    return [m.group(1) for m in TABLE_RX.finditer(sql or "")]


def secrets_in(text: str, where: str) -> list[str]:
    out = []
    for m in SECRET_RX.finditer(text or ""):
        v = m.group(2)
        if v.startswith(("$", "@", "{", "%", "*", "#")) or v.lower() in ("none", "null", "true", "false", "******") or v.lower().startswith(("enc:", "secret:", "keyvault")):
            continue
        out.append(f"{where}: {m.group(1).lower()} written in clear")
    return sorted(set(out))


# ================================================================== APIs

def from_api(c: dict, since: float) -> tuple[list[dict], list[dict]]:
    a = connectors.sdk.get(c["kind"])
    fn = {"adf": _adf_api, "dbt_cloud": _dbt_api, "airflow": _airflow_api, "iics": _iics_api, "talend": _talend_api, "fivetran": _fivetran_api}.get(c["kind"])
    if not fn:
        return [], []
    jobs, runs = fn(a, c, since)
    for j in jobs:
        j["where"] = c["id"]
    return jobs, runs


def adf_jobs(pipelines: list, dataflows: list, triggers: list, links: list, datasets: list) -> list[dict]:
    dfs = {d["name"]: d for d in dataflows}
    dss = {d["name"]: d for d in datasets}
    sched = {}
    for t in triggers:
        p = t.get("properties") or {}
        rec = ((p.get("typeProperties") or {}).get("recurrence") or {})
        for pp in p.get("pipelines") or []:
            nm = (pp.get("pipelineReference") or {}).get("referenceName")
            sched[nm] = (f"{rec.get('frequency', '')} every {rec.get('interval', 1)}".strip() if rec else p.get("type", ""), p.get("runtimeState") != "Stopped")
    link_secrets = []
    for ls in links:
        tp = (ls.get("properties") or {}).get("typeProperties") or {}
        pw = tp.get("password")
        if isinstance(pw, dict) and pw.get("type") == "SecureString":
            link_secrets.append(ls["name"])
        link_secrets += [ls["name"] for _ in secrets_in(json.dumps(tp), ls["name"])]
    out = []
    for p in pipelines:
        pr = p.get("properties") or {}
        acts = pr.get("activities") or []
        text = json.dumps(acts, sort_keys=True)
        srcs, tgt, logic, nsteps = [], "", None, 0
        used_ds = set()
        for a in _walk_acts(acts):
            tp = a.get("typeProperties") or {}
            used_ds |= {x.get("referenceName") for x in (a.get("inputs") or []) + (a.get("outputs") or [])}
            if a.get("type") == "Copy":
                srcs += tables_in((tp.get("source") or {}).get("sqlReaderQuery") or "")
                for o in a.get("outputs") or []:
                    tgt = tgt or _ds_table(dss.get(o.get("referenceName")), o.get("referenceName"))
                for i in a.get("inputs") or []:
                    srcs.append(_ds_table(dss.get(i.get("referenceName")), i.get("referenceName")))
                nsteps += 1
            if a.get("type") == "ExecuteDataFlow":
                df = dfs.get(((tp.get("dataflow") or {}).get("referenceName")) or "")
                if df:
                    dtp = (df.get("properties") or {}).get("typeProperties") or {}
                    text += "\n".join(dtp.get("scriptLines") or [])
                    srcs += [_ds_table(dss.get((s.get("dataset") or {}).get("referenceName")), (s.get("dataset") or {}).get("referenceName")) for s in dtp.get("sources") or []]
                    used_ds |= {(s.get("dataset") or {}).get("referenceName") for s in (dtp.get("sources") or []) + (dtp.get("sinks") or [])}
                    for s in dtp.get("sinks") or []:
                        tgt = tgt or _ds_table(dss.get((s.get("dataset") or {}).get("referenceName")), (s.get("dataset") or {}).get("referenceName"))
                    nsteps += len(dtp.get("transformations") or [])
                    logic = {"lang": "adf", "dataflow": df["name"], "script": dtp.get("scriptLines") or [], "properties": df.get("properties") or {},
                             "sources": {s.get("name"): _ds_table(dss.get((s.get("dataset") or {}).get("referenceName")), (s.get("dataset") or {}).get("referenceName")) for s in dtp.get("sources") or []},
                             "sink": next((_ds_table(dss.get((s.get("dataset") or {}).get("referenceName")), (s.get("dataset") or {}).get("referenceName")) for s in dtp.get("sinks") or []), "")}
        owner = next((a.split(":", 1)[1] for a in pr.get("annotations") or [] if str(a).startswith("owner:")), None)
        s, on = sched.get(p["name"], ("", False))
        via = {((dss.get(d) or {}).get("properties") or {}).get("linkedServiceName", {}).get("referenceName") for d in used_ds}
        uses = [ls for ls in link_secrets if ls in text or ls in via]
        out.append(job("adf", "pipeline", p["name"], folder=(pr.get("folder") or {}).get("name") or "", description=pr.get("description") or "", owner=owner,
                       schedule=s or "manual", enabled=bool(s) and on, sources=srcs, target=tgt, steps=nsteps or len(acts), fingerprint=fingerprint(text, p["name"].replace("PL_", "")),
                       secrets=[f"linked service {x}: password kept in the factory, not Key Vault" for x in sorted(set(uses))], logic=logic))
    return out


def _walk_acts(acts):
    for a in acts or []:
        yield a
        tp = a.get("typeProperties") or {}
        for k in ("ifTrueActivities", "ifFalseActivities", "activities"):
            yield from _walk_acts(tp.get(k))


def _ds_table(ds: dict | None, name: str | None) -> str:
    tp = ((ds or {}).get("properties") or {}).get("typeProperties") or {}
    sch, tab = tp.get("schema"), tp.get("table") or tp.get("tableName")
    if sch and tab:
        return f"{sch}.{tab}"
    if isinstance(tab, str) and "." in tab:
        return tab
    m = re.match(r"DS_(STAGE|DW|MART|DBO)_(.+)", name or "")
    return f"{m.group(1)}.{m.group(2)}" if m else ""


def _adf_api(a, c, since):
    pipes, dfs, trig, links, dss = (a.items(c, k) for k in ("pipelines", "dataflows", "triggers", "linkedservices", "datasets"))
    jobs = adf_jobs(pipes, dfs, trig, links, dss)
    runs = [run(r["pipelineName"], "adf", r.get("runStart"), r.get("runEnd"), {"Succeeded": "succeeded", "Failed": "failed", "Cancelled": "failed"}.get(r.get("status"), "running"),
                r.get("message")) for r in a.runs(c, since)]
    for j in jobs:
        j["native_kind"] = "pipeline"
    return jobs, runs


def _dbt_api(a, c, since):
    jobs = []
    for j in a.jobs(c):
        steps = j.get("execute_steps") or []
        sch = (j.get("schedule") or {}).get("cron") or ""
        jobs.append(job("dbt", "job", j["name"], description=j.get("description") or " · ".join(steps), schedule=sch or "manual", enabled=bool((j.get("triggers") or {}).get("schedule")) and not j.get("deactivated"),
                        steps=len(steps), fingerprint=fingerprint(" ".join(steps)), native=j["id"]))
    names = {j["native"]: j["name"] for j in jobs}
    runs = [run(names.get(r.get("job_definition_id"), str(r.get("job_definition_id"))), "dbt", r.get("started_at"), r.get("finished_at"),
                "succeeded" if r.get("is_success") else "failed" if r.get("is_error") else "running", r.get("status_message"))
            for r in a.runs(c) if (_w1.ts(r.get("finished_at") or r.get("started_at")) or 0) >= since]
    return jobs, runs


def _airflow_api(a, c, since):
    jobs, runs = [], []
    for d in a.dags(c):
        src = ""
        try:
            src = a.source(c, d["file_token"]) if d.get("file_token") else ""
        except connectors.ConnectorError:
            src = ""
        jobs.append(_airflow_job(d["dag_id"], src, schedule=(d.get("schedule_interval") or {}).get("value") or "", enabled=not d.get("is_paused"), owner=",".join(d.get("owners") or []) or None,
                                 description=d.get("description") or "", folder=(d.get("fileloc") or "").rsplit("/", 2)[-2] if "/" in (d.get("fileloc") or "") else ""))
        for r in a.dag_runs(c, d["dag_id"]):
            end = r.get("end_date") or r.get("start_date")
            if (_w1.ts(end) or 0) < since:
                continue
            st = {"success": "succeeded", "failed": "failed"}.get(r.get("state"), "running")
            err = None
            if st == "failed":
                try:
                    err = a.failed_log(c, d["dag_id"], r["dag_run_id"])
                except connectors.ConnectorError:
                    err = "a task failed"
            runs.append(run(d["dag_id"], "airflow", r.get("start_date"), r.get("end_date"), st, err))
    return jobs, runs


def _airflow_job(dag_id: str, src: str, **kw) -> dict:
    sqls = re.findall(r'sql\s*=\s*"""(.*?)"""', src, re.S) + re.findall(r"sql\s*=\s*\"([^\"]+)\"", src)
    text = "\n".join(sqls)
    tgt = next((m.group(1) for m in re.finditer(r"(?i)\b(?:MERGE\s+INTO|INSERT\s+INTO|INTO)\s+([\w$]+\.[\w$]+)", text)), "")
    if not kw.get("owner"):
        m = re.search(r'"owner"\s*:\s*"([^"]+)"', src)
        kw["owner"] = m.group(1) if m else None
    if not kw.get("schedule"):
        m = re.search(r'schedule(?:_interval)?\s*=\s*"([^"]*)"', src)
        kw["schedule"] = m.group(1) if m else ""
    if not kw.get("description"):
        m = re.match(r'\s*"""(.*?)"""', src, re.S)
        kw["description"] = (m.group(1).strip() if m else "")[:300]
    return job("airflow", "DAG", dag_id, sources=tables_in(text), target=tgt, steps=len(re.findall(r"Operator\(", src)) or len(sqls), fingerprint=fingerprint(text, dag_id),
               secrets=secrets_in(src, f"{dag_id}.py"), logic={"lang": "sql", "sql": sqls[0] if sqls else ""} if sqls else None, **kw)


def _iics_api(a, c, since):
    maps = {m["id"]: m for m in a.mappings(c)}
    jobs = []
    for t in a.tasks(c):
        q = next((p.get("text") or p.get("value") or "" for p in t.get("parameters") or [] if p.get("name") == "$src_query$"), "")
        m = maps.get(t.get("mappingId")) or {}
        jobs.append(job("iics", "mapping task", t["name"], description=t.get("description") or "", schedule=t.get("scheduleId") or "manual", enabled=bool(t.get("scheduleId")),
                        sources=tables_in(q), target=_iics_target(t, m), steps=len(m.get("sourceFields") or []) and 1, fingerprint=fingerprint(q, t["name"]), native=t["id"],
                        logic={"lang": "sql", "sql": q} if q else None))
    names = {j["native"]: j["name"] for j in jobs}
    runs = []
    for x in a.activity(c):
        if (_w1.ts(x.get("endTime") or x.get("startTime")) or 0) < since:
            continue
        runs.append(run(x.get("objectName") or names.get(x.get("objectId"), "?"), "iics", x.get("startTime"), x.get("endTime"),
                        {1: "succeeded", 2: "succeeded", 3: "failed"}.get(x.get("state"), "running"), x.get("errorMsg"), x.get("successTargetRows")))
    return jobs, runs


def _iics_target(t: dict, m: dict) -> str:
    n = re.sub(r"^(mt_|mct_|task_)", "", t["name"], flags=re.I)
    return {"FACT_": "DW.", "DIM_": "DW.", "STG_": "STAGE.", "AGG_": "MART."}.get(next((p for p in ("FACT_", "DIM_", "STG_", "AGG_") if n.upper().startswith(p)), ""), "") + \
        re.sub(r"_(LOAD|BUILD|IMPORT|SCD2|EXPORT)(_V2)?$", "", n.upper()) if n.upper().startswith(("FACT_", "DIM_", "STG_", "AGG_")) else ""


def _talend_api(a, c, since):
    jobs, by_id = [], {}
    for t in a.tasks(c):
        tr = t.get("trigger") or {}
        j = job("talend", "task", t["name"], description=t.get("description") or "", folder=",".join(t.get("tags") or []),
                schedule=f"{tr.get('type', '').lower()} {((tr.get('atTimes') or {}).get('time') or '')}".strip() if tr else "manual", enabled=bool(tr),
                fingerprint=fingerprint(t.get("description") or "", t["name"]), native=t["executable"])
        jobs.append(j)
        by_id[t["executable"]] = t["name"]
    runs = [run(x.get("taskName") or by_id.get(x.get("taskId"), "?"), "talend", x.get("startTimestamp"), x.get("finishTimestamp"),
                {"execution_successful": "succeeded", "execution_failed": "failed", "execution_terminated": "failed"}.get(x.get("status"), "running"), x.get("errorMessage"), x.get("rowsWritten"))
            for x in a.executions(c, since)]
    return jobs, runs


def _fivetran_api(a, c, since):
    jobs, runs = [], []
    for x in a.connections(c):
        st = x.get("status") or {}
        nm = f"{x['service']}.{x['schema']}"
        jobs.append(job("fivetran", "connection", nm, description=f"{x['service']} connection syncing into schema {x['schema']}", schedule=f"every {x.get('sync_frequency')} min",
                        enabled=not x.get("paused"), target=x["schema"].upper() + ".*", native=x["id"], fingerprint=fingerprint(json.dumps(x.get("config") or {}, sort_keys=True)),
                        broken=st.get("setup_state") == "broken", tasks=[t.get("message") for t in st.get("tasks") or []]))
        if x.get("failed_at") and (_w1.ts(x["failed_at"]) or 0) >= since:
            runs.append(run(nm, "fivetran", x["failed_at"], x["failed_at"], "failed", "; ".join(t.get("message") or "" for t in st.get("tasks") or []) or "the last sync failed"))
        if x.get("succeeded_at") and (_w1.ts(x["succeeded_at"]) or 0) >= since:
            runs.append(run(nm, "fivetran", x["succeeded_at"], x["succeeded_at"], "succeeded"))
    return jobs, runs


# ================================================================== exports (uploads)

def from_files(paths: list[Path]) -> tuple[list[dict], list[dict], list[str]]:
    """Jobs and runs from uploaded exports; the files Relay could not read are named."""
    files: dict[str, bytes] = {}
    for p in paths:
        if p.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(p) as z:
                    for n in z.namelist():
                        if not n.endswith("/"):
                            data = z.read(n)
                            if n.lower().endswith(".ispac"):
                                with zipfile.ZipFile(io.BytesIO(data)) as zz:
                                    for m in zz.namelist():
                                        files[f"{n}/{m}"] = zz.read(m)
                            else:
                                files[n] = data
            except zipfile.BadZipFile:
                files[p.name] = b""
        else:
            files[p.name] = p.read_bytes()
    jobs, runs, unread = [], [], []
    ssis = {n: b for n, b in files.items() if n.lower().endswith(".dtsx")}
    if ssis:
        j, r = _ssis(ssis, files)
        jobs += j
        runs += r
    handled = set(ssis)
    for n, b in files.items():
        low = n.lower()
        txt = b.decode("utf-8", "replace") if b else ""
        try:
            if low.endswith(".xml") and "<POWERMART" in txt[:2000]:
                jobs += _powercenter(txt, files)
            elif low.endswith(".json") and '"Microsoft.DataFactory/factories' in txt[:200000]:
                jobs += _adf_arm(txt)
            elif low.endswith("manifest.json") and '"nodes"' in txt:
                jobs += _dbt_manifest(txt)
            elif low.endswith("run_results.json"):
                runs += _dbt_results(txt)
            elif low.endswith(".py") and "DAG(" in txt:
                m = re.search(r'dag_id\s*=\s*"([^"]+)"', txt)
                jobs.append(_airflow_job(m.group(1) if m else Path(n).stem, txt, folder=Path(n).parent.name))
            elif low.endswith(".py") and ("GlueContext" in txt or "awsglue" in txt):
                jobs.append(_glue_script(Path(n).stem, txt))
            elif low.endswith(".item") and "talendfile" in txt[:500]:
                jobs.append(_talend_item(Path(n).stem, txt, Path(n).parent.name))
            elif low.endswith(".dsx"):
                jobs += _dsx(txt)
            elif low.endswith(".jobinfo.txt"):
                runs += _dsjob(Path(n).name.split(".")[0], txt)
            elif low.endswith(".xml") and ("SmartExport" in txt[:3000] or "<SmartExport" in txt[:3000]) and "SCEN_" not in Path(n).name:
                jobs += _odi(txt)
            elif low.endswith("catalog.executions.csv"):
                continue                                             # read with the SSIS packages
            elif low.endswith("log.csv") and "MESSAGE_EVENT" in txt[:300]:
                runs += _fivetran_log(txt, files)
            elif n in handled or low.endswith((".properties", ".par", ".conmgr", ".dtproj", ".params", ".manifest", ".yml", ".yaml", ".md", ".sql", ".csv", ".txt", ".json", ".xml", ".project", ".bat")):
                continue
            else:
                unread.append(n)
        except (ET.ParseError, ValueError, KeyError) as e:
            unread.append(f"{n} ({e.__class__.__name__}: {str(e)[:80]})")
    return _dedupe(jobs), runs, unread


def _dedupe(jobs: list[dict]) -> list[dict]:
    out = {}
    for j in jobs:
        out.setdefault(j["id"], j)
    return list(out.values())


def _ssis(pkgs: dict, files: dict) -> tuple[list, list]:
    jobs = []
    for n, b in sorted(pkgs.items()):
        name = Path(n).stem
        txt = b.decode("utf-8", "replace")
        try:
            root = ET.fromstring(b)
        except ET.ParseError:
            continue
        D = "{www.microsoft.com/SqlServer/Dts}"
        desc = root.get(D + "Description") or ""
        srcs, tgt = [], ""
        for prop in root.iter("property"):
            if prop.get("name") == "SqlCommand" and prop.text and prop.text.strip().upper().startswith("SELECT"):
                srcs += tables_in(prop.text)
            if prop.get("name") == "OpenRowset" and prop.text:
                tgt = tgt or prop.text.replace("[", "").replace("]", "")
        steps = sum(1 for c in root.iter("component"))
        conns = " ".join(cm.get(D + "ConnectionString") or "" for cm in root.iter(D + "ConnectionManager")) + " " + " ".join(
            (p.text or "") for p in root.iter(D + "Property") if (p.get(D + "Name") or "") in ("Password", "ConnectionString"))
        jobs.append(job("ssis", "package", name, folder=Path(n).parent.name, description=desc, sources=srcs, target=tgt, steps=steps,
                        secrets=secrets_in(conns + " " + " ".join(re.findall(r"Password=[^;\"<]+", txt)), f"{name}.dtsx connection"), fingerprint=fingerprint(_strip_ssis(txt), name),
                        logic=_ssis_logic(root) if steps else None))
    runs = []
    errors = {}
    for n, b in files.items():
        if n.lower().endswith("catalog.event_messages.errors.json"):
            try:
                for e in json.loads(b.decode("utf-8", "replace")):
                    errors.setdefault(e.get("operation_id"), e.get("message"))
            except ValueError:
                pass
    for n, b in files.items():
        if n.lower().endswith("catalog.executions.csv"):
            for r in csv.DictReader(io.StringIO(b.decode("utf-8", "replace"))):
                st = {"7": "succeeded", "9": "succeeded", "4": "failed", "6": "failed", "3": "failed"}.get(str(r.get("status")), "running")
                runs.append(run(Path(r.get("package_name") or "").stem, "ssis", r.get("start_time"), r.get("end_time"), st,
                                errors.get(int(r["execution_id"])) if st == "failed" and str(r.get("execution_id", "")).isdigit() else None))
    return jobs, runs


def _strip_ssis(txt: str) -> str:
    t = re.sub(r'DTS:(DTSID|CreationDate|VersionGUID|refId|ObjectName|Description)="[^"]*"', "", txt)
    t = re.sub(r"\{[0-9A-F-]{36}\}", "", t)
    return re.sub(r'refId="[^"]*"|lineageId="[^"]*"|externalMetadataColumnId="[^"]*"|name="[^"]*"', "", t)


def _ssis_logic(root) -> dict:
    """The data flow as the converter reads it: sources (their SQL), merge joins, lookups (their SQL and join columns),
    derived columns (SSIS expressions), conditional splits, aggregates and the destination with its column mapping."""
    comps = []
    for c in root.iter("component"):
        cls = c.get("componentClassID") or ""
        props = {p.get("name"): (p.text or "") for p in c.findall("./properties/property")}
        item = {"name": c.get("name"), "class": cls.split(".")[-1], "props": props, "out": [], "in": []}
        for oc in c.iter("outputColumn"):
            ex = {p.get("name"): (p.text or "") for p in oc.findall("./properties/property")}
            item["out"].append({"name": oc.get("name"), "expr": ex.get("Expression") or ex.get("FriendlyExpression"), "copy": ex.get("CopyFromReferenceColumn")})
        for ic in c.iter("inputColumn"):
            ex = {p.get("name"): (p.text or "") for p in ic.findall("./properties/property")}
            item["in"].append({"name": ic.get("cachedName") or ic.get("name"), "join": ex.get("JoinToReferenceColumn"), "ext": (ic.get("externalMetadataColumnId") or "").rsplit("[", 1)[-1].rstrip("]")})
        comps.append(item)
    return {"lang": "ssis", "components": comps}


def _powercenter(txt: str, files: dict) -> list[dict]:
    root = ET.fromstring(re.sub(r'encoding="[^"]+"', 'encoding="utf-8"', txt, count=1).encode("utf-8"))
    out = []
    params = {}
    for n, b in files.items():
        if n.lower().endswith(".par"):
            params[Path(n).stem] = b.decode("utf-8", "replace")
    for folder in root.iter("FOLDER"):
        targets = {t.get("NAME"): t for t in folder.findall("TARGET")}
        sources = {s.get("NAME"): s for s in folder.findall("SOURCE")}
        sessions = {s.get("NAME"): s.get("MAPPINGNAME") for s in folder.iter("SESSION")}
        flows = {}
        for wf in folder.iter("WORKFLOW"):
            sess = next((t.get("TASKNAME") for t in wf.iter("TASKINSTANCE") if t.get("TASKTYPE") == "Session"), None)
            sched = wf.find(".//SCHEDULEINFO")
            start, rec = wf.find(".//STARTOPTIONS"), wf.find(".//RECURRING")
            stype = sched.get("SCHEDULETYPE") if sched is not None else "ONDEMAND"
            text = "manual" if stype in ("ONDEMAND", None) else (
                f"every {rec.get('DAYS')} day(s) at {start.get('STARTTIME')}" if rec is not None and rec.get("DAYS") not in (None, "0") else
                f"every {rec.get('HOURS')} hour(s)" if rec is not None and rec.get("HOURS") not in (None, "0") else f"once at {start.get('STARTTIME') if start is not None else '?'}")
            flows[sessions.get(sess) or ""] = {"name": wf.get("NAME"), "enabled": wf.get("ISENABLED") == "YES" and stype != "ONDEMAND", "schedule": text, "desc": wf.get("DESCRIPTION") or ""}
        for m in folder.iter("MAPPING"):
            mname = m.get("NAME")
            base = re.sub(r"^m_", "", mname)
            insts = {i.get("NAME"): i for i in m.findall("INSTANCE")}
            tgt_inst = next((i for i in insts.values() if i.get("TYPE") == "TARGET"), None)
            tgt_def = targets.get(tgt_inst.get("TRANSFORMATION_NAME")) if tgt_inst is not None else None
            tgt = f"{(tgt_def.get('OWNERNAME') if tgt_def is not None and tgt_def.get('OWNERNAME') else _schema_of(tgt_inst.get('NAME')))}.{tgt_inst.get('NAME')}" if tgt_inst is not None else ""
            srcs = []
            for t in m.findall("TRANSFORMATION"):
                for a in t.findall("TABLEATTRIBUTE"):
                    if a.get("NAME") == "Sql Query":
                        srcs += tables_in(a.get("VALUE") or "")
                    if a.get("NAME") == "Lookup table name" and a.get("VALUE"):
                        srcs.append(a.get("VALUE") if "." in a.get("VALUE") else f"{_schema_of(a.get('VALUE'))}.{a.get('VALUE')}")
            for i in insts.values():
                if i.get("TYPE") == "SOURCE" and sources.get(i.get("TRANSFORMATION_NAME")) is not None:
                    s = sources[i.get("TRANSFORMATION_NAME")]
                    srcs.append(f"{s.get('OWNERNAME') or _schema_of(s.get('NAME'))}.{s.get('NAME')}")
            wf = flows.get(mname) or {"name": f"wf_{base}", "enabled": True, "schedule": "", "desc": ""}
            par = params.get(wf["name"]) or ""
            out.append(job("powercenter", "mapping", base, folder=folder.get("NAME") or "", description=m.get("DESCRIPTION") or wf["desc"], schedule=wf["schedule"] or "manual",
                           enabled=wf["enabled"], sources=srcs, target=tgt, steps=len(m.findall("TRANSFORMATION")),
                           fingerprint=fingerprint(re.sub(r'NAME="[^"]*"', "", ET.tostring(m, encoding="unicode")), base),
                           secrets=secrets_in(par, f"{wf['name']}.par"), logic=_pc_logic(m, targets, sources), native=mname))
    return out


def _schema_of(table: str | None) -> str:
    t = (table or "").upper()
    return "STAGE" if t.startswith(("STG_", "TMP_")) else "MART" if t.startswith(("AGG_", "V_")) else "DW" if t.startswith(("DIM_", "FACT_")) else "DBO"


def _pc_logic(m, targets: dict, sources: dict) -> dict:
    tr = []
    for t in m.findall("TRANSFORMATION"):
        attrs = {a.get("NAME"): a.get("VALUE") or "" for a in t.findall("TABLEATTRIBUTE")}
        fields = [{"name": f.get("NAME"), "expr": f.get("EXPRESSION"), "port": f.get("PORTTYPE") or "", "etype": f.get("EXPRESSIONTYPE") or ""} for f in t.findall("TRANSFORMFIELD")]
        tr.append({"name": t.get("NAME"), "type": t.get("TYPE"), "attrs": attrs, "fields": fields})
    conns = [{"from": c.get("FROMINSTANCE"), "ff": c.get("FROMFIELD"), "to": c.get("TOINSTANCE"), "tf": c.get("TOFIELD")} for c in m.findall("CONNECTOR")]
    insts = [{"name": i.get("NAME"), "type": i.get("TYPE"), "def": i.get("TRANSFORMATION_NAME")} for i in m.findall("INSTANCE")]
    tdefs = {}
    for i in insts:
        if i["type"] == "TARGET" and i["def"] in targets:
            t = targets[i["def"]]
            tdefs[i["name"]] = {"schema": t.get("OWNERNAME") or _schema_of(t.get("NAME")), "fields": [f.get("NAME") for f in t.findall("TARGETFIELD")],
                                "keys": [f.get("NAME") for f in t.findall("TARGETFIELD") if f.get("KEYTYPE") == "PRIMARY KEY"]}
    return {"lang": "infa", "transformations": tr, "connectors": conns, "instances": insts, "targets": tdefs}


def _adf_arm(txt: str) -> list[dict]:
    d = json.loads(txt)
    res = d.get("resources") or []

    def kind(r, k):
        return [{"name": re.search(r"/([^/']+)'\)\]?$", r["name"]).group(1) if re.search(r"/([^/']+)'\)\]?$", r["name"]) else r["name"].rsplit("/", 1)[-1], "properties": r.get("properties") or {}}
                for r in res if r.get("type") == f"Microsoft.DataFactory/factories/{k}"]
    return adf_jobs(kind(res, "pipelines"), kind(res, "dataflows"), kind(res, "triggers"), kind(res, "linkedServices"), kind(res, "datasets"))


def _dbt_manifest(txt: str) -> list[dict]:
    m = json.loads(txt)
    out = []
    for n in (m.get("nodes") or {}).values():
        if n.get("resource_type") not in ("model", "snapshot"):
            continue
        deps = [x.split(".")[-1] for x in (n.get("depends_on") or {}).get("nodes") or []]
        code = n.get("raw_code") or n.get("raw_sql") or ""
        out.append(job("dbt", n["resource_type"], n["name"], folder=(n.get("original_file_path") or "").rsplit("/", 2)[-2] if "/" in (n.get("original_file_path") or "") else "",
                       description=n.get("description") or "", owner=((n.get("config") or {}).get("meta") or {}).get("owner"), schedule="with its job",
                       sources=[f"{(n.get('schema') or 'DBT')}.{x}" for x in deps], target=f"{n.get('schema') or 'DBT'}.{n['name']}", steps=1, fingerprint=fingerprint(code, n["name"]),
                       logic={"lang": "dbt", "sql": code}))
    return out


def _dbt_results(txt: str) -> list[dict]:
    r = json.loads(txt)
    gen = (r.get("metadata") or {}).get("generated_at")
    return [run(x.get("unique_id", "").split(".")[-1], "dbt", gen, gen, "succeeded" if x.get("status") in ("success", "pass") else "failed", x.get("message")) for x in r.get("results") or []]


def _glue_script(name: str, txt: str) -> dict:
    tgt = next(iter(re.findall(r'(?i)(?:dbtable|table_name|"table")\W+["\']([\w.]+)["\']', txt)[-1:]), "")
    return job("glue", "job", name.upper(), sources=tables_in(txt) + re.findall(r'(?i)FROM\s+([\w]+\.[\w]+)', txt), target=tgt, steps=len(re.findall(r"\.(?:join|filter|withColumn|groupBy)\(", txt)) or 1,
               fingerprint=fingerprint(txt, name), secrets=secrets_in(txt, f"{name}.py"))


def _talend_item(name: str, txt: str, folder: str) -> dict:
    nm = re.sub(r"_\d+\.\d+$", "", name)
    sql = " ".join(re.findall(r'name="QUERY" value="([^"]*)"', txt))
    tgt = next(iter(re.findall(r'name="TABLE" value="&quot;([^&]+)&quot;"', txt)[-1:]), "")
    pw = [] if re.search(r'name="PASS" value="enc:', txt) or not re.search(r'name="(?:PASS|PASSWORD)" value="&quot;[^&]+&quot;"', txt) else [f"{nm}.item: password written in clear"]
    pw += [f"{nm}.item: context password in clear"] if re.search(r'type="id_Password"[^>]*value="(?!enc:)[^"]{4,}"', txt) else []
    return job("talend", "job", nm, folder=folder, sources=tables_in(sql.replace("&quot;", "")), target=tgt, steps=len(re.findall(r'<node ', txt)), fingerprint=fingerprint(txt, nm), secrets=pw)


def _dsx(txt: str) -> list[dict]:
    out = []
    for blk in re.split(r"(?m)^BEGIN DSJOB", txt)[1:]:
        m = re.search(r'Identifier "([^"]+)"', blk)
        if not m:
            continue
        nm = m.group(1)
        sqls = " ".join(re.findall(r'(?:SelectStatement|UserSQL|SQL) "([^"]*)"', blk))
        tgt = next(iter(re.findall(r'TableName "([\w.]+)"', blk)[-1:]), "")
        pw = [f"{nm}.dsx: password parameter has a default in clear"] if re.search(r'Name "p\w*Password"[^}]*?Default "[^"]{4,}"', blk, re.S) else []
        out.append(job("datastage", "job", nm, folder=next(iter(re.findall(r'Category "\\\\?Jobs\\\\?([^"]*)"', blk)), ""), description=next(iter(re.findall(r'Description "([^"]*)"', blk)), ""),
                       sources=tables_in(sqls), target=tgt, steps=blk.count("BEGIN DSRECORD"), fingerprint=fingerprint(blk, nm), secrets=pw))
    return out


def _dsjob(name: str, txt: str) -> list[dict]:
    st = "failed" if "FAILED" in txt or "ABORTED" in txt else "succeeded" if "RUN OK" in txt or "FINISHED" in txt else "running"
    t = re.search(r"Job Start Time\s*:\s*(.+)", txt)
    import datetime as dt
    when = None
    if t:
        try:
            when = dt.datetime.strptime(" ".join(t.group(1).split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            when = None
    return [run(name, "datastage", when, when, st, "the last run failed (see the job log)" if st == "failed" else None)]


def _odi(txt: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<Object class="com\.sunopsis\.dwg\.dbobj\.SnpPop">(.*?)</Object>|<Object class="com\.oracle\.odi\.domain\.mapping\.Mapping">(.*?)</Object>', txt, re.S):
        blk = m.group(1) or m.group(2)
        nm = re.search(r'<Field name="(?:PopName|Name)" type="java.lang.String"><!\[CDATA\[([^\]]+)\]\]>', blk)
        if not nm:
            continue
        sql = " ".join(re.findall(r"<!\[CDATA\[([^\]]*(?:SELECT|FROM)[^\]]*)\]\]>", blk, re.I))
        out.append(job("odi", "mapping", nm.group(1), sources=tables_in(sql), target=next(iter(re.findall(r'(?:TableName|TargetTable)[^>]*><!\[CDATA\[([\w.]+)\]\]>', blk)), ""),
                       steps=blk.count("<Object"), fingerprint=fingerprint(blk, nm.group(1)), secrets=secrets_in(blk, nm.group(1))))
    if not out:
        for nm in sorted(set(re.findall(r'(?:SCEN_|MAP_)([A-Z0-9_]+?)(?:_001|_V\d)?["<\]]', txt))):
            out.append(job("odi", "mapping", nm, fingerprint=fingerprint(nm)))
    return out


def _fivetran_log(txt: str, files: dict) -> list[dict]:
    names = {}
    for n, b in files.items():
        if n.lower().endswith("connection.csv"):
            for r in csv.DictReader(io.StringIO(b.decode("utf-8", "replace"))):
                names[r.get("CONNECTION_ID")] = f"{r.get('CONNECTOR_TYPE')}.{r.get('CONNECTION_NAME')}"
    out, starts = [], {}
    for r in csv.DictReader(io.StringIO(txt)):
        if r.get("MESSAGE_EVENT") == "sync_start":
            starts[r.get("SYNC_ID")] = r.get("TIME_STAMP")
        elif r.get("MESSAGE_EVENT") == "sync_end":
            try:
                d = json.loads(r.get("MESSAGE_DATA") or "{}")
            except ValueError:
                d = {}
            ok = (d.get("status") or "").upper() == "SUCCESSFUL"
            out.append(run(names.get(r.get("CONNECTION_ID"), r.get("CONNECTION_ID")), "fivetran", starts.get(r.get("SYNC_ID")) or r.get("TIME_STAMP"), r.get("TIME_STAMP"),
                           "succeeded" if ok else "failed", None if ok else d.get("reason") or "the sync failed"))
    return out


def now() -> float:
    return time.time()
