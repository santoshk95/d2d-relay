"""D2D Relay: GST tax invoices for credits bought online (item 25; the user, 2026-11-11: "GST invoice is required, no
refunds, dollar sales as per govt").

Every payment that adds credits gets a tax invoice (CGST Rules 2017, rule 46), numbered in one series per financial
year (April to March, India time): <prefix>/<yy-yy>/<5 digits>, at most 16 characters, consecutive and never reused. The
number is taken in the same database transaction that marks the payment paid (relay.tn_invoice_seq), so a number is
never lost or given twice. Payments made with test keys use their own series (TEST/...) and are marked as test
invoices, so the real series starts clean. An invoice is a snapshot of what was true when it was issued (the payment's
`invoice`, JSON): seller, buyer, place of supply, amounts and tax; later changes to the settings do not alter it.

Seller: PASDACS's legal name, address, state, PIN, GSTIN, the SAC code of the service, the invoice prefix, the
description, and the ARN of the Letter of Undertaking for exports (admin portal, Payments, Tax invoices). With live keys
selling stays shut until they are filled in (missing() is empty) and a GST rate is set.

Buyer: the organisation's billing details (relay.tn_orgs.billing): its legal name and address; in India the state and
PIN, or a GSTIN (which gives the state); outside India the country. Asked for once, before the first purchase; the
owners change them on the Organisation page. Each checkout keeps the details it was made with (tn_payments.billing).

Tax, at the GST rate set on the admin portal (18% for these services):
  - rupees, buyer in India: CGST and SGST (UTGST in a union territory without a legislature) when the buyer's state is
    the seller's, else IGST; rupee prices either include GST or have it added (the admin portal says which);
  - rupees, buyer outside India: IGST (a supplier in India, the place of supply outside it: an inter-State supply);
  - US dollars, buyer outside India: an export of services, zero-rated. Under a Letter of Undertaking (its ARN set):
    without IGST. Without one: on payment of IGST, included in the dollar price (PASDACS may claim it back). The rupee
    value is the one Razorpay converted at (the payment's base_amount).
The place of supply of an online service is where the buyer is (its billing address). Whether the SAC code, the rate and
the treatment of exports fit PASDACS is for its accountant to confirm; all of them are settings.

No refunds (the user's rule): credits bought are not refundable; the invoice and Buy credits say so.
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
from datetime import datetime, timedelta, timezone

from . import db

IST = timezone(timedelta(hours=5, minutes=30))
# GST state codes (the first two digits of a GSTIN)
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory"}
UTGST = {"04", "26", "31", "35", "38"}           # union territories without a legislature: UTGST in place of SGST
ABROAD = "96"                                   # GSTR-1's code for a place of supply outside India
GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SELLER = {"name": "", "address": "", "state": "", "pin": "", "gstin": "", "sac": "", "prefix": "D2D", "lut": "",
          "description": "D2D Relay credits"}
NO_REFUNDS = "Credits are not refundable."


class Invalid(ValueError):
    """Shown to the person as it is."""


def gstin_ok(g: str) -> bool:
    """A GSTIN in the right shape, of a known state, with the right check character (mod 36)."""
    g = (g or "").strip().upper()
    if not GSTIN.match(g) or g[:2] not in STATES:
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        v = _B36.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _B36[(36 - total % 36) % 36] == g[14]


def fiscal_year(ts: float) -> str:
    """India's financial year (April to March) of a moment, as '26-27'."""
    d = datetime.fromtimestamp(ts, IST)
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y % 100:02d}-{(y + 1) % 100:02d}"


def india(country: str | None) -> bool:
    return (country or "").strip().lower() in ("india", "in", "bharat")


# ---------------------------------------------------------------- the buyer's billing details

