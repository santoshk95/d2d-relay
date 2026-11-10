#!/usr/bin/env python3
"""Reference definition for the Atlas Retail report: semantic model + 5 pages.

This is the hand-written version of what the Gen BI pipeline will later ask the AI to produce
(same JSON schema). Running it writes definition.json and builds the Power BI project:

    python reference.py [--data-folder C:\\path\\to\\Data\\] [--out ../../output/GlobalRetail]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from genbi_kit import report_builder  # noqa: E402

CUR, CUR2, SCUR = "\\$#,0", "\\$#,0.00", "+\\$#,0;-\\$#,0;\\$#,0"
PCT, SPCT, PCT0 = "0.0%", "+0.0%;-0.0%;0.0%", "0%"
INT, SINT = "#,0", "+#,0;-#,0;0"
WKS = '0.0" wks"'
SPTS = '+0.00" pts";-0.00" pts";0.00" pts"'
LFL = '"Like-for-like stores"'


# ---------------------------------------------------------------- model
def csv_table(name, file, columns, renames=None, nulls=False, hidden=(), description=""):
    cols = []
    for col, typ in columns:
        model_name = (renames or {}).get(col, col)
        cols.append({"name": model_name, "source": col, "type": typ, "hidden": col in hidden or model_name in hidden})
    return {"name": name, "csv": file, "columns": cols, "blanks_to_null": nulls, "description": description}


TABLES = [
    csv_table("Country", "dim_country.csv", [("CountryKey", "int"), ("CountryCode", "string"), ("Country", "string"),
              ("Region", "string"), ("Currency", "string"), ("OnlineAvailable", "string")],
              hidden={"CountryKey"}, description="Countries and regions"),
    csv_table("Store", "dim_store.csv", [("StoreKey", "int"), ("StoreCode", "string"), ("Store", "string"),
              ("StoreType", "string"), ("Channel", "string"), ("Format", "string"), ("City", "string"),
              ("CountryKey", "int"), ("OpenDate", "date"), ("CloseDate", "date"), ("SellingAreaSqm", "int"),
              ("Manager", "string")], nulls=True, hidden={"StoreKey", "CountryKey"},
              description="Physical stores plus one online store per online market"),
    csv_table("Category", "dim_category.csv", [("CategoryKey", "int"), ("Category", "string"),
              ("Department", "string"), ("SortOrder", "int")], hidden={"CategoryKey", "SortOrder"}),
    csv_table("Sales", "fact_sales.csv", [("Date", "date"), ("StoreKey", "int"), ("CategoryKey", "int"),
              ("NetSales", "decimal"), ("GrossProfit", "decimal"), ("Units", "int"), ("Discount", "decimal")],
              renames={"Units": "Unit Count", "Discount": "Discount Amount"},
              hidden={"Date", "StoreKey", "CategoryKey", "NetSales", "GrossProfit", "Unit Count", "Discount Amount"},
              description="Daily sales by store and category"),
    csv_table("Targets", "fact_targets.csv", [("Month", "date"), ("StoreKey", "int"), ("SalesTarget", "decimal"),
              ("GrossProfitTarget", "decimal")], hidden={"Month", "StoreKey", "SalesTarget", "GrossProfitTarget"}),
    csv_table("Footfall", "fact_footfall.csv", [("Date", "date"), ("StoreKey", "int"), ("Hour", "int"),
              ("Footfall", "int"), ("Transactions", "int")], renames={"Footfall": "Visitors",
              "Transactions": "Transaction Count"}, hidden={"Date", "StoreKey", "Visitors", "Transaction Count"},
              description="Hourly footfall and transactions, physical stores"),
    csv_table("Inventory", "fact_inventory.csv", [("WeekEnding", "date"), ("StoreKey", "int"),
              ("CategoryKey", "int"), ("StockValue", "decimal"), ("StockUnits", "int")],
              hidden={"WeekEnding", "StoreKey", "CategoryKey", "StockValue", "StockUnits"}),
    csv_table("Online Funnel", "fact_online_funnel.csv", [("Date", "date"), ("CountryKey", "int"),
              ("Device", "string"), ("Source", "string"), ("Sessions", "int"), ("ProductViews", "int"),
              ("AddToCart", "int"), ("Checkouts", "int"), ("Orders", "int")],
              renames={"Sessions": "Session Count", "Orders": "Order Count"},
              hidden={"Date", "CountryKey", "Session Count", "ProductViews", "AddToCart", "Checkouts", "Order Count"}),
    csv_table("Customers", "fact_customers.csv", [("Month", "date"), ("StoreKey", "int"), ("Tier", "string"),
              ("ActiveCustomers", "int"), ("NewCustomers", "int"), ("RepeatCustomers", "int"),
              ("CustomerSales", "decimal")],
              hidden={"Month", "StoreKey", "ActiveCustomers", "NewCustomers", "RepeatCustomers", "CustomerSales"}),
    csv_table("Cohorts", "fact_cohorts.csv", [("CohortMonth", "date"), ("CountryKey", "int"), ("MonthsSince", "int"),
              ("CohortSize", "int"), ("ActiveCustomers", "int")],
              hidden={"CohortMonth", "CountryKey", "CohortSize", "ActiveCustomers"}),
    {"name": "Date", "date_table": True, "description": "Calendar built in Power Query",
     "m": """let
    Start = #date(2024, 1, 1),
    End = #date(2026, 12, 31),
    Dates = List.Dates(Start, Duration.Days(End - Start) + 1, #duration(1, 0, 0, 0)),
    Base = Table.TransformColumnTypes(Table.FromList(Dates, Splitter.SplitByNothing(), {"Date"}), {{"Date", type date}}),
    Year = Table.AddColumn(Base, "Year", each Date.Year([Date]), Int64.Type),
    MonthNumber = Table.AddColumn(Year, "Month Number", each Date.Month([Date]), Int64.Type),
    Month = Table.AddColumn(MonthNumber, "Month", each Date.ToText([Date], [Format = "MMM", Culture = "en-US"]), type text),
    MonthStart = Table.AddColumn(Month, "Month Start", each Date.StartOfMonth([Date]), type date),
    YearMonth = Table.AddColumn(MonthStart, "Year Month", each Date.ToText([Date], [Format = "yyyy-MM", Culture = "en-US"]), type text),
    Quarter = Table.AddColumn(YearMonth, "Quarter", each "Q" & Text.From(Date.QuarterOfYear([Date])), type text),
    WeekdayNumber = Table.AddColumn(Quarter, "Weekday Number", each Date.DayOfWeek([Date], Day.Monday) + 1, Int64.Type),
    Weekday = Table.AddColumn(WeekdayNumber, "Weekday", each Date.ToText([Date], [Format = "ddd", Culture = "en-US"]), type text),
    WeekdayName = Table.AddColumn(Weekday, "Weekday Name", each Date.ToText([Date], [Format = "dddd", Culture = "en-US"]), type text),
    KeyEvent = Table.AddColumn(WeekdayName, "Key Event", each
        let m = Date.Month([Date]), d = Date.Day([Date]) in
        if (m = 3 and d >= 20) or (m = 4 and d <= 5) then "Spring sale"
        else if m = 7 and d <= 16 then "Summer sale"
        else if m = 10 and d <= 19 then "Autumn promo"
        else if m = 11 and d >= 24 then "Black Friday"
        else if m = 12 and d >= 10 and d <= 24 then "Christmas"
        else null, type text)
in
    KeyEvent""",
     "columns": [{"name": "Date", "type": "date"}, {"name": "Year", "type": "int"},
                 {"name": "Month Number", "type": "int", "hidden": True}, {"name": "Month", "type": "string", "sortBy": "Month Number"},
                 {"name": "Month Start", "type": "date"}, {"name": "Year Month", "type": "string"},
                 {"name": "Quarter", "type": "string"}, {"name": "Weekday Number", "type": "int", "hidden": True},
                 {"name": "Weekday", "type": "string", "sortBy": "Weekday Number"},
                 {"name": "Weekday Name", "type": "string", "sortBy": "Weekday Number"},
                 {"name": "Key Event", "type": "string"}]},
    {"name": "Sales Driver", "description": "Drivers of the change in sales vs last year (DAX calculated table)",
     "dax": 'DATATABLE ( "Driver", STRING, "Sort", INTEGER, { { "Like-for-like stores", 1 }, { "Online", 2 }, '
            '{ "New stores", 3 }, { "Closed stores", 4 }, { "Price and promo", 5 } } )',
     "columns": [{"name": "Driver", "type": "string", "sortBy": "Sort"}, {"name": "Sort", "type": "int", "hidden": True}]},
    {"name": "Metrics", "description": "Home of all measures (DAX calculated table)",
     "dax": 'DATATABLE ( "Metric", STRING, { { "Measures live here" } } )',
     "columns": [{"name": "Metric", "type": "string", "hidden": True}]},
]

CALCULATED = [
    {"table": "Date", "name": "Is Past", "type": "bool", "hidden": True,
     "expression": "'Date'[Date] <= MAX ( Sales[Date] )"},
    {"table": "Store", "name": "Store Group", "type": "string",
     "expression": "SWITCH ( TRUE (), 'Store'[StoreType] = \"Online\", \"Online\", NOT ISBLANK ( 'Store'[CloseDate] ), "
                   "\"Closed stores\", 'Store'[OpenDate] > DATE ( 2025, 1, 1 ), \"New stores\", \"Like-for-like stores\" )"},
    {"table": "Store", "name": "Region", "type": "string", "expression": "RELATED ( 'Country'[Region] )"},
    {"table": "Store", "name": "Country", "type": "string", "expression": "RELATED ( 'Country'[Country] )"},
]

RELATIONSHIPS = [
    ("Sales[Date]", "Date[Date]"), ("Sales[StoreKey]", "Store[StoreKey]"), ("Sales[CategoryKey]", "Category[CategoryKey]"),
    ("Store[CountryKey]", "Country[CountryKey]"),
    ("Targets[Month]", "Date[Date]"), ("Targets[StoreKey]", "Store[StoreKey]"),
    ("Footfall[Date]", "Date[Date]"), ("Footfall[StoreKey]", "Store[StoreKey]"),
    ("Inventory[WeekEnding]", "Date[Date]"), ("Inventory[StoreKey]", "Store[StoreKey]"),
    ("Inventory[CategoryKey]", "Category[CategoryKey]"),
    ("'Online Funnel'[Date]", "Date[Date]"), ("'Online Funnel'[CountryKey]", "Country[CountryKey]"),
    ("Customers[Month]", "Date[Date]"), ("Customers[StoreKey]", "Store[StoreKey]"),
    ("Cohorts[CohortMonth]", "Date[Date]"), ("Cohorts[CountryKey]", "Country[CountryKey]"),
]


# ---------------------------------------------------------------- measures
MEASURES = []


def m(name, expression, fmt="", folder="", description="", guard=None):
    """guard: only evaluate when this measure has a value (keeps title measures from adding empty rows)."""
    expression = expression.strip()
    if guard:
        expression = f"IF ( NOT ISBLANK ( [{guard}] ),\n{expression}\n)"
    MEASURES.append({"name": name, "expression": expression, "format": fmt, "folder": folder,
                     "description": description})


def ly(measure):
    """Same period last year, limited to dates that already have data (so YTD compares like for like)."""
    return (f"CALCULATE ( [{measure}], SAMEPERIODLASTYEAR ( CALCULATETABLE ( VALUES ( 'Date'[Date] ), "
            f"'Date'[Is Past] = TRUE () ) ) )")


def change(a, b):
    return f"DIVIDE ( [{a}] - [{b}], [{b}] )"


def card(measure, guard="Net Sales"):
    """KPI card value: ignores the sparkline's month axis, blank for months without data."""
    return f"IF ( ISBLANK ( [{guard}] ), BLANK (), CALCULATE ( [{measure}], ALLSELECTED ( 'Date'[Month Start] ) ) )"


def lfl_only(measure):
    return f"IF ( SELECTEDVALUE ( 'Store'[Store Group] ) = {LFL}, [{measure}] )"


WEEKDAY = ('SWITCH ( {}, 1, "Monday", 2, "Tuesday", 3, "Wednesday", 4, "Thursday", 5, "Friday", 6, "Saturday", '
           '"Sunday" )')
PAST = "'Date'[Is Past] = TRUE ()"

# --- sales core
m("Net Sales", "SUM ( Sales[NetSales] )", CUR, "Sales", "Sales after discounts")
m("Gross Profit", "SUM ( Sales[GrossProfit] )", CUR, "Sales")
m("Gross Margin %", "DIVIDE ( [Gross Profit], [Net Sales] )", PCT, "Sales")
m("COGS", "[Net Sales] - [Gross Profit]", CUR, "Sales")
m("Discount", "SUM ( Sales[Discount Amount] )", CUR, "Sales", "Markdown and promotion cost")
m("Units", "SUM ( Sales[Unit Count] )", INT, "Sales")
m("Net Sales LY", ly("Net Sales"), CUR, "Sales")
m("Gross Profit LY", ly("Gross Profit"), CUR, "Sales")
m("Gross Margin % LY", "DIVIDE ( [Gross Profit LY], [Net Sales LY] )", PCT, "Sales")
m("Discount LY", ly("Discount"), CUR, "Sales")
m("Units LY", ly("Units"), INT, "Sales")
m("Sales Change vs LY", "[Net Sales] - [Net Sales LY]", SCUR, "Sales")
m("Net Sales vs LY %", change("Net Sales", "Net Sales LY"), SPCT, "Sales")
m("Sales Target", f"CALCULATE ( SUM ( Targets[SalesTarget] ), {PAST} )", CUR, "Targets", "Plan for months that have actuals")
m("Gross Profit Target", f"CALCULATE ( SUM ( Targets[GrossProfitTarget] ), {PAST} )", CUR, "Targets")
m("Gross Margin Target %", "DIVIDE ( [Gross Profit Target], [Sales Target] )", PCT, "Targets")
m("Net Sales vs Target %", "VAR t = [Sales Target] RETURN IF ( NOT ISBLANK ( t ), DIVIDE ( [Net Sales] - t, t ) )", SPCT, "Targets")
m("LFL Sales", f"CALCULATE ( [Net Sales], 'Store'[Store Group] = {LFL} )", CUR, "Like-for-like")
m("LFL Sales LY", f"CALCULATE ( [Net Sales LY], 'Store'[Store Group] = {LFL} )", CUR, "Like-for-like")
m("LFL Growth %", change("LFL Sales", "LFL Sales LY"), SPCT, "Like-for-like", "Growth of stores open all of last year")
m("LFL Growth Target %", f"VAR t = CALCULATE ( [Sales Target], 'Store'[Store Group] = {LFL} ) VAR l = [LFL Sales LY] "
  "RETURN DIVIDE ( t - l, l )", SPCT, "Like-for-like")
m("LFL Growth LY %", ly("LFL Growth %"), SPCT, "Like-for-like")

# --- inventory
LAST_WEEK = f"VAR LastWeek = CALCULATE ( MAX ( Inventory[WeekEnding] ), {PAST} )"
m("Stock Value", f"{LAST_WEEK} RETURN IF ( NOT ISBLANK ( LastWeek ), CALCULATE ( SUM ( Inventory[StockValue] ), 'Date'[Date] = LastWeek ) )", CUR,
  "Inventory", "Closing stock at cost (latest week in the period)")
m("Avg Weekly COGS (13w)", f"{LAST_WEEK} RETURN IF ( NOT ISBLANK ( LastWeek ), DIVIDE ( CALCULATE ( [COGS], "
  "REMOVEFILTERS ( 'Date' ), DATESINPERIOD ( 'Date'[Date], LastWeek, -91, DAY ), 'Store'[StoreType] = \"Physical\" ), 13 ) )",
  CUR, "Inventory")
m("Inventory Cover (wks)", "DIVIDE ( [Stock Value], [Avg Weekly COGS (13w)] )", WKS, "Inventory")
m("Inventory Cover LY (wks)", ly("Inventory Cover (wks)"), WKS, "Inventory")
m("Inventory Cover Target (wks)", "7", WKS, "Inventory")

# --- KPI card helpers (value ignores the sparkline axis)
for base in ["Net Sales", "Sales Target", "Net Sales LY", "Gross Margin %", "Gross Margin Target %", "Gross Margin % LY",
             "LFL Growth %", "LFL Growth Target %", "LFL Growth LY %", "Inventory Cover (wks)",
             "Inventory Cover Target (wks)", "Inventory Cover LY (wks)", "Units", "Units LY"]:
    src = next(x for x in MEASURES if x["name"] == base)
    m(f"{base} (card)", card(base), src["format"], "Cards")

# --- overview visuals
m("Event Label", "IF ( NOT ISBLANK ( [Net Sales] ), CALCULATE ( SELECTEDVALUE ( 'Date'[Key Event] ), "
  "NOT ISBLANK ( 'Date'[Key Event] ) ) )", "", "Titles")
m("Title Sales Trend", """
IF ( NOT ISBLANK ( [Net Sales] ),
    VAR s = CALCULATE ( [Net Sales], ALLSELECTED ( 'Date' ) )
    VAR t = CALCULATE ( [Sales Target], ALLSELECTED ( 'Date' ) )
    VAR l = CALCULATE ( [Net Sales LY], ALLSELECTED ( 'Date' ) )
    VAR vt = DIVIDE ( s - t, t )
    VAR vl = DIVIDE ( s - l, l )
    RETURN "Sales are " & FORMAT ( ABS ( vt ), "0.0%" ) & IF ( vt >= 0, " ahead of", " behind" ) & " target and "
        & FORMAT ( ABS ( vl ), "0.0%" ) & IF ( vl >= 0, " up on", " down on" ) & " last year"
)""", "", "Titles")
m("Sales Change by Driver", f"""
VAR d = SELECTEDVALUE ( 'Sales Driver'[Driver] )
VAR promo = CALCULATE ( [Discount] - [Discount LY], 'Store'[Store Group] = {LFL} )
RETURN SWITCH ( d,
    "Like-for-like stores", CALCULATE ( [Sales Change vs LY], 'Store'[Store Group] = {LFL} ) + promo,
    "Online", CALCULATE ( [Sales Change vs LY], 'Store'[Store Group] = "Online" ),
    "New stores", CALCULATE ( [Sales Change vs LY], 'Store'[Store Group] = "New stores" ),
    "Closed stores", CALCULATE ( [Sales Change vs LY], 'Store'[Store Group] = "Closed stores" ),
    "Price and promo", - promo )""", SCUR, "Drivers", "Bridge from last year's sales to this year's")
m("Title Drivers", """
VAR total = [Sales Change vs LY]
VAR lfl = CALCULATE ( [Sales Change by Driver], 'Sales Driver'[Driver] = "Like-for-like stores" )
RETURN IF ( total >= 0,
    "Like-for-like stores delivered " & FORMAT ( DIVIDE ( lfl, total ), "0%" ) & " of the "
        & FORMAT ( total / 1000000, "$#,0.0" ) & "M growth",
    "Sales are " & FORMAT ( - total / 1000000, "$#,0.0" ) & "M below last year" )""", "", "Titles")
m("LFL Store Growth %", lfl_only("Net Sales vs LY %"), SPCT, "Stores")
m("LFL Store Margin %", lfl_only("Gross Margin %"), PCT, "Stores")
m("LFL Store Sales", lfl_only("Net Sales"), CUR, "Stores")
m("Growth Target %", "CALCULATE ( [LFL Growth Target %], ALLSELECTED ( 'Store' ) )", SPCT, "Stores")
m("Avg LFL Margin %", f"CALCULATE ( [Gross Margin %], ALLSELECTED ( 'Store' ), 'Store'[Store Group] = {LFL} )", PCT, "Stores")
m("Title Store Quadrant", """
VAR target = [Growth Target %]
VAR avgm = [Avg LFL Margin %]
VAR n = COUNTROWS ( FILTER ( ALLSELECTED ( 'Store'[Store] ), [LFL Store Growth %] > target && [LFL Store Margin %] > avgm ) )
RETURN FORMAT ( COALESCE ( n, 0 ), "0" ) & " stores beat both the growth target and average margin" """, "", "Titles")
m("Title Category Mix", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Category'[Category] ), "@s", [Net Sales], "@m", [Gross Margin %] )
VAR total = SUMX ( t, [@s] )
VAR big = TOPN ( 1, t, [@s], DESC )
VAR best = TOPN ( 1, t, [@m], DESC )
RETURN MAXX ( big, 'Category'[Category] ) & " is " & FORMAT ( DIVIDE ( MAXX ( big, [@s] ), total ), "0%" )
    & " of sales at " & FORMAT ( MAXX ( big, [@m] ), "0.0%" ) & " margin; " & MAXX ( best, 'Category'[Category] )
    & " earns " & FORMAT ( MAXX ( best, [@m] ), "0%" )""", "", "Titles", guard="Net Sales")

# --- stores / footfall
m("Footfall", "SUM ( Footfall[Visitors] )", INT, "Stores")
m("Footfall LY", ly("Footfall"), INT, "Stores")
m("Footfall vs LY %", change("Footfall", "Footfall LY"), SPCT, "Stores")
m("Transactions", "SUM ( Footfall[Transaction Count] )", INT, "Stores")
m("Store Conversion %", "DIVIDE ( [Transactions], [Footfall] )", PCT, "Stores", "Transactions per visitor")
m("Store Conversion % LY", ly("Store Conversion %"), PCT, "Stores")
m("Store Sales", "CALCULATE ( [Net Sales], 'Store'[Channel] = \"Store\" )", CUR, "Stores")
m("Store Sales LY", ly("Store Sales"), CUR, "Stores")
m("Avg Transaction Value", "DIVIDE ( [Store Sales], [Transactions] )", CUR2, "Stores")
m("Avg Transaction Value LY", ly("Avg Transaction Value"), CUR2, "Stores")
m("Sales per sqm", "DIVIDE ( [Store Sales], CALCULATE ( SUM ( 'Store'[SellingAreaSqm] ), 'Store'[Channel] = \"Store\" ) )",
  CUR, "Stores")
m("Sales per sqm LY", ly("Sales per sqm"), CUR, "Stores")
for base in ["Footfall", "Footfall LY", "Store Conversion %", "Store Conversion % LY", "Avg Transaction Value",
             "Avg Transaction Value LY", "Sales per sqm", "Sales per sqm LY"]:
    src = next(x for x in MEASURES if x["name"] == base)
    m(f"{base} (card)", card(base), src["format"], "Cards")
m("Title Footfall Trend", """
IF ( NOT ISBLANK ( [Footfall] ),
    VAR f = CALCULATE ( [Footfall], ALLSELECTED ( 'Date' ) )
    VAR fl = CALCULATE ( [Footfall LY], ALLSELECTED ( 'Date' ) )
    VAR c = CALCULATE ( [Store Conversion %], ALLSELECTED ( 'Date' ) )
    VAR cl = CALCULATE ( [Store Conversion % LY], ALLSELECTED ( 'Date' ) )
    VAR g = DIVIDE ( f - fl, fl )
    RETURN "Footfall is " & FORMAT ( ABS ( g ), "0.0%" ) & IF ( g >= 0, " up", " down" ) & " on last year; conversion "
        & FORMAT ( ( c - cl ) * 100, "+0.0;-0.0" ) & " pts"
)""", "", "Titles")
m("Title Region Change", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Country'[Region] ), "@c", [Sales Change vs LY] )
VAR leader = TOPN ( 1, t, [@c], DESC )
RETURN MAXX ( leader, 'Country'[Region] ) & " added the most sales: " & FORMAT ( MAXX ( leader, [@c] ) / 1000000, "+$#,0.0;-$#,0.0" )
    & "M vs last year" """, "", "Titles", guard="Sales Change vs LY")
m("LFL Footfall vs LY %", lfl_only("Footfall vs LY %"), SPCT, "Stores")
m("LFL Store Conversion %", lfl_only("Store Conversion %"), PCT, "Stores")
m("LFL Store Sales (stores)", lfl_only("Store Sales"), CUR, "Stores")
m("Zero Line", "0", SPCT, "Stores")
m("Avg Store Conversion %", f"CALCULATE ( [Store Conversion %], ALLSELECTED ( 'Store' ), 'Store'[Store Group] = {LFL} )",
  PCT, "Stores")
m("Title Store Traffic", """
VAR avgc = [Avg Store Conversion %]
VAR n = COUNTROWS ( FILTER ( ALLSELECTED ( 'Store'[Store] ), [LFL Footfall vs LY %] > 0 && [LFL Store Conversion %] > avgc ) )
RETURN FORMAT ( COALESCE ( n, 0 ), "0" ) & " stores grew traffic and convert above average" """, "", "Titles")
m("Title Conversion Heatmap", f"""
VAR t = ADDCOLUMNS ( CROSSJOIN ( ALLSELECTED ( 'Date'[Weekday], 'Date'[Weekday Number] ), ALLSELECTED ( Footfall[Hour] ) ),
    "@f", [Footfall], "@c", [Store Conversion %] )
VAR leader = TOPN ( 1, t, [@f], DESC )
VAR wd = MAXX ( leader, 'Date'[Weekday Number] )
VAR h = MAXX ( leader, Footfall[Hour] )
VAR avgc = CALCULATE ( [Store Conversion %], ALLSELECTED ( 'Date' ), ALLSELECTED ( Footfall[Hour] ) )
RETURN "Conversion dips to " & FORMAT ( MAXX ( leader, [@c] ), "0.0%" ) & " in the busiest hour (" & {WEEKDAY.format("wd")}
    & " " & FORMAT ( h, "00" ) & ":00) vs " & FORMAT ( avgc, "0.0%" ) & " overall" """, "", "Titles", guard="Store Conversion %")
m("Title Footfall Heatmap", f"""
VAR t = ADDCOLUMNS ( CROSSJOIN ( ALLSELECTED ( 'Date'[Weekday], 'Date'[Weekday Number] ), ALLSELECTED ( Footfall[Hour] ) ),
    "@f", [Footfall] )
VAR leader = TOPN ( 1, t, [@f], DESC )
VAR wd = MAXX ( leader, 'Date'[Weekday Number] )
VAR h = MAXX ( leader, Footfall[Hour] )
RETURN {WEEKDAY.format("wd")} & IF ( h < 12, " mornings", IF ( h < 17, " afternoons", " evenings" ) )
    & " are the busiest; roster for " & FORMAT ( h - 1, "00" ) & ":00-" & FORMAT ( h + 3, "00" ) & ":00" """, "", "Titles", guard="Footfall")
m("Title Country Mix", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Country'[Country] ), "@s", [Net Sales], "@g", [LFL Growth %] )
VAR total = SUMX ( t, [@s] )
VAR big = TOPN ( 1, t, [@s], DESC )
VAR fast = TOPN ( 1, FILTER ( t, [@s] > total * 0.01 ), [@g], DESC )
RETURN MAXX ( big, 'Country'[Country] ) & " is " & FORMAT ( DIVIDE ( MAXX ( big, [@s] ), total ), "0%" ) & " of sales; "
    & MAXX ( fast, 'Country'[Country] ) & " grows fastest like-for-like (" & FORMAT ( MAXX ( fast, [@g] ), "+0.0%;-0.0%" ) & ")" """,
  "", "Titles", guard="Net Sales")

# --- categories
m("Margin Change Contribution (pts)", """
VAR s = CALCULATE ( [Net Sales], ALLSELECTED ( 'Category' ) )
VAR sl = CALCULATE ( [Net Sales LY], ALLSELECTED ( 'Category' ) )
RETURN ( DIVIDE ( [Gross Profit], s ) - DIVIDE ( [Gross Profit LY], sl ) ) * 100""", SPTS, "Categories",
  "Each category's contribution to the change in gross margin vs last year")
m("Title Margin Trend", """
IF ( NOT ISBLANK ( [Net Sales] ),
    VAR g = CALCULATE ( [Gross Margin %], ALLSELECTED ( 'Date' ) )
    VAR gt = CALCULATE ( [Gross Margin Target %], ALLSELECTED ( 'Date' ) )
    VAR gl = CALCULATE ( [Gross Margin % LY], ALLSELECTED ( 'Date' ) )
    VAR a = ( g - gt ) * 100
    VAR b = ( g - gl ) * 100
    RETURN "Margin is " & FORMAT ( ABS ( a ), "0.0" ) & " pts " & IF ( a >= 0, "above", "under" ) & " target and "
        & FORMAT ( ABS ( b ), "0.0" ) & " pts " & IF ( b >= 0, "above", "below" ) & " last year"
)""", "", "Titles")
m("Title Margin Drivers", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Category'[Category] ), "@c", [Margin Change Contribution (pts)] )
VAR worst = TOPN ( 1, t, [@c], ASC )
VAR best = TOPN ( 1, t, [@c], DESC )
RETURN MAXX ( worst, 'Category'[Category] ) & " took " & FORMAT ( ABS ( MAXX ( worst, [@c] ) ), "0.00" ) & " pts off margin; "
    & MAXX ( best, 'Category'[Category] ) & " added " & FORMAT ( MAXX ( best, [@c] ), "0.00" )""", "", "Titles", guard="Margin Change Contribution (pts)")
m("Total Growth %", "CALCULATE ( [Net Sales vs LY %], ALLSELECTED ( 'Category' ) )", SPCT, "Categories")
m("Total Margin %", "CALCULATE ( [Gross Margin %], ALLSELECTED ( 'Category' ) )", PCT, "Categories")
m("Title Category Quadrant", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Category'[Category] ), "@g", [Net Sales vs LY %] )
VAR best = TOPN ( 1, t, [@g], DESC )
VAR worst = TOPN ( 1, t, [@g], ASC )
RETURN MAXX ( best, 'Category'[Category] ) & " leads growth at " & FORMAT ( MAXX ( best, [@g] ), "+0.0%;-0.0%" ) & "; "
    & MAXX ( worst, 'Category'[Category] ) & IF ( MAXX ( worst, [@g] ) < 0, " is shrinking", " lags" ) & " ("
    & FORMAT ( MAXX ( worst, [@g] ), "+0.0%;-0.0%" ) & ")" """, "", "Titles")
m("Title Category Growth", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Category'[Category] ), "@g", CALCULATE ( [Net Sales vs LY %], ALLSELECTED ( 'Date' ) ) )
VAR best = TOPN ( 1, t, [@g], DESC )
VAR worst = TOPN ( 1, t, [@g], ASC )
RETURN MAXX ( best, 'Category'[Category] ) & " grew fastest (" & FORMAT ( MAXX ( best, [@g] ), "+0.0%;-0.0%" ) & "); "
    & MAXX ( worst, 'Category'[Category] ) & " " & FORMAT ( MAXX ( worst, [@g] ), "+0.0%;-0.0%" ) & " vs last year" """,
  "", "Titles", guard="Net Sales vs LY %")
m("Title Category Change", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Category'[Category] ), "@c", [Sales Change vs LY] )
VAR leader = TOPN ( 1, t, [@c], DESC )
RETURN MAXX ( leader, 'Category'[Category] ) & " added the most sales: " & FORMAT ( MAXX ( leader, [@c] ) / 1000000, "+$#,0.0;-$#,0.0" )
    & "M vs last year" """, "", "Titles", guard="Sales Change vs LY")
m("Title Inventory Mix", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Category'[Category] ), "@w", [Inventory Cover (wks)] )
VAR hi = TOPN ( 1, t, [@w], DESC )
VAR lo = TOPN ( 1, t, [@w], ASC )
RETURN MAXX ( hi, 'Category'[Category] ) & " holds " & FORMAT ( MAXX ( hi, [@w] ), "0.0" ) & " weeks of cover; "
    & MAXX ( lo, 'Category'[Category] ) & " only " & FORMAT ( MAXX ( lo, [@w] ), "0.0" )""", "", "Titles", guard="Stock Value")

# --- customers
m("Active Customers", "AVERAGEX ( VALUES ( 'Date'[Month Start] ), CALCULATE ( SUM ( Customers[ActiveCustomers] ) ) )",
  INT, "Customers", "Average monthly active loyalty members")
m("Active Customers LY", ly("Active Customers"), INT, "Customers")
m("Active Customers vs LY %", change("Active Customers", "Active Customers LY"), SPCT, "Customers")
m("New Customers", "SUM ( Customers[NewCustomers] )", INT, "Customers")
m("New Customers LY", ly("New Customers"), INT, "Customers")
m("Repeat Rate %", "DIVIDE ( SUM ( Customers[RepeatCustomers] ), SUM ( Customers[ActiveCustomers] ) )", PCT, "Customers")
m("Repeat Rate % LY", ly("Repeat Rate %"), PCT, "Customers")
m("Spend per Customer", "DIVIDE ( SUM ( Customers[CustomerSales] ), SUM ( Customers[ActiveCustomers] ) )", CUR2,
  "Customers", "Monthly spend per active member")
m("Spend per Customer LY", ly("Spend per Customer"), CUR2, "Customers")
m("Member Sales", "SUM ( Customers[CustomerSales] )", CUR, "Customers")
m("Member Sales LY", ly("Member Sales"), CUR, "Customers")
m("Member Sales Change", "[Member Sales] - [Member Sales LY]", SCUR, "Customers")
m("Cohort Retention %", "DIVIDE ( SUM ( Cohorts[ActiveCustomers] ), SUM ( Cohorts[CohortSize] ) )", PCT0, "Customers")
m("Active", "[Active Customers]", INT, "Customer funnel")
m("Repeat", "AVERAGEX ( VALUES ( 'Date'[Month Start] ), CALCULATE ( SUM ( Customers[RepeatCustomers] ) ) )", INT, "Customer funnel")
m("Gold & Platinum", "CALCULATE ( [Active Customers], Customers[Tier] IN { \"Gold\", \"Platinum\" } )", INT, "Customer funnel")
m("Platinum", "CALCULATE ( [Active Customers], Customers[Tier] = \"Platinum\" )", INT, "Customer funnel")
m("Avg Spend per Customer", "CALCULATE ( [Spend per Customer], ALLSELECTED ( 'Country' ) )", CUR2, "Customers")
for base in ["Active Customers", "Active Customers LY", "New Customers", "New Customers LY", "Repeat Rate %",
             "Repeat Rate % LY", "Spend per Customer", "Spend per Customer LY"]:
    src = next(x for x in MEASURES if x["name"] == base)
    m(f"{base} (card)", card(base), src["format"], "Cards")
m("Title Customer Trend", """
IF ( NOT ISBLANK ( [Active Customers] ),
    VAR a = CALCULATE ( [Active Customers], ALLSELECTED ( 'Date' ) )
    VAR l = CALCULATE ( [Active Customers LY], ALLSELECTED ( 'Date' ) )
    VAR g = DIVIDE ( a - l, l )
    RETURN "Active members are " & FORMAT ( ABS ( g ), "0.0%" ) & IF ( g >= 0, " up", " down" ) & " on last year"
)""", "", "Titles")
m("Title Tier Drivers", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( Customers[Tier] ), "@c", [Member Sales Change] )
VAR leader = TOPN ( 1, t, [@c], DESC )
RETURN MAXX ( leader, Customers[Tier] ) & " members added the most spend: " & FORMAT ( MAXX ( leader, [@c] ) / 1000000, "+$#,0.0;-$#,0.0" )
    & "M vs last year" """, "", "Titles", guard="Member Sales Change")
m("Title Cohorts", """
VAR r1 = CALCULATE ( [Cohort Retention %], Cohorts[MonthsSince] = 1, ALLSELECTED ( 'Date' ) )
VAR r3 = CALCULATE ( [Cohort Retention %], Cohorts[MonthsSince] = 3, ALLSELECTED ( 'Date' ) )
RETURN FORMAT ( r1, "0%" ) & " of new members come back the next month; " & FORMAT ( r3, "0%" ) & " are still active after 3 months" """,
  "", "Titles", guard="Cohort Retention %")
m("Title Customer Funnel", """
"Repeat buyers are " & FORMAT ( DIVIDE ( [Repeat], [Active] ), "0%" ) & " of active members; "
    & FORMAT ( DIVIDE ( [Gold & Platinum], [Active] ), "0%" ) & " are Gold or Platinum" """, "", "Titles")
m("Title Country Customers", """
VAR avgs = [Avg Spend per Customer]
VAR n = COUNTROWS ( FILTER ( ALLSELECTED ( 'Country'[Country] ), [Active Customers vs LY %] > 0 && [Spend per Customer] > avgs ) )
RETURN FORMAT ( COALESCE ( n, 0 ), "0" ) & " countries grow members and spend above average" """, "", "Titles")
m("Title Tier Mix", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( Customers[Tier] ), "@s", [Member Sales] )
VAR total = SUMX ( t, [@s] )
VAR leader = TOPN ( 1, t, [@s], DESC )
RETURN MAXX ( leader, Customers[Tier] ) & " drives " & FORMAT ( DIVIDE ( MAXX ( leader, [@s] ), total ), "0%" ) & " of member spend" """,
  "", "Titles", guard="Member Sales")

