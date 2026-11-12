"""The sample estate: a synthetic IBM Cognos Analytics estate (seeded, about 1,800 objects) written as real export
files so the Cognos reader is exercised end to end - content listing, report specifications (XML), dashboards and
stories (JSON), packages and data modules (JSON), the Audit database export (CSV) - plus the data behind the five
packages / data modules the reports use, as CSVs, so conversions can be proven against it.

Everything is made up (DemoData style): names, folders, usage, complexity mix, shared objects, nine reports pointing
to packages that no longer exist, a few that failed recently, HTML items with scripts and Active Reports that no
rule converts. Nothing is a client's. The numbers a Discover step shows are derived by reading these files back,
never typed in here.

    from genbi_kit.migrate import sample_estate
    sample_estate.generate(Path("source"), seed=42, objects=1842)
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import random
import re
from pathlib import Path
from xml.sax.saxutils import escape

AS_OF = dt.date(2026, 9, 30)             # the day the audit export was taken
AUDIT_DAYS = 913                         # two and a half years of runs in the export
PERIOD = (dt.date(2024, 11, 1), dt.date(2026, 10, 31))
NS = "http://developer.cognos.com/schemas/report/16.2/"

# ------------------------------------------------------------------ the five datasets with data

def _cols(spec: str) -> list[dict]:
    out = []
    for part in spec.split(","):
        name, typ, role = (part.strip().split(":") + [None, None])[:3]
        out.append({"name": name, "type": typ or "string", "role": role or ("measure" if typ in ("int", "decimal") else "date" if typ == "date" else "attribute")})
    return out


DATASETS = [
    {"id": "pkg-sales", "name": "Sales", "kind": "package", "folder": "Team content/Packages", "tables": [
        {"name": "Sales", "file": "sales.csv", "role": "fact", "columns": _cols("OrderDate:date,StoreKey:int:key,ProductKey:int:key,CustomerKey:int:key,Revenue:decimal,Cost:decimal,Units:int,Discount:decimal")},
        {"name": "Store", "file": "store.csv", "role": "dimension", "key": "StoreKey", "columns": _cols("StoreKey:int:key,Store:string,Region:string,Country:string,Channel:string")},
        {"name": "Product", "file": "product.csv", "role": "dimension", "key": "ProductKey", "columns": _cols("ProductKey:int:key,Product:string,Category:string,Brand:string")},
        {"name": "Customer", "file": "customer.csv", "role": "dimension", "key": "CustomerKey", "columns": _cols("CustomerKey:int:key,Customer:string,Segment:string")}],
     "relationships": [{"from": "Sales[StoreKey]", "to": "Store[StoreKey]"}, {"from": "Sales[ProductKey]", "to": "Product[ProductKey]"}, {"from": "Sales[CustomerKey]", "to": "Customer[CustomerKey]"}]},
    {"id": "pkg-finance", "name": "Finance", "kind": "package", "folder": "Team content/Packages", "tables": [
        {"name": "GL", "file": "gl.csv", "role": "fact", "columns": _cols("PostingDate:date,AccountKey:int:key,CostCentreKey:int:key,Amount:decimal,Budget:decimal")},
        {"name": "Account", "file": "account.csv", "role": "dimension", "key": "AccountKey", "columns": _cols("AccountKey:int:key,Account:string,AccountType:string")},
        {"name": "CostCentre", "file": "costcentre.csv", "role": "dimension", "key": "CostCentreKey", "columns": _cols("CostCentreKey:int:key,CostCentre:string,Department:string")}],
     "relationships": [{"from": "GL[AccountKey]", "to": "Account[AccountKey]"}, {"from": "GL[CostCentreKey]", "to": "CostCentre[CostCentreKey]"}]},
    {"id": "dm-retail", "name": "Retail DM", "kind": "data module", "folder": "Team content/Data modules", "tables": [
        {"name": "Inventory", "file": "inventory.csv", "role": "fact", "columns": _cols("StockDate:date,StoreKey:int:key,ProductKey:int:key,OnHand:int,OnOrder:int,SafetyStock:int,StockValue:decimal")},
        {"name": "Store", "file": "store.csv", "role": "dimension", "key": "StoreKey", "columns": _cols("StoreKey:int:key,Store:string,Region:string,Country:string,Channel:string")},
        {"name": "Product", "file": "product.csv", "role": "dimension", "key": "ProductKey", "columns": _cols("ProductKey:int:key,Product:string,Category:string,Brand:string")}],
     "relationships": [{"from": "Inventory[StoreKey]", "to": "Store[StoreKey]"}, {"from": "Inventory[ProductKey]", "to": "Product[ProductKey]"}]},
    {"id": "pkg-hr", "name": "HR", "kind": "package", "folder": "Team content/Packages", "tables": [
        {"name": "Headcount", "file": "headcount.csv", "role": "fact", "columns": _cols("SnapshotDate:date,DepartmentKey:int:key,Headcount:int,Joiners:int,Leavers:int,Payroll:decimal")},
        {"name": "Department", "file": "department.csv", "role": "dimension", "key": "DepartmentKey", "columns": _cols("DepartmentKey:int:key,Department:string,Division:string")}],
     "relationships": [{"from": "Headcount[DepartmentKey]", "to": "Department[DepartmentKey]"}]},
    {"id": "dm-supply", "name": "Supply DM", "kind": "data module", "folder": "Team content/Data modules", "tables": [
        {"name": "Shipments", "file": "shipments.csv", "role": "fact", "columns": _cols("ShipDate:date,CarrierKey:int:key,SupplierKey:int:key,Shipments:int,OnTime:int,Late:int,FreightCost:decimal")},
        {"name": "Carrier", "file": "carrier.csv", "role": "dimension", "key": "CarrierKey", "columns": _cols("CarrierKey:int:key,Carrier:string,Mode:string")},
        {"name": "Supplier", "file": "supplier.csv", "role": "dimension", "key": "SupplierKey", "columns": _cols("SupplierKey:int:key,Supplier:string,SupplierCountry:string")}],
     "relationships": [{"from": "Shipments[CarrierKey]", "to": "Carrier[CarrierKey]"}, {"from": "Shipments[SupplierKey]", "to": "Supplier[SupplierKey]"}]},
]
# what a report can group by / add up, per dataset: (table, column) and the fact's date column
SHAPES = {
    "pkg-sales": {"fact": "Sales", "date": "OrderDate", "attrs": [("Store", "Region"), ("Store", "Country"), ("Store", "Channel"), ("Product", "Category"), ("Product", "Brand"), ("Customer", "Segment")],
                  "measures": [("Sales", "Revenue"), ("Sales", "Cost"), ("Sales", "Units"), ("Sales", "Discount")], "key": ("Sales", "CustomerKey")},
    "pkg-finance": {"fact": "GL", "date": "PostingDate", "attrs": [("Account", "AccountType"), ("Account", "Account"), ("CostCentre", "Department"), ("CostCentre", "CostCentre")],
                    "measures": [("GL", "Amount"), ("GL", "Budget")], "key": ("GL", "AccountKey")},
    "dm-retail": {"fact": "Inventory", "date": "StockDate", "attrs": [("Store", "Region"), ("Store", "Channel"), ("Product", "Category"), ("Product", "Brand")],
                  "measures": [("Inventory", "OnHand"), ("Inventory", "OnOrder"), ("Inventory", "SafetyStock"), ("Inventory", "StockValue")], "key": ("Inventory", "ProductKey")},
    "pkg-hr": {"fact": "Headcount", "date": "SnapshotDate", "attrs": [("Department", "Division"), ("Department", "Department")],
               "measures": [("Headcount", "Headcount"), ("Headcount", "Joiners"), ("Headcount", "Leavers"), ("Headcount", "Payroll")], "key": ("Headcount", "DepartmentKey")},
    "dm-supply": {"fact": "Shipments", "date": "ShipDate", "attrs": [("Carrier", "Carrier"), ("Carrier", "Mode"), ("Supplier", "Supplier"), ("Supplier", "SupplierCountry")],
                  "measures": [("Shipments", "Shipments"), ("Shipments", "OnTime"), ("Shipments", "Late"), ("Shipments", "FreightCost")], "key": ("Shipments", "SupplierKey")},
}
OTHER_PACKAGES = ["Marketing", "Procurement", "Treasury", "Fixed assets", "Payables", "Receivables", "Tax", "Audit", "Budgeting", "Planning",
                  "Quality", "Returns", "Warranty", "Fleet", "Stores", "Pricing", "Promotions", "Loyalty", "Web analytics", "Call centre",
                  "Projects", "Capex", "Energy", "Facilities", "Legal", "Risk", "Compliance", "Payroll", "Recruiting", "Training", "GO Sales (query)"]
OTHER_MODULES = ["Marketing DM", "Promotions DM", "Customer 360", "Web sessions", "Call centre DM", "Returns DM", "Claims DM", "Quality DM", "Fleet DM", "Energy DM",
                 "Projects DM", "Capex DM", "Treasury DM", "Cash DM", "Payables DM", "Receivables DM", "Tax DM", "Budget DM", "Forecast DM", "Headcount DM",
                 "Recruiting DM", "Training DM", "Payroll DM", "Stores DM", "Pricing DM", "Loyalty DM", "Supplier DM", "Carrier DM", "Warehouse DM", "Orders DM",
                 "Pipeline DM", "Churn DM", "Margin DM", "Shipments DM", "Store ops DM", "Audit DM", "Risk DM", "Compliance DM", "Legal DM", "Facilities DM",
                 "Fixed assets DM", "Procurement DM", "Planning DM", "Quality checks DM", "Returns detail DM", "Loyalty tiers DM", "Web funnel DM"]
MISSING_PACKAGE = "GO Sales (legacy)"
FOLDERS = {"Team content/Finance": 0.30, "Team content/Finance/Month end": 0.06, "Team content/Supply chain": 0.18, "Team content/Supply chain/Carriers": 0.05,
           "Team content/Operations": 0.12, "Team content/Operations/Stores": 0.04, "Team content/HR": 0.04, "My content": 0.21}
FOLDER_DATASETS = {"Team content/Finance": ["pkg-finance", "pkg-sales"], "Team content/Finance/Month end": ["pkg-finance"], "Team content/Supply chain": ["dm-supply", "dm-retail"],
                   "Team content/Supply chain/Carriers": ["dm-supply"], "Team content/Operations": ["dm-retail", "pkg-sales"], "Team content/Operations/Stores": ["pkg-sales", "dm-retail"],
                   "Team content/HR": ["pkg-hr"], "My content": ["pkg-sales", "pkg-finance", "dm-retail", "pkg-hr", "dm-supply"]}
OWNERS = {"Team content/Finance": "Finance", "Team content/Finance/Month end": "Finance", "Team content/Supply chain": "Supply chain", "Team content/Supply chain/Carriers": "Supply chain",
          "Team content/Operations": "Operations", "Team content/Operations/Stores": "Operations", "Team content/HR": "HR", "My content": None, "Executive": "Finance"}
SUBJECTS = ["Sales", "Revenue", "Inventory", "Claims", "Customers", "Churn", "Margin", "Returns", "Pipeline", "Orders", "Budget", "Headcount", "Forecast", "Shipments",
            "Store", "Pricing", "Promotions", "Suppliers", "Payroll", "Cash"]
QUALIFIERS = ["by Month", "by Region", "Weekly", "- APAC", "- EMEA", "vs Target", "Detail", "Summary", "Daily", "YTD", "- Team", "Trend", "by Customer", "Exceptions", "by Product", "Scorecard"]
PEOPLE = ["a.patel", "b.okafor", "c.novak", "d.rossi", "e.schmidt", "f.tanaka", "g.silva", "h.murphy", "i.kowalski", "j.andersen", "k.mehta", "l.dubois", "m.garcia", "n.ivanova",
          "o.nguyen", "p.cohen", "q.ali", "r.berg", "s.lee", "t.fischer", "u.rao", "v.costa", "w.chen", "x.moreau", "y.park", "z.haas"]
# the twelve showcase reports in the Executive folder: rich, used every day, every one convertible
SHOWCASE = ["Board Pack - Monthly Sales", "Margin Deep Dive", "Region vs Plan", "Customer Loyalty Segments", "Returns & Quality", "Cash Position Daily",
            "Working Capital", "Supplier Scorecard", "Inventory Health", "OTIF by Carrier", "Store Benchmarks", "Time Comparison Workbench"]
SHOWCASE_DS = ["pkg-sales", "pkg-sales", "pkg-finance", "pkg-sales", "dm-retail", "pkg-finance", "pkg-finance", "dm-supply", "dm-retail", "dm-supply", "pkg-sales", "pkg-sales"]


# ------------------------------------------------------------------ data

def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def generate_data(out: Path, r: random.Random) -> dict:
    """The CSVs behind the five datasets (small, deterministic, 2 decimals everywhere)."""
    out.mkdir(parents=True, exist_ok=True)
    months = []
    d = PERIOD[0]
    while d <= PERIOD[1]:
        months.append(d)
        d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    regions = [("North", "United Kingdom"), ("South", "United Kingdom"), ("DACH", "Germany"), ("Nordics", "Sweden"), ("APAC", "Singapore"), ("EMEA", "France")]
    stores = [[i + 1, f"Store {i + 1:02d}", regions[i % 6][0], regions[i % 6][1], "Online" if i % 4 == 3 else "In store"] for i in range(12)]
    cats = [("Bikes", "Trailhead"), ("Accessories", "Trailhead"), ("Clothing", "Northline"), ("Components", "Northline"), ("Services", "Relay Works")]
    products = [[i + 1, f"{cats[i % 5][0][:-1] if cats[i % 5][0].endswith('s') else cats[i % 5][0]} {i + 1:02d}", cats[i % 5][0], cats[i % 5][1]] for i in range(30)]
    prices = {p[0]: round(20 + (p[0] * 37) % 400 + r.random() * 30, 2) for p in products}
    segments = ["Enterprise", "Mid-market", "Small business", "Consumer"]
    customers = [[i + 1, f"Customer {i + 1:03d}", segments[i % 4]] for i in range(200)]
    sales = []
    for i, m in enumerate(months):
        n = 110 + int(i * 1.5) + r.randint(-10, 10)
        for _ in range(n):
            day = m + dt.timedelta(days=r.randint(0, 27))
            p = r.choice(products)
            units = r.randint(1, 20)
            rev = round(units * prices[p[0]] * (0.9 + r.random() * 0.2), 2)
            cost = round(rev * (0.55 + r.random() * 0.2), 2)
            disc = "" if r.random() < 0.05 else round(rev * r.random() * 0.1, 2)
            sales.append([day.isoformat(), r.choice(stores)[0], p[0], r.choice(customers)[0], rev, cost, units, disc])
    _write_csv(out / "sales.csv", ["OrderDate", "StoreKey", "ProductKey", "CustomerKey", "Revenue", "Cost", "Units", "Discount"], sales)
    _write_csv(out / "store.csv", ["StoreKey", "Store", "Region", "Country", "Channel"], stores)
    _write_csv(out / "product.csv", ["ProductKey", "Product", "Category", "Brand"], products)
    _write_csv(out / "customer.csv", ["CustomerKey", "Customer", "Segment"], customers)
    accounts = [[i + 1, f"{4000 + i * 10} {n}", t] for i, (n, t) in enumerate([("Product sales", "Revenue"), ("Service revenue", "Revenue"), ("Cost of goods", "Cost of sales"),
                 ("Freight in", "Cost of sales"), ("Salaries", "Operating expense"), ("Rent", "Operating expense"), ("Marketing", "Operating expense"), ("IT", "Operating expense"),
                 ("Depreciation", "Operating expense"), ("Interest", "Finance cost"), ("Bank charges", "Finance cost"), ("Tax", "Tax")])]
    ccs = [[i + 1, f"CC-{100 + i}", ["Sales", "Operations", "Finance", "IT", "HR", "Supply chain"][i % 6]] for i in range(12)]
    gl = []
    for m in months:
        for a in accounts:
            for cc in ccs[: r.randint(3, 8)]:
                base = {"Revenue": 90000, "Cost of sales": -45000, "Operating expense": -18000, "Finance cost": -4000, "Tax": -6000}[a[2]]
                amt = round(base * (0.7 + r.random() * 0.6) / 6, 2)
                gl.append([(m + dt.timedelta(days=r.randint(0, 27))).isoformat(), a[0], cc[0], amt, round(amt * (0.9 + r.random() * 0.2), 2)])
    _write_csv(out / "gl.csv", ["PostingDate", "AccountKey", "CostCentreKey", "Amount", "Budget"], gl)
    _write_csv(out / "account.csv", ["AccountKey", "Account", "AccountType"], accounts)
    _write_csv(out / "costcentre.csv", ["CostCentreKey", "CostCentre", "Department"], ccs)
    inv = []
    for m in months:
        for s in stores:
            for p in products[::2]:
                on = r.randint(0, 400)
                inv.append([m.isoformat(), s[0], p[0], on, r.randint(0, 120), r.randint(20, 80), round(on * prices[p[0]] * 0.6, 2)])
    _write_csv(out / "inventory.csv", ["StockDate", "StoreKey", "ProductKey", "OnHand", "OnOrder", "SafetyStock", "StockValue"], inv)
    depts = [[i + 1, n, d] for i, (n, d) in enumerate([("Field sales", "Commercial"), ("Inside sales", "Commercial"), ("Marketing", "Commercial"), ("Customer care", "Operations"),
             ("Warehouse", "Operations"), ("Logistics", "Operations"), ("Stores", "Operations"), ("Finance", "Corporate"), ("HR", "Corporate"), ("IT", "Corporate"),
             ("Legal", "Corporate"), ("Product", "Engineering"), ("Platform", "Engineering"), ("Data", "Engineering"), ("Quality", "Engineering")])]
    hc = []
    for m in months:
        for d_ in depts:
            n = 20 + d_[0] * 3 + r.randint(-3, 3)
            hc.append([m.isoformat(), d_[0], n, r.randint(0, 4), r.randint(0, 3), round(n * (4200 + r.random() * 900), 2)])
    _write_csv(out / "headcount.csv", ["SnapshotDate", "DepartmentKey", "Headcount", "Joiners", "Leavers", "Payroll"], hc)
    _write_csv(out / "department.csv", ["DepartmentKey", "Department", "Division"], depts)
    carriers = [[i + 1, n, mode] for i, (n, mode) in enumerate([("Northline Freight", "Road"), ("Skyward", "Air"), ("BlueOcean", "Sea"), ("Parcelio", "Parcel"), ("RailLink", "Rail"), ("Swiftpost", "Parcel")])]
    suppliers = [[i + 1, f"Supplier {i + 1:02d}", ["Germany", "Vietnam", "Poland", "China", "Italy", "India"][i % 6]] for i in range(18)]
    sh = []
    for m in months:
        for _ in range(100):
            n = r.randint(1, 40)
            late = r.randint(0, max(1, n // 5))
            sh.append([(m + dt.timedelta(days=r.randint(0, 27))).isoformat(), r.choice(carriers)[0], r.choice(suppliers)[0], n, n - late, late, round(n * (30 + r.random() * 90), 2)])
    _write_csv(out / "shipments.csv", ["ShipDate", "CarrierKey", "SupplierKey", "Shipments", "OnTime", "Late", "FreightCost"], sh)
    _write_csv(out / "carrier.csv", ["CarrierKey", "Carrier", "Mode"], carriers)
    _write_csv(out / "supplier.csv", ["SupplierKey", "Supplier", "SupplierCountry"], suppliers)
    return {"sales": len(sales), "gl": len(gl), "inventory": len(inv), "headcount": len(hc), "shipments": len(sh)}


# ------------------------------------------------------------------ reports

def _ref(ds: dict, table: str, col: str) -> str:
    return f"[{ds['name']}].[{table}].[{col}]"


class _Spec:
    """One report's content as it is being made: queries with data items, filters, prompts, pages with visuals."""

    def __init__(self, ds: dict, r: random.Random):
        self.ds, self.r, self.shape = ds, r, SHAPES[ds["id"]]
        self.queries: list[dict] = []
        self.prompts: list[dict] = []
        self.pages: list[dict] = []
        self.features: list[str] = []
        self.no_rule = 0

    def query(self, n_attr: int, n_meas: int, calcs: list[str], filters: list[str] | None = None, date_attr: str | None = None) -> dict:
        r, ds, sh = self.r, self.ds, self.shape
        attrs = r.sample(sh["attrs"], min(n_attr, len(sh["attrs"])))
        meas = r.sample(sh["measures"], min(n_meas, len(sh["measures"])))
        items = []
        for t, c in attrs:
            items.append({"name": c, "expression": _ref(ds, t, c), "aggregate": None})
        if date_attr:
            fn = {"Year": "_year", "Month": "_month"}[date_attr]
            items.append({"name": date_attr, "expression": f"{fn}({_ref(ds, sh['fact'], sh['date'])})", "aggregate": None})
        for t, c in meas:
            items.append({"name": c, "expression": _ref(ds, t, c), "aggregate": "total"})
        names = {it["name"] for it in items}
        m1, m2 = [c for _, c in meas][:2] if len(meas) >= 2 else ([c for _, c in meas] * 2)[:2]
        a1 = attrs[0][1] if attrs else None
        key_t, key_c = sh["key"]
        fact, date = sh["fact"], sh["date"]
        avail = {
            "total": (f"Total {m1}", f"total({_ref(ds, fact, m1)})", "total"),
            "average": (f"Average {m1}", f"average({_ref(ds, fact, m1)})", "average"),
            "count": (f"{m1} Count", f"count({_ref(ds, fact, m1)})", "count"),
            "maximum": (f"Max {m1}", f"maximum({_ref(ds, fact, m1)})", "maximum"),
            "minimum": (f"Min {m1}", f"minimum({_ref(ds, fact, m1)})", "minimum"),
            "diff": (f"{m1} less {m2}", f"[{m1}] - [{m2}]", None),
            "ratio": (f"{m2} share of {m1}", f"([{m1}] - [{m2}]) / [{m1}]", None),
            "percentage": (f"{m1} Share", f"percentage({_ref(ds, fact, m1)})", None),
            "round": (f"{m1} per {m2}", f"_round([{m1}] / [{m2}], 2)", None),
            "if": (f"Large {m1}", f"if (total({_ref(ds, fact, m1)}) > 100000) then (total({_ref(ds, fact, m1)})) else (0)", None),
            "coalesce": (f"{m1} (no blanks)", f"total(coalesce({_ref(ds, fact, m1)}, 0))", "total"),
            "upper": (f"Upper {a1}", f"upper({_ref(ds, attrs[0][0], a1)})", None) if a1 else None,
            "for": (f"{m1} by {a1}", f"total({_ref(ds, fact, m1)} for {_ref(ds, attrs[0][0], a1)})", None) if a1 else None,
            "case": (f"{m1} ({a1} A)", f"total(case when {_ref(ds, attrs[0][0], a1)} = 'A' then {_ref(ds, fact, m1)} else 0 end)", None) if a1 else None,
            "substring": (f"Short {a1}", f"substring({_ref(ds, attrs[0][0], a1)}, 1, 3)", None) if a1 else None,
            "share": (f"{m1} share of report", f"[{m1}] / total({_ref(ds, fact, m1)} for report)", None),
            "per_key": (f"{m1} per {key_c}", f"total({_ref(ds, fact, m1)}) / count(distinct {_ref(ds, key_t, key_c)})", None),
            "yearmonth": ("Year Month", f"_year({_ref(ds, fact, date)}) * 100 + _month({_ref(ds, fact, date)})", None),
            "running": (f"Running {m1}", f"running-total({_ref(ds, fact, m1)})", None),
            "running_for": (f"Running {m1} by {a1}", f"running-total({_ref(ds, fact, m1)} for {_ref(ds, attrs[0][0], a1)})", None) if a1 else None,
            "rank": (f"{m1} Rank", f"rank({_ref(ds, fact, m1)})", None),
            "moving": (f"{m1} 3-period average", f"moving-average({_ref(ds, fact, m1)}, 3)", None),
            "percentile": (f"{m1} Percentile", f"percentile({_ref(ds, fact, m1)})", None),
            "macro_user": ("Run by", "#sq($account.defaultName)#", None),
            "macro_prompt": ("Chosen year", "#prompt('pYear', 'integer', '2026')#", None),
        }
        for key in calcs:
            spec = avail.get(key)
            if not spec or spec[0] in names:
                continue
            items.append({"name": spec[0], "expression": spec[1], "aggregate": spec[2]})
            names.add(spec[0])
            if key in ("running", "running_for", "rank", "moving", "percentile", "macro_user", "macro_prompt"):
                self.no_rule += 1
        q = {"name": f"Query{len(self.queries) + 1}", "items": items, "filters": list(filters or []), "attrs": [c for _, c in attrs] + ([date_attr] if date_attr else []),
             "measures": [c for _, c in meas], "calc_names": [it["name"] for it in items if it["name"] not in {c for _, c in attrs} | {c for _, c in meas} | {date_attr}]}
        self.queries.append(q)
        return q

    def prompt(self, q: dict) -> None:
        if not q["attrs"]:
            return
        a = self.r.choice([x for x in q["attrs"] if x not in ("Year", "Month")] or q["attrs"])
        name = "p" + re.sub(r"\W", "", a)
        if any(p["name"] == name for p in self.prompts):
            return
        q["filters"].append(f"[{a}] = ?{name}?")
        self.prompts.append({"name": name, "item": a, "query": q["name"], "multi": True})

    def year_filter(self, q: dict) -> None:
        if "Year" in q["attrs"]:
            q["filters"].append(f"[Year] = {self.r.choice([2025, 2026])}")

    def page(self, name: str, visuals: list[dict]) -> None:
        self.pages.append({"name": name, "visuals": visuals})

    def vis(self, kind: str, q: dict, title: str | None = None, n_meas: int = 1, category: str | None = None, series: str | None = None, columns: list | None = None) -> dict:
        meas_pool = [m for m in q["measures"] + q["calc_names"] if m not in ("Year", "Month", "Year Month") and not m.startswith(("Upper", "Short", "Run by", "Chosen"))]
        meas = meas_pool[:n_meas] if meas_pool else []
        cat = category or (q["attrs"][0] if q["attrs"] else None)
        self.n_vis = getattr(self, "n_vis", 0) + 1
        return {"id": f"{kind.title()}{self.n_vis}", "kind": kind, "query": q["name"], "title": title or (f"{meas[0]} by {cat}" if meas and cat else kind.title()),
                "measures": meas, "category": cat, "series": series, "columns": columns or (q["attrs"] + meas)}


