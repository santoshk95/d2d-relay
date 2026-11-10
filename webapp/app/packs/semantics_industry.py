"""Industry packs for the ontology, the metrics and the sample data (finance, supply chain, operations): each pack is
the entities of its industry with their keys and relations, the metrics and KPIs a team certifies (DAX for the BI
model, SQL for the warehouse, a target per KPI), and a sample-data recipe (genbi_kit.datagen) whose tables the
entities and metrics are built on, with stories planted for a demo to find. Installing a pack writes through the
modules that own each part — entities into the ontology, metrics as drafts for the four-eyes review of Formulas &
metrics, the recipe for Sample & synthetic data — nothing is rebuilt here.
"""
from __future__ import annotations

FINANCE_RECIPE = """\
seed: 11
period: {start: 2025-11-01, end: 2026-10-31}
story: [Customers in the North pay later from July, Marketing spends over its budget in the third quarter]
tables:
  - name: customers
    count: 120
    columns:
      customer_id: {id: "C", width: 4}
      customer_name: {fake: company}
      region: {choice: {North: 30, South: 30, London: 25, Midlands: 15}}
      segment: {choice: {Retail: 50, Wholesale: 35, Online: 15}}
  - name: cost_centres
    rows: [{cost_centre: CC100, cost_centre_name: Sales}, {cost_centre: CC200, cost_centre_name: Marketing},
           {cost_centre: CC300, cost_centre_name: Operations}, {cost_centre: CC400, cost_centre_name: Finance}]
  - name: invoices
    count: 3000
    columns:
      invoice_id: {id: "INV-", width: 6}
      customer_id: {ref: customers.customer_id, skew: 0.6}
      region: {lookup: customers.region, by: customer_id}
      invoice_date: {date: {trend: 0.2, weekdays: true}}
      net_amount: {number: {median: 1800, spread: 0.7, min: 50, max: 40000}, decimals: 2}
      tax_amount: {formula: "net_amount * 0.2", decimals: 2}
      days_to_pay: {int: {median: 34, spread: 0.3, min: 1, max: 150}, when: [{if: "region == 'North' and month(invoice_date) >= 7", times: 1.6}]}
      paid: {bool: 0.86, labels: [1, 0]}
  - name: gl_lines
    count: 4000
    columns:
      line_id: {id: "GL", width: 6}
      posting_date: {date: {weekdays: true}}
      cost_centre: {ref: cost_centres.cost_centre}
      account: {choice: {"6000": 60, "6100": 25, "6300": 15}}
      amount: {number: {median: 900, spread: 0.5, min: 10, max: 20000}, decimals: 2, when: [{if: "cost_centre == 'CC200' and quarter(posting_date) == 3", times: 1.8}]}
  - name: budgets
    count: 480
    columns:
      budget_id: {id: "B", width: 5}
      cost_centre: {ref: cost_centres.cost_centre}
      budget_date: {date: {}}
      amount: {number: {median: 7500, spread: 0.2, min: 1000, max: 30000}, decimals: 2}
"""

SUPPLY_RECIPE = """\
seed: 12
period: {start: 2025-11-01, end: 2026-10-31}
story: [OTIF dips in September for the North DC, Frozen products run out more often]
tables:
  - name: products
    count: 80
    columns:
      product_id: {id: "P", width: 4}
      product_name: {fake: company}
      category: {choice: {Bakery: 25, Dairy: 25, Frozen: 20, Ambient: 30}}
      unit_cost: {number: {median: 3.5, spread: 0.5, min: 0.5, max: 40}, decimals: 2}
  - name: warehouses
    rows: [{warehouse_id: DC-N, warehouse_name: North DC, region: North}, {warehouse_id: DC-S, warehouse_name: South DC, region: South},
           {warehouse_id: DC-L, warehouse_name: London DC, region: London}]
  - name: suppliers
    count: 25
    columns:
      supplier_id: {id: "S", width: 3}
      supplier_name: {fake: company}
      lead_time_days: {int: {median: 9, spread: 0.4, min: 2, max: 40}}
  - name: shipments
    count: 3500
    columns:
      shipment_id: {id: "SH", width: 6}
      warehouse_id: {ref: warehouses.warehouse_id, weights: {DC-N: 40}}
      product_id: {ref: products.product_id, skew: 0.5}
      category: {lookup: products.category, by: product_id}
      promised_date: {date: {weekdays: true}}
      qty_ordered: {int: {median: 40, spread: 0.6, min: 1, max: 600}}
      qty_shipped: {formula: "qty_ordered if rand() > 0.06 else max(0, qty_ordered - randint(1, 10))"}
      on_time: {bool: 0.94, labels: [1, 0], when: [{if: "warehouse_id == 'DC-N' and month(promised_date) == 9", p: 0.72}]}
  - name: inventory
    count: 2400
    columns:
      snapshot_id: {id: "INV", width: 6}
      warehouse_id: {ref: warehouses.warehouse_id}
      product_id: {ref: products.product_id}
      category: {lookup: products.category, by: product_id}
      snapshot_date: {date: {}}
      on_hand: {int: {median: 220, spread: 0.7, min: 0, max: 5000}, when: [{if: "category == 'Frozen'", times: 0.45}]}
      daily_demand: {number: {median: 30, spread: 0.4, min: 1, max: 400}, decimals: 1}
"""

