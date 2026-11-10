#!/usr/bin/env python3
"""Synthetic star-schema dataset for "Atlas Retail", a large worldwide retailer.

Jan 2024 - Oct 2026, 122 stores in 24 countries, 17 online markets, 8 categories.
Writes CSVs into --out (deterministic seed, so numbers are reproducible):

  dim_country.csv          one row per country (region, currency, online availability)
  dim_store.csv            physical stores + one online "store" per online market
  dim_category.csv         8 merchandise categories
  fact_sales.csv           daily x store x category: net sales, gross profit, units, discount
  fact_targets.csv         monthly x store: sales and gross profit plan (2025, 2026)
  fact_footfall.csv        daily x store x hour (08-21): footfall and transactions
  fact_inventory.csv       weekly (week ending Saturday) x store x category: stock at cost
  fact_online_funnel.csv   daily x country x device x traffic source: funnel stages
  fact_customers.csv       monthly x store x loyalty tier: active, new, repeat, spend
  fact_cohorts.csv         monthly acquisition cohorts x country x months since joining

The story baked into the numbers (YTD 2026 vs 2025): sales grow ~6% with online and
Beauty leading; Asia Pacific misses plan; Electronics and Grocery margins erode so gross
margin lands under target; a bigger Autumn promo lifts October but costs margin; Asia
Pacific stores carry too much stock; Saturday 12:00-16:00 is the footfall peak.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261102
START, END = "2024-01-01", "2026-10-31"
YEARS = (2024, 2025, 2026)

# code, country, region, currency, price level, online market, physical stores, cities
COUNTRIES = [
    ("US", "United States", "North America", "USD", 1.15, True, 22,
     ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Seattle", "Boston", "Atlanta", "Dallas", "Miami"]),
    ("CA", "Canada", "North America", "CAD", 1.00, True, 6, ["Toronto", "Vancouver", "Montreal", "Calgary"]),
    ("MX", "Mexico", "North America", "MXN", 0.55, False, 4, ["Mexico City", "Guadalajara", "Monterrey"]),
    ("GB", "United Kingdom", "Europe", "GBP", 1.05, True, 12, ["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Bristol"]),
    ("DE", "Germany", "Europe", "EUR", 1.00, True, 8, ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne"]),
    ("FR", "France", "Europe", "EUR", 1.00, True, 7, ["Paris", "Lyon", "Marseille", "Lille"]),
    ("ES", "Spain", "Europe", "EUR", 0.85, True, 5, ["Madrid", "Barcelona", "Valencia"]),
    ("IT", "Italy", "Europe", "EUR", 0.90, True, 5, ["Milan", "Rome", "Turin"]),
    ("NL", "Netherlands", "Europe", "EUR", 1.00, True, 3, ["Amsterdam", "Rotterdam", "Utrecht"]),
    ("SE", "Sweden", "Europe", "SEK", 1.05, True, 2, ["Stockholm", "Gothenburg"]),
    ("PL", "Poland", "Europe", "PLN", 0.60, False, 3, ["Warsaw", "Krakow"]),
    ("AU", "Australia", "Asia Pacific", "AUD", 1.05, True, 6, ["Sydney", "Melbourne", "Brisbane", "Perth"]),
    ("JP", "Japan", "Asia Pacific", "JPY", 0.95, True, 6, ["Tokyo", "Osaka", "Yokohama", "Nagoya"]),
    ("SG", "Singapore", "Asia Pacific", "SGD", 1.10, True, 2, ["Singapore"]),
    ("IN", "India", "Asia Pacific", "INR", 0.35, True, 5, ["Mumbai", "Delhi", "Bengaluru", "Hyderabad"]),
    ("CN", "China", "Asia Pacific", "CNY", 0.60, False, 5, ["Shanghai", "Beijing", "Shenzhen", "Guangzhou"]),
    ("KR", "South Korea", "Asia Pacific", "KRW", 0.85, True, 3, ["Seoul", "Busan"]),
    ("BR", "Brazil", "Latin America", "BRL", 0.50, True, 5, ["São Paulo", "Rio de Janeiro", "Brasília"]),
    ("CL", "Chile", "Latin America", "CLP", 0.60, False, 2, ["Santiago"]),
    ("CO", "Colombia", "Latin America", "COP", 0.45, False, 2, ["Bogotá", "Medellín"]),
    ("AE", "United Arab Emirates", "Middle East & Africa", "AED", 1.10, True, 3, ["Dubai", "Abu Dhabi"]),
    ("SA", "Saudi Arabia", "Middle East & Africa", "SAR", 0.95, False, 2, ["Riyadh", "Jeddah"]),
    ("ZA", "South Africa", "Middle East & Africa", "ZAR", 0.50, True, 3, ["Johannesburg", "Cape Town"]),
    ("EG", "Egypt", "Middle East & Africa", "EGP", 0.30, False, 1, ["Cairo"]),
]
# Underlying growth for 2024, 2025, 2026 and the plan (target growth) for 2025, 2026.
REGIONS = {
    "North America": dict(g=(0.035, 0.045, 0.042), plan=(0.040, 0.040)),
    "Europe": dict(g=(0.025, 0.030, 0.036), plan=(0.030, 0.033)),
    "Asia Pacific": dict(g=(0.060, 0.062, 0.015), plan=(0.055, 0.050)),
    "Latin America": dict(g=(0.070, 0.085, 0.068), plan=(0.070, 0.060)),
    "Middle East & Africa": dict(g=(0.045, 0.050, 0.052), plan=(0.045, 0.048)),
}
ONLINE_GROWTH = (0.10, 0.10, 0.08)   # sessions and orders momentum
ONLINE_PLAN = (0.10, 0.12)
# annual sales $M at 2024 level, share of stores, avg transaction value $, conversion, selling area
FORMATS = {
    "Superstore": dict(sales=46.0, p=0.38, atv=78.0, conv=0.36, sqm=(9000, 14000)),
    "Department": dict(sales=29.0, p=0.24, atv=92.0, conv=0.27, sqm=(6000, 9000)),
    "Express": dict(sales=8.5, p=0.28, atv=27.0, conv=0.61, sqm=(600, 1400)),
    "Outlet": dict(sales=15.0, p=0.10, atv=61.0, conv=0.31, sqm=(2500, 4500)),
}
FORMAT_NAMES = list(FORMATS)
# name, department, store share by format (Superstore, Department, Express, Outlet), online share,
# gross margin 2024/25/26, extra growth 2025/26, avg unit price $, base weeks of cover
CATEGORIES = [
    ("Grocery", "Food", (0.40, 0.18, 0.70, 0.12), 0.10, (0.340, 0.338, 0.331), (0.000, 0.000), 4.6, 3.4),
    ("Apparel", "Fashion", (0.13, 0.27, 0.04, 0.42), 0.26, (0.478, 0.482, 0.490), (0.010, 0.012), 29.0, 11.5),
    ("Home", "Home", (0.11, 0.16, 0.05, 0.14), 0.14, (0.425, 0.428, 0.430), (-0.005, -0.012), 36.0, 10.0),
    ("Electronics", "Technology", (0.13, 0.16, 0.03, 0.10), 0.22, (0.228, 0.214, 0.195), (0.000, -0.035), 145.0, 6.5),
    ("Beauty", "Health & Beauty", (0.07, 0.10, 0.07, 0.08), 0.12, (0.528, 0.534, 0.540), (0.040, 0.060), 23.0, 8.0),
    ("Toys", "Leisure", (0.06, 0.05, 0.02, 0.06), 0.07, (0.352, 0.356, 0.360), (-0.010, -0.025), 25.0, 12.0),
    ("Sports & Outdoors", "Leisure", (0.06, 0.05, 0.02, 0.06), 0.06, (0.405, 0.408, 0.412), (0.020, 0.025), 39.0, 10.5),
    ("Health & Wellness", "Health & Beauty", (0.04, 0.03, 0.07, 0.02), 0.03, (0.452, 0.456, 0.460), (0.030, 0.040), 17.0, 8.5),
]
MONTH_SEASON = np.array([0.84, 0.80, 0.93, 0.95, 0.98, 0.96, 1.00, 1.02, 0.99, 1.06, 1.17, 1.42])
WEEKDAY_STORE = np.array([0.86, 0.88, 0.92, 0.98, 1.10, 1.32, 0.94])     # Mon..Sun
WEEKDAY_ONLINE = np.array([1.04, 1.02, 1.00, 0.99, 0.95, 0.92, 1.08])
# name, start (m, d), end (m, d), sales uplift, extra discount rate
EVENTS = [
    ("Spring sale", (3, 20), (4, 5), 0.07, 0.05),
    ("Summer sale", (7, 1), (7, 16), 0.10, 0.08),
    ("Back to school", (8, 18), (9, 6), 0.05, 0.02),
    ("Autumn promo", (10, 1), (10, 19), 0.09, 0.06),
    ("Black Friday", (11, 24), (11, 30), 0.38, 0.12),
    ("Christmas", (12, 10), (12, 24), 0.22, 0.03),
]
BASE_DISCOUNT = {2024: 0.040, 2025: 0.043, 2026: 0.049}
HOURS = np.arange(8, 22)
HOUR_PROFILE = {  # share of daily footfall by hour 08..21
    "weekday": [0.030, 0.045, 0.060, 0.075, 0.100, 0.100, 0.080, 0.075, 0.080, 0.095, 0.090, 0.075, 0.055, 0.040],
    "friday": [0.025, 0.040, 0.055, 0.070, 0.090, 0.090, 0.075, 0.075, 0.085, 0.100, 0.100, 0.090, 0.065, 0.040],
    "saturday": [0.018, 0.035, 0.060, 0.082, 0.112, 0.125, 0.125, 0.118, 0.104, 0.078, 0.058, 0.040, 0.027, 0.018],
    "sunday": [0.010, 0.030, 0.070, 0.100, 0.120, 0.120, 0.115, 0.110, 0.100, 0.090, 0.070, 0.040, 0.020, 0.005],
}
HOUR_CONV = np.array([1.12, 1.08, 1.04, 1.00, 0.95, 0.93, 0.94, 0.96, 0.98, 1.00, 1.02, 1.04, 1.07, 1.10])
DEVICES = [("Mobile", 0.60, 0.78), ("Desktop", 0.30, 1.25), ("App", 0.10, 1.90)]
SOURCES = [("Organic search", 0.33, 1.00), ("Direct", 0.22, 1.30), ("Paid search", 0.17, 0.90),
           ("Social", 0.15, 0.45), ("Email", 0.13, 1.60)]
ONLINE_SESSIONS = {"US": 165e3, "CA": 26e3, "GB": 70e3, "DE": 55e3, "FR": 45e3, "ES": 22e3, "IT": 20e3,
                   "NL": 14e3, "SE": 9e3, "AU": 25e3, "JP": 50e3, "SG": 7e3, "IN": 40e3, "KR": 18e3,
                   "BR": 30e3, "AE": 8e3, "ZA": 9e3}
TIERS = [  # tier, share of identified transactions, visits per month, repeat rate, share of identified sales
    ("Platinum", 0.12, 5.5, 0.93, 0.17),
    ("Gold", 0.25, 3.6, 0.82, 0.29),
    ("Silver", 0.33, 2.2, 0.58, 0.32),
    ("Bronze", 0.30, 1.4, 0.31, 0.22),
]
NEW_RATE = {"Platinum": 0.001, "Gold": 0.004, "Silver": 0.015, "Bronze": 0.070}
RETENTION = [1.0, 0.47, 0.41, 0.38, 0.36, 0.345, 0.335, 0.325, 0.315, 0.31, 0.30, 0.295, 0.29]
LOCALES = [
    "Riverside", "Northgate", "Mill Road", "Harbour Point", "Westfield", "Old Town", "Parkside", "Station Square",
    "Canal Street", "Hillcrest", "Lakeside", "Market Street", "Kingsway", "Eastgate", "Southbank", "Meadowhall",
    "Crossroads", "Bayview", "Oakwood", "Brookfield", "Fairview", "Highfield", "Greenway", "Victoria Park",
    "Union Square", "Downtown", "Midtown", "Uptown", "Seaside", "Airport Plaza", "Central Mall", "City Centre",
    "Waterfront", "Garden City", "Pinewood", "Maple Grove", "Silver Lake", "Stonebridge", "Ashford", "Redwood",
    "Elm Park", "Clearwater", "Sunset Mall", "Gateway", "Queensway", "Marina", "Heritage Square", "Palm Court",
    "Cedar Point", "Willow Bank", "Forest Hill", "Rosewood", "Kings Cross", "Grand Arcade", "Bridgewater",
    "Castle Gate", "Northpoint", "Southgate", "West End", "East Village", "Harbourfront", "Lighthouse",
    "Orchard Park", "Riverbend", "Sky Plaza", "Summit", "Valley Fair", "Wharf Side", "Beacon Hill", "Copper Square",
    "Crystal Court", "Dockside", "Emerald Mall", "Fountain Square", "Glen Park", "Hampton", "Ivy Lane", "Jubilee",
    "Kensal", "Linden", "Mayfair", "Newbridge", "Oxford Row", "Pier Point", "Quayside", "Regent", "Sandhurst",
    "Tower Hill", "University", "Vista", "Windmill", "Yardley", "Zenith", "Avenue One", "Bellevue", "Chestnut",
    "Dunmore", "Elmstead", "Fernhill", "Goldcrest", "Hawthorn", "Iris Gardens", "Juniper", "Kestrel", "Larkspur",
    "Moorgate", "Nightingale", "Oakfield", "Primrose", "Queens Park", "Raven Court", "Seabrook", "Thornbury",
    "Upton", "Verity", "Westbrook", "Yew Tree", "Alder", "Birchwood", "Coral Bay", "Delta Park", "Echo Square",
]
FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Lucas", "Mia", "Ethan", "Sofia", "Mateo", "Hana", "Arjun",
         "Chloe", "Leon", "Aisha", "Kenji", "Elena", "Omar", "Ines", "Daniel", "Priya", "Jonas", "Yuna", "Carlos"]
LAST = ["Smith", "Garcia", "Müller", "Rossi", "Tanaka", "Patel", "Nguyen", "Silva", "Kowalski", "Johansson",
        "Dubois", "Kim", "Brown", "Martin", "Haddad", "Okafor", "Lopez", "Chen", "Novak", "Taylor"]


def growth_index(rates: np.ndarray, years: np.ndarray, frac: np.ndarray) -> np.ndarray:
    """rates (n, 3) for 2024..2026 -> level index (n, days). Each year's rate is its growth over the
    same day of the previous year, so YTD vs LY comparisons show exactly that rate (plus mix effects)."""
    del frac
    return np.exp(np.cumsum(np.log1p(rates), axis=1)[:, years])


def main(out: Path) -> None:
    rng = np.random.default_rng(SEED)
    out.mkdir(parents=True, exist_ok=True)

    dates = pd.date_range(START, END, freq="D")
    n_days = len(dates)
    year = dates.year.values
    yi = year - 2024
    month = dates.month.values
    dow = dates.dayofweek.values
    frac = (dates.dayofyear.values - 1) / np.where(dates.is_leap_year, 366, 365)
    date_str = dates.strftime("%Y-%m-%d").values

    uplift = np.zeros(n_days)
    disc_extra = np.zeros(n_days)
    for name, (m1, d1), (m2, d2), up, disc in EVENTS:
        for y in YEARS:
            mask = (dates >= pd.Timestamp(y, m1, d1)) & (dates <= pd.Timestamp(y, m2, d2))
            boost = 1.35 if (name == "Autumn promo" and y == 2026) else 1.0   # the 2026 promo went bigger
            uplift[mask] += up * boost
            disc_extra[mask] += disc * boost
    base_disc = np.vectorize(BASE_DISCOUNT.get)(year)

    # ---------- dimensions ----------
    countries = pd.DataFrame([dict(CountryKey=i + 1, CountryCode=c[0], Country=c[1], Region=c[2], Currency=c[3],
                                   OnlineAvailable="Yes" if c[5] else "No") for i, c in enumerate(COUNTRIES)])
    price = {c[0]: c[4] for c in COUNTRIES}
    region_of = {c[0]: c[2] for c in COUNTRIES}

    rows = []
    for ci, (code, _, region, _, plevel, _, n, cities) in enumerate(COUNTRIES):
        for i in range(n):
            fmt = rng.choice(FORMAT_NAMES, p=[FORMATS[f]["p"] for f in FORMAT_NAMES])
            if i == 0 and n >= 5:
                fmt = "Superstore"   # flagship in the larger markets
            rows.append(dict(CountryKey=ci + 1, cc=code, region=region, City=cities[i % len(cities)], Format=fmt,
                             OpenDate=pd.Timestamp("2004-01-01") + pd.DateOffset(days=int(rng.integers(0, 7100)))))
    phys = pd.DataFrame(rows)
    # 8 new stores (2025-26) and 5 closures (2025-26) give the "new" and "closed" growth drivers.
    new_idx = rng.choice(phys.index[phys.region != "Asia Pacific"], 8, replace=False)
    phys.loc[new_idx, "OpenDate"] = [pd.Timestamp("2025-02-01") + pd.DateOffset(days=int(d))
                                     for d in rng.integers(0, 500, 8)]
    old = phys.index[(~phys.index.isin(new_idx)) & (phys.OpenDate < "2015-01-01")]
    closed_idx = rng.choice(old, 5, replace=False)
    phys["CloseDate"] = pd.NaT
    phys.loc[closed_idx, "CloseDate"] = [pd.Timestamp("2025-03-01") + pd.DateOffset(days=int(d))
                                         for d in rng.integers(0, 390, 5)]
    phys = phys.sort_values("OpenDate").reset_index(drop=True)   # store codes follow opening order
    phys["StoreCode"] = [f"{i + 1:03d}" for i in range(len(phys))]
    locales = rng.permutation(LOCALES)[:len(phys)]
    phys["Store"] = [f"{c} {loc}" for c, loc in zip(phys.StoreCode, locales)]
    phys["SellingAreaSqm"] = [int(rng.integers(*FORMATS[f]["sqm"])) for f in phys.Format]
    phys["Manager"] = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(len(phys))]
    n_p = len(phys)

    online_cc = [c[0] for c in COUNTRIES if c[5]]
    online = pd.DataFrame(dict(cc=online_cc, region=[region_of[c] for c in online_cc],
                               CountryKey=[countries.set_index("CountryCode").CountryKey[c] for c in online_cc]))
    online["StoreCode"] = [f"9{i + 1:02d}" for i in range(len(online))]
    online["Store"] = [f"{countries.set_index('CountryCode').Country[c]} Online" for c in online.cc]
    n_o = len(online)

    stores = pd.concat([
        phys.assign(StoreType="Physical", Channel="Store"),
        online.assign(StoreType="Online", Channel="Online", Format="Online", City="",
                      OpenDate=pd.Timestamp("2016-03-01"), CloseDate=pd.NaT, SellingAreaSqm=np.nan,
                      Manager="Digital team"),
    ], ignore_index=True)
    stores["StoreKey"] = np.arange(1, len(stores) + 1)
    phys["StoreKey"] = stores.StoreKey[:n_p].values
    online["StoreKey"] = stores.StoreKey[n_p:].values

    categories = pd.DataFrame([dict(CategoryKey=i + 1, Category=c[0], Department=c[1], SortOrder=i + 1)
                               for i, c in enumerate(CATEGORIES)])
    n_c = len(CATEGORIES)
    share = np.array([[c[2][FORMAT_NAMES.index(f)] for c in CATEGORIES] for f in phys.Format])     # (n_p, 8)
    online_share = np.array([c[3] for c in CATEGORIES])
    margin = np.array([c[4] for c in CATEGORIES])                                                     # (8, 3)
    unit_price = np.array([c[6] for c in CATEGORIES])
    cover = np.array([c[7] for c in CATEGORIES])
    cat_rates = np.array([[0.0, c[5][0], c[5][1]] for c in CATEGORIES])

    # ---------- physical store sales: (store, category, day) ----------
    plev = phys.cc.map(price).values
    base = np.array([FORMATS[f]["sales"] for f in phys.Format]) * 1e6 * plev ** 0.7 \
        * rng.lognormal(0, 0.22, n_p) / 365.0
    reg = phys.region.values
    store_rates = np.stack([np.array([REGIONS[r]["g"][k] for r in reg]) + rng.normal(0, sd, n_p)
                            for k, sd in enumerate((0.02, 0.03, 0.035))], axis=1)
    open_d = phys.OpenDate.values[:, None]
    close_d = phys.CloseDate.fillna(pd.Timestamp("2099-01-01")).values[:, None]
    alive = (dates.values[None, :] >= open_d) & (dates.values[None, :] <= close_d)
    months_open = (dates.values[None, :] - open_d).astype("timedelta64[D]").astype(float) / 30.4
    ramp = np.clip(0.65 + 0.35 * months_open / 6.0, 0, 1)
    season = MONTH_SEASON[month - 1] * WEEKDAY_STORE[dow] * (1 + uplift)
    level = base[:, None] * growth_index(store_rates, yi, frac) * season[None, :] * ramp * alive    # (n_p, days)
    sales = level[:, None, :] * share[:, :, None] * growth_index(cat_rates, yi, frac)[None, :, :] \
        * rng.lognormal(0, 0.12, (n_p, n_c, n_days))
    store_margin = rng.normal(0, 0.018, n_p) - np.where(reg == "Asia Pacific", 0.008, 0)
    gm = margin[:, yi][None, :, :] + store_margin[:, None, None] - 0.3 * disc_extra[None, None, :] \
        + rng.normal(0, 0.008, (n_p, n_c, n_days))

    # ---------- online funnel: (country, day, device, source) ----------
    sess_base = np.array([ONLINE_SESSIONS[c] for c in online_cc])
    o_rates = np.tile(np.array(ONLINE_GROWTH), (n_o, 1)) + rng.normal(0, 0.02, (n_o, 3))
    o_level = sess_base[:, None] * growth_index(o_rates, yi, frac) \
        * (MONTH_SEASON[month - 1] * WEEKDAY_ONLINE[dow] * (1 + 1.2 * uplift))[None, :] \
        * rng.lognormal(0, 0.06, (n_o, n_days))
    dev_share = np.array([d[1] for d in DEVICES])
    src_share = np.array([s[1] for s in SOURCES])
    seg_share = dev_share[:, None] * src_share[None, :]                                   # (3, 5)
    seg_conv = np.array([d[2] for d in DEVICES])[:, None] * np.array([s[2] for s in SOURCES])[None, :]
    seg_conv = seg_conv / (seg_conv * seg_share).sum()                                     # mean 1.0
    conv_year = np.array([0.0372, 0.0381, 0.0392])[yi]                                     # conversion improves
    sessions = o_level[:, :, None, None] * seg_share[None, None] \
        * rng.lognormal(0, 0.05, (n_o, n_days, 3, 5))
    country_conv = rng.lognormal(0, 0.18, n_o)
    country_conv /= country_conv.mean()                                                    # markets convert differently
    conv = conv_year[None, :, None, None] * seg_conv[None, None] * country_conv[:, None, None, None]         * rng.lognormal(0, 0.05, (n_o, n_days, 3, 5))
    orders = np.round(sessions * conv)
    checkout = np.round(orders / (0.63 * rng.lognormal(0, 0.03, orders.shape)))
    cart = np.round(checkout / (0.487 * rng.lognormal(0, 0.03, orders.shape)))
    views = np.round(np.maximum(sessions * 0.61 * rng.lognormal(0, 0.03, orders.shape), cart * 1.2))
    sessions = np.round(sessions)
    o_plev = np.array([price[c] for c in online_cc])
    aov = 112.0 * o_plev[:, None] ** 0.6 * (1.03 ** yi)[None, :]
    online_sales = (orders.sum(axis=(2, 3)) * aov)[:, None, :] * online_share[None, :, None] \
        * rng.lognormal(0, 0.10, (n_o, n_c, n_days))
    online_gm = margin[:, yi][None, :, :] - 0.03 - 0.3 * disc_extra[None, None, :] \
        + rng.normal(0, 0.008, (n_o, n_c, n_days))

    # ---------- fact_sales ----------
    all_sales = np.concatenate([sales, online_sales])                                       # (stores, 8, days)
    all_gm = np.concatenate([gm, online_gm])
    all_plev = np.concatenate([plev, o_plev])
    disc_rate = (base_disc + disc_extra)[None, None, :] + np.array(
        [0.02 if c[0] == "Apparel" else 0.0 for c in CATEGORIES])[None, :, None]
    s_i, c_i, d_i = np.nonzero(all_sales > 1.0)
    net = all_sales[s_i, c_i, d_i]
    fact_sales = pd.DataFrame({
        "Date": date_str[d_i],
        "StoreKey": stores.StoreKey.values[s_i],
        "CategoryKey": c_i + 1,
        "NetSales": np.round(net, 2),
        "GrossProfit": np.round(net * all_gm[s_i, c_i, d_i], 2),
        "Units": np.maximum(1, np.round(net / (unit_price[c_i] * all_plev[s_i] ** 0.6 * (1.03 ** yi[d_i])))).astype(int),
        "Discount": np.round(net * disc_rate[0, c_i, d_i] / (1 - disc_rate[0, c_i, d_i]), 2),
    })

    # ---------- fact_footfall: physical stores, hourly ----------
    day_sales = sales.sum(axis=1)                                                           # (n_p, days)
    atv = np.array([FORMATS[f]["atv"] for f in phys.Format])[:, None] * plev[:, None] ** 0.6 \
        * (1.025 ** yi)[None, :] * np.where(month == 12, 1.08, 1.0)[None, :]
    tx_day = day_sales / atv * rng.lognormal(0, 0.03, day_sales.shape)
    store_conv = np.array([FORMATS[f]["conv"] for f in phys.Format]) * rng.lognormal(0, 0.06, n_p)
    conv_day = store_conv[:, None] * (1 + 0.012 * yi)[None, :] * np.where(dow >= 5, 0.95, 1.0)[None, :]
    foot_day = tx_day / conv_day
    prof_key = np.where(dow == 5, "saturday", np.where(dow == 6, "sunday", np.where(dow == 4, "friday", "weekday")))
    profiles = np.array([HOUR_PROFILE[k] for k in prof_key])                               # (days, 14)
    prof = profiles[None] * rng.lognormal(0, 0.08, (n_p, n_days, len(HOURS)))
    prof /= prof.sum(axis=2, keepdims=True)
    prof_tx = prof * HOUR_CONV[None, None, :]
    prof_tx /= prof_tx.sum(axis=2, keepdims=True)
    foot = np.round(foot_day[:, :, None] * prof)
    tx = np.minimum(np.round(tx_day[:, :, None] * prof_tx), foot)
    fs, fd, fh = np.nonzero(foot > 0)
    fact_footfall = pd.DataFrame({"Date": date_str[fd], "StoreKey": phys.StoreKey.values[fs], "Hour": HOURS[fh],
                                  "Footfall": foot[fs, fd, fh].astype(int), "Transactions": tx[fs, fd, fh].astype(int)})

    # ---------- fact_inventory: weekly stock at cost, physical stores ----------
    cogs = sales * (1 - gm)
    cum = np.cumsum(cogs, axis=2)
    week_end = np.nonzero(dow == 5)[0]                                                      # Saturdays
    week_end = week_end[week_end >= 6]
    weekly = cum[:, :, week_end] - cum[:, :, week_end - 7]
    roll = pd.DataFrame(weekly.reshape(-1, len(week_end)).T).rolling(13, min_periods=4).mean().T.values \
        .reshape(weekly.shape)
    wk_year = yi[week_end]
    wk_month = month[week_end]
    year_factor = np.array([1.05, 1.035, 0.982])[wk_year]
    seasonal = np.ones((n_c, len(week_end)))
    seasonal[[c[0] for c in CATEGORIES].index("Toys"), np.isin(wk_month, [9, 10, 11])] = 1.35
    seasonal[[c[0] for c in CATEGORIES].index("Apparel"), np.isin(wk_month, [3, 9])] = 1.10
    store_cover = rng.lognormal(0, 0.08, n_p) * np.where(reg == "Asia Pacific", 1.30, 1.0)
    heavy = rng.choice(np.nonzero(reg == "Asia Pacific")[0], 2, replace=False)
    store_cover[heavy] *= 1.30                                                              # two badly overstocked stores
    stock = roll * cover[None, :, None] * store_cover[:, None, None] * year_factor[None, None, :] \
        * seasonal[None] * rng.lognormal(0, 0.06, roll.shape)
    is_, ic, iw = np.nonzero(np.nan_to_num(stock) > 0)
    fact_inventory = pd.DataFrame({
        "WeekEnding": date_str[week_end[iw]],
        "StoreKey": phys.StoreKey.values[is_],
        "CategoryKey": ic + 1,
        "StockValue": np.round(stock[is_, ic, iw], 2),
        "StockUnits": np.round(stock[is_, ic, iw] / (unit_price[ic] * plev[is_] ** 0.6 * 0.6)).astype(int),
    })

    # ---------- fact_online_funnel ----------
    oi, od, ov, os_ = np.indices(orders.shape).reshape(4, -1)
    fact_online = pd.DataFrame({
        "Date": date_str[od], "CountryKey": online.CountryKey.values[oi],
        "Device": np.array([d[0] for d in DEVICES])[ov], "Source": np.array([s[0] for s in SOURCES])[os_],
        "Sessions": sessions.reshape(-1).astype(int), "ProductViews": views.reshape(-1).astype(int),
        "AddToCart": cart.reshape(-1).astype(int), "Checkouts": checkout.reshape(-1).astype(int),
        "Orders": orders.reshape(-1).astype(int),
    })

    # ---------- monthly aggregates used by customers / targets ----------
    month_id = (year - 2024) * 12 + (month - 1)                                            # 0..33
    n_m = month_id.max() + 1
    month_start = pd.date_range("2024-01-01", periods=36, freq="MS")
    onehot = np.zeros((n_days, n_m))
    onehot[np.arange(n_days), month_id] = 1.0
    store_month_sales = np.concatenate([sales.sum(axis=1), online_sales.sum(axis=1)]) @ onehot      # (stores, m)
    store_month_tx = np.concatenate([tx.sum(axis=2), orders.sum(axis=(2, 3))]) @ onehot
    gp_all = np.concatenate([(sales * gm).sum(axis=1), (online_sales * online_gm).sum(axis=1)]) @ onehot

    # ---------- fact_customers ----------
    is_online = np.r_[np.zeros(n_p, bool), np.ones(n_o, bool)]
    ident = np.where(is_online[:, None], 0.90, 0.58 + 0.02 * (np.arange(n_m) // 12)[None, :])
    cust_rows = []
    new_by_store = np.zeros((len(stores), n_m))
    for tier, tx_share, visits, repeat, sales_share in TIERS:
        active = store_month_tx * ident * tx_share / visits * rng.lognormal(0, 0.03, store_month_tx.shape)
        new = active * NEW_RATE[tier] * rng.lognormal(0, 0.10, active.shape) * (1 + 0.08 * (np.arange(n_m) // 12))
        rep = np.minimum(active * repeat * rng.lognormal(0, 0.02, active.shape), active)
        spend = store_month_sales * np.minimum(ident * 1.05, 0.97) * sales_share
        new_by_store += new
        si, mi = np.nonzero(active >= 1)
        cust_rows.append(pd.DataFrame({
            "Month": month_start[mi].strftime("%Y-%m-%d"), "StoreKey": stores.StoreKey.values[si], "Tier": tier,
            "ActiveCustomers": np.round(active[si, mi]).astype(int), "NewCustomers": np.round(new[si, mi]).astype(int),
            "RepeatCustomers": np.round(rep[si, mi]).astype(int), "CustomerSales": np.round(spend[si, mi], 2)}))
    fact_customers = pd.concat(cust_rows, ignore_index=True)

    # ---------- fact_cohorts ----------
    cohort_rows = []
    region_ret = {"North America": 1.02, "Europe": 1.00, "Asia Pacific": 0.92, "Latin America": 0.96,
                  "Middle East & Africa": 0.97}
    store_country = stores.CountryKey.values
    for ck, region in zip(countries.CountryKey, countries.Region):
        size = new_by_store[store_country == ck].sum(axis=0)
        for m0 in range(n_m):
            if size[m0] < 1:
                continue
            lift = 0.02 if m0 >= 24 else 0.0                                               # 2026 cohorts retain better
            for k in range(n_m - m0):
                ret = 1.0 if k == 0 else min(1.0, (RETENTION[k] if k < len(RETENTION) else RETENTION[-1] * 0.995 ** (k - 12))
                                         * region_ret[region] + lift)
                cohort_rows.append((month_start[m0].strftime("%Y-%m-%d"), ck, k, int(round(size[m0])),
                                    int(round(size[m0] * ret * rng.lognormal(0, 0.03)))))
    fact_cohorts = pd.DataFrame(cohort_rows, columns=["CohortMonth", "CountryKey", "MonthsSince", "CohortSize",
                                                       "ActiveCustomers"])

    # ---------- fact_targets: monthly plan for 2025 and 2026 (full years) ----------
    reg_all = np.r_[phys.region.values, online.region.values]
    tgt_rows = []
    exp_month = np.r_[np.array([FORMATS[f]["sales"] for f in phys.Format]) * 1e6 * plev ** 0.7 / 12,
                      online_sales.sum(axis=(1, 2)) / n_days * 30.4]
    open_all = stores.OpenDate.values
    close_all = stores.CloseDate.fillna(pd.Timestamp("2099-01-01")).values
    for y_idx, y in ((0, 2025), (1, 2026)):
        for m in range(12):
            mid_ly = (y - 1 - 2024) * 12 + m
            ms = pd.Timestamp(y, m + 1, 1)
            if ms > pd.Timestamp("2026-12-01"):
                continue
            ly = store_month_sales[:, mid_ly]
            ly_gp = gp_all[:, mid_ly]
            plan = np.array([ONLINE_PLAN[y_idx] if o else REGIONS[r]["plan"][y_idx] for r, o in zip(reg_all, is_online)])
            tgt = ly * (1 + plan + rng.normal(0, 0.012, len(ly)))
            typical = exp_month * MONTH_SEASON[m]
            fresh = ly < 0.5 * typical                       # no full LY month (new store): plan from format
            tgt = np.where(fresh, typical * (1.0 + 0.04 * (y - 2024)), tgt)
            ly_margin = np.where(ly > 0, ly_gp / np.maximum(ly, 1), 0.38)
            gp_tgt = tgt * (np.clip(ly_margin, 0.15, 0.6) + (0.0035 if y == 2026 else 0.002))
            live = (open_all <= np.datetime64(ms + pd.offsets.MonthEnd(0))) & (close_all >= np.datetime64(ms))
            for si in np.nonzero(live)[0]:
                tgt_rows.append((ms.strftime("%Y-%m-%d"), int(stores.StoreKey[si]), round(float(tgt[si]), 2),
                                 round(float(gp_tgt[si]), 2)))
    fact_targets = pd.DataFrame(tgt_rows, columns=["Month", "StoreKey", "SalesTarget", "GrossProfitTarget"])

    # ---------- write ----------
    dim_store = stores[["StoreKey", "StoreCode", "Store", "StoreType", "Channel", "Format", "City", "CountryKey",
                        "OpenDate", "CloseDate", "SellingAreaSqm", "Manager"]].copy()
    dim_store["OpenDate"] = dim_store.OpenDate.dt.strftime("%Y-%m-%d")
    dim_store["CloseDate"] = dim_store.CloseDate.dt.strftime("%Y-%m-%d")
    dim_store["SellingAreaSqm"] = dim_store.SellingAreaSqm.astype("Int64")
    files = {
        "dim_country.csv": countries, "dim_store.csv": dim_store, "dim_category.csv": categories,
        "fact_sales.csv": fact_sales, "fact_targets.csv": fact_targets, "fact_footfall.csv": fact_footfall,
        "fact_inventory.csv": fact_inventory, "fact_online_funnel.csv": fact_online,
        "fact_customers.csv": fact_customers, "fact_cohorts.csv": fact_cohorts,
    }
    for name, df in files.items():
        df.to_csv(out / name, index=False)
        print(f"{name:26s} {len(df):>9,} rows  {(out / name).stat().st_size / 1e6:6.1f} MB")
    print(f"{'total':26s} {sum(len(d) for d in files.values()):>9,} rows")

    expected = expected_kpis(fact_sales, fact_targets, fact_inventory, fact_footfall, fact_online, stores)
    (out.parent / "expected_kpis.json").write_text(json.dumps(expected, indent=2))
    print(json.dumps(expected, indent=2))


def expected_kpis(sales, targets, inventory, footfall, online, stores) -> dict:
    """YTD Jan-Oct 2026 vs the same period of 2025, computed the way the DAX measures define them."""
    s = sales.copy()
    s["Date"] = pd.to_datetime(s.Date)
    ytd = s[(s.Date >= "2026-01-01") & (s.Date <= "2026-10-31")]
    ly = s[(s.Date >= "2025-01-01") & (s.Date <= "2025-10-31")]
    t = targets[(targets.Month >= "2026-01-01") & (targets.Month <= "2026-10-01")]
    st = stores.set_index("StoreKey")
    lfl_keys = st.index[(st.StoreType == "Physical") & (st.OpenDate <= "2025-01-01") & st.CloseDate.isna()]
    lfl = lambda df: df[df.StoreKey.isin(lfl_keys)].NetSales.sum()
    inv = inventory[inventory.WeekEnding == inventory.WeekEnding.max()].StockValue.sum()
    last = pd.Timestamp(inventory.WeekEnding.max())
    win = s[(s.Date > last - pd.DateOffset(days=91)) & (s.Date <= last) & s.StoreKey.isin(st.index[st.StoreType == "Physical"])]
    f = footfall[(footfall.Date >= "2026-01-01")]
    o = online[(online.Date >= "2026-01-01")]
    return {
        "net_sales_ytd": round(ytd.NetSales.sum(), 0),
        "net_sales_ly": round(ly.NetSales.sum(), 0),
        "vs_ly_pct": round(ytd.NetSales.sum() / ly.NetSales.sum() - 1, 4),
        "sales_target_ytd": round(t.SalesTarget.sum(), 0),
        "vs_target_pct": round(ytd.NetSales.sum() / t.SalesTarget.sum() - 1, 4),
        "gross_margin_pct": round(ytd.GrossProfit.sum() / ytd.NetSales.sum(), 4),
        "gross_margin_ly_pct": round(ly.GrossProfit.sum() / ly.NetSales.sum(), 4),
        "gross_margin_target_pct": round(t.GrossProfitTarget.sum() / t.SalesTarget.sum(), 4),
        "lfl_growth_pct": round(lfl(ytd) / lfl(ly) - 1, 4),
        "inventory_cover_wks": round(inv / ((win.NetSales.sum() - win.GrossProfit.sum()) / 13), 2),
        "store_conversion_pct": round(f.Transactions.sum() / f.Footfall.sum(), 4),
        "online_conversion_pct": round(o.Orders.sum() / o.Sessions.sum(), 4),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data")
    main(ap.parse_args().out)
