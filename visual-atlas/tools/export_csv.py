"""Write the test sample data as CSV files, for building a quick test report in Power BI Desktop.

usage: export_csv.py   ->  visuals/test/sample-data/*.csv
Load them with Get data > Text/CSV. Sort Month by MonthNo (Column tools > Sort by column).
"""
import csv
import json
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
data = json.loads((root / "visuals/test/data.json").read_text(encoding="utf-8"))
out = root / "visuals/test/sample-data"
out.mkdir(parents=True, exist_ok=True)
months = data["months"]


def write(name, header, rows):
    with open(out / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


write("flow_web_traffic.csv", ["Source", "Target", "Sessions"], data["traffic"])
write("flow_income_statement.csv", ["Source", "Target", "Amount"], data["pnl"])
write("flow_brand_switching.csv", ["From", "To", "Customers"], data["switching"])
write("flow_trade.csv", ["Exporter", "Importer", "Value"], data["trade"])
write("flow_product_network.csv", ["Product A", "Product B", "Orders"], data["net"])
write("sales_by_date.csv", ["Year", "Quarter", "Month", "MonthNo", "Sales", "Profit"],
      [[y, q, m, months.index(m) + 1, s, p] for y, q, m, s, p in data["hd"]])
write("sales_by_product.csv", ["Category", "Subcategory", "Product", "Sales", "Profit"], data["hp"])
write("revenue_by_channel.csv", ["Month", "MonthNo", "Channel", "Revenue"],
      [[m, months.index(m) + 1, c, v] for m, c, v in data["chan"]])
