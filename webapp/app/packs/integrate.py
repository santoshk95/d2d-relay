"""Finance & accounting (registry id `integrate`) on the workbench - Oracle Fusion Financials, TallyPrime, Zoho Books,
QuickBooks Online, Xero; Busy, ClearTax and the GST / TRACES / MCA portals through their exports.

Assess   the ledgers (with each one's debits and credits: a trial balance), vouchers, customers and invoices of each
         book; rules: the trial balance must balance, the import jobs that keep failing (Tally's import log, Fusion's
         ESS), duplicate customers, GSTINs, invoices GSTR-1 would refuse (no place of supply, an odd tax rate), and
         Tally's XML port answering without a sign-in.
Develop  Discover -> Map -> Build -> Prove -> Ship -> Run: the chart of accounts and ledger mapping - each source ledger onto
         the target's chart (same name, then its group's rule: debtors -> receivables, duties & taxes by tax), corrected
         in place; the trial-balance proof (every ledger with a balance mapped, debits = credits, the mapped totals equal
         the source's, account types that fit); a named approver; the missing accounts created through one approval.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: a voucher import that names a ledger the company lacks
         (the ledger created under its group), invoices without a place of supply (corrected from the customer's own
         place of contact), released with approval and checked on the system.
Migrate  Discover -> Decide -> Convert -> Prove -> Hand over -> Run: opening balances between ledgers (Tally -> Zoho Books ...):
         keep / merge / retire ledgers, one balanced opening journal on the mapped accounts, the trial-balance proof
         before the load and after it (read back from the target's journals).
Run      the imports and the GST checks on a schedule; the GSTR-1 B2B file of the period prepared from the invoices that
         pass (filed by a person on the portal); breaks routed after approval.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from .. import connectors, db
from .. import workbench as wb
from . import _systems as w3
from . import erp_adapters  # noqa: F401 - Oracle Fusion Financials (one connection serves ERP and finance)
from . import integrate_adapters as fa

MODULE = "integrate"
GST_RATES = (0, 5, 12, 18, 28)
GROUP_RULE = {   # a source group (Tally's reserved groups) -> the target account it rolls into, and the type of a new one
    "Sundry Debtors": ("Accounts Receivable", "accounts_receivable"), "Sundry Creditors": ("Accounts Payable", "accounts_payable"),
    "Sales Accounts": ("Sales", "income"), "Purchase Accounts": ("Cost of Goods Sold", "cost_of_goods_sold"), "Cash-in-Hand": ("Petty Cash", "cash"),
    "Capital Account": ("Owner's Equity", "equity")}
TYPE_FITS = {"asset": {"accounts_receivable", "bank", "cash", "other_current_asset", "fixed_asset", "stock"}, "liability": {"accounts_payable", "other_current_liability", "long_term_liability"},
             "income": {"income", "other_income"}, "expense": {"expense", "other_expense", "cost_of_goods_sold"}, "equity": {"equity"}}


# ------------------------------------------------------------------ trial balance

@wb.proof("w3_trial_balance", "Trial balance: debits equal credits")
def _p_tb(ctx, file: str, **_):
    rows = w3.read_csv(ctx.dir / "data" / file)
    dr = round(sum(float(r.get("debit") or 0) for r in rows), 2)
    cr = round(sum(float(r.get("credit") or 0) for r in rows), 2)
    ok = abs(dr - cr) <= 0.01
    return {"status": "pass" if ok else "fail", "measured": f"{dr:,.2f} debit - {cr:,.2f} credit", "expected": "equal",
            "detail": f"{len(rows)} account(s); debits {dr:,.2f}, credits {cr:,.2f}" + ("" if ok else f" - off by {abs(dr - cr):,.2f}"), "rows": rows[:500]}


def rule_trial_balance(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("account"):
        dr = round(sum(float(r.get("debit") or 0) for r in rows), 2)
        cr = round(sum(float(r.get("credit") or 0) for r in rows), 2)
        if abs(dr - cr) > 0.01:
            out.append(w3.finding("unbalanced_tb", system, "account", "trial balance", f"The trial balance does not balance: debits {dr:,.2f}, credits {cr:,.2f}", "high",
                                  measured=f"{abs(dr - cr):,.2f}", fix="Find the one-sided entries (a suspense posting, an import that stopped half-way) before anything moves.", work="change"))
    return out


rule_trial_balance.label = "The trial balance balances (debits = credits)"


def rule_gstr1(ctx, inv, spec=None) -> list[dict]:
    """GSTR-1 readiness of India invoices: a place of supply on every one (proposed from the customer's own place of
    contact - the data, never a guess) and a tax rate GST knows."""
    out = []
    for system, rows in inv.rows("invoice"):
        india = [r for r in rows if (r.get("currency") == "INR" or r.get("gstin") or r.get("customer_place"))]
        gap = [r for r in india if not r.get("place_of_supply")]
        if gap:
            props = [{"action": "update", "entity": "invoice", "key": r["key"], "label": f"Invoice {r.get('number')} ({r.get('party')})", "field": "place_of_supply",
                      "value": r.get("customer_place") or fa.state_of_gstin(r.get("gstin")) or "", "before": "",
                      "why": f"the customer's place of contact is {r.get('customer_place')}" if r.get("customer_place") else "the customer's GSTIN is registered in that state" if r.get("gstin") else "type it in"}
                     for r in gap]
            out.append(w3.finding("no_place_of_supply", system, "invoice", f"{len(gap)} invoices", f"{len(gap)} India invoice(s) without a place of supply: GSTR-1 refuses them ({', '.join(str(r.get('number')) for r in gap[:6])})",
                                  "high", measured=", ".join(str(r.get("number")) for r in gap), fix="Set the place of supply from the customer's place of contact, then prepare GSTR-1.",
                                  work="change", keys=[r["key"] for r in gap], proposals=props))
        odd = []
        for r in india:
            amt, tax = w3.num(r.get("amount")) or 0, w3.num(r.get("tax")) or 0
            net = amt - tax
            if net > 0 and tax and min(abs(tax / net * 100 - g) for g in GST_RATES) > 0.6:
                odd.append(r)
        if odd:
            out.append(w3.finding("odd_gst_rate", system, "invoice", f"{len(odd)} invoices", f"{len(odd)} invoice(s) whose tax is not 0, 5, 12, 18 or 28 % of the taxable value", "medium",
                                  measured=", ".join(str(r.get("number")) for r in odd[:8]), fix="Check the tax lines before GSTR-1.", work="change", keys=[r["key"] for r in odd]))
    return out


rule_gstr1.label = "GSTR-1 readiness: place of supply and GST rates"


def rule_open_port(ctx, inv, spec=None) -> list[dict]:
    out = []
    for it in inv.items:
        if it.get("platform") == "TallyPrime" and it.get("entity") == "account":
            out.append(w3.finding("open_port", it["system"], "account", "XML port", f"{it['system']}: Tally's XML port answered Relay without any sign-in - anyone on the network can read and post vouchers",
                                  "high", fix="Limit the port to the integration host (firewall) or put an authenticating gateway in front of it.", work="change"))
    return out


rule_open_port.label = "Tally's XML port needs no sign-in"


def import_log(ctx, seen) -> list[dict]:
    """TallyPrime's import log (tally.imp, uploaded as text): each nightly voucher import with what it created and its errors."""
    items = []
    for f in ctx.files((".txt",)):
        if not any(w in f["name"].lower() for w in ("import-log", "import_log", ".imp")):
            continue
        text = (ctx.dir / "data" / f["name"]).read_text(encoding="utf-8", errors="replace").splitlines()
        runs = []
        for ln in text:
            m = re.match(r"(\d{2}-\w{3}-\d{4} \d{2}:\d{2}:\d{2})\s+Import of Vouchers into '([^']+)'\s+Created: (\d+)\s+Altered: \d+\s+Errors: (\d+)", ln)
            if m:
                import datetime as dt
                t = dt.datetime.strptime(m.group(1), "%d-%b-%Y %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
                runs.append({"job": "voucher import", "label": f"Voucher import into {m.group(2)}", "id": f"imp-{len(runs) + 1}", "started": t, "ended": t,
                             "status": "failed" if int(m.group(4)) else "succeeded", "error": None})
            elif ln.strip().startswith("ERROR:") and runs:
                runs[-1]["error"] = ln.strip()[6:].strip()
        if runs:
            runs.sort(key=lambda r: r["started"], reverse=True)
            fn = w3.snap(ctx, f"inv-{w3.slug(f['name'])}-jobs", runs, ["job", "label", "id", "started", "ended", "status", "error"])
            items.append({"id": f"file:{f['name']}", "include": True, "system": f["name"], "platform": "TallyPrime import log", "object": f["name"], "what": "Voucher imports and their errors",
                          "records": len(runs), "usage": f"{sum(1 for r in runs if r['status'] == 'failed')} failed", "file": fn, "entity": "jobs"})
    return items


def propose_ledger(ctx, c, a, api, run) -> list[dict]:
    """A voucher names a ledger the company does not have: create it under the group its name says (a tax ledger
    under Duties & Taxes) - the person confirms the group."""
    m = re.search(r"Ledger '([^']+)' does not exist", run.get("error") or "")
    if not m:
        return []
    name = m.group(1)
    group = "Duties & Taxes" if re.search(r"\b(GST|IGST|CGST|SGST|TDS|TCS|VAT)\b", name, re.I) else ""
    return [{"action": "create", "entity": "account", "key": name, "label": f"Ledger {name}", "field": "group", "value": group,
             "why": "a tax ledger lives under Duties & Taxes" if group else "give the group it belongs to"}]


def propose_pos(ctx, c, a, api, run) -> list[dict]:
    """Invoices without a place of supply: each takes its customer's own place of contact (or the state its GSTIN is
    registered in) - from the data, never a guess; an empty value waits for the person."""
    out = []
    for r in a.records(api, "invoice"):
        if not r.get("place_of_supply") and (r.get("currency") == "INR" or r.get("gstin")):
            v = r.get("customer_place") or fa.state_of_gstin(r.get("gstin")) or ""
            out.append({"action": "update", "entity": "invoice", "key": r["key"], "label": f"Invoice {r.get('number')} ({r.get('party')})", "field": "place_of_supply", "value": v, "before": "",
                        "why": f"the customer's place of contact is {v}" if r.get("customer_place") else "the customer's GSTIN is registered there" if v else "type it in"})
    return out


SIGNATURES = [
    w3.Signature(r"Ledger '([^']+)' does not exist", "the vouchers name a ledger the company does not have, so Tally refuses the whole voucher",
                 "Create the ledger under its group (a tax ledger under Duties & Taxes), then import the vouchers again.", propose=propose_ledger, route="change", kinds=("tally",)),
    w3.Signature(r"Place of supply is mandatory|without a place of supply", "the invoices have no place of supply, which GST requires for a B2B supply",
                 "Set the place of supply (the customer's state), then prepare GSTR-1 again.", propose=propose_pos, route="change", kinds=("zoho_books",)),
    w3.Signature(r"INVALID SUPPLIER SITE", "invoices carry a supplier site the supplier does not have", "Correct the site to the supplier's own, then import again.", route="change"),
    w3.Signature(r"Stale Object Error|5010", "someone changed the record between the read and the update (SyncToken)", "Read the record again and repeat the change on the new SyncToken.", route="ticket"),
]


def gst_monitor(ctx, seen) -> list[dict]:
    """Run > Watch: GSTR-1 readiness of each Zoho Books organisation, and the B2B file of the period from what passes."""
    rows = []
    for c, a in w3.systems(ctx, ("zoho_books",)):
        inv = seen.records(c, a, "invoice")
        period = max((r["date"] for r in inv if r.get("date")), default="")[:7]
        cur = [r for r in inv if (r.get("date") or "")[:7] == period]
        gap = [r for r in inv if not r.get("place_of_supply")]          # any invoice still without one (an earlier period needs an amendment)
        good = [r for r in cur if r.get("place_of_supply") and r.get("gstin")]
        b2b: dict[str, list] = {}
        for r in good:
            txval = round((w3.num(r.get("amount")) or 0) - (w3.num(r.get("tax")) or 0), 2)
            rt = min(GST_RATES, key=lambda g: abs(((w3.num(r.get("tax")) or 0) / txval * 100 if txval else 0) - g))
            pos = fa.GST_STATE.get(r["place_of_supply"], r["place_of_supply"])
            inter = fa.state_of_gstin(r.get("gstin")) != r["place_of_supply"]
            tax = w3.num(r.get("tax")) or 0
            b2b.setdefault(r["gstin"], []).append({"inum": r.get("number"), "idt": "-".join(reversed((r.get("date") or "").split("-"))), "val": w3.num(r.get("amount")), "pos": pos, "rchrg": "N",
                                                   "inv_typ": "R", "itms": [{"num": 1, "itm_det": {"txval": txval, "rt": rt, **({"iamt": tax} if inter else {"camt": round(tax / 2, 2), "samt": round(tax - round(tax / 2, 2), 2)})}}]})
        if period:
            fp = period[5:7] + period[:4]
            ctx.output(f"gstr1-{fp}-{w3.slug(c['name'])}.json", json.dumps({"fp": fp, "b2b": [{"ctin": k, "inv": v} for k, v in b2b.items()]}, indent=1),
                       label=f"GSTR-1 B2B for {period} - {c['name']} (to file on the portal)")
        row = {"name": f"gstr1:{c['id']}", "label": f"GSTR-1 for {period or 'the period'} - {c['name']}", "status": "fail" if gap else "pass", "measured": f"{len(gap)} without a place of supply",
               "expected": "0", "detail": f"{len(good)} B2B invoice(s) ready in the file" + (f"; {len(gap)} held back: {', '.join(str(r.get('number')) for r in gap[:6])}" if gap else "")}
        if gap:
            row["break"] = {"conn": c["id"], "system": c["name"], "job": "gstr1", "label": f"GSTR-1 for {period}", "status": "failed", "streak": 1,
                            "error": f"Place of supply is mandatory: {len(gap)} invoice(s) without a place of supply ({', '.join(str(r.get('number')) for r in gap[:6])})",
                            "cause": "invoices without a place of supply cannot go into GSTR-1", "fix": "set the place of supply from the customer's state (a Change item proposes it)", "route": "change"}
        rows.append(row)
    return rows


SPEC = w3.Spec(
    module=MODULE, noun="books", system="Relay finance", entities=("account", "customer", "invoice", "supplier", "voucher"),
    rules=[rule_trial_balance, w3.rule_failing_jobs, rule_gstr1, w3.rule_duplicates("customer"), w3.rule_tax_ids("customer"), rule_open_port],
    signatures=SIGNATURES, minutes={"unbalanced_tb": 240, "no_place_of_supply": 10, "odd_gst_rate": 15, "open_port": 60},
    upload_entities={"import-log": "jobs", "import_log": "jobs", ".imp": "jobs", "trial_balance": "account", "trial-balance": "account", "ledger": "account", "chart": "account", "coa": "account",
                     "daybook": "voucher", "invoice": "invoice", "debtor": "customer", "customer": "customer"},
    inventory_extra=import_log, monitors=[gst_monitor], measures={})


# ------------------------------------------------------------------ the ledger mapping (Develop) and the opening balances (Migrate)

def _target(ctx) -> tuple[dict, w3.SysAdapter]:
    tid = ctx.scope.get("target") or ""
    if not tid:
        raise wb.StepFailed("Pick the books to map into (Target).")
    c = ctx.connection(tid)
    a = w3.adapter_of(c)
    if not a or "account" not in a.CREATES:
        raise wb.StepFailed(f"{c['name']} is not a ledger Relay creates accounts in.")
    return c, a


def _sources(ctx, tc) -> tuple[str, list[dict]]:
    """The source ledgers with their debits and credits: a connected book, else an uploaded trial balance."""
    for c, a in w3.systems(ctx):
        if c["id"] != tc["id"] and "account" in a.ENTITIES:
            return c["name"], ctx.seen.records(c, a, "account")
    for f in ctx.files(w3.UPLOADS):
        ent, recs, _ = w3.from_upload(ctx, SPEC, f)
        if ent == "account":
            return f["name"], recs
    raise wb.StepFailed("Nothing to map: connect the source books (Tally ...) or upload their trial balance (ledger, group, debit, credit).")


def suggest(ledger: dict, chart: dict[str, dict]) -> tuple[str, str]:
    """(target account, why) for one source ledger: the same name, a tax ledger by its tax, its group's rule - or ''."""
    n = w3.norm_name(ledger["name"])
    hit = next((t for t in chart if w3.norm_name(t) == n), None)
    if hit:
        return hit, "the same name in the target"
    m = re.search(r"\b(output|input)\b.*?\b(cgst|sgst|igst|utgst)\b", ledger["name"], re.I)
    if m:
        want = f"{m.group(1).title()} {m.group(2).upper()}"
        if want in chart:
            return want, f"a {m.group(2).upper()} ledger maps to {want}"
        return f"+{want}", f"no {want} in the target yet: create it"
    rule = GROUP_RULE.get(ledger.get("group") or "")
    if rule and rule[0] in chart:
        return rule[0], f"{ledger.get('group')} roll into {rule[0]}"
    if ledger.get("group") == "Bank Accounts":
        return f"+{ledger['name']}", "a bank ledger becomes a bank account of the same name"
    return "", ""


def _new_type(name: str, ledger: dict) -> str:
    if ledger.get("group") == "Bank Accounts":
        return "bank"
    if re.search(r"\boutput\b", name, re.I):
        return "other_current_liability"
    if re.search(r"\binput\b", name, re.I):
        return "other_current_asset"
    return (GROUP_RULE.get(ledger.get("group") or "") or ("", "other_current_liability"))[1]


def _options(ctx):
    chart = (ctx.get("ledgers") or {}).get("chart") or []
    new = sorted({r["target"] for r in ctx.records("map") if str(r.get("target") or "").startswith("+")} | set((ctx.get("ledgers") or {}).get("creates") or []))
    return [("", "- not mapped -")] + [(n, n) for n in chart] + [(n, f"Create: {n[1:]}") for n in new]


def discover(ctx):
    tc, ta = _target(ctx)
    src, ledgers = _sources(ctx, tc)
    chart = {r["name"]: r for r in ctx.seen.records(tc, ta, "account")}
    w3.snap(ctx, "source-tb", [{k: r.get(k) for k in ("key", "name", "group", "type", "debit", "credit", "balance")} for r in ledgers], ["key", "name", "group", "type", "debit", "credit", "balance"])
    creates = sorted({suggest(r, chart)[0] for r in ledgers if suggest(r, chart)[0].startswith("+")})
    ctx.put("ledgers", {"source": src, "target": tc["id"], "chart": sorted(chart), "types": {n: r.get("type") for n, r in chart.items()}, "creates": creates})
    w3.keep(ctx, "ledgers", ledgers)
    dr = round(sum(float(r.get("debit") or 0) for r in ledgers), 2)
    cr = round(sum(float(r.get("credit") or 0) for r in ledgers), 2)
    s_node = ctx.lineage_node("system", "books", src, label=f"{src} (source books)", own=False)
    t_node = ctx.lineage_node("system", ta.label, tc["name"], label=f"{tc['name']} ({ta.label})", own=False)
    ctx.lineage_edge(s_node, t_node, "feeds", {"ledgers": len(ledgers), "work_item": ctx.id})
    return {"summary": f"{len(ledgers)} ledger(s) in {src} (debits {dr:,.2f}, credits {cr:,.2f}); {tc['name']} has {len(chart)} account(s) in its chart.",
            "counts": {"ledgers": len(ledgers), "target accounts": len(chart)},
            "data": {"columns": ["Ledger", "Group", "Debit", "Credit"], "rows": [[r["name"], r.get("group"), r.get("debit"), r.get("credit")] for r in ledgers]}}


def map_step(ctx):
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    lg = ctx.get("ledgers") or {}
    chart = {n: {"type": t} for n, t in (lg.get("types") or {}).items()}
    recs = []
    for r in w3.kept(ctx, "ledgers") or []:
        t, why = suggest(r, chart)
        base = {"id": r["name"], "ledger": r["name"], "group": r.get("group"), "debit": r.get("debit"), "credit": r.get("credit"), "target": t, "why": why or "no rule fits: pick the account"}
        recs.append({**base, **({"target": have[r["name"]]["target"]} if r["name"] in have else {})})
    mapped = sum(1 for r in recs if r["target"])
    return {"summary": f"{mapped} of {len(recs)} ledger(s) mapped by rule - the same name, a tax ledger by its tax, its group's rule; correct any, then confirm the mapping.",
            "records": recs, "counts": {"mapped": mapped, "ledgers": len(recs)},
            "data": {"pairs": [{"from": f"{r['ledger']} ({r['group']})", "to": (r["target"][1:] + " (new)") if str(r["target"]).startswith("+") else (r["target"] or "-"), "rule": r["why"],
                                "status": "mapped" if r["target"] else "missing"} for r in recs]},
            "items": [f"{r['ledger']} {r['target'] or '-'}" for r in recs[:8]]}


def validate_map(recs, ctx):
    out = [f"{r['ledger']}: it carries {float(r.get('debit') or 0) - float(r.get('credit') or 0):,.2f} - map it to an account" for r in recs
           if not r.get("target") and (float(r.get("debit") or 0) or float(r.get("credit") or 0))]
    types = (ctx.get("ledgers") or {}).get("types") or {}
    for r in recs:
        t = str(r.get("target") or "")
        src_type = fa.TALLY_TYPE.get(r.get("group") or "", "")
        tt = types.get(t) if not t.startswith("+") else _new_type(t[1:], r)
        if t and src_type and tt and tt not in TYPE_FITS.get(src_type, {tt}):
            out.append(f"{r['ledger']} ({r['group']}, {src_type}) cannot roll into {t.lstrip('+')} ({tt})")
    return out


def _mapped_tb(ctx, recs) -> list[dict]:
    by: dict[str, dict] = {}
    for r in recs:
        t = str(r.get("target") or "").lstrip("+")
        if not t:
            continue
        a = by.setdefault(t, {"account": t, "debit": 0.0, "credit": 0.0})
        a["debit"] = round(a["debit"] + float(r.get("debit") or 0), 2)
        a["credit"] = round(a["credit"] + float(r.get("credit") or 0), 2)
        a["balance"] = round(a["debit"] - a["credit"], 2)
    return list(by.values())


def build(ctx):
    recs = ctx.records("map")
    probs = validate_map(recs, ctx)
    if probs:
        raise wb.StepFailed("The confirmed mapping has problems: " + "; ".join(probs[:5]))
    creates = sorted({str(r["target"])[1:] for r in recs if str(r.get("target") or "").startswith("+")})
    ledgers = {r["name"]: r for r in w3.kept(ctx, "ledgers") or []}
    new = [{"name": n, "type": _new_type(n, next((ledgers.get(r["ledger"]) or {} for r in recs if str(r.get("target")) == "+" + n), {}))} for n in creates]
    ctx.put("creates", new)
    ctx.output("ledger-mapping.csv", w3._csv([{"ledger": r["ledger"], "group": r["group"], "target_account": str(r["target"]).lstrip("+"), "new": str(r["target"]).startswith("+"),
                                                "debit": r.get("debit"), "credit": r.get("credit"), "rule": r.get("why")} for r in recs]), label="Ledger mapping (CSV)")
    tb = _mapped_tb(ctx, recs)
    w3.snap(ctx, "mapped-tb", tb, ["account", "debit", "credit", "balance"])
    w3.snap(ctx, "source-tb-mapped", [{"ledger": r["ledger"], "account": str(r.get("target") or "").lstrip("+"), "debit": r.get("debit"), "credit": r.get("credit"),
                                       "balance": round(float(r.get("debit") or 0) - float(r.get("credit") or 0), 2)} for r in recs], ["ledger", "account", "debit", "credit", "balance"])
    return {"summary": f"The mapping of {len(recs)} ledger(s) onto {len(tb)} target account(s); {len(new)} account(s) to create in the target.",
            "counts": {"ledgers": len(recs), "target accounts": len(tb), "to create": len(new)},
            "data": {"columns": ["Target account", "Debit", "Credit"], "rows": [[t["account"], t["debit"], t["credit"]] for t in tb]}}


def tb_proofs(ctx, src_file: str, tgt_file: str, label_: str, measures: tuple = ("balance",)) -> list[dict]:
    S, T = {"source": "file", "file": src_file}, {"source": "file", "file": tgt_file}
    return [ctx.proof("w3_trial_balance", label=f"{label_}: the source trial balance balances", file=src_file),
            ctx.proof("w3_trial_balance", label=f"{label_}: the target side balances", file=tgt_file),
            ctx.proof("totals", label=f"{label_}: each target account's {' and '.join(measures)} agree", source=S, target=T, measures=list(measures), by="account", tolerance_pct=0.0)]


def prove(ctx):
    recs = ctx.records("map")
    moving = [r["ledger"] for r in recs if float(r.get("debit") or 0) or float(r.get("credit") or 0)]
    checks = [ctx.proof("references_real", label="Every ledger with a balance is mapped", refs=moving, known=[r["ledger"] for r in recs if r.get("target")])]
    checks += tb_proofs(ctx, "source-tb-mapped.csv", "mapped-tb.csv", "Trial balance", ("debit", "credit", "balance"))
    probs = validate_map(recs, ctx)
    checks.append({"name": "types", "label": "Every ledger rolls into an account of a type that fits", "status": "fail" if probs else "pass", "detail": "; ".join(probs[:4]) or "debtors to receivables, taxes to liabilities ...",
                   "measured": len(probs), "expected": 0})
    bad = sum(1 for c in checks if c["status"] == "fail")
    return {"summary": f"The trial-balance proof of the mapping: {len(checks) - bad} of {len(checks)} pass.", "data": {"checks": checks}, "counts": {"pass": len(checks) - bad, "fail": bad}}


def ship(ctx):
    new = ctx.get("creates") or []
    tc = ctx.connection((ctx.get("ledgers") or {})["target"])
    approver = db.user(ctx.st.get("approver") or "") or {}
    return {"summary": f"Go live: the mapping, and {len(new)} new account(s) in {tc['name']}.",
            "data": {"items": [{"title": "New accounts", "detail": ", ".join(f"{n['name']} ({n['type']})" for n in new) or "none - every target account exists"},
                               {"title": "The mapping", "detail": "ledger-mapping.csv - the interface and the migrations use it"},
                               {"title": "Then", "detail": "The accounts are created through one write a named person approves; Relay reads the chart back."},
                               {"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"}]}}


def run(ctx):
    new = ctx.get("creates") or []
    tc = ctx.connection((ctx.get("ledgers") or {})["target"])
    ta = w3.adapter_of(tc)
    if not new:
        return {"summary": "Every target account exists: nothing to create.", "data": {"checks": [{"name": "write", "label": "No write was needed", "status": "pass", "detail": "the chart already holds every account"}]}}
    w3.keep(ctx, f"load-{ctx.step_id}", {"conn": tc["id"], "entities": {"account": [{"ref": n["name"], "name": n["name"], "type": n["type"]} for n in new]}, "compare": {"account": ["name", "type"]}})
    cp = w3.request_write(ctx, tc, "chartofaccounts", [{"op": "create", "entity": "account", "ref": n["name"], "data": ta.payload("account", {"name": n["name"], "type": n["type"]})} for n in new],
                          f"Create {len(new)} account(s) in {tc['name']}", [f"{n['name']} ({n['type']})" for n in new])
    return {"summary": f"{len(new)} new account(s) wait for the write approval; once written, Relay reads {tc['name']}'s chart back.", "counts": {"to create": len(new)},
            "data": {"checks": [w3.pending(cp, tc, len(new))]}}


# ---- Migrate: opening balances

def m_discover(ctx):
    out = discover(ctx)
    lg = ctx.get("ledgers")
    ctx.put("migrate", {"target": lg["target"]})
    return out


def m_decide(ctx):
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    ledgers = w3.kept(ctx, "ledgers") or []
    recs, dup_of = [], {}
    for g in w3.dupes(ledgers):
        g = sorted(g, key=lambda r: -abs(float(r.get("debit") or 0) - float(r.get("credit") or 0)))
        for o in g[1:]:
            dup_of[o["name"]] = g[0]["name"]
    for r in ledgers:
        bal = round(float(r.get("debit") or 0) - float(r.get("credit") or 0), 2)
        if r["name"] in dup_of:
            d, why = "merge", f"the same as {dup_of[r['name']]}"
        elif not bal:
            d, why = "retire", "no balance to carry"
        else:
            d, why = "keep", f"carries {bal:,.2f}"
        base = {"id": r["name"], "ledger": r["name"], "group": r.get("group"), "balance": bal, "decision": d, "into": dup_of.get(r["name"], ""), "reason": why}
        recs.append({**base, **({"decision": have[r["name"]]["decision"]} if r["name"] in have else {})})
    n = Counter(r["decision"] for r in recs)
    return {"summary": f"Keep {n['keep']}, merge {n['merge']}, retire {n['retire']} ledger(s) - rules first: a zero balance needs no opening line, duplicates merge into the one that carries more.",
            "records": recs, "counts": dict(n), "data": {"columns": ["Ledger", "Group", "Balance", "Decision", "Why"], "rows": [[r["ledger"], r["group"], r["balance"], r["decision"], r["reason"]] for r in recs]}}


def m_convert(ctx):
    lg = ctx.get("ledgers") or {}
    chart = {n: {"type": t} for n, t in (lg.get("types") or {}).items()}
    dec = {r["id"]: r for r in ctx.records("decide")}
    mapping = {}
    src = ctx.scope.get("from_item")
    if src:                                              # a Develop item's confirmed ledger mapping wins over the rules
        try:
            prev = wb._load(src)
            mapping = {r["ledger"]: r["target"] for s in prev["steps"] if s["id"] == "map" for r in s.get("records") or [] if r.get("target")}
        except (KeyError, FileNotFoundError):
            mapping = {}
    lines, kept_rows, cross, unmapped = {}, [], [], []
    by_name = {r["name"]: r for r in w3.kept(ctx, "ledgers") or []}
    for r in w3.kept(ctx, "ledgers") or []:
        d = (dec.get(r["name"]) or {}).get("decision", "keep")
        into = (dec.get(r["name"]) or {}).get("into") or ""
        led = by_name.get(into) if d == "merge" and into in by_name else r
        tgt = mapping.get(led["name"]) or suggest(led, chart)[0]
        if d == "retire":
            cross.append({"ledger": r["name"], "decision": "retire", "account": "", "debit": r.get("debit"), "credit": r.get("credit")})
            continue
        if not tgt:
            unmapped.append(r["name"])
            continue
        acc = str(tgt).lstrip("+")
        bal = round(float(r.get("debit") or 0) - float(r.get("credit") or 0), 2)
        ln = lines.setdefault(acc, {"account": acc, "debit": 0.0, "credit": 0.0, "new": str(tgt).startswith("+"), "type": _new_type(acc, led)})
        if bal > 0:
            ln["debit"] = round(ln["debit"] + bal, 2)
        else:
            ln["credit"] = round(ln["credit"] - bal, 2)
        kept_rows.append({"ledger": r["name"], "account": acc, "debit": bal if bal > 0 else 0.0, "credit": -bal if bal < 0 else 0.0, "balance": bal})
        cross.append({"ledger": r["name"], "decision": d, "account": acc, "debit": r.get("debit"), "credit": r.get("credit")})
    if unmapped:
        raise wb.StepFailed(f"{len(unmapped)} ledger(s) with a balance have no target account: {', '.join(unmapped[:6])}. Map them (a Develop item's mapping, or Decide > retire).")
    for ln in lines.values():                            # an account's opening is its net balance on one side
        net = round(ln["debit"] - ln["credit"], 2)
        ln["debit"], ln["credit"] = (net, 0.0) if net > 0 else (0.0, -net)
    journal = [ln for ln in lines.values() if ln["debit"] or ln["credit"]]
    w3.snap(ctx, "opening-source", kept_rows, ["ledger", "account", "debit", "credit", "balance"])
    w3.snap(ctx, "opening-journal", [{"account": ln["account"], "debit": ln["debit"], "credit": ln["credit"], "balance": round(ln["debit"] - ln["credit"], 2)} for ln in journal],
            ["account", "debit", "credit", "balance"])
    w3.keep(ctx, "journal", {"lines": journal, "creates": [{"name": ln["account"], "type": ln["type"]} for ln in lines.values() if ln["new"]]})
    ctx.output("crosswalk.csv", w3._csv(cross), label="Crosswalk: every source ledger and where its balance goes (CSV)")
    ctx.output("opening-journal.json", json.dumps({"lines": journal}, indent=1), label="The opening-balance journal (JSON)")
    dr, cr = round(sum(x["debit"] for x in journal), 2), round(sum(x["credit"] for x in journal), 2)
    return {"summary": f"One opening journal of {len(journal)} line(s) (debits {dr:,.2f}, credits {cr:,.2f}) on the mapped accounts; the crosswalk accounts for every ledger.",
            "counts": {"lines": len(journal), "ledgers": len(cross)}, "data": {"columns": ["Account", "Debit", "Credit", "New"], "rows": [[x["account"], x["debit"], x["credit"], "yes" if x["new"] else ""] for x in journal]}}


def m_prove(ctx):
    ledgers = w3.kept(ctx, "ledgers") or []
    xw = ctx.dir / "outputs" / "crosswalk.csv"
    checks = [ctx.proof("references_real", label="Every source ledger is accounted for (carried, merged or retired)", refs=[r["name"] for r in ledgers],
                        known=[r["ledger"] for r in w3.read_csv(xw)] if xw.exists() else [])]
    checks += tb_proofs(ctx, "opening-source.csv", "opening-journal.csv", "Opening balances")
    bad = sum(1 for c in checks if c["status"] == "fail")
    return {"summary": f"The trial-balance proof of the opening journal, old and new side by side: {len(checks) - bad} of {len(checks)} pass.", "data": {"checks": checks}, "counts": {"pass": len(checks) - bad, "fail": bad}}


def m_handover(ctx):
    j = w3.kept(ctx, "journal") or {}
    tc = ctx.connection((ctx.get("migrate") or {})["target"])
    approver = db.user(ctx.st.get("approver") or "") or {}
    return {"summary": f"Sign-off: {len(j.get('creates') or [])} new account(s) and one opening journal of {len(j.get('lines') or [])} line(s) into {tc['name']}.",
            "data": {"items": [{"title": "Opening journal", "detail": f"{len(j.get('lines') or [])} line(s), balanced (see Prove)"}, {"title": "New accounts", "detail": ", ".join(x["name"] for x in j.get("creates") or []) or "none"},
                               {"title": "Then", "detail": "One write a named person approves; Relay reads the target's journals back and proves the trial balance again."},
                               {"title": "Owner sign-off", "detail": approver.get("name") or "the owner of this work item"}]}}


def m_run(ctx):
    j = w3.kept(ctx, "journal") or {}
    tc = ctx.connection((ctx.get("migrate") or {})["target"])
    ta = w3.adapter_of(tc)
    ref = f"Relay opening {ctx.id[-4:]}"
    ops = [{"op": "create", "entity": "account", "ref": x["name"], "data": ta.payload("account", x)} for x in j.get("creates") or []]
    ops.append({"op": "create", "entity": "journal", "ref": ref, "data": {"date": ctx.scope.get("as_of") or wb.dt.date.today().isoformat(), "reference": ref, "notes": f"Opening balances from {(ctx.get('ledgers') or {}).get('source')}",
                                                                          "lines": j.get("lines") or []}})
    ctx.put("journal_ref", ref)
    cp = w3.request_write(ctx, tc, "journals", ops, f"Load the opening balances into {tc['name']}", [f"{len(j.get('creates') or [])} new account(s)", f"one journal of {len(j.get('lines') or [])} line(s): {ref}"])
    return {"summary": f"The opening balances wait for their approval in the Validation queue; once written, Relay reads {tc['name']}'s journals back and proves the trial balance again.",
            "counts": {"lines": len(j.get("lines") or [])}, "data": {"checks": [w3.pending(cp, tc, len(ops))]}}


@w3.stepfn
def m_verify(ctx):
    hs = w3.writes(ctx, ctx.step_id)
    if not hs or hs[-1].get("status") != "written":
        return {"summary": "The load is not written yet - approve it in the Validation queue first.", "data": {"checks": []}}
    tc = ctx.connection((ctx.get("migrate") or {})["target"])
    ta = w3.adapter_of(tc)
    ref = ctx.get("journal_ref")
    lines = [r for r in ctx.seen.records(tc, ta, "voucher") if r.get("reference") == ref]
    tb = w3_tb(lines)
    w3.snap(ctx, "landed-journal", tb, ["account", "debit", "credit", "balance"])
    checks = tb_proofs(ctx, "opening-source.csv", "landed-journal.csv", "Read back from the target")
    good = all(c["status"] == "pass" for c in checks)
    return {"summary": (f"Read back from {tc['name']}: the journal {ref} is there and the trial balance agrees account by account." if good else f"Read back from {tc['name']}: the trial balance disagrees - see the checks."),
            "data": {"checks": checks}, "counts": {"lines": len(lines)}}


def w3_tb(lines: list[dict]) -> list[dict]:
    by: dict[str, dict] = {}
    for ln in lines:
        a = by.setdefault(ln["account"], {"account": ln["account"], "debit": 0.0, "credit": 0.0})
        a["debit"] = round(a["debit"] + float(ln.get("debit") or 0), 2)
        a["credit"] = round(a["credit"] + float(ln.get("credit") or 0), 2)
        a["balance"] = round(a["debit"] - a["credit"], 2)
    return list(by.values())


@w3.stepfn
def d_verify(ctx):
    hs = w3.writes(ctx, ctx.step_id)
    if not hs or hs[-1].get("status") != "written":
        return {"summary": "The accounts are not created yet - approve the write in the Validation queue first.", "data": {"checks": []}}
    tc = ctx.connection((ctx.get("ledgers") or {})["target"])
    ta = w3.adapter_of(tc)
    chart = [r["name"] for r in ctx.seen.records(tc, ta, "account")]
    targets = sorted({str(r["target"]).lstrip("+") for r in ctx.records("map") if r.get("target")})
    checks = [ctx.proof("references_real", label="Every account the mapping uses is in the target's chart now", refs=targets, known=chart)]
    return {"summary": f"Read back from {tc['name']}: " + ("every mapped account exists." if checks[0]["status"] == "pass" else "some mapped accounts are missing."), "data": {"checks": checks}}


def _targets_opt(u):
    out = [("", "Pick the books to map into")]
    for c in connectors.mine(u["id"]):
        a = w3.adapter_of({"kind": c["kind"]})
        if a and "account" in a.CREATES:
            out.append((c["id"], f"{c['name']} - {c['label']}"))
    return out


def _develop_items(u):
    rows = db.q("SELECT id, title FROM wb_items WHERE module = ? AND work = 'develop' AND status = 'done' ORDER BY updated DESC LIMIT 50", (MODULE,))
    from .. import auth
    vis = auth.access_map(u, [r["id"] for r in rows])
    return [("", "No - by the mapping rules")] + [(r["id"], r["title"]) for r in rows if r["id"] in vis]


PLATFORMS = {
    "tally": w3.SysPlatform("TallyPrime", ("tally",), "tests/mocklab/sims: tally (XML over HTTP)", "ledgers with their movements, the Day Book and party ledgers through the XML port; the import log (tally.imp, as tally-import-log.txt) as an upload",
                            uploads=(".txt", ".csv", ".xlsx")),
    "zoho": w3.SysPlatform("Zoho Books", ("zoho_books",), "tests/mocklab/sims: zoho_books (API v3)", "the chart of accounts, journals, customers and invoices of the organisation"),
    "fusion": w3.SysPlatform("Oracle Fusion Cloud Financials", ("oracle_fusion",), "tests/mocklab/sims: oracle_fusion", "suppliers, Payables invoices and scheduled processes (ESS)"),
    "quickbooks": w3.SysPlatform("QuickBooks Online", ("quickbooks",), "tests/mocklab/sims: quickbooks", "customers and invoices (query language)"),
    "xero": w3.SysPlatform("Xero", ("xero",), "tests/mocklab/sims: xero", "contacts and invoices"),
    "exports": w3.SysPlatform("Busy, ClearTax and the GST / TRACES / MCA portals (exports)", (), "export fixtures the tests write", "trial balances, day books and returns you upload (CSV, Excel)",
                              uploads=(".csv", ".xlsx", ".json")),
}

GUIDE = """# Finance & accounting - the work item

Relay's Finance & accounting module maps ledgers between books, moves opening balances with a trial-balance proof and
prepares GST returns. Rules do the mapping, the checks and the proofs; nothing is filed or posted without a named
person's approval. `data/` holds the uploads and Relay's read-only snapshots (source-tb.csv, mapped-tb.csv ...);
`outputs/` the mapping, the journal and the GSTR-1 file. Never invent a ledger, an amount or a GSTIN."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each set of books read (system), the ledger mapping and the opening balances as feeds edges from the source books to the target's",
    schemas={"mapping": ["ledger", "group", "target", "why"], "decision": ["ledger", "decision", "reason"]},
    work={
        "assess": w3.assess_work(SPEC, "See what the books hold - the trial balance, the imports that fail, what GSTR-1 would refuse"),
        "develop": wb.Work(title="Map the chart of accounts: each source ledger onto the target's, proven on the trial balance", needs_source=True,
                           fields=[wb.Field("target", "Map into", "select", options=_targets_opt, required=True, help="The books whose chart the ledgers map onto (its scope must allow writes for new accounts).")],
                           steps={
            "Discover": wb.Step(kind="platform", run=w3.stepfn(discover), agent="Ledger reader", text="The source ledgers with their debits and credits, and the target's chart of accounts - read-only"),
            "Map": wb.Step(kind="deterministic", run=map_step, view="mapping", agent="Mapper", confirm="the ledger mapping, side by side with each ledger's group and balance",
                           edit=wb.Edit(columns=[wb.Column("ledger", "Ledger", readonly=True), wb.Column("group", "Group", readonly=True), wb.Column("target", "Target account", "select", options=_options),
                                                 wb.Column("why", "Why", readonly=True)], add=False, remove=False, validate=validate_map, label="ledger"),
                           text="Each ledger onto the target's chart - the same name, a tax ledger by its tax, its group's rule - you correct it in place"),
            "Build": wb.Step(kind="deterministic", run=build, agent="Mapper", text="The mapping file, the mapped trial balance and the accounts the target still needs"),
            "Prove": wb.Step(kind="proof", run=prove, view="gates", agent="Prover", back_to="map", text="The trial-balance proof: every ledger with a balance mapped, debits equal credits, the mapped totals equal the source's, types that fit"),
            "Ship": wb.Step(kind="person", run=ship, view="plan", approver=True, text="The named approver confirms the mapping and the new accounts"),
            "Run": wb.Step(kind="platform", run=run, view="gates", agent="Loader", text="The new accounts through one approved write; Relay reads the chart back",
                           actions={"verify": wb.Action(label="Read the chart back", kind="platform", run=d_verify, agent="Reconciler", help="Checks every mapped account exists in the target now.")})}),
        "change": w3.change_work(SPEC, "Fix a failing import or the invoices GSTR-1 refuses, released with approval and checked on the books"),
        "migrate": wb.Work(title="Move opening balances between ledgers, proven on the trial balance before and after the load", needs_source=True,
                           fields=[wb.Field("target", "Move into", "select", options=_targets_opt, required=True), wb.Field("from_item", "Use the mapping of", "select", options=_develop_items),
                                   wb.Field("as_of", "Opening balances as of (YYYY-MM-DD)", "text", help="The journal date in the target (blank: today).")], steps={
            "Discover": wb.Step(kind="platform", run=w3.stepfn(m_discover), agent="Ledger reader", text="The source trial balance and the target's chart - read-only"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Decider", edit=wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("merge", "Merge"), ("retire", "Retire"))),
                                                                                             wb.Column("ledger", "Ledger", readonly=True), wb.Column("reason", "Why", readonly=True)], add=False, remove=False, label="ledger"),
                              text="Keep, merge or retire each ledger with the reason - a zero balance needs no opening line"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Converter", text="One balanced opening journal on the mapped accounts, and a crosswalk for every ledger"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Prover", back_to="decide", text="The trial-balance proof, old and new side by side: every ledger accounted for, both sides balance, every account's totals agree"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The owner signs off the opening balances"),
            "Run": wb.Step(kind="platform", run=m_run, view="gates", agent="Loader", text="One approved write; Relay reads the target's journals back and proves the trial balance again",
                           actions={"verify": wb.Action(label="Read back and prove the trial balance", kind="platform", run=m_verify, agent="Reconciler", help="Reads the journal back from the target.")})}),
        "run": w3.run_work(SPEC, "Watch the imports and the GST checks; prepare GSTR-1; breaks go to a person first"),
    }))