def clean_billing(b: dict) -> dict:
    """The billing details as kept, or Invalid with what to fix."""
    name = " ".join(str(b.get("name") or "").split())[:120]
    address = "\n".join(" ".join(x.split()) for x in str(b.get("address") or "").splitlines() if x.strip())[:300]
    country = " ".join(str(b.get("country") or "").split())[:60]
    gstin = re.sub(r"\s", "", str(b.get("gstin") or "")).upper()
    pin = re.sub(r"\s", "", str(b.get("pin") or ""))[:12]
    if len(name) < 2:
        raise Invalid("Give the organisation's legal name, as it should appear on invoices.")
    if len(address) < 5:
        raise Invalid("Give the billing address.")
    if india(country):
        state = str(b.get("state") or "").strip()
        if gstin:
            if not gstin_ok(gstin):
                raise Invalid("That GSTIN is not valid: check it (15 characters, as on the GST certificate).")
            state = gstin[:2]
        if state not in STATES:
            raise Invalid("Choose the state (it decides CGST and SGST or IGST).")
        if not re.fullmatch(r"[1-9][0-9]{5}", pin):
            raise Invalid("Give the 6-digit PIN code.")
        return {"name": name, "address": address, "country": "India", "state": state, "pin": pin, "gstin": gstin}
    if len(country) < 2:
        raise Invalid("Choose India, or give the country.")
    if gstin:
        raise Invalid("A GSTIN is for organisations in India.")
    return {"name": name, "address": address, "country": country, "state": "", "pin": pin, "gstin": ""}


def complete(b: dict | None) -> bool:
    try:
        return bool(b) and clean_billing(b) == b
    except Invalid:
        return False


def where(b: dict | None) -> str:
    """'Karnataka (29)' or the country."""
    b = b or {}
    return f"{STATES.get(b.get('state') or '', '?')} ({b.get('state')})" if india(b.get("country")) else (b.get("country") or "Outside India")


# ---------------------------------------------------------------- the seller (PASDACS)

def seller(s: dict) -> dict:
    return {**SELLER, **{k: v for k, v in (s.get("invoice") or {}).items() if k in SELLER}}


def clean_seller(v: dict) -> dict:
    """The admin portal's Tax invoices card, as kept, or Invalid. Parts may be empty until selling goes live."""
    out = {k: " ".join(str(v.get(k) or "").split()) for k in SELLER if k != "address"}
    out["address"] = "\n".join(" ".join(x.split()) for x in str(v.get("address") or "").splitlines() if x.strip())[:300]
    out["name"], out["description"] = out["name"][:120], (out["description"] or SELLER["description"])[:80]
    out["gstin"], out["prefix"], out["lut"] = out["gstin"].upper().replace(" ", ""), out["prefix"].upper(), out["lut"].upper()[:30]
    if out["gstin"]:
        if not gstin_ok(out["gstin"]):
            raise Invalid("PASDACS's GSTIN is not valid: check it.")
        out["state"] = out["gstin"][:2]
    if out["state"] and out["state"] not in STATES:
        raise Invalid("Choose PASDACS's state.")
    if out["pin"] and not re.fullmatch(r"[1-9][0-9]{5}", out["pin"]):
        raise Invalid("PASDACS's PIN code has 6 digits.")
    if out["sac"] and not re.fullmatch(r"[0-9]{4,8}", out["sac"]):
        raise Invalid("The SAC code is 4 to 8 digits (6 as a rule).")
    if not re.fullmatch(r"[A-Z0-9]{1,4}", out["prefix"]) or out["prefix"] == "TEST":
        raise Invalid("The invoice prefix is 1 to 4 letters or digits (not TEST): invoice numbers may have 16 characters at most.")
    if out["lut"] and not re.fullmatch(r"[A-Z0-9/-]{5,30}", out["lut"]):
        raise Invalid("The LUT's ARN is letters and digits, as the GST portal gave it.")
    return out


def missing(s: dict) -> list[str]:
    """What still has to be filled in before invoices can be issued for real money (empty: ready)."""
    v = seller(s)
    need = [label for key, label in (("name", "legal name"), ("address", "address"), ("state", "state"), ("pin", "PIN code"),
                                     ("gstin", "GSTIN"), ("sac", "SAC code")) if not v.get(key)]
    if not float(s.get("gst") or 0) > 0:
        need.append("GST rate")
    return need


# ---------------------------------------------------------------- issuing

def _share(total: int, part: int, whole: int) -> int:
    """total * part / whole, rounded half up (whole > 0)."""
    return (total * part * 2 + whole) // (whole * 2)