def _random_report(spec: _Spec, complexity: str, r: random.Random) -> None:
    """Fill a report's content for its complexity (what decides how many rules it needs)."""
    simple_calcs = ["total", "average", "count", "maximum", "minimum", "diff"]
    medium_calcs = simple_calcs + ["ratio", "percentage", "round", "if", "coalesce", "upper"]
    complex_calcs = medium_calcs + ["for", "case", "substring", "share", "per_key", "yearmonth"]
    hard_calcs = ["running", "running_for", "rank", "moving", "percentile", "macro_user", "macro_prompt"]
    if complexity == "simple":
        q = spec.query(r.randint(1, 2), r.randint(1, 2), r.sample(simple_calcs, r.randint(0, 2)), date_attr=r.choice([None, "Month"]))
        spec.page("Page1", [spec.vis(r.choice(["list", "column", "kpi"]), q, n_meas=r.randint(1, 2))])
        if r.random() < 0.3:
            spec.prompt(q)
    elif complexity == "medium":
        q = spec.query(r.randint(1, 3), r.randint(1, 3), r.sample(medium_calcs, r.randint(2, 4)), date_attr=r.choice([None, "Month", "Year"]))
        vis = [spec.vis(r.choice(["list", "column", "bar", "line", "pie", "kpi", "crosstab"]), q, n_meas=r.randint(1, 2)) for _ in range(r.randint(1, 3))]
        if any(v["kind"] == "crosstab" for v in vis) and len(q["attrs"]) > 1:
            for v in vis:
                if v["kind"] == "crosstab":
                    v["series"] = q["attrs"][1]
        spec.page("Page1", vis)
        if r.random() < 0.5:
            spec.prompt(q)
        spec.year_filter(q)
    elif complexity == "complex":
        for p in range(r.randint(1, 3)):
            q = spec.query(r.randint(2, 3), r.randint(2, 3), r.sample(complex_calcs, r.randint(3, 5)) + (["running"] if r.random() < 0.12 else []),
                           date_attr=r.choice([None, "Month", "Year"]))
            vis = [spec.vis(r.choice(["list", "column", "bar", "line", "pie", "kpi", "crosstab", "gauge"]), q, n_meas=r.randint(1, 3)) for _ in range(r.randint(2, 4))]
            for v in vis:
                if v["kind"] == "crosstab" and len(q["attrs"]) > 1:
                    v["series"] = q["attrs"][1]
            spec.page(f"Page{p + 1}", vis)
            if r.random() < 0.5:
                spec.prompt(q)
            spec.year_filter(q)
        if r.random() < 0.08:
            spec.pages[0]["visuals"].append({"id": "Map1", "kind": "map", "query": spec.queries[0]["name"], "title": "Map", "measures": spec.queries[0]["measures"][:1],
                                             "category": spec.queries[0]["attrs"][0] if spec.queries[0]["attrs"] else None, "series": None, "columns": []})
    else:
        n_hard = r.choice([0, 1, 1, 2, 3, 4, 5])
        for p in range(r.randint(2, 3)):
            hard = r.sample(hard_calcs, min(n_hard, len(hard_calcs))) if p == 0 else (["running"] if r.random() < 0.3 else [])
            q = spec.query(r.randint(2, 4), r.randint(2, 4), r.sample(complex_calcs, r.randint(4, 7)) + hard, date_attr=r.choice(["Month", "Year"]))
            vis = [spec.vis(r.choice(["list", "column", "bar", "line", "pie", "kpi", "crosstab", "gauge"]), q, n_meas=r.randint(1, 3)) for _ in range(r.randint(3, 5))]
            for v in vis:
                if v["kind"] == "crosstab" and len(q["attrs"]) > 1:
                    v["series"] = q["attrs"][1]
            spec.page(f"Page{p + 1}", vis)
            spec.prompt(q)
            spec.year_filter(q)
        x = r.random()
        if x < 0.12:
            spec.features.append("active report")
        elif x < 0.24:
            spec.features.append("custom javascript")
        elif x < 0.30:
            spec.pages[0]["visuals"].append({"id": "Map1", "kind": "map", "query": spec.queries[0]["name"], "title": "Map", "measures": spec.queries[0]["measures"][:1],
                                             "category": spec.queries[0]["attrs"][0] if spec.queries[0]["attrs"] else None, "series": None, "columns": []})