OPS_RECIPE = """\
seed: 13
period: {start: 2025-11-01, end: 2026-10-31}
story: [Line 3 loses more time to breakdowns from May, Night shifts scrap more]
tables:
  - name: lines
    rows: [{line_id: L1, line_name: Line 1, plant: Leeds}, {line_id: L2, line_name: Line 2, plant: Leeds},
           {line_id: L3, line_name: Line 3, plant: Pune}, {line_id: L4, line_name: Line 4, plant: Pune}]
  - name: production_runs
    count: 3000
    columns:
      run_id: {id: "R", width: 6}
      line_id: {ref: lines.line_id}
      run_date: {date: {}}
      shift: {choice: {Day: 50, Evening: 30, Night: 20}}
      planned_minutes: {int: {min: 420, max: 480}}
      downtime_minutes: {int: {median: 25, spread: 0.6, min: 0, max: 300}, when: [{if: "line_id == 'L3' and month(run_date) >= 5", times: 2.4}]}
      ideal_rate: {number: {min: 9, max: 11}, decimals: 2}
      units_made: {formula: "int(max(0, planned_minutes - downtime_minutes) * ideal_rate * 0.9)"}
      units_scrapped: {int: {median: 40, spread: 0.6, min: 0, max: 900}, when: [{if: "shift == 'Night'", times: 1.9}]}
  - name: breakdowns
    count: 600
    columns:
      breakdown_id: {id: "BD", width: 5}
      line_id: {ref: lines.line_id, weights: {L3: 40}}
      started: {date: {}}
      repair_minutes: {int: {median: 55, spread: 0.6, min: 5, max: 600}}
"""

