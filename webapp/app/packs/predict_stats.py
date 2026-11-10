"""Forecasting maths for Predictive analytics & forecasting (registry id `predict`) — simple, explainable methods only,
in numpy (no model library, no AI): seasonal naive (the baseline every other method must beat), exponential smoothing
(ETS: Holt-Winters with an additive trend and season, smoothing weights chosen by the in-sample one-step error), and a
linear trend with seasonal effects (ordinary least squares). Each method is back-tested on a holdout of the latest
periods it never saw, and its accuracy is reported as MAPE and WAPE against those actuals.

Every function is pure (lists in, dicts out), so the tests check the maths directly."""
from __future__ import annotations

import math

import numpy as np

METHODS = {"seasonal_naive": "Seasonal naive (same period last cycle)", "linear_seasonal": "Linear trend with seasonality",
           "ets": "Exponential smoothing (Holt-Winters)"}
SIMPLE_FIRST = ("seasonal_naive", "linear_seasonal", "ets")       # the order of simplicity: a tie goes to the simpler one
SEASON = {"day": 7, "week": 52, "month": 12, "quarter": 4}
WHY = {"seasonal_naive": "repeats the same period of the last cycle: the yardstick",
       "linear_seasonal": "a straight-line trend plus the average effect of each period of the cycle",
       "ets": "weights recent periods more and follows the trend and the seasonal shape as they move"}


def season_for(grain: str, n: int) -> int:
    """The cycle length used for a grain, or 1 when the history holds fewer than two full cycles."""
    m = SEASON.get(grain, 1)
    return m if n >= 2 * m else 1


# ------------------------------------------------------------------ the three methods: fit on y, forecast h periods

def seasonal_naive(y: list[float], m: int, h: int) -> list[float]:
    y = [float(v) for v in y]
    if not y:
        return [0.0] * h
    if m <= 1 or len(y) < m:
        return [y[-1]] * h
    return [y[len(y) - m + (i % m)] for i in range(h)]


def linear_seasonal(y: list[float], m: int, h: int) -> list[float]:
    """y_t = a + b·t + s_(t mod m), least squares (the seasonal effects sum to zero through dummy coding)."""
    n = len(y)
    if n < 3:
        return seasonal_naive(y, m, h)
    t = np.arange(n, dtype=float)

    def design(ts):
        cols = [np.ones(len(ts)), ts]
        if m > 1:
            for k in range(1, m):
                cols.append(np.array([1.0 if int(x) % m == k else 0.0 for x in ts]))
        return np.column_stack(cols)
    X = design(t)
    beta, *_ = np.linalg.lstsq(X, np.asarray(y, dtype=float), rcond=None)
    tf = np.arange(n, n + h, dtype=float)
    return [float(v) for v in design(tf) @ beta]


def _hw(y: np.ndarray, m: int, alpha: float, beta: float, gamma: float, h: int, mult: bool = False) -> tuple[float, list[float]]:
    """Holt-Winters with a trend and an additive (or multiplicative: the season as a share of the level) season:
    (one-step in-sample SSE, h forecasts). Level and trend start from the first two cycles; the season from the first
    cycle with that trend taken out."""
    n = len(y)
    if m > 1:
        level = float(np.mean(y[:m]))
        trend = float((np.mean(y[m:2 * m]) - np.mean(y[:m])) / m) if n >= 2 * m else 0.0
        base = [level + trend * (i - (m - 1) / 2) for i in range(m)]
        season = [float(y[i] / base[i]) if mult else float(y[i] - base[i]) for i in range(m)]
        level += trend * (m - 1) / 2
        start = m
    else:
        level, trend, season, start = float(y[0]), float(y[1] - y[0]) if n > 1 else 0.0, [0.0], 1
    sse = 0.0
    for t in range(start, n):
        s = season[t % m] if m > 1 else (1.0 if mult else 0.0)
        pred = (level + trend) * s if mult else level + trend + s
        err = float(y[t]) - pred
        sse += err * err
        new_level = alpha * (float(y[t]) / s if mult else float(y[t]) - s) + (1 - alpha) * (level + trend)
        trend = beta * (new_level - level) + (1 - beta) * trend
        if m > 1:
            season[t % m] = gamma * (float(y[t]) / new_level if mult else float(y[t]) - new_level) + (1 - gamma) * s
        level = new_level
    if mult and m > 1:
        out = [(level + (i + 1) * trend) * season[(n + i) % m] for i in range(h)]
    else:
        out = [level + (i + 1) * trend + (season[(n + i) % m] if m > 1 else 0.0) for i in range(h)]
    return sse, out


GRID_A = (0.1, 0.3, 0.5, 0.8)
GRID_B = (0.01, 0.1, 0.3)
GRID_G = (0.05, 0.2, 0.5)