def issue(r: dict, s: dict, now: float, pay: dict) -> dict:
    """The invoice of a payment being marked paid: the next number of its series and the snapshot. Called inside the
    transaction that marks it paid, so the number is taken only if that commits."""
    test = not r.get("live")
    v = seller(s)
    fy = fiscal_year(now)
    series = "TEST" if test else v["prefix"]
    b = r.get("billing") or {}
    if isinstance(b, str):
        b = json.loads(b or "{}")
    buyer_india = india(b.get("country")) if b else r["currency"] == "INR"
    cur, total, rate = r["currency"], int(r["amount"]), float(s.get("gst") or 0)
    inv = {"no": "", "series": series, "fy": fy, "date": now, "test": test,
           "seller": {k: v[k] for k in ("name", "address", "state", "pin", "gstin")} | {"state_name": STATES.get(v["state"], "")},
           "buyer": {k: b.get(k, "") for k in ("name", "address", "country", "state", "pin", "gstin")} | {"state_name": STATES.get(b.get("state") or "", "")},
           "sac": v["sac"], "description": f"{v['description']} ({int(r['credits']):,} credits)", "quantity": int(r["credits"]),
           "currency": cur, "rate": rate, "cgst": 0, "sgst": 0, "igst": 0, "utgst": False, "total": total, "export": None, "inr": None,
           "reverse_charge": False, "notes": [NO_REFUNDS],
           "payment": {"razorpay": pay.get("id"), "order": r.get("order_id"), "method": pay.get("method")}}
    if cur == "INR":
        taxable, tax = int(r["price"]), int(r["gst"])                    # as charged: price before GST and the GST in it
        if buyer_india and b.get("state") and b.get("state") == v["state"]:
            inv["cgst"], inv["sgst"] = (tax + 1) // 2, tax // 2
            inv["utgst"] = v["state"] in UTGST
        else:
            inv["igst"] = tax
        inv["place"] = ((f"{STATES[b['state']]} ({b['state']})" if b.get("state") in STATES else "India") if buyer_india
                        else f"Outside India ({ABROAD})")
    else:                                                               # an export of services, paid in foreign currency
        lut = v["lut"]
        if lut or rate <= 0:
            taxable = total
        else:                                                           # without a LUT: IGST, included in the price
            taxable = _share(total, 100, int(round(100 + rate)))
            inv["igst"] = total - taxable
        inv["place"] = f"Outside India ({ABROAD})"
        inv["export"] = {"lut": lut, "country": b.get("country") or "", "declaration":
                         f"SUPPLY MEANT FOR EXPORT UNDER LETTER OF UNDERTAKING WITHOUT PAYMENT OF INTEGRATED TAX (LUT ARN {lut})" if lut
                         else "SUPPLY MEANT FOR EXPORT ON PAYMENT OF INTEGRATED TAX" if rate > 0 else "SUPPLY MEANT FOR EXPORT"}
        base = int(pay.get("base_amount") or 0) if (pay.get("base_currency") or "INR") == "INR" else 0
        if base:
            inv["inr"] = {"rate": round(base / total, 4), "total": base, "taxable": _share(base, taxable, total),
                          "igst": base - _share(base, taxable, total)}
    inv["taxable"] = taxable
    # the number last, once everything else is worked out: taken only if the payment's transaction commits
    n = db.one("INSERT INTO relay.tn_invoice_seq AS seq (series, fy, last) VALUES (?, ?, 1) "
               "ON CONFLICT (series, fy) DO UPDATE SET last = seq.last + 1 RETURNING last", (series, fy))["last"]
    inv["no"] = f"{series}/{fy}/{n:05d}"
    return inv


# ---------------------------------------------------------------- showing it

def money(minor: int | None, cur: str) -> str:
    v = int(minor or 0)
    if cur == "USD":
        return f"${v // 100:,}.{v % 100:02d}"
    rupees, p = divmod(v, 100)
    s = str(rupees)
    if len(s) > 3:
        head, groups = s[:-3], [s[-3:]]
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups)
    return f"₹{s}.{p:02d}"


def taxes(inv: dict) -> list[tuple[str, int]]:
    """The tax lines: (label, amount) in the invoice's currency."""
    half = inv["rate"] / 2
    if inv["cgst"] or inv["sgst"]:
        return [(f"CGST {half:g}%", inv["cgst"]), (f"{'UTGST' if inv.get('utgst') else 'SGST'} {half:g}%", inv["sgst"])]
    if inv["igst"]:
        return [(f"IGST {inv['rate']:g}%", inv["igst"])]
    return [("IGST 0% (zero-rated export)" if inv.get("export") else "GST", 0)]