def _showcase_report(spec: _Spec, name: str, r: random.Random) -> None:
    """The Executive reports: three pages, every visual kind, rules-covered calculations and one running total."""
    sh = spec.shape
    q1 = spec.query(2, 3, ["total", "ratio", "percentage", "for", "running"], date_attr="Month")
    q2 = spec.query(2, 2, ["diff", "round", "case", "share"], date_attr="Year")
    q3 = spec.query(1, 2, ["average", "maximum", "per_key"], date_attr=None)
    m = q1["measures"]
    spec.page("Overview", [spec.vis("kpi", q1, f"{m[0]} this year", n_meas=3), spec.vis("line", q1, f"{m[0]} by month", category="Month"),
                           spec.vis("column", q1, f"{m[0]} by {q1['attrs'][0]}", n_meas=2), spec.vis("pie", q1, f"Share of {m[0]}", category=q1["attrs"][1] if len(q1["attrs"]) > 1 else q1["attrs"][0])])
    spec.page("Detail", [spec.vis("crosstab", q2, f"{q2['measures'][0]} by {q2['attrs'][0]} and {q2['attrs'][1]}", category=q2["attrs"][0], series=q2["attrs"][1]),
                         spec.vis("list", q2, "Detail list", n_meas=3), spec.vis("bar", q2, f"{q2['measures'][0]} by {q2['attrs'][1]}", category=q2["attrs"][1])])
    spec.page("Benchmarks", [spec.vis("gauge", q3, f"Average {q3['measures'][0]}", n_meas=1), spec.vis("column", q3, f"Max {q3['measures'][0]} by {q3['attrs'][0]}", n_meas=2)])
    spec.prompt(q1)
    spec.year_filter(q2)
    spec.no_rule = 1


