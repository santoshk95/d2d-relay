#!/usr/bin/env python3
"""Render the Overview page as an HTML prototype with the Gen BI visual renderers.

Numbers are computed from the CSVs with pandas, mirroring the DAX measures in reference.py
(so they double as expected values when checking the Power BI report). Layout comes from
definition.json. Output: <out>/Prototype - Overview.html (self-contained).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
YTD = ("2026-01-01", "2026-10-31")
LY = ("2025-01-01", "2025-10-31")
LY2 = ("2024-01-01", "2024-10-31")
EVENTS = {3: "Spring sale", 4: "Spring sale", 7: "Summer sale", 10: "Autumn promo"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def between(df, col, period):
    return df[(df[col] >= period[0]) & (df[col] <= period[1])]


def pct(v, signed=False, d=1):
    s = f"{abs(v) * 100:.{d}f}%"
    return (("+" if v >= 0 else "−") + s) if signed else s


def compute(data: Path) -> dict:
    rd = lambda f, **kw: pd.read_csv(data / f, **kw)
    stores = rd("dim_store.csv")
    countries = rd("dim_country.csv")
    cats = rd("dim_category.csv")
    sales = rd("fact_sales.csv")
    targets = rd("fact_targets.csv")
    foot = rd("fact_footfall.csv")
    inv = rd("fact_inventory.csv")
    funnel = rd("fact_online_funnel.csv")

    stores["Group"] = np.select(
        [stores.StoreType == "Online", stores.CloseDate.notna(), stores.OpenDate > "2025-01-01"],
        ["Online", "Closed stores", "New stores"], "Like-for-like stores")
    stores = stores.merge(countries[["CountryKey", "Region", "Country"]], on="CountryKey")
    sales = sales.merge(stores[["StoreKey", "Group", "Region", "Channel", "StoreType"]], on="StoreKey")
    sales = sales.merge(cats[["CategoryKey", "Category"]], on="CategoryKey")
    sales["month"] = sales.Date.str[5:7].astype(int)
    targets = targets.merge(stores[["StoreKey", "Group", "Region", "Channel"]], on="StoreKey")
    y, l, l2 = between(sales, "Date", YTD), between(sales, "Date", LY), between(sales, "Date", LY2)
    t = between(targets, "Month", ("2026-01-01", "2026-10-01"))
    lfl = lambda df: df[df.Group == "Like-for-like stores"]

    # --- KPI cards
    ns, ns_ly, ns_t = y.NetSales.sum(), l.NetSales.sum(), t.SalesTarget.sum()
    gm, gm_ly, gm_t = y.GrossProfit.sum() / ns, l.GrossProfit.sum() / ns_ly, t.GrossProfitTarget.sum() / ns_t
    lfl_y, lfl_l, lfl_l2 = lfl(y).NetSales.sum(), lfl(l).NetSales.sum(), lfl(l2).NetSales.sum()
    lfl_t = (lfl(t).SalesTarget.sum() - lfl_l) / lfl_l
    by_m = y.groupby("month").agg(ns=("NetSales", "sum"), gp=("GrossProfit", "sum"))
    by_m_ly = l.groupby("month").agg(ns=("NetSales", "sum"), gp=("GrossProfit", "sum"))
    lfl_m = lfl(y).groupby("month").NetSales.sum() / lfl(l).groupby("month").NetSales.sum() - 1

    phys_cogs = sales[sales.StoreType == "Physical"].assign(cogs=lambda d: d.NetSales - d.GrossProfit) \
        .groupby("Date").cogs.sum()

    def cover(week_end: str) -> float:
        stock = inv[inv.WeekEnding == week_end].StockValue.sum()
        end = pd.Timestamp(week_end)
        idx = pd.to_datetime(phys_cogs.index)
        window = phys_cogs[(idx > end - pd.Timedelta(days=91)) & (idx <= end)].sum()
        return stock / (window / 13)

    weeks = sorted(inv.WeekEnding.unique())
    last_in = lambda lo, hi: max(w for w in weeks if lo <= w <= hi)
    cov = cover(last_in(*YTD))
    cov_ly = cover(last_in(*LY))
    cov_m = [cover(last_in(f"2026-{m:02d}-01", f"2026-{m:02d}-31")) for m in range(1, 11)]

    kpis = {
        "ov_kpi0": dict(value=ns, valueFormat="\\$#,0", target=ns_t, comparison=ns_ly, spark=list(by_m.ns)),
        "ov_kpi1": dict(value=gm, valueFormat="0.0%", target=gm_t, comparison=gm_ly, spark=list(by_m.gp / by_m.ns)),
        "ov_kpi2": dict(value=lfl_y / lfl_l - 1, valueFormat="+0.0%;-0.0%;0.0%", target=lfl_t,
                        comparison=lfl_l / lfl_l2 - 1, spark=list(lfl_m), signedValue=True),
        "ov_kpi3": dict(value=cov, valueFormat='0.0" wks"', target=7.0, comparison=cov_ly, spark=cov_m, lowerIsBetter=True),
    }

    # --- trend
    tm = t.assign(month=t.Month.str[5:7].astype(int)).groupby("month").SalesTarget.sum()
    vt, vl = ns / ns_t - 1, ns / ns_ly - 1
    trend = dict(categories=MONTHS[:10], actual=list(by_m.ns), target=[tm.get(m) for m in range(1, 11)],
                 comparison=list(by_m_ly.ns[:10]), annotations=[EVENTS.get(m) for m in range(1, 11)], format="\\$#,0")
    trend_title = (f"Sales are {pct(abs(vt))} {'ahead of' if vt >= 0 else 'behind'} target and "
                   f"{pct(abs(vl))} {'up on' if vl >= 0 else 'down on'} last year")

    # --- drivers
    chg = lambda g: y[y.Group == g].NetSales.sum() - l[l.Group == g].NetSales.sum()
    promo = lfl(y).Discount.sum() - lfl(l).Discount.sum()
    drivers = [("Like-for-like stores", chg("Like-for-like stores") + promo), ("Online", chg("Online")),
               ("New stores", chg("New stores")), ("Closed stores", chg("Closed stores")), ("Price and promo", -promo)]
    total = ns - ns_ly
    drivers_title = (f"Like-for-like stores delivered {drivers[0][1] / total:.0%} of the ${total / 1e6:,.1f}M growth"
                     if total >= 0 else f"Sales are ${-total / 1e6:,.1f}M below last year")

    # --- quadrant (like-for-like stores)
    names = stores.set_index("StoreKey").Store
    sy, sl = lfl(y).groupby("StoreKey"), lfl(l).groupby("StoreKey").NetSales.sum()
    q = pd.DataFrame({"sales": sy.NetSales.sum(), "gp": sy.GrossProfit.sum()}).join(sl.rename("ly"))
    q["x"], q["y"] = q.sales / q.ly - 1, q.gp / q.sales
    x_ref, y_ref = lfl_t, lfl(y).GrossProfit.sum() / lfl_y
    points = [dict(label=names[k], x=r.x, y=r.y, size=r.sales) for k, r in q.iterrows()]
    beat = int(((q.x > x_ref) & (q.y > y_ref)).sum())

    # --- treemap
    tc = y.groupby("Category").agg(s=("NetSales", "sum"), g=("GrossProfit", "sum"))
    tc["m"] = tc.g / tc.s
    big, best = tc.s.idxmax(), tc.m.idxmax()
    tree_title = f"{big} is {tc.s[big] / tc.s.sum():.0%} of sales at {tc.m[big]:.1%} margin; {best} earns {tc.m[best]:.0%}"

    # --- heatmap (footfall)
    fy = between(foot, "Date", YTD).copy()
    fy["wd"] = pd.to_datetime(fy.Date).dt.dayofweek
    hm = fy.pivot_table(index="wd", columns="Hour", values="Footfall", aggfunc="sum").sort_index()
    wd, h = np.unravel_index(np.argmax(hm.values), hm.shape)
    hour = hm.columns[h]
    part = "mornings" if hour < 12 else "afternoons" if hour < 17 else "evenings"
    heat_title = f"{WEEKDAY_NAMES[wd]} {part} are the busiest; roster for {hour - 1:02d}:00-{hour + 3:02d}:00"

    # --- funnel
    fu = between(funnel, "Date", YTD)
    stages = [("Sessions", fu.Sessions.sum()), ("Product views", fu.ProductViews.sum()), ("Add to cart", fu.AddToCart.sum()),
              ("Checkout", fu.Checkouts.sum()), ("Orders", fu.Orders.sum())]
    funnel_title = (f"Online converts {stages[4][1] / stages[0][1]:.1%}; "
                    f"{1 - stages[3][1] / stages[2][1]:.0%} of carts never reach checkout")

    # --- insights
    gap = ns - ns_t
    ch = y.groupby("Channel").NetSales.sum() / t.groupby("Channel").SalesTarget.sum() - 1
    rg = y.groupby("Region").NetSales.sum() / t.groupby("Region").SalesTarget.sum() - 1
    cat_c = (y.groupby("Category").GrossProfit.sum() / ns - l.groupby("Category").GrossProfit.sum() / ns_ly).sort_values()
    worst_r = rg.idxmin()
    reg_stores = stores[(stores.Region == worst_r) & (stores.Channel == "Store")].StoreKey
    stock = inv[inv.WeekEnding == last_in(*YTD)].groupby("StoreKey").StockValue.sum()
    end = pd.Timestamp(last_in(*YTD))
    win = sales[(pd.to_datetime(sales.Date) > end - pd.Timedelta(days=91)) & (pd.to_datetime(sales.Date) <= end)]
    st_cogs = (win.NetSales - win.GrossProfit).groupby(win.StoreKey).sum() / 13
    over9 = int(((stock / st_cogs).reindex(reg_stores.values).dropna() > 9).sum())
    insights = [
        f"Sales are **${abs(gap) / 1e6:,.1f}M {'ahead of' if gap >= 0 else 'behind'} target**, led by {ch.idxmax()} "
        f"({pct(ch.max(), True)} vs target) and {rg.idxmax()} ({pct(rg.max(), True)}).",
        f"Margin is **{abs(gm - gm_t) * 100:.1f} pts {'above' if gm >= gm_t else 'under'} target**: "
        + " and ".join(f"{c} ({tc.m[c]:.1%})" for c in cat_c.index[:2]) + " pull it down most.",
        f"**{worst_r}** is {pct(abs(rg.min()))} {'behind' if rg.min() < 0 else 'ahead of'} target; "
        f"{over9} of its stores hold more than 9 weeks of stock.",
    ]

    return {
        **{k: {"model": v} for k, v in kpis.items()},
        "ov_trend": {"model": trend, "title": trend_title},
        "ov_drivers": {"model": {"rows": [dict(label=a, value=b) for a, b in drivers], "format": "+\\$#,0;-\\$#,0;\\$#,0"},
                       "title": drivers_title},
        "ov_quadrant": {"model": {"points": points, "xRef": x_ref, "yRef": y_ref, "xFormat": "+0.0%;-0.0%;0.0%",
                                  "yFormat": "0.0%", "sizeFormat": "\\$#,0",
                                  "names": {"x": "Growth vs LY", "y": "Gross margin", "size": "Net sales"}},
                        "title": f"{beat} stores beat both the growth target and average margin"},
        "ov_treemap": {"model": {"items": [dict(label=c, size=r.s, color=r.m) for c, r in tc.iterrows()],
                                 "sizeFormat": "\\$#,0", "colorFormat": "0.0%",
                                 "names": {"size": "Net sales", "color": "Gross margin"}}, "title": tree_title},
        "ov_heatmap": {"model": {"rows": WEEKDAYS, "cols": [f"{c:02d}" for c in hm.columns],
                                 "values": hm.values.tolist(), "format": "#,0"}, "title": heat_title},
        "ov_funnel": {"model": {"stages": [dict(label=a, value=float(b), format="#,0") for a, b in stages]},
                      "title": funnel_title},
        "ov_insights": {"model": {"items": insights}},
        "expected": {"net_sales_ytd": ns, "target": ns_t, "ly": ns_ly, "margin": gm, "margin_target": gm_t,
                     "margin_ly": gm_ly, "lfl_growth": lfl_y / lfl_l - 1, "lfl_target": lfl_t, "cover": cov,
                     "cover_ly": cov_ly, "lfl_stores": len(q), "beat_both": beat},
    }


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas Retail prototype</title>
<style>{css}
html,body{{margin:0;background:#F7F3EE;font-family:'Segoe UI',system-ui,sans-serif;color:#1F1A17}}
.page{{position:relative;width:1280px;height:{height}px;margin:0 auto}}
.v{{position:absolute}}
.nav{{display:flex;gap:6px;align-items:stretch;height:100%;box-sizing:border-box;padding:4px;background:#fff;border:1px solid #E7E0D7;border-radius:22px}}
.nav span{{flex:1;display:flex;align-items:center;justify-content:center;border-radius:18px;font-size:14px;color:#6F6761;cursor:pointer}}
.nav span:hover{{background:#FBE7CC;color:#1F1A17}}
.nav span.on{{background:#DD7A12;color:#fff;font-weight:700}}
.pill{{height:100%;display:flex;flex-direction:column;justify-content:flex-end;gap:3px}}
.pill small{{font-size:11px;color:#6F6761;padding-left:2px}}
.pill b{{display:flex;justify-content:space-between;align-items:center;background:#fff;border:1px solid #E7E0D7;border-radius:6px;padding:6px 10px;font-size:13px;font-weight:400}}
</style></head><body><div class="page" id="page"></div>
<script>{js}</script>
<script>
const defn = {defn};
const data = {data};
const page = document.getElementById('page');
for (const v of defn.visuals) {{
  const box = document.createElement('div');
  box.className = 'v';
  Object.assign(box.style, {{left: v.x + 'px', top: v.y + 'px', width: v.w + 'px', height: v.h + 'px'}});
  page.appendChild(box);
  if (v.type === 'pageNavigator') {{
    box.innerHTML = '<div class="nav">' + ['Overview','Stores','Categories','Customers','Online']
      .map((p, i) => '<span class="' + (i ? '' : 'on') + '">' + p + '</span>').join('') + '</div>';
  }} else if (v.type === 'slicer') {{
    box.innerHTML = '<div class="pill"><small>' + v.label + '</small><b><span>' + (v.default || 'All') + '</span><span>⌄</span></b></div>';
  }} else if (v.type === 'textbox') {{
    box.innerHTML = (v.paragraphs || []).map(runs => '<div style="text-align:' + (v.align || 'left') + '">' +
      runs.map(r => '<span style="color:' + (r.color || '#1F1A17') + ';font-weight:' + (r.bold ? 600 : 400) + '">' + r.text + '</span>').join('') + '</div>').join('');
  }} else {{
    const d = data[v.id] || {{}};
    const f = v.format || {{}};
    let model = d.model || {{}};
    if (v.type === 'kpiCard') model = {{...model, label: f.kpi.label}};
    if (v.type === 'narrative') model = {{heading: f.narrative.heading, note: f.narrative.note, style: f.narrative.style,
      items: (d.model && d.model.items) || (f.narrative.lines || '').split('\\n')}};
    if (v.type === 'quadrant') model = {{...model, corners: f.quadrant, labelTop: f.quadrant.labelTop, labelBottom: f.quadrant.labelBottom}};
    if (v.type === 'heatmap') model = {{...model, indexMode: f.heatmap.indexMode, legend: {{low: f.heatmap.lowLabel, high: f.heatmap.highLabel}}}};
    const header = {{title: d.title || (f.header || {{}}).title, subtitle: (f.header || {{}}).subtitle,
      showCard: !(f.card && f.card.show === false)}};
    GenBIVisuals.render(v.type, box, model, header);
  }}
}}
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    root = HERE.parents[1]
    ap.add_argument("--data", type=Path, default=root / "output" / "GlobalRetail" / "Data")
    ap.add_argument("--out", type=Path, default=root / "output" / "GlobalRetail")
    ap.add_argument("--bundle", type=Path, default=root / "custom_visuals" / "prototype")
    args = ap.parse_args()
    data = compute(args.data)
    expected = data.pop("expected")
    defn = json.loads((HERE / "definition.json").read_text(encoding="utf-8"))
    page = next(p for p in defn["pages"] if p["name"] == "Overview")
    html = PAGE.format(css=(args.bundle / "genbi-visuals.css").read_text(encoding="utf-8"),
                       js=(args.bundle / "genbi-visuals.js").read_text(encoding="utf-8"),
                       height=page["height"], defn=json.dumps(page), data=json.dumps(data, default=float))
    out = args.out / "Prototype - Overview.html"
    out.write_text(html, encoding="utf-8")
    (args.out / "expected_overview.json").write_text(json.dumps(expected, indent=2, default=float))
    print(json.dumps(expected, indent=2, default=float))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