# --- online
m("Sessions", "SUM ( 'Online Funnel'[Session Count] )", INT, "Online funnel")
m("Product views", "SUM ( 'Online Funnel'[ProductViews] )", INT, "Online funnel")
m("Add to cart", "SUM ( 'Online Funnel'[AddToCart] )", INT, "Online funnel")
m("Checkout", "SUM ( 'Online Funnel'[Checkouts] )", INT, "Online funnel")
m("Orders", "SUM ( 'Online Funnel'[Order Count] )", INT, "Online funnel")
m("Sessions LY", ly("Sessions"), INT, "Online")
m("Orders LY", ly("Orders"), INT, "Online")
m("Sessions vs LY %", change("Sessions", "Sessions LY"), SPCT, "Online")
m("Orders Change vs LY", "[Orders] - [Orders LY]", SINT, "Online")
m("Online Conversion %", "DIVIDE ( [Orders], [Sessions] )", PCT, "Online", "Orders per session")
m("Online Conversion % LY", ly("Online Conversion %"), PCT, "Online")
m("Online Sales", "CALCULATE ( [Net Sales], 'Store'[Channel] = \"Online\" )", CUR, "Online")
m("Online Sales LY", ly("Online Sales"), CUR, "Online")
m("Online Sales Target", "CALCULATE ( [Sales Target], 'Store'[Channel] = \"Online\" )", CUR, "Online")
m("Avg Order Value", "DIVIDE ( [Online Sales], [Orders] )", CUR2, "Online")
m("Avg Order Value LY", ly("Avg Order Value"), CUR2, "Online")
m("Avg Online Conversion %", "CALCULATE ( [Online Conversion %], ALLSELECTED ( 'Country' ) )", PCT, "Online")
for base in ["Online Sales", "Online Sales Target", "Online Sales LY", "Online Conversion %", "Online Conversion % LY",
             "Avg Order Value", "Avg Order Value LY", "Sessions", "Sessions LY"]:
    src = next(x for x in MEASURES if x["name"] == base)
    m(f"{base} (card)", card(base), src["format"], "Cards")