def ets(y: list[float], m: int, h: int) -> tuple[list[float], dict]:
    """Holt-Winters with the smoothing weights — and the seasonal form, additive or multiplicative when every value is
    positive — that give the smallest one-step error on the history (a small grid: explainable and repeatable).
    Returns the forecasts and what was chosen."""
    arr = np.asarray([float(v) for v in y], dtype=float)
    if len(arr) < 4:
        return seasonal_naive(y, m, h), {"alpha": None, "beta": None, "gamma": None, "season": None}
    best = None
    forms = (False, True) if m > 1 and float(arr.min()) > 0 else (False,)
    for mult in forms:
        for a in GRID_A:
            for b in GRID_B:
                for g in (GRID_G if m > 1 else (0.0,)):
                    sse, out = _hw(arr, m, a, b, g, h, mult)
                    if math.isfinite(sse) and (best is None or sse < best[0] - 1e-9):
                        best = (sse, out, {"alpha": a, "beta": b, "gamma": g if m > 1 else None, "season": ("multiplicative" if mult else "additive") if m > 1 else None})
    if best is None:
        return seasonal_naive(y, m, h), {"alpha": None, "beta": None, "gamma": None, "season": None}
    return [float(v) for v in best[1]], best[2]


def forecast(method: str, y: list[float], m: int, h: int) -> tuple[list[float], dict]:
    if method == "seasonal_naive":
        return seasonal_naive(y, m, h), {}
    if method == "linear_seasonal":
        return linear_seasonal(y, m, h), {}
    if method == "ets":
        return ets(y, m, h)
    raise ValueError(f"unknown method {method!r}")


# ------------------------------------------------------------------ accuracy against the holdout

def accuracy(actual: list[float], fc: list[float]) -> dict:
    """MAPE (mean absolute percentage error, periods with a zero actual left out), WAPE (absolute errors over the
    total of the actuals — stable when some periods are small), bias (forecast minus actual, as a share), RMSE."""
    a = np.asarray([float(v) for v in actual], dtype=float)
    f = np.asarray([float(v) for v in fc[:len(a)]], dtype=float)
    if not len(a):
        return {"mape": None, "wape": None, "bias": None, "rmse": None, "n": 0}
    err = f - a
    nz = a != 0
    mape = float(np.mean(np.abs(err[nz]) / np.abs(a[nz])) * 100) if nz.any() else None
    tot = float(np.sum(np.abs(a)))
    wape = float(np.sum(np.abs(err)) / tot * 100) if tot else None
    bias = float(np.sum(err) / tot * 100) if tot else None
    rmse = float(math.sqrt(float(np.mean(err * err))))
    return {"mape": _r(mape), "wape": _r(wape), "bias": _r(bias), "rmse": _r(rmse, 4), "n": int(len(a))}


def _r(v, d: int = 2):
    return None if v is None or not math.isfinite(v) else round(float(v), d)