# ------------------------------------------------------------------ writing the export files

def _query_xml(q: dict) -> str:
    items = "".join(f'<dataItem name="{escape(it["name"], {chr(34): "&quot;"})}"' + (f' aggregate="{it["aggregate"]}"' if it["aggregate"] else "")
                    + f"><expression>{escape(it['expression'])}</expression></dataItem>" for it in q["items"])
    filters = "".join(f"<detailFilter><filterExpression>{escape(f)}</filterExpression></detailFilter>" for f in q["filters"])
    return (f'<query name="{escape(q["name"])}"><source><model/></source><selection>{items}</selection>'
            + (f"<detailFilters>{filters}</detailFilters>" if filters else "") + "</query>")


def _visual_xml(v: dict) -> str:
    k, q, nm = v["kind"], escape(v["query"] or ""), escape(v["id"])
    ms = v.get("measures") or []
    cat = v.get("category")
    if k == "list":
        cols = "".join(f'<listColumn><listColumnTitle><contents><textItem><dataSource><dataItemLabel refDataItem="{escape(c)}"/></dataSource></textItem></contents></listColumnTitle>'
                       f'<listColumnBody><contents><textItem><dataSource><dataItemValue refDataItem="{escape(c)}"/></dataSource></textItem></contents></listColumnBody></listColumn>'
                       for c in v.get("columns") or [])
        return f'<list horizontalPagination="true" name="{nm}" refQuery="{q}"><listColumns>{cols}</listColumns></list>'
    if k == "crosstab":
        rows = f'<crosstabRows><crosstabNodeMember refDataItem="{escape(cat)}" edgeLocation="e1"/></crosstabRows>' if cat else ""
        cols = f'<crosstabColumns><crosstabNodeMember refDataItem="{escape(v["series"])}" edgeLocation="e2"/></crosstabColumns>' if v.get("series") else ""
        return f'<crosstab name="{nm}" refQuery="{q}"><crosstabCorner/>{rows}{cols}' + (f'<defaultMeasure refDataItem="{escape(ms[0])}"/>' if ms else "") + "</crosstab>"
    if k in ("column", "bar", "line"):
        typ = "v2_combinationTypeLine" if k == "line" else "v2_combinationTypeBar"
        measures = "".join(f'<v2_combinationTypeMeasure refDataItem="{escape(m)}"/>' for m in ms)
        series = f'<v2_seriesAxis><v2_seriesNodeMember refDataItem="{escape(v["series"])}"/></v2_seriesAxis>' if v.get("series") else ""
        return (f'<v2_combinationChart name="{nm}" refQuery="{q}"' + (' orientation="horizontal"' if k == "bar" else "") + f'><v2_combinationTypeMeasures><{typ}>{measures}</{typ}></v2_combinationTypeMeasures>'
                + (f'<v2_categoryAxis><v2_categoryNodeMember refDataItem="{escape(cat)}"/></v2_categoryAxis>' if cat else "") + series + "</v2_combinationChart>")
    if k == "pie":
        return (f'<v2_pieChart name="{nm}" refQuery="{q}">' + (f'<v2_pieTypeMeasure refDataItem="{escape(ms[0])}"/>' if ms else "")
                + (f'<v2_pieAxis><v2_pieNodeMember refDataItem="{escape(cat)}"/></v2_pieAxis>' if cat else "") + "</v2_pieChart>")
    if k == "gauge":
        return f'<v2_gaugeChart name="{nm}" refQuery="{q}">' + (f'<v2_gaugeTypeMeasure refDataItem="{escape(ms[0])}"/>' if ms else "") + "</v2_gaugeChart>"
    if k == "kpi":
        vals = "".join(f'<textItem><dataSource><dataItemValue refDataItem="{escape(m)}"/></dataSource></textItem>' for m in ms)
        return f'<singleton name="{nm}" refQuery="{q}"><contents>{vals}</contents></singleton>'
    if k == "map":
        return (f'<v2_mapChart name="{nm}" refQuery="{q}">' + (f'<v2_mapTypeMeasure refDataItem="{escape(ms[0])}"/>' if ms else "")
                + (f'<v2_mapNodeMember refDataItem="{escape(cat)}"/>' if cat else "") + "</v2_mapChart>")
    return f'<block name="{nm}"/>'