m("Title Funnel", """
"Online converts " & FORMAT ( [Online Conversion %], "0.0%" ) & "; " & FORMAT ( 1 - DIVIDE ( [Checkout], [Add to cart] ), "0%" )
    & " of carts never reach checkout" """, "", "Titles")
m("Title Online Trend", """
IF ( NOT ISBLANK ( [Online Sales] ),
    VAR s = CALCULATE ( [Online Sales], ALLSELECTED ( 'Date' ) )
    VAR t = CALCULATE ( [Online Sales Target], ALLSELECTED ( 'Date' ) )
    VAR l = CALCULATE ( [Online Sales LY], ALLSELECTED ( 'Date' ) )
    VAR vt = DIVIDE ( s - t, t )
    VAR vl = DIVIDE ( s - l, l )
    RETURN "Online sales are " & FORMAT ( ABS ( vt ), "0.0%" ) & IF ( vt >= 0, " ahead of", " behind" ) & " plan and "
        & FORMAT ( ABS ( vl ), "0.0%" ) & IF ( vl >= 0, " up on", " down on" ) & " last year"
)""", "", "Titles")
m("Title Source Drivers", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Online Funnel'[Source] ), "@c", [Orders Change vs LY] )
VAR leader = TOPN ( 1, t, [@c], DESC )
RETURN MAXX ( leader, 'Online Funnel'[Source] ) & " added the most orders: " & FORMAT ( MAXX ( leader, [@c] ), "+#,0;-#,0" ) & " vs last year" """,
  "", "Titles", guard="Orders Change vs LY")
m("Title Device Source", """
VAR t = ADDCOLUMNS ( CROSSJOIN ( ALLSELECTED ( 'Online Funnel'[Device] ), ALLSELECTED ( 'Online Funnel'[Source] ) ),
    "@c", [Online Conversion %] )
VAR leader = TOPN ( 1, t, [@c], DESC )
VAR laggard = TOPN ( 1, t, [@c], ASC )
RETURN MAXX ( leader, 'Online Funnel'[Device] ) & " from " & MAXX ( leader, 'Online Funnel'[Source] ) & " converts best ("
    & FORMAT ( MAXX ( leader, [@c] ), "0.0%" ) & "); " & MAXX ( laggard, 'Online Funnel'[Device] ) & " from "
    & MAXX ( laggard, 'Online Funnel'[Source] ) & " only " & FORMAT ( MAXX ( laggard, [@c] ), "0.0%" )""", "", "Titles", guard="Online Conversion %")
m("Title Online Markets", """
VAR avgc = [Avg Online Conversion %]
VAR n = COUNTROWS ( FILTER ( ALLSELECTED ( 'Country'[Country] ), [Sessions vs LY %] > 0 && [Online Conversion %] > avgc ) )
RETURN FORMAT ( COALESCE ( n, 0 ), "0" ) & " markets grow traffic and convert above average" """, "", "Titles")
m("Title Online Mix", """
VAR t = ADDCOLUMNS ( ALLSELECTED ( 'Country'[Country] ), "@s", [Online Sales] )
VAR total = SUMX ( t, [@s] )
VAR leader = TOPN ( 1, t, [@s], DESC )
RETURN MAXX ( leader, 'Country'[Country] ) & " is " & FORMAT ( DIVIDE ( MAXX ( leader, [@s] ), total ), "0%" ) & " of online sales" """,
  "", "Titles", guard="Online Sales")

# --- insights (Overview)
m("Insight Sales", """
VAR s = [Net Sales]
VAR t = [Sales Target]
VAR gap = s - t
VAR ch = TOPN ( 1, ADDCOLUMNS ( VALUES ( 'Store'[Channel] ), "@v", [Net Sales vs Target %] ), [@v], DESC )
VAR rg = TOPN ( 1, ADDCOLUMNS ( VALUES ( 'Country'[Region] ), "@v", [Net Sales vs Target %] ), [@v], DESC )
RETURN "Sales are **" & FORMAT ( ABS ( gap ) / 1000000, "$#,0.0" ) & "M " & IF ( gap >= 0, "ahead of", "behind" )
    & " target**, led by " & MAXX ( ch, 'Store'[Channel] ) & " (" & FORMAT ( MAXX ( ch, [@v] ), "+0.0%;-0.0%" )
    & " vs target) and " & MAXX ( rg, 'Country'[Region] ) & " (" & FORMAT ( MAXX ( rg, [@v] ), "+0.0%;-0.0%" ) & ")." """,
  "", "Insights")
m("Insight Margin", """
VAR g = [Gross Margin %]
VAR d = ( g - [Gross Margin Target %] ) * 100
VAR s = CALCULATE ( [Net Sales], ALLSELECTED ( 'Category' ) )
VAR sl = CALCULATE ( [Net Sales LY], ALLSELECTED ( 'Category' ) )
VAR cats = ADDCOLUMNS ( VALUES ( 'Category'[Category] ),
    "@c", DIVIDE ( [Gross Profit], s ) - DIVIDE ( [Gross Profit LY], sl ), "@m", [Gross Margin %] )
VAR worst = TOPN ( 2, cats, [@c], ASC )
RETURN "Margin is **" & FORMAT ( ABS ( d ), "0.0" ) & " pts " & IF ( d >= 0, "above", "under" ) & " target**: "
    & CONCATENATEX ( worst, 'Category'[Category] & " (" & FORMAT ( [@m], "0.0%" ) & ")", " and ", [@c], ASC )
    & " pull it down most." """, "", "Insights")
m("Insight Region", """
VAR rg = TOPN ( 1, ADDCOLUMNS ( VALUES ( 'Country'[Region] ), "@v", [Net Sales vs Target %] ), [@v], ASC )
VAR rname = MAXX ( rg, 'Country'[Region] )
VAR rv = MAXX ( rg, [@v] )
VAR n = COUNTROWS ( FILTER ( CALCULATETABLE ( VALUES ( 'Store'[Store] ), 'Country'[Region] = rname, 'Store'[Channel] = "Store" ),
    [Inventory Cover (wks)] > 9 ) )
RETURN "**" & rname & "** is " & FORMAT ( ABS ( rv ), "0.0%" ) & IF ( rv < 0, " behind", " ahead of" ) & " target; "
    & FORMAT ( COALESCE ( n, 0 ), "0" ) & " of its stores hold more than 9 weeks of stock." """, "", "Insights")


# ---------------------------------------------------------------- pages
W, MARGIN, GAP = 1280, 24, 16
COL = (W - 2 * MARGIN - GAP) // 2          # 608
KPI_W = (W - 2 * MARGIN - 3 * GAP) // 4    # 296
Y_NAV, Y_SLICERS, Y_KPI = 16, 64, 128
H_KPI, H_ROW = 150, 312
ROWS = [Y_KPI + H_KPI + GAP + i * (H_ROW + GAP) for i in range(3)]   # 294, 622, 950
X = [MARGIN, MARGIN + COL + GAP]


def header_visuals(page):
    # Full-width navigator, and the four filters on the same columns as the KPI cards below.
    vs = [{"id": f"{page}_nav", "type": "pageNavigator", "x": MARGIN, "y": Y_NAV - 4, "w": W - 2 * MARGIN, "h": 44}]
    for i, (field, label, default) in enumerate([("Date[Year]", "Period", 2026), ("Country[Region]", "Region", None),
                                                  ("Store[Channel]", "Channel", None), ("Category[Category]", "Category", None)]):
        vs.append({"id": f"{page}_slicer_{label.lower()}", "type": "slicer", "x": MARGIN + i * (KPI_W + GAP),
                   "y": Y_SLICERS - 4, "w": KPI_W, "h": 56, "field": field, "label": label, "default": default,
                   "single": default is not None, "sync": label})
    return vs


def kpi(page, i, label, value, target=None, comparison=None, trend=None, lower_is_better=False, signed=False):
    fields = {"value": f"[{value} (card)]", "axis": "Date[Month Start]", "trend": f"[{trend or value}]"}
    if target:
        fields["target"] = f"[{target} (card)]"
    if comparison:
        fields["comparison"] = f"[{comparison} (card)]"
    return {"id": f"{page}_kpi{i}", "type": "kpiCard", "x": MARGIN + i * (KPI_W + GAP), "y": Y_KPI, "w": KPI_W, "h": H_KPI,
            "fields": fields, "format": {"kpi": {"label": label, "lowerIsBetter": lower_is_better, "signedValue": signed}}}


def vis(vid, vtype, row, col, fields, title="", subtitle="", fmt=None, w=None):
    f = {"header": {"title": title, "subtitle": subtitle}}
    for k, v in (fmt or {}).items():
        f[k] = v
    return {"id": vid, "type": vtype, "x": X[col], "y": ROWS[row], "w": w or COL, "h": H_ROW, "fields": fields, "format": f}


OVERVIEW = header_visuals("ov") + [
    kpi("ov", 0, "Net sales · YTD", "Net Sales", "Sales Target", "Net Sales LY"),
    kpi("ov", 1, "Gross margin · YTD", "Gross Margin %", "Gross Margin Target %", "Gross Margin % LY"),
    kpi("ov", 2, "Like-for-like growth · YTD", "LFL Growth %", "LFL Growth Target %", "LFL Growth LY %", signed=True),
    kpi("ov", 3, "Inventory cover · latest week", "Inventory Cover (wks)", "Inventory Cover Target (wks)",
        "Inventory Cover LY (wks)", lower_is_better=True),
    vis("ov_trend", "trendLine", 0, 0, {"axis": "Date[Month]", "actual": "[Net Sales]", "target": "[Sales Target]",
        "comparison": "[Net Sales LY]", "annotation": "[Event Label]", "title": "[Title Sales Trend]"},
        "Sales vs target", "Net sales by month"),
    vis("ov_drivers", "driverBars", 0, 1, {"category": "'Sales Driver'[Driver]", "value": "[Sales Change by Driver]",
        "title": "[Title Drivers]"}, "What drove the change", "Change in net sales vs last year by driver"),
    vis("ov_quadrant", "quadrant", 1, 0, {"details": "Store[Store]", "x": "[LFL Store Growth %]", "y": "[LFL Store Margin %]",
        "size": "[LFL Store Sales]", "xRef": "[Growth Target %]", "yRef": "[Avg LFL Margin %]", "title": "[Title Store Quadrant]"},
        "Store performance", "{n} like-for-like stores · growth vs LY (x), gross margin (y), size = sales",
        {"quadrant": {"topLeft": "Margin, low growth", "topRight": "Stars", "bottomLeft": "Fix first",
                      "bottomRight": "Growth, thin margin", "labelTop": 2, "labelBottom": 1}}),
    vis("ov_treemap", "treemap", 1, 1, {"category": "Category[Category]", "size": "[Net Sales]", "color": "[Gross Margin %]",
        "title": "[Title Category Mix]"}, "Category mix", "Net sales by category (size) and gross margin (colour)"),
    vis("ov_heatmap", "heatmap", 2, 0, {"rows": "Date[Weekday]", "columns": "Footfall[Hour]", "value": "[Footfall]",
        "title": "[Title Footfall Heatmap]"}, "Store traffic", "Store footfall by weekday and hour · busiest hour = 100",
        {"heatmap": {"indexMode": True, "lowLabel": "Quiet", "highLabel": "Busy"}}),
    vis("ov_funnel", "funnel", 2, 1, {"stages": ["[Sessions]", "[Product views]", "[Add to cart]", "[Checkout]", "[Orders]"],
        "title": "[Title Funnel]"}, "Online funnel", "Online funnel · selected period"),
    {"id": "ov_insights", "type": "narrative", "x": MARGIN, "y": ROWS[2] + H_ROW + GAP, "w": W - 2 * MARGIN, "h": 124,
     "fields": {"items": ["[Insight Sales]", "[Insight Margin]", "[Insight Region]"]},
     "format": {"narrative": {"heading": "Key insights", "style": "numbered"}}},
]

STORES = header_visuals("st") + [
    kpi("st", 0, "Footfall · YTD", "Footfall", comparison="Footfall LY"),
    kpi("st", 1, "Store conversion · YTD", "Store Conversion %", comparison="Store Conversion % LY"),
    kpi("st", 2, "Avg transaction value · YTD", "Avg Transaction Value", comparison="Avg Transaction Value LY"),
    kpi("st", 3, "Sales per sqm · YTD", "Sales per sqm", comparison="Sales per sqm LY"),
    vis("st_trend", "trendLine", 0, 0, {"axis": "Date[Month]", "actual": "[Footfall]", "comparison": "[Footfall LY]",
        "annotation": "[Event Label]", "title": "[Title Footfall Trend]"}, "Footfall", "Store visitors by month"),
    vis("st_regions", "driverBars", 0, 1, {"category": "Country[Region]", "value": "[Sales Change vs LY]",
        "title": "[Title Region Change]"}, "Change by region", "Change in net sales vs last year by region",
        {"bars": {"sortDescending": True}}),
    vis("st_quadrant", "quadrant", 1, 0, {"details": "Store[Store]", "x": "[LFL Footfall vs LY %]",
        "y": "[LFL Store Conversion %]", "size": "[LFL Store Sales (stores)]", "xRef": "[Zero Line]",
        "yRef": "[Avg Store Conversion %]", "title": "[Title Store Traffic]"}, "Traffic vs conversion",
        "{n} like-for-like stores · footfall growth (x), conversion (y), size = sales",
        {"quadrant": {"topLeft": "Converting, fewer visitors", "topRight": "Growing and converting",
                      "bottomLeft": "Losing traffic", "bottomRight": "Busy, under-converting"}}),
    vis("st_heatmap", "heatmap", 1, 1, {"rows": "Date[Weekday]", "columns": "Footfall[Hour]", "value": "[Store Conversion %]",
        "title": "[Title Conversion Heatmap]"}, "Conversion by hour", "Store conversion by weekday and hour",
        {"heatmap": {"indexMode": False, "lowLabel": "Low", "highLabel": "High"}}),
    vis("st_treemap", "treemap", 2, 0, {"category": "Country[Country]", "size": "[Net Sales]", "color": "[LFL Growth %]",
        "title": "[Title Country Mix]"}, "Countries", "Net sales by country (size) and like-for-like growth (colour)"),
    {"id": "st_table", "type": "table", "x": X[1], "y": ROWS[2], "w": COL, "h": H_ROW, "title": "Store league table",
     "fields": ["Store[Store]", "Store[Region]", "Store[Format]", "[Store Sales]", "[Net Sales vs LY %]",
                "[Store Conversion %]", "[Avg Transaction Value]"], "sort": ("[Store Sales]", "desc")},
]

CATEGORIES = header_visuals("ca") + [
    kpi("ca", 0, "Net sales · YTD", "Net Sales", "Sales Target", "Net Sales LY"),
    kpi("ca", 1, "Gross margin · YTD", "Gross Margin %", "Gross Margin Target %", "Gross Margin % LY"),
    kpi("ca", 2, "Units sold · YTD", "Units", comparison="Units LY"),
    kpi("ca", 3, "Inventory cover · latest week", "Inventory Cover (wks)", "Inventory Cover Target (wks)",
        "Inventory Cover LY (wks)", lower_is_better=True),
    vis("ca_trend", "trendLine", 0, 0, {"axis": "Date[Month]", "actual": "[Gross Margin %]", "target": "[Gross Margin Target %]",
        "comparison": "[Gross Margin % LY]", "annotation": "[Event Label]", "title": "[Title Margin Trend]"},
        "Gross margin", "Gross margin % by month"),
    vis("ca_margin", "driverBars", 0, 1, {"category": "Category[Category]", "value": "[Margin Change Contribution (pts)]",
        "title": "[Title Margin Drivers]"}, "Margin drivers", "Contribution to the change in gross margin vs last year, pts",
        {"bars": {"sortDescending": True}}),
    vis("ca_quadrant", "quadrant", 1, 0, {"details": "Category[Category]", "x": "[Net Sales vs LY %]", "y": "[Gross Margin %]",
        "size": "[Net Sales]", "xRef": "[Total Growth %]", "yRef": "[Total Margin %]", "title": "[Title Category Quadrant]"},
        "Growth vs margin", "{n} categories · growth vs LY (x), gross margin (y), size = sales",
        {"quadrant": {"topLeft": "Profitable, slowing", "topRight": "Stars", "bottomLeft": "Under pressure",
                      "bottomRight": "Growing, thin margin", "labelTop": 2, "labelBottom": 2}}),
    vis("ca_heatmap", "heatmap", 1, 1, {"rows": "Category[Category]", "columns": "Date[Month]", "value": "[Net Sales vs LY %]",
        "title": "[Title Category Growth]"}, "Growth by month", "Net sales growth vs last year by category and month",
        {"heatmap": {"indexMode": False, "showAll": True, "lowLabel": "Slower", "highLabel": "Faster"}}),
    vis("ca_change", "driverBars", 2, 0, {"category": "Category[Category]", "value": "[Sales Change vs LY]",
        "title": "[Title Category Change]"}, "Sales change", "Change in net sales vs last year by category",
        {"bars": {"sortDescending": True}}),
    vis("ca_stock", "treemap", 2, 1, {"category": "Category[Category]", "size": "[Stock Value]", "color": "[Inventory Cover (wks)]",
        "title": "[Title Inventory Mix]"}, "Stock", "Closing stock at cost (size) and weeks of cover (colour)"),
]

CUSTOMERS = header_visuals("cu") + [
    kpi("cu", 0, "Active members · monthly avg", "Active Customers", comparison="Active Customers LY", trend="Active Customers"),
    kpi("cu", 1, "New members · YTD", "New Customers", comparison="New Customers LY"),
    kpi("cu", 2, "Repeat rate · YTD", "Repeat Rate %", comparison="Repeat Rate % LY"),
    kpi("cu", 3, "Spend per member · monthly", "Spend per Customer", comparison="Spend per Customer LY"),
    vis("cu_trend", "trendLine", 0, 0, {"axis": "Date[Month]", "actual": "[Active Customers]",
        "comparison": "[Active Customers LY]", "title": "[Title Customer Trend]"}, "Active members", "Active loyalty members by month"),
    vis("cu_tiers", "driverBars", 0, 1, {"category": "Customers[Tier]", "value": "[Member Sales Change]",
        "title": "[Title Tier Drivers]"}, "Spend by tier", "Change in member spend vs last year by loyalty tier",
        {"bars": {"sortDescending": True}}),
    vis("cu_cohorts", "heatmap", 1, 0, {"rows": "Date[Year Month]", "columns": "Cohorts[MonthsSince]",
        "value": "[Cohort Retention %]", "title": "[Title Cohorts]"}, "Retention", "Share of each monthly cohort still active, by months since joining",
        {"heatmap": {"indexMode": False, "showAll": True, "lowLabel": "Churned", "highLabel": "Retained"}}),
    vis("cu_funnel", "funnel", 1, 1, {"stages": ["[Active]", "[Repeat]", "[Gold & Platinum]", "[Platinum]"],
        "title": "[Title Customer Funnel]"}, "Member value ladder", "Average monthly members by stage"),
    vis("cu_quadrant", "quadrant", 2, 0, {"details": "Country[Country]", "x": "[Active Customers vs LY %]",
        "y": "[Spend per Customer]", "size": "[Member Sales]", "xRef": "[Zero Line]", "yRef": "[Avg Spend per Customer]",
        "title": "[Title Country Customers]"}, "Markets", "{n} countries · member growth (x), spend per member (y), size = spend",
        {"quadrant": {"topLeft": "High value, shrinking", "topRight": "Growing high value", "bottomLeft": "Needs attention",
                      "bottomRight": "Growing, low spend", "labelTop": 2, "labelBottom": 1}}),
    vis("cu_treemap", "treemap", 2, 1, {"category": "Customers[Tier]", "size": "[Member Sales]", "color": "[Repeat Rate %]",
        "title": "[Title Tier Mix]"}, "Tier mix", "Member spend by tier (size) and repeat rate (colour)"),
]

ONLINE = header_visuals("on") + [
    kpi("on", 0, "Online sales · YTD", "Online Sales", "Online Sales Target", "Online Sales LY"),
    kpi("on", 1, "Conversion · YTD", "Online Conversion %", comparison="Online Conversion % LY"),
    kpi("on", 2, "Avg order value · YTD", "Avg Order Value", comparison="Avg Order Value LY"),
    kpi("on", 3, "Sessions · YTD", "Sessions", comparison="Sessions LY"),
    vis("on_funnel", "funnel", 0, 0, {"stages": ["[Sessions]", "[Product views]", "[Add to cart]", "[Checkout]", "[Orders]"],
        "title": "[Title Funnel]"}, "Online funnel", "Sessions to orders · selected period"),
    vis("on_trend", "trendLine", 0, 1, {"axis": "Date[Month]", "actual": "[Online Sales]", "target": "[Online Sales Target]",
        "comparison": "[Online Sales LY]", "annotation": "[Event Label]", "title": "[Title Online Trend]"},
        "Online sales", "Online net sales by month"),
    vis("on_sources", "driverBars", 1, 0, {"category": "'Online Funnel'[Source]", "value": "[Orders Change vs LY]",
        "title": "[Title Source Drivers]"}, "Orders by source", "Change in orders vs last year by traffic source",
        {"bars": {"sortDescending": True}}),
    vis("on_heatmap", "heatmap", 1, 1, {"rows": "'Online Funnel'[Device]", "columns": "'Online Funnel'[Source]",
        "value": "[Online Conversion %]", "title": "[Title Device Source]"}, "Conversion", "Online conversion by device and traffic source",
        {"heatmap": {"indexMode": False, "showAll": True, "lowLabel": "Low", "highLabel": "High"}}),
    vis("on_quadrant", "quadrant", 2, 0, {"details": "Country[Country]", "x": "[Sessions vs LY %]", "y": "[Online Conversion %]",
        "size": "[Online Sales]", "xRef": "[Zero Line]", "yRef": "[Avg Online Conversion %]", "title": "[Title Online Markets]"},
        "Online markets", "{n} markets · session growth (x), conversion (y), size = online sales",
        {"quadrant": {"topLeft": "Converting, less traffic", "topRight": "Growing and converting",
                      "bottomLeft": "Needs attention", "bottomRight": "Traffic, low conversion", "labelTop": 2, "labelBottom": 1}}),
    vis("on_treemap", "treemap", 2, 1, {"category": "Country[Country]", "size": "[Online Sales]", "color": "[Online Conversion %]",
        "title": "[Title Online Mix]"}, "Online by market", "Online sales by country (size) and conversion (colour)"),
]

PAGE_H_SHORT = ROWS[2] + H_ROW + 32
DEFINITION = {
    "name": "Atlas Retail",
    "description": "Worldwide retail performance: sales, stores, categories, customers and online (Jan 2024 - Oct 2026).",
    "theme": {"page_bg": "#F7F3EE", "card_bg": "#FFFFFF", "card_border": "#E7E0D7", "text": "#1F1A17", "muted": "#6F6761",
              "accent": "#DD7A12", "accent_tint": "#FBE7CC", "font": "Segoe UI", "radius": 10,
              "data_colors": ["#DD7A12", "#9C4F0C", "#F2B166", "#3B78D8", "#6F6761", "#C9A27A", "#2E7D3A", "#B3261E"]},
    "data": {"parameter": "DataFolder"},
    "tables": TABLES,
    "calculated_columns": CALCULATED,
    "relationships": [{"from": a, "to": b} for a, b in RELATIONSHIPS],
    "measures_table": "Metrics",
    "measures": MEASURES,
    "pages": [
        {"name": "Overview", "height": ROWS[2] + H_ROW + GAP + 124 + 32, "visuals": OVERVIEW},
        {"name": "Stores", "height": PAGE_H_SHORT, "visuals": STORES},
        {"name": "Categories", "height": PAGE_H_SHORT, "visuals": CATEGORIES},
        {"name": "Customers", "height": PAGE_H_SHORT, "visuals": CUSTOMERS},
        {"name": "Online", "height": PAGE_H_SHORT, "visuals": ONLINE},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "GlobalRetail")
    ap.add_argument("--data-folder", default=None, help="Folder holding the CSVs (default: <out>\\Data\\)")
    ap.add_argument("--catalog", type=Path, default=ROOT / "custom_visuals" / "catalog.json")
    args = ap.parse_args()
    data_folder = args.data_folder or str(args.out.resolve() / "Data") + "\\"
    defn = json.loads(json.dumps(DEFINITION))
    defn["data"]["folder"] = data_folder
    (HERE / "definition.json").write_text(json.dumps(defn, indent=2), encoding="utf-8")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    project = report_builder.build(defn, catalog, args.out, visuals_dir=args.catalog.parent)
    print(f"definition: {HERE / 'definition.json'}")
    print(f"measures: {len(MEASURES)}  tables: {len(TABLES)}  pages: {len(DEFINITION['pages'])}")
    print(f"project:  {project}")


if __name__ == "__main__":
    main()