def holdout_for(n: int, m: int, horizon: int) -> int:
    """How many of the latest periods the back-test hides: one cycle (or the horizon) — never more than a quarter of the
    history, at least one period."""
    want = max(horizon, m if m > 1 else 0) or horizon
    return max(1, min(want, n // 4))


def backtest(periods: list[str], y: list[float], m: int, horizon: int, holdout: int | None = None, methods=SIMPLE_FIRST) -> dict:
    """Every method trained on the history before the holdout and scored on the holdout it never saw."""
    n = len(y)
    k = holdout or holdout_for(n, m, horizon)
    train, test = y[:n - k], y[n - k:]
    mt = m if len(train) >= 2 * m else 1
    out = {"holdout": k, "season": mt, "train_from": periods[0] if periods else None, "train_to": periods[n - k - 1] if n - k - 1 >= 0 else None,
           "test_from": periods[n - k] if k <= n else None, "test_to": periods[-1] if periods else None, "models": {}}
    for meth in methods:
        fc, params = forecast(meth, train, mt, k)
        out["models"][meth] = {"method": meth, "label": METHODS[meth], "params": params, "forecast": [round(v, 4) for v in fc], **accuracy(test, fc)}
    out["actual"] = [float(v) for v in test]
    out["periods"] = periods[n - k:]
    out["recommended"] = recommend(out["models"])
    return out


def recommend(models: dict, tolerance_pp: float = 1.0) -> str:
    """The most accurate method on the holdout (lowest WAPE) — unless a simpler one is within `tolerance_pp`
    percentage points of it: the simplest method that is accurate enough wins."""
    scored = [(mm["wape"], meth) for meth, mm in models.items() if mm.get("wape") is not None]
    if not scored:
        return "seasonal_naive"
    best = min(w for w, _ in scored)
    for meth in SIMPLE_FIRST:
        mm = models.get(meth)
        if mm and mm.get("wape") is not None and mm["wape"] <= best + tolerance_pp:
            return meth
    return min(scored)[1]


def interval(rmse: float | None, z: float = 1.2816) -> float:
    """Half-width of an 80 % range from the back-test's error (normal errors assumed, said in the output)."""
    return 0.0 if not rmse else float(z * rmse)


def strength(y: list[float], m: int) -> float | None:
    """How seasonal a series is, 0 (none) to 1 (the cycle explains everything): 1 - var(remainder) / var(detrended)."""
    if m <= 1 or len(y) < 2 * m:
        return None
    arr = np.asarray([float(v) for v in y], dtype=float)
    t = np.arange(len(arr), dtype=float)
    trend = np.polyval(np.polyfit(t, arr, 1), t)
    det = arr - trend
    means = np.array([np.mean(det[i::m]) for i in range(m)])
    rem = det - np.array([means[i % m] for i in range(len(arr))])
    v = float(np.var(det))
    scale = max(1.0, float(np.mean(arr)) ** 2)
    return None if v <= 1e-12 * scale else round(max(0.0, 1 - float(np.var(rem)) / v), 3)


def period_labels(last: str, grain: str, h: int) -> list[str]:
    """The next h period labels after `last` (ISO dates for day / week, YYYY-MM-01 for month, YYYY-MM-01 for quarter)."""
    import datetime as dt
    d = dt.date.fromisoformat(str(last)[:10])
    out = []
    for i in range(1, h + 1):
        if grain == "day":
            out.append((d + dt.timedelta(days=i)).isoformat())
        elif grain == "week":
            out.append((d + dt.timedelta(weeks=i)).isoformat())
        else:
            step = 3 if grain == "quarter" else 1
            mm = d.month - 1 + i * step
            out.append(dt.date(d.year + mm // 12, mm % 12 + 1, 1).isoformat())
    return out


def gaps(periods: list[str], grain: str) -> int:
    """Missing periods inside the history (a month with no rows at all)."""
    if len(periods) < 2:
        return 0
    want = period_labels(periods[0], grain, len(periods) * 2 + 60)
    seen = set(p[:10] for p in periods)
    last = periods[-1][:10]
    n = 0
    for p in want:
        if p > last:
            break
        if p not in seen:
            n += 1
    return n


def svg_chart(title: str, periods: list[str], actual: list[float], lines: dict[str, list[float]], split: int | None = None) -> str:
    """A small, self-contained line chart (an output file, not a screen): actuals and each method's back-test."""
    w, h, pad = 760, 300, 46
    allv = [v for v in actual] + [v for vs in lines.values() for v in vs if v is not None]
    lo, hi = (min(allv), max(allv)) if allv else (0.0, 1.0)
    hi = hi if hi > lo else lo + 1
    n = max(len(periods), 2)
    x = lambda i: pad + (w - 2 * pad) * i / (n - 1)  # noqa: E731
    yv = lambda v: h - pad - (h - 2 * pad) * (v - lo) / (hi - lo)  # noqa: E731
    dash = ["", "6 4", "2 3", "8 3 2 3"]
    shades = ["#1A1A1A", "#0B7393", "#8A5A00", "#6B3FA0"]

    def path(vals, off=0):
        pts = [f"{x(i + off):.1f},{yv(v):.1f}" for i, v in enumerate(vals) if v is not None]
        return "M" + " L".join(pts) if pts else ""
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{_esc(title)}">',
             f'<title>{_esc(title)}</title><rect width="{w}" height="{h}" fill="#FFFFFF"/>',
             f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#56626E"/>',
             f'<text x="{pad}" y="20" font-family="Arial" font-size="13" fill="#1A1A1A">{_esc(title)}</text>',
             f'<text x="{pad}" y="{h - 12}" font-family="Arial" font-size="11" fill="#56626E">{_esc(periods[0] if periods else "")}</text>',
             f'<text x="{w - pad}" y="{h - 12}" font-family="Arial" font-size="11" fill="#56626E" text-anchor="end">{_esc(periods[-1] if periods else "")}</text>']
    if split is not None and 0 < split < n:
        parts.append(f'<line x1="{x(split):.1f}" y1="{pad}" x2="{x(split):.1f}" y2="{h - pad}" stroke="#56626E" stroke-dasharray="3 3"/>'
                     f'<text x="{x(split) + 4:.1f}" y="{pad + 10}" font-family="Arial" font-size="11" fill="#56626E">holdout</text>')
    parts.append(f'<path d="{path(actual)}" fill="none" stroke="{shades[0]}" stroke-width="2"/>')
    ly = 36
    parts.append(f'<text x="{w - pad}" y="{ly}" font-family="Arial" font-size="11" text-anchor="end" fill="{shades[0]}">actual</text>')
    for i, (name, vals) in enumerate(lines.items(), 1):
        off = (split or 0)
        parts.append(f'<path d="{path(vals, off)}" fill="none" stroke="{shades[i % 4]}" stroke-width="1.6" stroke-dasharray="{dash[i % 4]}"/>')
        parts.append(f'<text x="{w - pad}" y="{ly + 14 * i}" font-family="Arial" font-size="11" text-anchor="end" fill="{shades[i % 4]}">{_esc(name)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