def report_xml(name: str, spec: _Spec) -> str:
    ds = spec.ds
    model_path = (f"/content/package[@name='{escape(ds['name'])}']/model[@name='model']" if ds["kind"] == "package"
                  else f"/content/folder[@name='Data modules']/module[@name='{escape(ds['name'])}']")
    pages = "".join(f'<page name="{escape(p["name"])}"><pageBody><contents>' + "".join(_visual_xml(v) for v in p["visuals"])
                    + ('<HTMLItem><dataSource><staticValue>&lt;script&gt;window.print()&lt;/script&gt;</staticValue></dataSource></HTMLItem>' if "custom javascript" in spec.features and p is spec.pages[0] else "")
                    + "</contents></pageBody></page>" for p in spec.pages)
    prompts = ""
    if spec.prompts:
        prompts = '<promptPages><page name="Prompt Page1"><pageBody><contents>' + "".join(
            f'<valuePrompt parameter="{escape(p["name"])}" refQuery="{escape(p["query"])}" selectValueUI="listBox" multiSelect="{"true" if p["multi"] else "false"}"><useItem refDataItem="{escape(p["item"])}"/></valuePrompt>'
            for p in spec.prompts) + "</contents></pageBody></page></promptPages>"
    queries = "".join(_query_xml(q) for q in spec.queries)
    root = "activeReport" if "active report" in spec.features else "report"
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<{root} xmlns="{NS}" expressionLocale="en-us" useStyleVersion="11.6">'
            f"<modelPath>{model_path}</modelPath><drillBehavior/><layouts><layout><reportPages>{pages}</reportPages>{prompts}</layout></layouts>"
            f"<queries>{queries}</queries><reportName>{escape(name)}</reportName></{root}>")