PACKS = {
    "finance": {
        "title": "Finance", "summary": "Customers, invoices, the general ledger and budgets: revenue, receivables, days sales outstanding and budget variance.",
        "entities": [
            {"name": "Customer", "description": "A party that buys from us; one record per legal entity.", "synonyms": ["Client", "Debtor"], "keys": [("customers", "customer_id")]},
            {"name": "Invoice", "description": "A bill sent to a customer for goods or services, net of tax.", "synonyms": ["Bill", "Sales invoice"], "keys": [("invoices", "invoice_id")]},
            {"name": "Cost centre", "description": "A part of the organisation that budgets and spends.", "synonyms": ["Department", "Cost center"], "keys": [("cost_centres", "cost_centre")]},
            {"name": "Ledger line", "description": "One posting to the general ledger: an account, a cost centre, an amount and a date.", "synonyms": ["GL line", "Journal line"], "keys": [("gl_lines", "line_id")]},
            {"name": "Budget line", "description": "The amount a cost centre plans to spend in a period.", "synonyms": ["Plan", "Budget"], "keys": [("budgets", "budget_id")]},
        ],
        "relations": [("Invoice", "is billed to", "Customer"), ("Ledger line", "is charged to", "Cost centre"), ("Budget line", "is planned by", "Cost centre")],
        "metrics": [
            {"name": "Revenue", "description": "Invoiced amount net of tax.", "dax": "SUM('invoices'[net_amount])", "sql": "SUM(net_amount)", "query": "SELECT SUM(net_amount) FROM invoices",
             "format": "#,0", "kpi": {"target": 4_000_000, "better": "higher", "unit": "GBP"}},
            {"name": "Open receivables", "description": "Invoiced amounts, gross of tax, not yet paid.", "dax": "CALCULATE(SUM('invoices'[net_amount]) + SUM('invoices'[tax_amount]), 'invoices'[paid] = 0)",
             "sql": "SUM(CASE WHEN paid = 0 THEN net_amount + tax_amount ELSE 0 END)", "query": "SELECT SUM(CASE WHEN paid = 0 THEN net_amount + tax_amount ELSE 0 END) FROM invoices",
             "format": "#,0", "kpi": {"target": 900_000, "better": "lower", "unit": "GBP"}},
            {"name": "Days sales outstanding", "description": "The average number of days customers take to pay an invoice.", "dax": "AVERAGE('invoices'[days_to_pay])",
             "sql": "AVG(days_to_pay)", "query": "SELECT AVG(days_to_pay) FROM invoices", "format": "0.0", "kpi": {"target": 40, "better": "lower", "unit": "days"}},
            {"name": "Spend", "description": "Amounts posted to the expense accounts of the general ledger.", "dax": "SUM('gl_lines'[amount])", "sql": "SUM(amount)",
             "query": "SELECT SUM(amount) FROM gl_lines", "format": "#,0", "kpi": None},
            {"name": "Budget variance %", "description": "Spend less budget, as a share of the budget, per cost centre.", "dax": "DIVIDE(SUM('gl_lines'[amount]) - SUM('budgets'[amount]), SUM('budgets'[amount]))",
             "sql": "(SUM(amount) - (SELECT SUM(amount) FROM budgets)) / (SELECT SUM(amount) FROM budgets)",
             "query": "SELECT (SELECT SUM(amount) FROM gl_lines) / NULLIF((SELECT SUM(amount) FROM budgets), 0) - 1", "format": "0.0%", "kpi": {"target": 0.05, "better": "lower", "unit": "share"}},
        ],
        "stories": [
            {"story": "Customers in the North pay later from July", "query": "SELECT AVG(CASE WHEN region = 'North' AND month(CAST(invoice_date AS DATE)) >= 7 THEN days_to_pay END) "
             "- AVG(CASE WHEN region <> 'North' THEN days_to_pay END) FROM invoices", "check": "> 5"},
            {"story": "Marketing spends over its budget in the third quarter", "query": "SELECT AVG(CASE WHEN cost_centre = 'CC200' AND quarter(CAST(posting_date AS DATE)) = 3 THEN amount END) "
             "/ AVG(CASE WHEN NOT (cost_centre = 'CC200' AND quarter(CAST(posting_date AS DATE)) = 3) THEN amount END) FROM gl_lines", "check": "> 1.3"},
        ],
        "recipe": FINANCE_RECIPE},
    "supply_chain": {
        "title": "Supply chain", "summary": "Products, warehouses, suppliers, shipments and stock: on time in full, fill rate, stock cover and supplier lead time.",
        "entities": [
            {"name": "Product", "description": "An item we stock and sell, by its SKU.", "synonyms": ["Item", "SKU"], "keys": [("products", "product_id")]},
            {"name": "Warehouse", "description": "A distribution centre that holds stock and ships orders.", "synonyms": ["DC", "Depot"], "keys": [("warehouses", "warehouse_id")]},
            {"name": "Supplier", "description": "A party we buy from.", "synonyms": ["Vendor"], "keys": [("suppliers", "supplier_id")]},
            {"name": "Shipment", "description": "Goods sent to a customer against a promised date and quantity.", "synonyms": ["Delivery", "Despatch"], "keys": [("shipments", "shipment_id")]},
            {"name": "Stock snapshot", "description": "What a warehouse holds of a product on a day, with the daily demand.", "synonyms": ["Inventory", "Stock on hand"], "keys": [("inventory", "snapshot_id")]},
        ],
        "relations": [("Shipment", "leaves from", "Warehouse"), ("Shipment", "carries", "Product"), ("Stock snapshot", "counts", "Product"), ("Stock snapshot", "is held in", "Warehouse")],
        "metrics": [
            {"name": "OTIF %", "description": "Shipments delivered on time and in full, as a share of all shipments.", "dax": "DIVIDE(CALCULATE(COUNTROWS('shipments'), 'shipments'[on_time] = 1, 'shipments'[qty_shipped] >= 'shipments'[qty_ordered]), COUNTROWS('shipments'))",
             "sql": "AVG(CASE WHEN on_time = 1 AND qty_shipped >= qty_ordered THEN 1.0 ELSE 0 END)", "query": "SELECT AVG(CASE WHEN on_time = 1 AND qty_shipped >= qty_ordered THEN 1.0 ELSE 0 END) FROM shipments",
             "format": "0.0%", "kpi": {"target": 0.95, "better": "higher", "unit": "share"}},
            {"name": "Fill rate", "description": "Units shipped as a share of units ordered.", "dax": "DIVIDE(SUM('shipments'[qty_shipped]), SUM('shipments'[qty_ordered]))", "sql": "SUM(qty_shipped) / SUM(qty_ordered)",
             "query": "SELECT SUM(qty_shipped) * 1.0 / SUM(qty_ordered) FROM shipments", "format": "0.0%", "kpi": {"target": 0.98, "better": "higher", "unit": "share"}},
            {"name": "Stock cover days", "description": "Stock on hand divided by daily demand: the days of demand the stock covers.", "dax": "DIVIDE(SUM('inventory'[on_hand]), SUM('inventory'[daily_demand]))",
             "sql": "SUM(on_hand) / SUM(daily_demand)", "query": "SELECT SUM(on_hand) / SUM(daily_demand) FROM inventory", "format": "0.0", "kpi": {"target": 6, "better": "higher", "unit": "days"}},
            {"name": "Supplier lead time", "description": "The average days a supplier takes from order to delivery.", "dax": "AVERAGE('suppliers'[lead_time_days])", "sql": "AVG(lead_time_days)",
             "query": "SELECT AVG(lead_time_days) FROM suppliers", "format": "0.0", "kpi": {"target": 10, "better": "lower", "unit": "days"}},
        ],
        "stories": [
            {"story": "OTIF dips in September for the North DC", "query": "SELECT AVG(CASE WHEN warehouse_id = 'DC-N' AND month(CAST(promised_date AS DATE)) = 9 THEN on_time * 1.0 END) FROM shipments", "check": "< 0.85"},
            {"story": "Frozen products run out more often", "query": "SELECT AVG(CASE WHEN category = 'Frozen' THEN on_hand / daily_demand END) / AVG(CASE WHEN category <> 'Frozen' THEN on_hand / daily_demand END) FROM inventory",
             "check": "< 0.7"},
        ],
        "recipe": SUPPLY_RECIPE},
    "operations": {
        "title": "Operations", "summary": "Lines, production runs and breakdowns: availability, OEE, scrap rate, mean time to repair.",
        "entities": [
            {"name": "Production line", "description": "A line in a plant that makes products in shifts.", "synonyms": ["Line", "Cell"], "keys": [("lines", "line_id")]},
            {"name": "Production run", "description": "One shift of one line: planned time, downtime, units made and scrapped.", "synonyms": ["Run", "Shift run", "Work order"], "keys": [("production_runs", "run_id")]},
            {"name": "Breakdown", "description": "A stop of a line that needs a repair.", "synonyms": ["Failure", "Stoppage"], "keys": [("breakdowns", "breakdown_id")]},
        ],
        "relations": [("Production run", "runs on", "Production line"), ("Breakdown", "stops", "Production line")],
        "metrics": [
            {"name": "Availability", "description": "Run time as a share of planned time.", "dax": "DIVIDE(SUM('production_runs'[planned_minutes]) - SUM('production_runs'[downtime_minutes]), SUM('production_runs'[planned_minutes]))",
             "sql": "(SUM(planned_minutes) - SUM(downtime_minutes)) / SUM(planned_minutes)", "query": "SELECT (SUM(planned_minutes) - SUM(downtime_minutes)) * 1.0 / SUM(planned_minutes) FROM production_runs",
             "format": "0.0%", "kpi": {"target": 0.9, "better": "higher", "unit": "share"}},
            {"name": "Scrap rate", "description": "Units scrapped as a share of units made.", "dax": "DIVIDE(SUM('production_runs'[units_scrapped]), SUM('production_runs'[units_made]))",
             "sql": "SUM(units_scrapped) / SUM(units_made)", "query": "SELECT SUM(units_scrapped) * 1.0 / SUM(units_made) FROM production_runs", "format": "0.0%", "kpi": {"target": 0.02, "better": "lower", "unit": "share"}},
            {"name": "OEE", "description": "Availability × performance × quality: the share of planned time spent making good units at the ideal rate.",
             "dax": "DIVIDE(SUM('production_runs'[units_made]) - SUM('production_runs'[units_scrapped]), SUMX('production_runs', 'production_runs'[planned_minutes] * 'production_runs'[ideal_rate]))",
             "sql": "(SUM(units_made) - SUM(units_scrapped)) / SUM(planned_minutes * ideal_rate)",
             "query": "SELECT (SUM(units_made) - SUM(units_scrapped)) * 1.0 / SUM(planned_minutes * ideal_rate) FROM production_runs", "format": "0.0%", "kpi": {"target": 0.75, "better": "higher", "unit": "share"}},
            {"name": "Mean time to repair", "description": "The average minutes a breakdown takes to repair.", "dax": "AVERAGE('breakdowns'[repair_minutes])", "sql": "AVG(repair_minutes)",
             "query": "SELECT AVG(repair_minutes) FROM breakdowns", "format": "0", "kpi": {"target": 60, "better": "lower", "unit": "minutes"}},
        ],
        "stories": [
            {"story": "Line 3 loses more time to breakdowns from May", "query": "SELECT AVG(CASE WHEN line_id = 'L3' AND month(CAST(run_date AS DATE)) >= 5 THEN downtime_minutes END) / "
             "AVG(CASE WHEN line_id <> 'L3' THEN downtime_minutes END) FROM production_runs", "check": "> 1.8"},
            {"story": "Night shifts scrap more", "query": "SELECT AVG(CASE WHEN shift = 'Night' THEN units_scrapped END) / AVG(CASE WHEN shift <> 'Night' THEN units_scrapped END) FROM production_runs",
             "check": "> 1.5"},
        ],
        "recipe": OPS_RECIPE},
}
