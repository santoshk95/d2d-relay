"""Build a Power BI project (.pbip) that shows every Atlas custom visual on ready-made pages.

usage: python3 tools/mk_report.py [out_dir]        (default: release/report)

- The semantic model embeds the sample data (visuals/test/sample-data and visuals/test/data.json)
  inside each Power Query, so Refresh works on any machine without file paths.
- The .pbiviz files from release/ are unpacked into <name>.Report/CustomVisuals/<GUID>/ and
  registered in report.json, so nothing needs importing.
- The Atlas Soft theme is applied as the report theme.
Open the .pbip in Power BI Desktop; File > Save as turns it into a .pbix.
Only the standard library is used.
"""
import base64
import csv
import datetime
import json
import math
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "release" / "report"
NAME = "Visual Atlas Test"
SAMPLE = ROOT / "visuals" / "test" / "sample-data"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
BASE_THEME = "CY24SU10"
VERSION_AT_IMPORT = {"visual": "1.8.97", "report": "2.0.97", "page": "1.3.97"}


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def read_csv(name):
    with open(SAMPLE / name, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


# ------------------------------------------------------------------ data
# One star schema so slicers and clicks filter every visual: an Orders fact table and Date, Carrier,
# Channel, Device and Product dimensions (many-to-one, single direction). The data comes from a
# seeded generator, so every build is identical. Chord and network keep their own small tables.
def num(v):
    return None if v in ("", None) else float(v)


TABLES = []  # (name, columns [(name, type)], rows, measures [(name, dax, format)], sort_by {col: col}, hidden {col})
RELATIONSHIPS = []  # (from table, from column, to table, to column)


def table(name, cols, rows, measures=(), sort_by=None, hidden=()):
    TABLES.append((name, cols, rows, list(measures), sort_by or {}, set(hidden)))


class Rng:
    """small linear congruential generator, so the sample data never changes between builds"""
    def __init__(self, seed):
        self.s = seed

    def u(self):
        self.s = (self.s * 1664525 + 1013904223) % 4294967296
        return self.s / 4294967296

    def gauss(self):
        a, b = max(self.u(), 1e-12), self.u()
        return math.sqrt(-2 * math.log(a)) * math.cos(2 * math.pi * b)

    def pick(self, items, weights):
        x, acc = self.u() * sum(weights), 0.0
        for it, w in zip(items, weights):
            acc += w
            if x < acc:
                return it
        return items[-1]


rng = Rng(20261103)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Date: every day of 2024 and 2025
day, dates = datetime.date(2024, 1, 1), []
while day <= datetime.date(2025, 12, 31):
    dates.append(day)
    day += datetime.timedelta(days=1)
table("Date", [("Date", "dateTime"), ("Year", "string"), ("Quarter", "string"), ("Month", "string"), ("MonthNo", "int64")],
      [[d.isoformat(), str(d.year), f"Qtr {(d.month - 1) // 3 + 1}", MONTHS[d.month - 1], d.month] for d in dates], sort_by={"Month": "MonthNo"}, hidden={"MonthNo"})

# Carrier: service level, typical delivery days (mean, spread) and share of orders
CARRIERS = [("Swift", "Express", 2.6, 0.8, 0.28), ("Northline", "Standard", 3.4, 1.1, 0.22), ("Parcel+", "Standard", 4.1, 1.6, 0.18),
            ("Coastal", "Express", 3.0, 0.7, 0.20), ("Freightway", "Economy", 5.2, 1.9, 0.12)]
table("Carrier", [("Carrier", "string"), ("Service", "string")], [[c[0], c[1]] for c in CARRIERS])
table("Channel", [("Channel", "string")], [["Online"], ["Retail"]])
# Device: online orders only; the app has two peaks in minutes on site (quick checks and long browses)
DEVICES = [("App", 0.34), ("Desktop", 0.30), ("Tablet", 0.14), ("Mobile web", 0.22)]
table("Device", [("Device", "string"), ("Type", "string")], [["App", "Mobile"], ["Desktop", "Computer"], ["Tablet", "Mobile"], ["Mobile web", "Mobile"], ["In store", "Store"]])

# Product: the 48 products of the sample data, with a list price and margin rate per category
h, r = read_csv("sales_by_product.csv")
PRICE = {"Bikes": (650, 2600), "Components": (60, 520), "Clothing": (25, 140), "Accessories": (9, 95)}
MARGIN = {"Bikes": 0.14, "Components": 0.24, "Clothing": 0.38, "Accessories": 0.46}
products = []
for cat, sub, p, sales, _ in r:
    lo, hi = PRICE[cat]
    price = round(lo + (hi - lo) * ((len(p) * 37 + len(sub) * 11) % 100) / 100, 2)
    rate = round(MARGIN[cat] + ((len(p) * 13) % 9 - 4) / 100, 3)
    products.append((cat, sub, p, price, rate, float(sales)))
table("Product", [("Category", "string"), ("Subcategory", "string"), ("Product", "string"), ("List price", "double"), ("Margin rate", "double")],
      [[c, sb, p, pr, mr] for c, sb, p, pr, mr, _ in products], hidden={"Margin rate"})

# Orders: 2,400 orders over two years, busier in November and December and in 2025
orders = []
season = [0.8, 0.75, 0.9, 0.9, 0.95, 0.9, 0.85, 0.9, 1.0, 1.05, 1.35, 1.6]
day_w = [season[d.month - 1] * (1.15 if d.year == 2025 else 1.0) for d in dates]
for i in range(2400):
    d = rng.pick(dates, day_w)
    channel = rng.pick(["Online", "Retail"], [0.58, 0.42])
    car = rng.pick(CARRIERS, [c[4] for c in CARRIERS])
    days = max(0.5, round(car[2] + car[3] * rng.gauss() + (car[3] * 3.5 if i % 53 == 0 else 0), 1))
    prod = rng.pick(products, [x[5] / x[3] for x in products])
    qty = 1 if prod[0] == "Bikes" else 1 + int(rng.u() * 3)
    value = round(prod[3] * qty * (0.85 + 0.25 * rng.u()), 2)
    if channel == "Online":
        dev = rng.pick([x[0] for x in DEVICES], [x[1] for x in DEVICES])
        two = rng.u() < 0.5
        mean, sd = {"App": (2.2, 0.8) if two else (11, 2.4), "Desktop": (8.5, 2.8), "Tablet": (6.4, 2.2), "Mobile web": (3.6, 1.4)}[dev]
        minutes = max(0.2, round(mean + sd * rng.gauss(), 1))
    else:
        dev, minutes = "In store", None
    orders.append([f"SO{50001 + i}", d.isoformat(), channel, car[0], dev, prod[2], qty, value, days, minutes])
orders.sort(key=lambda o: (o[1], o[0]))
table("Orders", [("Order ID", "string"), ("Order date", "dateTime"), ("Channel", "string"), ("Carrier", "string"), ("Device", "string"), ("Product", "string"),
                 ("Quantity", "int64"), ("Order value", "double"), ("Delivery days", "double"), ("Minutes on site", "double")], orders,
      [("Sales", "SUM ( Orders[Order value] )", "\\$#,0"),
       ("Profit", "SUMX ( Orders, Orders[Order value] * RELATED ( Product[Margin rate] ) )", "\\$#,0"),
       ("Margin %", "DIVIDE ( [Profit], [Sales] )", "0.0%"),
       ("Order Count", "COUNTROWS ( Orders )", "#,0"),
       ("Units", "SUM ( Orders[Quantity] )", "#,0"),
       ("Avg Order Value", "DIVIDE ( [Sales], [Order Count] )", "\\$#,0"),
       ("Days to Deliver", "SUM ( Orders[Delivery days] )", "0.0"),
       ("Avg Delivery Days", "AVERAGE ( Orders[Delivery days] )", "0.0"),
       ("Session Minutes", "SUM ( Orders[Minutes on site] )", "0.0"),
       ("Sales 2024", "CALCULATE ( [Sales], 'Date'[Year] = \"2024\" )", "\\$#,0"),
       ("Sales 2025", "CALCULATE ( [Sales], 'Date'[Year] = \"2025\" )", "\\$#,0"),
       ("Sales Target", "[Sales 2024] * 1.12", "\\$#,0"),
       ("Margin Score", "[Margin %] * 100", "0.0")],
      hidden={"Channel", "Carrier", "Device", "Product", "Order date"})
for fact_col, (dim, key) in [("Order date", ("Date", "Date")), ("Channel", ("Channel", "Channel")), ("Carrier", ("Carrier", "Carrier")),
                             ("Device", ("Device", "Device")), ("Product", ("Product", "Product"))]:
    RELATIONSHIPS.append(("Orders", fact_col, dim, key))

# extra sample tables for the other families: an org chart, daily prices, a sales pipeline, review phrases and a project plan
emp = [["E1", "", "Avery Chen", 410]]
nid = 2
for k, vp in enumerate(["Sales", "Product", "Operations", "Finance", "People"]):
    v = f"E{nid}"; nid += 1; emp.append([v, "E1", f"{vp} VP", 260])
    for j in range(2 + k % 3):
        mg = f"E{nid}"; nid += 1; emp.append([mg, v, f"{vp} manager {j + 1}", 150])
        for i in range(2 + (k + j) % 3):
            emp.append([f"E{nid}", mg, f"{vp} analyst {j + 1}.{i + 1}", 90 + (k * 7 + i * 3) % 30]); nid += 1
table("Employees", [("Employee", "string"), ("Manager", "string"), ("Name", "string"), ("Salary K", "double")], emp, [("Total Salary", "SUM ( Employees[Salary K] )", "#,0")])
prices, px = [], 84.0
prng = Rng(77)
for d in dates:
    if d.year != 2025 or d.month < 5 or d.month > 10 or d.weekday() >= 5:
        continue
    o = px; c2 = max(20.0, o * (1 + (prng.u() - 0.48) * 0.04)); h = max(o, c2) * (1 + prng.u() * 0.012); l = min(o, c2) * (1 - prng.u() * 0.012)
    prices.append([d.isoformat(), round(o, 2), round(h, 2), round(l, 2), round(c2, 2), int(1e6 * (0.6 + prng.u()))]); px = c2
table("Prices", [("Day", "dateTime"), ("Open", "double"), ("High", "double"), ("Low", "double"), ("Close", "double"), ("Volume", "int64")], prices,
      [("Price Open", "MIN ( Prices[Open] )", "\\$0.00"), ("Price High", "MAX ( Prices[High] )", "\\$0.00"), ("Price Low", "MIN ( Prices[Low] )", "\\$0.00"), ("Price Close", "MAX ( Prices[Close] )", "\\$0.00"), ("Trade Volume", "SUM ( Prices[Volume] )", "#,0")])
table("Pipeline", [("Stage", "string"), ("Order", "int64"), ("Deals", "int64")], [["Leads", 1, 1240], ["Qualified", 2, 610], ["Proposal", 3, 290], ["Negotiation", 4, 148], ["Closed won", 5, 92]],
      [("Deal Count", "SUM ( Pipeline[Deals] )", "#,0")], sort_by={"Stage": "Order"}, hidden={"Order"})
REVIEWS = [["fast delivery", 412, 0.8, "Service"], ["friendly staff", 365, 0.9, "Service"], ["great price", 301, 0.7, "Price"], ["easy returns", 244, 0.6, "Service"], ["long wait", 233, -0.7, "Service"],
           ["comfortable saddle", 198, 0.7, "Product"], ["broken part", 176, -0.8, "Product"], ["website slow", 165, -0.6, "Online"], ["good quality", 160, 0.8, "Product"], ["expensive", 152, -0.5, "Price"],
           ["helpful advice", 140, 0.8, "Service"], ["out of stock", 132, -0.6, "Online"], ["smooth gears", 120, 0.7, "Product"], ["discount code", 110, 0.4, "Price"], ["late order", 104, -0.7, "Online"],
           ["light frame", 96, 0.6, "Product"], ["app crashes", 90, -0.8, "Online"], ["free shipping", 88, 0.7, "Price"], ["nice design", 84, 0.6, "Product"], ["rude reply", 70, -0.9, "Service"],
           ["quick repair", 66, 0.7, "Service"], ["easy checkout", 62, 0.6, "Online"], ["loyalty points", 58, 0.4, "Price"], ["squeaky brakes", 54, -0.6, "Product"], ["clear tracking", 50, 0.5, "Online"]]
table("Reviews", [("Phrase", "string"), ("Mentions", "int64"), ("Sentiment", "double"), ("Topic", "string")], REVIEWS,
      [("Mention Count", "SUM ( Reviews[Mentions] )", "#,0"), ("Avg Sentiment", "AVERAGE ( Reviews[Sentiment] )", "0.00")])
TASKS = [["Discovery", "Plan", "2026-09-01", "2026-09-12", "Avery", 1], ["Requirements", "Plan", "2026-09-08", "2026-09-26", "Kai", 1], ["Kick-off", "Plan", "2026-09-28", None, "Avery", 1],
         ["Design", "Build", "2026-09-29", "2026-10-24", "Mira", 0.9], ["Build API", "Build", "2026-10-13", "2026-11-21", "Jon", 0.55], ["Build app", "Build", "2026-10-20", "2026-12-05", "Lee", 0.4],
         ["Data migration", "Build", "2026-11-02", "2026-11-28", "Kai", 0.2], ["Testing", "Launch", "2026-11-23", "2026-12-12", "Mira", 0], ["Training", "Launch", "2026-12-01", "2026-12-15", "Lee", 0], ["Go-live", "Launch", "2026-12-16", None, "Avery", 0]]
table("Tasks", [("Task", "string"), ("Phase", "string"), ("Start", "dateTime"), ("End", "dateTime"), ("Owner", "string"), ("Complete", "double")], TASKS, [("Percent Complete", "MAX ( Tasks[Complete] )", "0%")])

# chord and network: their own small tables (switching and co-purchase pairs are not order lines)
for file, tname, (a, b, v), meas in [("flow_brand_switching.csv", "Brand Switching", ("From", "To", "Customers"), "Switching Customers"),
                                    ("flow_product_network.csv", "Product Network", ("Product A", "Product B", "Orders"), "Co-purchase Orders")]:
    h, r = read_csv(file)
    table(tname, [(a, "string"), (b, "string"), (v, "double")], [[x, y, num(z)] for x, y, z in r], [(meas, f"SUM ( '{tname}'[{v}] )", "#,0")])

M_TYPES = {"string": "type text", "double": "type number", "int64": "Int64.Type", "dateTime": "type date"}


def partition_m(cols, rows):
    payload = base64.b64encode(json.dumps(rows, separators=(",", ":")).encode("utf-8")).decode("ascii")
    names = ", ".join(json.dumps(c) for c, _ in cols)
    types = ", ".join("{%s, %s}" % (json.dumps(c), M_TYPES[t]) for c, t in cols)
    return [
        "let",
        "    // sample data embedded as base64 JSON, so refresh needs no files",
        f"    Rows = Json.Document(Binary.FromText(\"{payload}\", BinaryEncoding.Base64)),",
        f"    Source = Table.FromRows(Rows, {{{names}}}),",
        f"    Typed = Table.TransformColumnTypes(Source, {{{types}}})",
        "in",
        "    Typed",
    ]


def check_names():
    """Power BI compares names without case: a measure may not share a name with any column of its
    table or with another measure anywhere in the model"""
    seen = {}
    for name, cols, _, measures, _, _ in TABLES:
        own = {c.lower() for c, _ in cols}
        for m, _, _ in measures:
            key = m.lower()
            if key in own:
                sys.exit(f"measure '{m}' clashes with a column of table '{name}' (names ignore case)")
            if key in seen:
                sys.exit(f"measure '{m}' in '{name}' clashes with a measure in '{seen[key]}'")
            seen[key] = name


def relationships():
    """many-to-one, single direction, from the fact table to each dimension; checks that key columns
    exist, that the one side is unique and that every fact value has a dimension row"""
    cols = {t[0]: [c for c, _ in t[1]] for t in TABLES}
    rows = {t[0]: t[2] for t in TABLES}
    out = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        if fc not in cols.get(ft, []) or tc not in cols.get(tt, []):
            sys.exit(f"relationship {ft}[{fc}] -> {tt}[{tc}] names a missing column")
        keys = [r[cols[tt].index(tc)] for r in rows[tt]]
        if len(set(keys)) != len(keys):
            sys.exit(f"{tt}[{tc}] is not unique, so it can't be the one side of a relationship")
        missing = {r[cols[ft].index(fc)] for r in rows[ft]} - set(keys)
        if missing:
            sys.exit(f"{ft}[{fc}] has values missing from {tt}[{tc}]: {sorted(missing)[:5]}")
        out.append({"name": f"{ft}_{fc}_{tt}".replace(" ", "_"), "fromTable": ft, "fromColumn": fc, "toTable": tt, "toColumn": tc})
    return out


def model_bim():
    check_names()
    tables = []
    for name, cols, rows, measures, sort_by, hidden in TABLES:
        columns = []
        for c, t in cols:
            col = {"name": c, "dataType": t, "sourceColumn": c, "summarizeBy": "sum" if t in ("double", "int64") and c != "MonthNo" else "none"}
            if t == "dateTime":
                col["formatString"] = "yyyy-MM-dd"
            if c in sort_by:
                col["sortByColumn"] = sort_by[c]
            if c in hidden:
                col["isHidden"] = True
            columns.append(col)
        tables.append({
            "name": name, "columns": columns,
            "partitions": [{"name": name, "mode": "import", "source": {"type": "m", "expression": partition_m(cols, rows)}}],
            "measures": [{"name": n, "expression": dax, "formatString": fmt} for n, dax, fmt in measures],
        })
    return {
        "name": "SemanticModel", "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3", "sourceQueryCulture": "en-US",
            "tables": tables,
            "relationships": relationships(),
            "annotations": [{"name": "PBI_QueryOrder", "value": json.dumps([t[0] for t in TABLES])}, {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"}],
        },
    }


# ------------------------------------------------------------------ report helpers
def lit(v):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def objects(spec):
    """{"chart": {"chartType": "box"}} -> PBIR objects; colors given as {"color": "#hex"}"""
    out = {}
    for obj, props in spec.items():
        p = {}
        for k, v in props.items():
            p[k] = {"solid": {"color": lit(v["color"])}} if isinstance(v, dict) and "color" in v else lit(v)
        out[obj] = [{"properties": p}]
    return out


def col(entity, prop, active=None):
    proj = {"field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if active is not None:
        proj["active"] = active
    return proj


def meas(entity, prop):
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def visual(name, vtype, pos, roles, title, objs=None, sort=None, show_title=True):
    x, y, w, hh = pos
    v = {"visualType": vtype, "query": {"queryState": {role: {"projections": projs} for role, projs in roles.items()}}, "drillFilterOtherVisuals": True}
    if sort:
        v["query"]["sortDefinition"] = {"sort": [{"field": sort["field"], "direction": "Ascending"}], "isDefaultSort": False}
    if objs:
        v["objects"] = objects(objs)
    v["visualContainerObjects"] = objects({"title": {"show": show_title, "text": title}})
    return {"$schema": f"{SCHEMA}/visualContainer/2.13.0/schema.json", "name": name, "position": {"x": x, "y": y, "z": 1000, "height": hh, "width": w, "tabOrder": 0}, "visual": v}


def by_col(entity, prop):
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}}


# ------------------------------------------------------------------ custom visuals
GUID = {}
ver = lambda p: tuple(int(x) for x in p.name.split(".")[1:5])
for pbiviz in sorted((ROOT / "release").glob("Atlas*.pbiviz"), key=ver):
    with zipfile.ZipFile(pbiviz) as z:
        pkg = json.loads(z.read("package.json"))
    GUID[pkg["visual"]["name"]] = (pkg["visual"]["guid"], pbiviz)
for need in ("atlasColumns", "atlasFlow", "atlasDistribution", "atlasCompare", "atlasHierarchy", "atlasProportion", "atlasTime", "atlasFinance", "atlasGauges", "atlasText", "atlasLines", "atlasParts", "atlasScatter"):
    if need not in GUID:
        sys.exit(f"release/ has no {need} .pbiviz - run make build first")
DIST, COLS, FLOW = GUID["atlasDistribution"][0], GUID["atlasColumns"][0], GUID["atlasFlow"][0]
G = {k: v[0] for k, v in GUID.items()}

PAGES = []  # (id, display name, [visuals])

# page 1: Atlas Distribution. Every visual reads Orders through the dimensions, so the slicers and
# a click on any box, bar, point or line filter the whole page.
O = "Orders"
dist = [
    visual("carrierSlicer", "slicer", (16, 16, 180, 236), {"Values": [col("Carrier", "Carrier", True)]}, "Carrier", {"data": {"mode": "Basic"}}, show_title=False),
    visual("channelSlicer", "slicer", (16, 268, 180, 132), {"Values": [col("Channel", "Channel", True)]}, "Channel", {"data": {"mode": "Basic"}}, show_title=False),
    visual("yearSlicer", "slicer", (16, 416, 180, 132), {"Values": [col("Date", "Year", True)]}, "Year", {"data": {"mode": "Basic"}}, show_title=False),
    visual("distBox", DIST, (212, 16, 520, 336), {"category": [col("Carrier", "Carrier")], "detail": [col(O, "Order ID")], "values": [meas(O, "Days to Deliver")]},
           "Box and whisker · delivery days by carrier", {"chart": {"chartType": "box", "look": "soft"}, "box": {"mean": True}, "valueAxis": {"title": True}}),
    visual("distRaincloud", DIST, (744, 16, 520, 336), {"category": [col("Device", "Device")], "detail": [col(O, "Order ID")], "values": [meas(O, "Session Minutes")]},
           "Raincloud · minutes on site by device (online orders)", {"chart": {"chartType": "violin"}, "violin": {"side": "half", "inner": "box", "points": "jitter"}}),
    visual("distHistogram", DIST, (212, 368, 520, 336), {"category": [col("Channel", "Channel")], "detail": [col(O, "Order ID")], "values": [meas(O, "Sales")]},
           "Histogram · order values by channel", {"chart": {"chartType": "histogram"}, "histogram": {"binMode": "width", "binWidth": 100}, "stats": {"median": True}}),
    visual("distParallel", DIST, (744, 368, 520, 336), {"category": [col("Product", "Category")], "detail": [col("Product", "Product")],
                                                        "values": [meas(O, m) for m in ("Sales", "Profit", "Margin %", "Units", "Avg Delivery Days")]},
           "Parallel coordinates · products across five measures", {"chart": {"chartType": "parallel"}, "parallel": {"curve": "smooth"}}),
]
PAGES.append(("atlasDistribution", "Atlas Distribution", dist))

# page 2: Atlas Columns next to the built-in column chart, on the Date dimension
ymq = [col("Date", "Year", True), col("Date", "Quarter", False), col("Date", "Month", False)]
cols = [
    visual("colsDrill", COLS, (16, 16, 616, 336), {"category": ymq, "values": [meas(O, "Sales"), meas(O, "Profit")]},
           "Atlas Columns · Year › Quarter › Month (drill down)", {"labels": {"show": True}}, sort=by_col("Date", "Year")),
    visual("builtinDrill", "clusteredColumnChart", (648, 16, 616, 336), {"Category": [dict(p) for p in ymq], "Y": [meas(O, "Sales"), meas(O, "Profit")]},
           "Built-in clustered column · same data", {"labels": {"show": True}}, sort=by_col("Date", "Year")),
    visual("colsStacked", COLS, (16, 368, 616, 336), {"category": [col("Date", "Month")], "series": [col("Channel", "Channel")], "values": [meas(O, "Sales")]},
           "Atlas Columns · monthly sales stacked by channel", {"chart": {"chartType": "stackedColumn", "look": "3d"}}, sort=by_col("Date", "Month")),
    visual("colsBar", COLS, (648, 368, 616, 336), {"category": [col("Product", "Category")], "values": [meas(O, "Sales"), meas(O, "Profit")]},
           "Atlas Columns · clustered bar by category", {"chart": {"chartType": "clusteredBar", "shape": "pill"}, "labels": {"show": True}}),
]
PAGES.append(("atlasColumns", "Atlas Columns", cols))

# page 3: Atlas Flow. The Sankey reads Orders (device to category), so it filters with the model;
# chord and network use their own small tables.
flow = [
    visual("flowSankey", FLOW, (16, 16, 800, 688), {"source": [col("Device", "Device")], "target": [col("Product", "Category")], "weight": [meas(O, "Sales")]},
           "Sankey · sales from device to product category", {"chart": {"chartType": "sankey"}}),
    visual("flowChord", FLOW, (832, 16, 432, 336), {"source": [col("Brand Switching", "From")], "target": [col("Brand Switching", "To")], "weight": [meas("Brand Switching", "Switching Customers")]},
           "Chord · brand switching", {"chart": {"chartType": "chord"}}),
    visual("flowNetwork", FLOW, (832, 368, 432, 336), {"source": [col("Product Network", "Product A")], "target": [col("Product Network", "Product B")], "weight": [meas("Product Network", "Co-purchase Orders")]},
           "Network · products bought together", {"chart": {"chartType": "network"}}),
]
PAGES.append(("atlasFlow", "Atlas Flow", flow))

# four tiles per page
Q = [(16, 16, 616, 336), (648, 16, 616, 336), (16, 368, 616, 336), (648, 368, 616, 336)]
P = "Product"

PAGES.append(("atlasCompare", "Atlas Compare", [
    visual("cmpLollipop", G["atlasCompare"], Q[0], {"category": [col(P, "Subcategory")], "values": [meas(O, "Sales")]}, "Lollipop · sales by subcategory", {"chart": {"chartType": "lollipop", "sort": "valueDesc"}, "labels": {"show": True}}),
    visual("cmpDumbbell", G["atlasCompare"], Q[1], {"category": [col(P, "Category")], "values": [meas(O, "Sales 2024"), meas(O, "Sales 2025")]}, "Dumbbell · 2024 vs 2025 by category", {"chart": {"chartType": "dumbbell", "sort": "changeDesc"}, "labels": {"show": True}}),
    visual("cmpSlope", G["atlasCompare"], Q[2], {"category": [col(P, "Subcategory")], "values": [meas(O, "Sales 2024"), meas(O, "Sales 2025")]}, "Slope · subcategories 2024 to 2025", {"chart": {"chartType": "slope"}}),
    visual("cmpRadar", G["atlasCompare"], Q[3], {"category": [col("Carrier", "Carrier")], "series": [col("Channel", "Channel")], "values": [meas(O, "Avg Delivery Days")]}, "Radar · delivery days by carrier and channel", {"chart": {"chartType": "radar"}}),
]))
PAGES.append(("atlasHierarchy", "Atlas Hierarchy", [
    visual("hiTreemap", G["atlasHierarchy"], Q[0], {"levels": [col(P, "Category"), col(P, "Subcategory"), col(P, "Product")], "values": [meas(O, "Sales")], "colorValue": [meas(O, "Margin %")]}, "Treemap · products (click a group to zoom)", {"chart": {"chartType": "treemap", "depth": 2}}),
    visual("hiSunburst", G["atlasHierarchy"], Q[1], {"levels": [col(P, "Category"), col(P, "Subcategory"), col(P, "Product")], "values": [meas(O, "Sales")]}, "Sunburst · products", {"chart": {"chartType": "sunburst"}}),
    visual("hiPack", G["atlasHierarchy"], Q[2], {"levels": [col(P, "Category"), col(P, "Subcategory"), col(P, "Product")], "values": [meas(O, "Sales")]}, "Circle packing · products", {"chart": {"chartType": "pack"}}),
    visual("hiOrg", G["atlasHierarchy"], Q[3], {"nodeId": [col("Employees", "Employee")], "parentId": [col("Employees", "Manager")], "label": [col("Employees", "Name")], "values": [meas("Employees", "Total Salary")]}, "Org chart · click a card to open its team", {"chart": {"chartType": "tree"}, "tree": {"expanded": 2}}),
]))
PAGES.append(("atlasProportion", "Atlas Proportion", [
    visual("prMekko", G["atlasProportion"], Q[0], {"category": [col("Carrier", "Carrier")], "series": [col("Channel", "Channel")], "values": [meas(O, "Sales")]}, "Mekko · carrier by channel", {"chart": {"chartType": "mekko"}}),
    visual("prWaffle", G["atlasProportion"], Q[1], {"category": [col(P, "Category")], "values": [meas(O, "Sales")]}, "Waffle · category shares", {"chart": {"chartType": "waffle"}, "waffle": {"shape": "circle"}}),
    visual("prAster", G["atlasProportion"], Q[2], {"category": [col(P, "Category")], "values": [meas(O, "Margin Score"), meas(O, "Sales")]}, "Aster · margin score, width by sales", {"chart": {"chartType": "aster"}, "radial": {"maxScore": 50}}),
    visual("prRose", G["atlasProportion"], Q[3], {"category": [col("Date", "Month")], "series": [col("Channel", "Channel")], "values": [meas(O, "Sales")]}, "Rose · sales by month and channel", {"chart": {"chartType": "rose"}, "labels": {"show": False}}, sort=by_col("Date", "Month")),
]))
PAGES.append(("atlasTime", "Atlas Time", [
    visual("tmTimeline", G["atlasTime"], (16, 16, 1248, 150), {"time": [col("Date", "Date")], "values": [meas(O, "Order Count")]}, "Timeline slicer · filters this page", {"chart": {"chartType": "timeline"}, "timeline": {"granularity": "month"}}),
    visual("tmCalendar", G["atlasTime"], (16, 182, 616, 260), {"time": [col("Date", "Date")], "values": [meas(O, "Order Count")]}, "Calendar heatmap · orders per day", {"chart": {"chartType": "calendar"}, "scale": {"mode": "quantile"}}),
    visual("tmHeat", G["atlasTime"], (648, 182, 616, 260), {"time": [col("Date", "Month")], "rows": [col("Carrier", "Carrier")], "values": [meas(O, "Avg Delivery Days")]}, "Heat grid · delivery days by carrier and month", {"chart": {"chartType": "heatgrid"}, "labels": {"show": True}}, sort=by_col("Date", "Month")),
    visual("tmStream", G["atlasTime"], (16, 458, 1248, 246), {"time": [col("Date", "Month")], "series": [col(P, "Category")], "values": [meas(O, "Sales")]}, "Stream graph · sales by category", {"chart": {"chartType": "stream"}, "labels": {"show": True}}, sort=by_col("Date", "Month")),
]))
PAGES.append(("atlasFinance", "Atlas Finance", [
    visual("fiCandle", G["atlasFinance"], Q[0], {"category": [col("Prices", "Day")], "open": [meas("Prices", "Price Open")], "high": [meas("Prices", "Price High")], "low": [meas("Prices", "Price Low")], "close": [meas("Prices", "Price Close")], "volume": [meas("Prices", "Trade Volume")]}, "Candlestick · six months", {"chart": {"chartType": "candlestick"}, "candles": {"movingAverage": 10}}, sort=by_col("Prices", "Day")),
    visual("fiWaterfall", G["atlasFinance"], Q[1], {"category": [col("Date", "Year")], "series": [col(P, "Category")], "values": [meas(O, "Sales")]}, "Waterfall · 2024 to 2025 by category", {"chart": {"chartType": "waterfall"}}, sort=by_col("Date", "Year")),
    visual("fiRibbon", G["atlasFinance"], Q[2], {"category": [col("Date", "Month")], "series": [col(P, "Category")], "values": [meas(O, "Sales")]}, "Ribbon · category rank by month", {"chart": {"chartType": "ribbon"}, "labels": {"show": False}}, sort=by_col("Date", "Month")),
    visual("fiFunnel", G["atlasFinance"], Q[3], {"category": [col("Pipeline", "Stage")], "values": [meas("Pipeline", "Deal Count")]}, "Funnel · sales pipeline", {"chart": {"chartType": "funnel"}, "funnel": {"shape": "tapered", "colors": "gradient"}}, sort=by_col("Pipeline", "Stage")),
]))
PAGES.append(("atlasGauges", "Atlas Gauges", [
    visual("gaCards", G["atlasGauges"], Q[0], {"values": [meas(O, "Sales"), meas(O, "Profit"), meas(O, "Order Count"), meas(O, "Margin %")]}, "Cards · four measures", {"chart": {"chartType": "card"}}),
    visual("gaKpi", G["atlasGauges"], Q[1], {"trend": [col("Date", "Month")], "values": [meas(O, "Sales 2025")], "target": [meas(O, "Sales Target")]}, "KPI · sales vs target by month", {"chart": {"chartType": "kpi"}}, sort=by_col("Date", "Month")),
    visual("gaGauge", G["atlasGauges"], Q[2], {"category": [col("Channel", "Channel")], "values": [meas(O, "Sales 2025")], "target": [meas(O, "Sales Target")]}, "Gauges · 2025 sales vs target by channel", {"chart": {"chartType": "gauge"}, "status": {"colorValue": True}}),
    visual("gaBullet", G["atlasGauges"], Q[3], {"category": [col(P, "Category")], "values": [meas(O, "Sales 2025")], "target": [meas(O, "Sales Target")]}, "Bullet · 2025 sales vs target by category", {"chart": {"chartType": "bullet"}}),
]))
PAGES.append(("atlasTextParts", "Atlas Text and Parts", [
    visual("ptDonut", G["atlasParts"], Q[0], {"category": [col("Channel", "Channel")], "values": [meas(O, "Sales")]}, "Donut · sales by channel", {"chart": {"chartType": "donut"}}),
    visual("ptPie", G["atlasParts"], Q[1], {"category": [col(P, "Category", True), col(P, "Subcategory", False)], "values": [meas(O, "Sales")]}, "Pie · category (drill to subcategory)", {"chart": {"chartType": "pie", "topN": 6}}),
    visual("txCloud", G["atlasText"], Q[2], {"category": [col("Reviews", "Phrase")], "values": [meas("Reviews", "Mention Count")], "colorValue": [meas("Reviews", "Avg Sentiment")]}, "Word cloud · review phrases by sentiment", {"wcolor": {"colorBy": "value"}}),
    visual("txBars", G["atlasText"], Q[3], {"category": [col("Reviews", "Phrase")], "group": [col("Reviews", "Topic")], "values": [meas("Reviews", "Mention Count")]}, "Ranked words · by topic", {"chart": {"chartType": "bars"}, "wcolor": {"colorBy": "group"}, "labels": {"show": True}}),
]))
dym = [col("Date", "Year", True), col("Date", "Quarter", False), col("Date", "Month", False)]
PAGES.append(("atlasLines", "Atlas Lines", [
    visual("lnDrill", G["atlasLines"], Q[0], {"category": dym, "values": [meas(O, "Sales")]}, "Line · Year › Quarter › Month (drill) · forecast", {"chart": {"chartType": "line"}, "lines": {"markers": "all"}, "analytics": {"forecast": 2, "trend": True}}, sort=by_col("Date", "Year")),
    visual("lnStacked", G["atlasLines"], Q[1], {"category": [col("Date", "Month")], "series": [col("Channel", "Channel")], "values": [meas(O, "Sales")]}, "Stacked area · sales by channel", {"chart": {"chartType": "stackedArea", "curve": "smooth"}}, sort=by_col("Date", "Month")),
    visual("lnCombo", G["atlasLines"], Q[2], {"category": [col("Date", "Month")], "values": [meas(O, "Sales 2024"), meas(O, "Sales 2025")], "lineValues": [meas(O, "Margin %")]}, "Line and clustered column · margin on a second axis", {"chart": {"chartType": "comboClustered"}, "lines": {"markers": "all"}}, sort=by_col("Date", "Month")),
    visual("lnZoom", G["atlasLines"], Q[3], {"category": [col("Date", "Date")], "values": [meas(O, "Order Count")]}, "Area · daily orders · zoom slider · anomalies", {"chart": {"chartType": "area", "zoom": True}, "analytics": {"anomalies": True}}, sort=by_col("Date", "Date")),
]))
PAGES.append(("atlasScatter", "Atlas Scatter", [
    visual("scBubble", G["atlasScatter"], Q[0], {"details": [col(P, "Product")], "legend": [col(P, "Category")], "x": [meas(O, "Sales")], "y": [meas(O, "Margin %")], "size": [meas(O, "Units")]}, "Bubble · products: sales vs margin (drag to zoom)", {"guides": {"quadrants": True}}),
    visual("scPlay", G["atlasScatter"], Q[1], {"details": [col(P, "Subcategory")], "legend": [col(P, "Category")], "play": [col("Date", "Year")], "x": [meas(O, "Sales")], "y": [meas(O, "Margin %")], "size": [meas(O, "Units")]}, "Bubble · play axis by year", {"labels": {"show": True}}),
    visual("scDot", G["atlasScatter"], Q[2], {"details": [col(O, "Order ID")], "xCategory": [col("Carrier", "Carrier")], "y": [meas(O, "Days to Deliver")]}, "Dot plot · delivery days per order by carrier", {"chart": {"chartType": "dotplot"}, "points": {"size": 2, "opacity": 45}}),
    visual("scGantt", G["atlasScatter"], Q[3], {"task": [col("Tasks", "Task")], "legend": [col("Tasks", "Phase")], "start": [col("Tasks", "Start")], "end": [col("Tasks", "End")], "owner": [col("Tasks", "Owner")], "progress": [meas("Tasks", "Percent Complete")]}, "Gantt · project plan", {"chart": {"chartType": "gantt"}}),
]))


# ------------------------------------------------------------------ write the project
def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    rep, sem = OUT / f"{NAME}.Report", OUT / f"{NAME}.SemanticModel"
    write(OUT / f"{NAME}.pbip", {"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
    write(OUT / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    write(sem / "definition.pbism", {"version": "1.0", "settings": {}})
    write(sem / "model.bim", model_bim())
    write(rep / "definition.pbir", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json", "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write(rep / "definition" / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})

    # base theme from the installed Power BI Desktop when there is one, else the Atlas theme alone carries the look
    packages = []
    base = None
    for cand in [pathlib.Path(r"C:\Program Files\Microsoft Power BI Desktop\bin\WebView2Resources\minerva\sharedresources\BaseThemes") / f"{BASE_THEME}.json",
                 ROOT / "tools" / "basetheme" / f"{BASE_THEME}.json"]:
        if cand.exists():
            base = cand
            break
    themes = {}
    if base:
        dst = rep / "StaticResources" / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base, dst)
        packages.append({"name": "SharedResources", "type": "SharedResources", "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]})
        themes["baseTheme"] = {"name": BASE_THEME, "reportVersionAtImport": VERSION_AT_IMPORT, "type": "SharedResources"}
    theme = ROOT / "release" / "themes" / "atlas-theme-soft.json"
    if theme.exists():
        dst = rep / "StaticResources" / "RegisteredResources" / "AtlasSoft.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(theme, dst)
        packages.append({"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": "AtlasSoft.json", "path": "AtlasSoft.json", "type": "CustomTheme"}]})
        themes["customTheme"] = {"name": "AtlasSoft.json", "reportVersionAtImport": VERSION_AT_IMPORT, "type": "RegisteredResources"}

    # private custom visuals: unpacked .pbiviz + a CustomVisual resource package each
    for _, (guid, pbiviz) in sorted(GUID.items()):
        with zipfile.ZipFile(pbiviz) as z:
            for item in z.namelist():
                if item.endswith("/"):
                    continue
                dst = rep / "CustomVisuals" / guid / item
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(item))
        packages.append({"name": guid, "type": "CustomVisual", "items": [{"name": f"{guid}.pbiviz.json", "path": f"{guid}.pbiviz.json", "type": "CustomVisualMetadata"}]})

    report = {"$schema": f"{SCHEMA}/report/3.3.0/schema.json", "themeCollection": themes, "resourcePackages": packages,
              "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True}}
    write(rep / "definition" / "report.json", report)

    # every field a visual uses must exist in the model
    known = {(t, c) for t, cols, _, ms, _, _ in TABLES for c in [x for x, _ in cols] + [m for m, _, _ in ms]}
    for _, _, visuals in PAGES:
        for v in visuals:
            for role in v["visual"]["query"]["queryState"].values():
                for pr in role["projections"]:
                    f = pr["field"].get("Column") or pr["field"].get("Measure")
                    if (f["Expression"]["SourceRef"]["Entity"], f["Property"]) not in known:
                        sys.exit(f"{v['name']}: unknown field {pr['queryRef']}")

    order = []
    for pid, title, visuals in PAGES:
        pdir = rep / "definition" / "pages" / pid
        write(pdir / "page.json", {"$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": pid, "displayName": title, "displayOption": "FitToPage", "height": 720, "width": 1280})
        for i, v in enumerate(visuals):
            v["position"]["tabOrder"] = i
            v["position"]["z"] = 1000 + i
            write(pdir / "visuals" / v["name"] / "visual.json", v)
        order.append(pid)
    write(rep / "definition" / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json", "pageOrder": order, "activePageName": order[0]})
    print("wrote", OUT / f"{NAME}.pbip", f"({len(TABLES)} tables, {sum(len(p[2]) for p in PAGES)} visuals, {len(GUID)} custom visuals)")


if __name__ == "__main__":
    main()