def dashboard_json(name: str, spec: _Spec, story: bool) -> str:
    ds = spec.ds
    tabs = []
    for p in spec.pages:
        widgets = []
        for v in p["visuals"]:
            q = next(q for q in spec.queries if q["name"] == v["query"])
            items = {it["name"]: it for it in q["items"]}
            vals = []
            for m in v["measures"]:
                it = items.get(m)
                if not it:
                    continue
                if it["aggregate"] and "].[" in it["expression"] and "(" not in it["expression"]:
                    vals.append({"item": m, "path": it["expression"], "aggregate": {"total": "sum", "average": "avg", "count": "count", "maximum": "max", "minimum": "min"}[it["aggregate"]], "label": m})
                else:
                    vals.append({"item": m, "expression": it["expression"], "label": m})
            cats = [v["category"]] if v["category"] and v["category"] in items and items[v["category"]]["aggregate"] is None else []
            widget = {"id": v["id"], "type": {"kpi": "summary", "list": "table", "column": "column", "bar": "bar", "line": "line", "pie": "pie", "crosstab": "crosstab", "gauge": "gauge", "map": "map"}.get(v["kind"], "column"),
                      "title": v["title"], "dataSource": "ds1", "categories": cats, "series": v.get("series"), "values": vals,
                      "itemPaths": {c: items[c]["expression"] for c in cats if c in items}, "filters": [f for f in q["filters"] if "?" not in f]}
            widgets.append(widget)
        tabs.append({"title": p["name"], "widgets": widgets})
    doc = {"name": name, "version": 2, "type": "story" if story else "dashboard", "dataSources": [{"id": "ds1", "name": ds["name"], "type": "module" if ds["kind"] == "data module" else "package"}]}
    doc["scenes" if story else "tabs"] = tabs
    return json.dumps(doc, indent=1)


