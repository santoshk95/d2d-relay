"""Test stack only (item 55): the model files the Semantic Review suites upload, made here: model.bim (TMSL), a .pbit
with its report (Report/Layout), a zipped Power BI project in TMDL, a .pbix connected live (no model) and a broken one.
Each has the problems the suites expect the review to find. Standard library only."""
import io
import json
import os
import zipfile


def col(name, typ="decimal", sb="sum", hidden=False, fmt=None):
    return {"name": name, "dataType": typ, "summarizeBy": sb, "isHidden": hidden, "sourceColumn": name, **({"formatString": fmt} if fmt else {})}


def measure(name, expr, fmt=None, desc=None):
    return {"name": name, "expression": expr, **({"formatString": fmt} if fmt else {}), **({"description": desc} if desc else {})}


SALES = {"name": "Sales model", "compatibilityLevel": 1567, "model": {"tables": [
    {"name": "Sales", "columns": [col("Amount"), col("NetAmount"), col("Status", "string", "none"), col("Region", "string", "none"),
                                  col("MarginPct", "double"), col("Cost"), col("CustomerKey", "int64")],
     "measures": [
         measure("Revenue", 'CALCULATE ( SUM ( Sales[NetAmount] ), Sales[Status] = "Completed" )', "\\$#,0", "Completed sales"),
         measure("Total Revenue", ["SUM (", "    Sales[Amount]", ")"], "0.00%"),
         measure("Revenue YTD", "TOTALYTD ( SUM ( Sales[Amount] ), 'Date'[Date] )", "\\$#,0"),
         measure("Gross Margin %", "AVERAGE ( Sales[MarginPct] )", "0.0"),
         measure("Sales EU", 'VAR s = SUM ( Sales[NetAmount] ) RETURN CALCULATE ( s, Sales[Region] = "EU" )'),
         measure("Revenue per Customer", "SUMX ( Customer, SUM ( Sales[NetAmount] ) )"),
         measure("Broken", "SUM ( Sales[Nope] )"),
         measure("Net Sales", 'CALCULATE ( SUM ( Sales[NetAmount] ), Sales[Status] = "Completed" )', "\\$#,0"),
         measure("Active Customers", "COUNTROWS ( Sales )", "#,0"),
         measure("COGS", "SUM ( Sales[Cost] )", "\\$#,0"),
         measure("Turnover", "SUM ( Sales[NetAmount] )")]},
    {"name": "Customer", "columns": [col("CustomerKey", "int64", "none"), col("Name", "string", "none")]},
    {"name": "Date", "columns": [col("Date", "dateTime", "none"), col("Year", "int64")]}],
    "relationships": [{"name": "r1", "fromTable": "Sales", "fromColumn": "CustomerKey", "toTable": "Customer", "toColumn": "CustomerKey",
                       "crossFilteringBehavior": "bothDirections"}]}}

FINANCE = {"name": "Finance model", "compatibilityLevel": 1567, "model": {"tables": [
    {"name": "Fact Sales", "columns": [col("Amount"), col("Cost")],
     "measures": [measure("Revenue", "SUM ( 'Fact Sales'[Amount] )", "\\$#,0"),
                  measure("COGS", "SUM ( 'Fact Sales'[Cost] )", "\\$#,0"),
                  measure("Gross Margin %", "DIVIDE ( [Revenue] - [COGS], [Revenue] )", "0.0%")]}], "relationships": []}}


def layout(visuals: list[tuple[str, str, str]]) -> bytes:
    """A Report/Layout (UTF-16 LE, as Power BI Desktop writes it) with cards: (page, title, measure)."""
    sections = {}
    for page, title, meas in visuals:
        cfg = {"singleVisual": {"visualType": "card", "prototypeQuery": {"Version": 2, "From": [{"Name": "f", "Entity": "Fact Sales", "Type": 0}],
               "Select": [{"Measure": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": meas}, "Name": f"Fact Sales.{meas}"}]},
               "vcObjects": {"title": [{"properties": {"text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}]}}}
        sections.setdefault(page, []).append({"config": json.dumps(cfg)})
    doc = {"sections": [{"displayName": k, "visualContainers": v} for k, v in sections.items()]}
    return json.dumps(doc).encode("utf-16-le")


def pbit() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Version", "1.28")
        z.writestr("DataModelSchema", json.dumps(FINANCE).encode("utf-16-le"))
        z.writestr("Report/Layout", layout([("Overview", "Gross Margin %", "Revenue"), ("Overview", "Revenue", "Revenue")]))
    return b.getvalue()


TMDL_TABLE = """table Orders
\tlineageTag: 0001

\t/// Completed orders' net value
\tmeasure Revenue = CALCULATE ( SUM ( Orders[Net] ), Orders[Status] = "Completed" )
\t\tformatString: \\$#,0
\t\tdisplayFolder: Sales

\tmeasure 'Revenue LY' =
\t\t\tCALCULATE (
\t\t\t\t[Revenue],
\t\t\t\tSAMEPERIODLASTYEAR ( 'Calendar'[Date] )
\t\t\t)
\t\tformatString: \\$#,0

\tmeasure 'Orders Count' = COUNTROWS ( Orders )

\tcolumn Net
\t\tdataType: decimal
\t\tsummarizeBy: sum
\t\tsourceColumn: Net

\tcolumn Status
\t\tdataType: string
\t\tsummarizeBy: none
\t\tsourceColumn: Status

\tcolumn OrderID
\t\tdataType: int64
\t\tsummarizeBy: sum
\t\tsourceColumn: OrderID

\tpartition Orders = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t    Source = Csv.Document(File.Contents("C:\\\\data\\\\orders.csv"))
\t\t\t\tin
\t\t\t\t    Source
"""
TMDL_CAL = """table Calendar
\tcolumn Date
\t\tdataType: dateTime
\t\tsummarizeBy: none
"""
TMDL_REL = """relationship 5e3b
\tfromColumn: Orders.OrderDate
\ttoColumn: Calendar.Date
"""


def pbip() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Ops.pbip", json.dumps({"version": "1.0"}))
        z.writestr("Ops.SemanticModel/definition/model.tmdl", "model Model\n\tculture: en-US\n")
        z.writestr("Ops.SemanticModel/definition/tables/Orders.tmdl", TMDL_TABLE)
        z.writestr("Ops.SemanticModel/definition/tables/Calendar.tmdl", TMDL_CAL)
        z.writestr("Ops.SemanticModel/definition/relationships.tmdl", TMDL_REL)
    return b.getvalue()


def live_pbix() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Version", "1.28")
        z.writestr("Connections", json.dumps({"Version": 3, "Connections": [{"Name": "EntityDataSource", "ConnectionType": "pbiServiceLive"}]}))
        z.writestr("Report/Layout", layout([("Page 1", "Revenue", "Revenue")]))
    return b.getvalue()


def broken_pbix() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Version", "1.28")
        z.writestr("DataModel", "This backup was created using XPress9 compression.".encode("utf-16-le") + os.urandom(4096))
    return b.getvalue()