def date_of(inv: dict) -> str:
    return datetime.fromtimestamp(inv["date"], IST).strftime("%d %b %Y")


def rows(inv: dict) -> list[tuple[str, str]]:
    """The invoice as label and value rows (the email)."""
    s, b, cur = inv["seller"], inv["buyer"], inv["currency"]
    out = [("Tax invoice" if not inv["test"] else "Test invoice (not a tax invoice)", inv["no"]), ("Date", date_of(inv)),
           ("Supplier", f"{s['name'] or '(not set)'}, GSTIN {s['gstin'] or '(not set)'}"),
           ("Billed to", b["name"] + (f", GSTIN {b['gstin']}" if b.get("gstin") else "")),
           ("Place of supply", inv["place"]), ("Description", f"{inv['description']}, SAC {inv['sac'] or '(not set)'}"),
           ("Taxable value", money(inv["taxable"], cur))]
    out += [(k, money(v, cur)) for k, v in taxes(inv)]
    out.append(("Total", money(inv["total"], cur)))
    if inv.get("inr"):
        out.append(("In rupees", f"{money(inv['inr']['total'], 'INR')} at ₹{inv['inr']['rate']:g} a dollar (Razorpay's rate)"))
    if inv.get("export"):
        out.append(("Export", inv["export"]["declaration"]))
    out.append(("Note", " ".join(inv.get("notes") or [])))
    return out


def page(inv: dict, extra: list[tuple[str, str]] | None = None) -> str:
    """The printable invoice."""
    e = html.escape
    s, b, cur = inv["seller"], inv["buyer"], inv["currency"]
    lines = lambda t: "<br>".join(e(x) for x in (t or "").splitlines())   # noqa: E731
    buyer_place = (f"{e(b.get('state_name') or '')} ({e(b.get('state') or '')})" + (f", PIN {e(b['pin'])}" if b.get("pin") else "")
                   if india(b.get("country")) else e(b.get("country") or "") + (f" {e(b['pin'])}" if b.get("pin") else ""))
    tax_rows = "".join(f"<tr><td colspan=4 class=r>{e(k)}</td><td class=r>{money(v, cur)}</td></tr>" for k, v in taxes(inv))
    inr = inv.get("inr")
    inr_row = (f"<p class=muted>In rupees, at ₹{inr['rate']:g} a US dollar (Razorpay's rate for this payment): taxable value "
               f"{money(inr['taxable'], 'INR')}, IGST {money(inr['igst'], 'INR')}, total {money(inr['total'], 'INR')}.</p>") if inr else ""
    export = f"<p class=decl>{e(inv['export']['declaration'])}</p>" if inv.get("export") else ""
    head = ("<div class=test>A test invoice, for a payment made with Razorpay test keys: not a tax invoice, and no money moved.</div>"
            if inv["test"] else "")
    pay = inv.get("payment") or {}
    extra_rows = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in (extra or []))
    return ("<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Invoice {e(inv['no'])}</title><style>"
            "body{font:14px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;color:#1d1d1f;background:#fff;margin:0;padding:28px 16px}"
            "main{max-width:760px;margin:0 auto}h1{font-size:22px;margin:0}.muted{color:#6b6b70}.top{display:flex;justify-content:space-between;"
            "gap:16px;flex-wrap:wrap;margin:6px 0 18px}.box{flex:1;min-width:230px}.lbl{font-size:11px;letter-spacing:.06em;text-transform:uppercase;"
            "color:#6b6b70;margin-bottom:2px}table{border-collapse:collapse;width:100%;margin:14px 0}th,td{padding:7px 8px;border-bottom:1px solid #e3e3e8;"
            "text-align:left;vertical-align:top}th{font-size:12px;color:#6b6b70;font-weight:600}.r{text-align:right}tr.tot td{font-weight:700;"
            "border-bottom:2px solid #1d1d1f}.decl{font-weight:600;border:1px solid #1d1d1f;padding:8px 10px}.test{background:#fff4e5;color:#8a4b00;"
            "padding:8px 12px;border-radius:6px;margin:0 0 14px}.meta td{border:0;padding:2px 12px 2px 0}"
            "@media (prefers-color-scheme:dark){body{background:#151517;color:#ececf0}th,td{border-color:#2c2c31}tr.tot td{border-color:#ececf0}"
            ".decl{border-color:#ececf0}.test{background:#3a2a12;color:#ffcf8a}}@media print{body{padding:0}.test{border:1px solid #8a4b00}}</style>"
            f"<main>{head}<h1>{'Tax invoice' if not inv['test'] else 'Test invoice'}</h1><div class=muted>Original for recipient</div>"
            "<div class=top><div class=box><div class=lbl>Supplier</div>"
            f"<b>{e(s['name'] or '(supplier name not set)')}</b><br>{lines(s['address'])}<br>{e(s.get('state_name') or '')}"
            f"{' (' + e(s['state']) + ')' if s.get('state') else ''}{', PIN ' + e(s['pin']) if s.get('pin') else ''}<br>GSTIN {e(s['gstin'] or '(not set)')}</div>"
            "<div class=box><table class=meta>"
            f"<tr><td class=muted>Invoice no.</td><td><b>{e(inv['no'])}</b></td></tr><tr><td class=muted>Date</td><td>{date_of(inv)}</td></tr>"
            f"<tr><td class=muted>Place of supply</td><td>{e(inv['place'])}</td></tr><tr><td class=muted>Reverse charge</td><td>No</td></tr>"
            "</table></div></div>"
            f"<div class=lbl>Billed to</div><b>{e(b['name'])}</b><br>{lines(b['address'])}<br>{buyer_place}"
            f"{'<br>GSTIN ' + e(b['gstin']) if b.get('gstin') else ''}"
            "<table><tr><th>Description</th><th>SAC</th><th class=r>Quantity</th><th class=r>Rate</th><th class=r>Taxable value</th></tr>"
            f"<tr><td>{e(inv['description'])}</td><td>{e(inv['sac'] or '-')}</td><td class=r>{inv['quantity']:,}</td>"
            f"<td class=r>{money(_share(inv['taxable'], 1, max(inv['quantity'], 1)), cur)}</td><td class=r>{money(inv['taxable'], cur)}</td></tr>"
            f"{tax_rows}<tr class=tot><td colspan=4 class=r>Total ({e(cur)})</td><td class=r>{money(inv['total'], cur)}</td></tr></table>"
            f"{inr_row}{export}"
            f"<p class=muted>Paid online through Razorpay{', payment ' + e(pay['razorpay']) if pay.get('razorpay') else ''}. "
            f"{e(' '.join(inv.get('notes') or []))}</p>"
            + (f"<table>{extra_rows}</table>" if extra_rows else "")
            + f"<p class=muted>A computer-generated invoice. For {e(s['name'] or 'the supplier')}: authorised signatory.</p></main></html>")