# ------------------------------------------------------------------ the estate

def generate(out: str | Path, seed: int = 42, objects: int = 1842, with_data: bool = True, pace=None) -> dict:
    """Write the sample estate under `out` (content.csv, specs/, datasets/, audit.csv, data/, manifest.json)."""
    out = Path(out)
    r = random.Random(seed)
    for sub in ("specs", "datasets", "data"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    data_rows = generate_data(out / "data", random.Random(seed + 1)) if with_data else {}
    # datasets: the five with data + the other packages and data modules (shared objects)
    datasets = [dict(d) for d in DATASETS]
    for i, n in enumerate(OTHER_PACKAGES):
        datasets.append({"id": f"pkg-{i + 10:02d}", "name": n, "kind": "package", "folder": "Team content/Packages",
                         "tables": [{"name": n.split(" (")[0], "file": None, "role": "fact", "columns": _cols("Date:date,Amount:decimal,Quantity:int,Region:string:attribute")}], "relationships": []})
    for i, n in enumerate(OTHER_MODULES):
        datasets.append({"id": f"dm-{i + 10:02d}", "name": n, "kind": "data module", "folder": "Team content/Data modules",
                         "tables": [{"name": n.replace(" DM", ""), "file": None, "role": "fact", "columns": _cols("Date:date,Value:decimal,Count:int,Group:string:attribute")}], "relationships": []})
    content = []
    folders = sorted(set(FOLDERS) | {"Team content", "Team content/Packages", "Team content/Data modules", "Executive"})
    for i, f in enumerate(folders):
        content.append({"id": f"f-{i + 1:03d}", "path": f, "name": f.rsplit("/", 1)[-1], "type": "Folder", "owner": OWNERS.get(f) or "", "created": "2021-03-02", "modified": "2026-06-01", "base": "", "dataset": "", "shared": "true"})
    for d in datasets:
        (out / "datasets" / f"{d['id']}.json").write_text(json.dumps(d, indent=1), encoding="utf-8")
        content.append({"id": d["id"], "path": f"{d['folder']}/{d['name']}", "name": d["name"], "type": "Package" if d["kind"] == "package" else "Data module", "owner": "BI team",
                        "created": "2021-05-10", "modified": "2025-11-20", "base": "", "dataset": "", "shared": "true"})
    by_id = {d["id"]: d for d in datasets}
    # the objects
    folder_names = list(FOLDERS)
    folder_w = [FOLDERS[f] for f in folder_names]
    n_show = len(SHOWCASE)
    n_rest = max(0, objects - n_show)
    reports: list[dict] = []
    n_views = round(n_rest * 0.075)
    n_dash = round(n_rest * 0.045)
    n_story = round(n_rest * 0.01)
    n_report = n_rest - n_views - n_dash - n_story
    kinds = ["Report"] * n_report + ["Dashboard"] * n_dash + ["Story"] * n_story
    r.shuffle(kinds)
    complexity_w = [("simple", 0.547), ("medium", 0.267), ("complex", 0.14), ("very complex", 0.046)]
    personal_owner = {}
    missing_left = 9
    for i, kind in enumerate(kinds):
        folder = r.choices(folder_names, folder_w)[0]
        if folder == "My content":
            who = r.choice(PEOPLE)
            folder = f"My content/{who}"
            personal_owner[folder] = who
        ds_id = r.choice(FOLDER_DATASETS[folder] if folder in FOLDER_DATASETS else FOLDER_DATASETS["My content"])
        ds = by_id[ds_id]
        complexity = r.choices([c for c, _ in complexity_w], [w for _, w in complexity_w])[0]
        name = f"{r.choice(SUBJECTS)} {r.choice(QUALIFIERS)}" + (f" ({r.randint(1, 3)})" if r.random() < 0.25 else "")
        spec = _Spec(ds, r)
        _random_report(spec, complexity, r)
        rid = f"r-{i + 1:04d}"
        missing = False
        if kind == "Report" and missing_left and r.random() < 0.006:
            missing, missing_left = True, missing_left - 1
        reports.append({"id": rid, "name": name, "type": kind, "folder": folder, "owner": personal_owner.get(folder) or OWNERS.get(folder),
                        "spec": spec, "complexity": complexity, "missing": missing, "ds": ds})
    for i, name in enumerate(SHOWCASE):
        ds = by_id[SHOWCASE_DS[i]]
        spec = _Spec(ds, r)
        _showcase_report(spec, name, r)
        reports.append({"id": f"r-{len(reports) + 1:04d}", "name": name, "type": "Dashboard" if i == 11 else "Report", "folder": "Executive", "owner": "Finance", "spec": spec,
                        "complexity": "very complex", "missing": False, "ds": ds, "showcase": True})
    # report views point at existing reports
    base_pool = [x for x in reports if x["type"] == "Report" and not x["missing"]]
    for i in range(n_views):
        base = r.choice(base_pool)
        reports.append({"id": f"r-{len(reports) + 1:04d}", "name": base["name"] + " (view)", "type": "Report view", "folder": base["folder"], "owner": base["owner"], "spec": None,
                        "complexity": base["complexity"], "missing": False, "ds": base["ds"], "base": base["id"]})
    # write specs and the listing
    for x in reports:
        spec = x["spec"]
        if spec is not None:
            if x["missing"]:
                spec = _Spec({**x["ds"], "name": MISSING_PACKAGE, "kind": "package"}, r)
                spec.queries, spec.pages, spec.prompts, spec.features = x["spec"].queries, x["spec"].pages, x["spec"].prompts, x["spec"].features
            if x["type"] in ("Dashboard", "Story"):
                (out / "specs" / f"{x['id']}.json").write_text(dashboard_json(x["name"], spec, x["type"] == "Story"), encoding="utf-8")
            else:
                (out / "specs" / f"{x['id']}.xml").write_text(report_xml(x["name"], spec), encoding="utf-8")
        created = AS_OF - dt.timedelta(days=r.randint(40, 1500))
        content.append({"id": x["id"], "path": f"{x['folder']}/{x['name']}", "name": x["name"], "type": x["type"], "owner": x["owner"] or "", "created": created.isoformat(),
                        "modified": (created + dt.timedelta(days=r.randint(0, min(400, (AS_OF - created).days)))).isoformat(), "base": x.get("base") or "", "dataset": "",
                        "shared": "false" if x["folder"].startswith("My content") and r.random() < 0.7 else "true"})
        x["created"] = created
        if pace:
            pace()
    with open(out / "content.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "path", "name", "type", "owner", "created", "modified", "base", "dataset", "shared"], lineterminator="\n")
        w.writeheader()
        w.writerows(content)
    # usage: two and a half years of runs, with a last-used mix and a few recent failures
    buckets = [(None, 0.18), ((0, 30), 0.25), ((30, 90), 0.13), ((90, 365), 0.21), ((365, 900), 0.23)]
    runs_rows = []
    users_seen = set()
    for x in reports:
        if x.get("showcase"):
            last, n = r.randint(0, 3), r.randint(500, 900)
        else:
            b = r.choices([b for b, _ in buckets], [w for _, w in buckets])[0]
            if b is None:
                continue
            age = (AS_OF - x["created"]).days
            lo, hi = b
            if lo >= age:
                continue
            last = r.randint(lo, min(hi, age - 1)) if hi > lo else lo
            n = max(1, round({0: 150, 30: 40, 90: 10, 365: 3}[lo] * (0.2 + r.random() * 1.6)))
        age = max(last + 1, (AS_OF - x["created"]).days)
        users = r.sample(PEOPLE, r.randint(1, 5))
        users_seen.update(users)
        fail_days = r.randint(0, 60) if r.random() < 0.035 else None
        stamps = [last] + [r.randint(last, min(age - 1, AUDIT_DAYS - 1)) for _ in range(n - 1)]
        for j, d_ago in enumerate(stamps):
            day = AS_OF - dt.timedelta(days=d_ago)
            status = "failed" if (fail_days is not None and j == 0 and d_ago >= fail_days) or (fail_days is not None and d_ago == fail_days) else "success"
            runs_rows.append([f"{day.isoformat()} {r.randint(6, 19):02d}:{r.randint(0, 59):02d}:00", f"{x['folder']}/{x['name']}", r.choice(users), status, round(r.random() * 40 + 1, 1)])
        if fail_days is not None and not any(row[3] == "failed" for row in runs_rows[-n:]):
            day = AS_OF - dt.timedelta(days=min(fail_days, age - 1))
            runs_rows.append([f"{day.isoformat()} 07:15:00", f"{x['folder']}/{x['name']}", users[0], "failed", 3.2])
    runs_rows.sort()
    with open(out / "audit.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["COGIPF_LOCALTIMESTAMP", "COGIPF_REPORTPATH", "COGIPF_USERNAME", "COGIPF_STATUS", "COGIPF_RUNTIME"])
        w.writerows(runs_rows)
    manifest = {"product": "IBM Cognos Analytics", "version": "11.2.4 FP2", "namespace": "CorpLDAP", "users": len(users_seen) + 1100, "exported": AS_OF.isoformat(),
                "as_of": AS_OF.isoformat(), "sample": True, "seed": seed, "objects": len(reports), "note": "Sample estate made by Relay: every name, folder and run is made up."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return {"objects": len(reports), "datasets": len(datasets), "runs": len(runs_rows), "data": data_rows, "showcase": list(SHOWCASE),
            "by_type": {t: sum(1 for x in reports if x["type"] == t) for t in ("Report", "Report view", "Dashboard", "Story")}}