CSV_COLUMNS = ["Invoice no", "Invoice date", "Test", "Buyer", "Buyer GSTIN", "Place of supply", "Buyer state code", "Buyer country",
               "Currency", "Taxable value", "CGST", "SGST/UTGST", "IGST", "Invoice value", "GST rate %", "SAC", "Export",
               "INR rate", "INR taxable value", "INR IGST", "INR invoice value", "Credits", "Razorpay payment"]


def to_csv(invs: list[dict]) -> str:
    """Invoices as the accountant needs them for GSTR-1 (amounts in the invoice's currency, with rupee values for exports)."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for i in invs:
        b, cur, inr = i["buyer"], i["currency"], i.get("inr") or {}
        unit = lambda v: f"{int(v or 0) / 100:.2f}"                 # noqa: E731
        w.writerow([i["no"], date_of(i), "yes" if i["test"] else "", b.get("name"), b.get("gstin"), i["place"], b.get("state"),
                    b.get("country"), cur, unit(i["taxable"]), unit(i["cgst"]), unit(i["sgst"]), unit(i["igst"]), unit(i["total"]),
                    f"{i['rate']:g}", i["sac"], ("LUT " + i["export"]["lut"] if i["export"]["lut"] else "on payment of IGST") if i.get("export") else "",
                    inr.get("rate", ""), unit(inr["taxable"]) if inr else "", unit(inr["igst"]) if inr else "", unit(inr["total"]) if inr else "",
                    i["quantity"], (i.get("payment") or {}).get("razorpay")])
    return out.getvalue()
