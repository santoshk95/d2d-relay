"""Detectors of Anomaly & risk detection (registry id `anomaly`): rules and plain statistics, no model to trust blindly.

On a metric over time (a series: periods and values):
  zscore     a period more than k standard deviations from the mean of the history before it
  iqr        a period outside [Q1 - k·IQR, Q3 + k·IQR] of the history (robust to the outliers themselves)
  seasonal   a period far from what its trend and its season say: the residual of a linear trend with seasonal
             effects, scored robustly (median and MAD) — the right detector for anything with a weekly or yearly shape
  threshold  a business rule: the value above (or below) a number a person sets
On a table (rows):
  row_iqr    a row whose number is far outside the usual range — per group when a group column is named (a supplier's
             invoices against that supplier's own range)
  row_rule   a row matching a rule: a column compared with a number (amount < 0, discount > 40)

Every finding carries its reason in plain words and the numbers behind it; nothing is flagged without them."""
from __future__ import annotations

import math
import re
import statistics

from . import predict_stats as ps

KINDS = {"seasonal": "Seasonal residual", "zscore": "Z-score", "iqr": "Outside the usual range (IQR)", "threshold": "Business threshold",
         "row_iqr": "Unusual row (IQR, per group)", "row_rule": "Row rule"}
SERIES_KINDS = ("seasonal", "zscore", "iqr", "threshold")
ROW_KINDS = ("row_iqr", "row_rule")
DEFAULT_K = {"seasonal": 4.5, "zscore": 3.0, "iqr": 3.0, "row_iqr": 3.0}
PARAM_HELP = "k=3 (how far from usual: standard deviations, IQRs or MADs) · threshold and row_rule: > 50000, < 0, >= 40"
SEVERITIES = (("high", "High"), ("medium", "Medium"), ("low", "Low"))
CMP = re.compile(r"^\s*(>=|<=|>|<|=|!=)\s*(-?\d+(?:\.\d+)?)\s*$")
OPS = {">": lambda a, b: a > b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "=": lambda a, b: a == b, "!=": lambda a, b: a != b}


def parse(d: dict) -> tuple[dict, list[str]]:
    """A detector's parameters from its `params` text; the problems that stop it from running."""
    kind, txt = d.get("kind"), str(d.get("params") or "").strip()
    out, probs = {}, []
    if kind not in KINDS:
        return out, [f"unknown detector {kind!r}"]
    if kind in ("threshold", "row_rule"):
        m = CMP.match(txt)
        if not m:
            probs.append("write the rule as a comparison, e.g. > 50000 or < 0")
        else:
            out.update(op=m.group(1), value=float(m.group(2)))
    else:
        k = DEFAULT_K[kind]
        if txt:
            m = re.match(r"^\s*k\s*=\s*(\d+(?:\.\d+)?)\s*$", txt)
            if not m:
                probs.append("write the sensitivity as k=3")
            else:
                k = float(m.group(1))
                if not 1 <= k <= 10:
                    probs.append("k is between 1 and 10")
        out["k"] = k
    if kind in SERIES_KINDS and not d.get("date"):
        probs.append("a metric over time needs its date column")
    if kind in ROW_KINDS and not d.get("value"):
        probs.append("name the number column the rule checks")
    return out, probs


def _q(vals: list[float], p: float) -> float:
    s = sorted(vals)
    if not s:
        return 0.0
    i = (len(s) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _mad(vals: list[float]) -> tuple[float, float]:
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals]) * 1.4826
    return med, mad


def fmt(v) -> str:
    if v is None:
        return "—"
    f = float(v)
    return f"{f:,.0f}" if abs(f) >= 100 else f"{f:,.2f}"


def series_findings(kind: str, params: dict, periods: list[str], y: list[float], grain: str = "month", min_history: int = 6) -> tuple[list[dict], dict]:
    """(findings, the bounds used) for a metric over time. Each period is judged against the history before it (z-score)
    or against the whole series' robust spread (IQR, seasonal residual), never against itself alone."""
    out = []
    n = len(y)
    if kind == "threshold":
        op, lim = params["op"], params["value"]
        for p, v in zip(periods, y):
            if OPS[op](v, lim):
                out.append({"at": p, "value": v, "expected": f"not {op} {fmt(lim)}", "score": None, "low": lim, "high": lim, "reason": f"{fmt(v)} is {op} the threshold {fmt(lim)}"})
        return out, {"op": op, "value": lim}
    k = params["k"]
    if kind == "zscore":
        for i in range(min_history, n):
            hist = y[:i]
            mu, sd = statistics.fmean(hist), statistics.pstdev(hist)
            if sd <= 0:
                continue
            z = (y[i] - mu) / sd
            if abs(z) > k:
                out.append({"at": periods[i], "value": y[i], "expected": f"{fmt(mu - k * sd)} to {fmt(mu + k * sd)}", "score": round(z, 2), "low": mu - k * sd, "high": mu + k * sd,
                            "reason": f"{fmt(y[i])} is {abs(z):.1f} standard deviations {'above' if z > 0 else 'below'} the mean of the {i} periods before it ({fmt(mu)})"})
        mu, sd = (statistics.fmean(y), statistics.pstdev(y)) if y else (0.0, 0.0)
        return out, {"low": mu - k * sd, "high": mu + k * sd}
    if kind == "iqr":
        q1, q3 = _q(y, 0.25), _q(y, 0.75)
        lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        for p, v in zip(periods, y):
            if v < lo or v > hi:
                out.append({"at": p, "value": v, "expected": f"{fmt(lo)} to {fmt(hi)}", "score": 1.0 if v > hi else -1.0, "low": lo, "high": hi,
                            "reason": f"{fmt(v)} is outside the usual range {fmt(lo)} to {fmt(hi)} (quartiles {fmt(q1)} and {fmt(q3)}, k = {k:g})"})
        return out, {"low": lo, "high": hi}
    # seasonal: residuals of a linear trend with seasonal effects, robust z (median, MAD)
    m = ps.SEASON.get(grain, 1) if n >= 2 * ps.SEASON.get(grain, 1) else 1
    keep = [True] * n
    for _ in range(max(1, n // 10)):                     # robust, one point at a time (as a generalised ESD test): the most
        fitted = _fit(y, m, keep)                        # extreme point is left out of the fit and the fit is redone, so
        res = [a - f for a, f in zip(y, fitted)]         # one spike cannot pull its season with it and mask the others
        med, mad = _mad([r for r, k_ in zip(res, keep) if k_]) if res else (0.0, 0.0)
        kept = sum(keep)
        mad *= math.sqrt(kept / max(1, kept - (2 + max(0, m - 1))))      # the fit used up degrees of freedom
        if mad <= 0:
            return out, {"mad": 0.0}
        worst = max((i for i in range(n) if keep[i]), key=lambda i: abs((res[i] - med) / mad), default=None)
        if worst is None or abs((res[worst] - med) / mad) <= k:
            break
        keep[worst] = False
    for p, v, f, r in zip(periods, y, fitted, res):
        z = (r - med) / mad
        if abs(z) > k:
            out.append({"at": p, "value": v, "expected": fmt(f), "score": round(z, 2), "low": f + med - k * mad, "high": f + med + k * mad,
                        "reason": f"{fmt(v)} against {fmt(f)} expected from the trend and the {'season' if m > 1 else 'level'} — {abs(z):.1f} robust deviations {'above' if z > 0 else 'below'}"})
    return out, {"mad": mad, "season": m}


def _fit(y: list[float], m: int, keep: list[bool] | None = None) -> list[float]:
    """A linear trend with seasonal effects (the same model the forecasting module explains), fitted on the points
    kept and evaluated on all of them."""
    import numpy as np
    n = len(y)
    if n < 3:
        return list(y)
    t = np.arange(n, dtype=float)
    cols = [np.ones(n), t] + ([np.array([1.0 if int(x) % m == j else 0.0 for x in t]) for j in range(1, m)] if m > 1 else [])
    X = np.column_stack(cols)
    mask = np.asarray(keep if keep is not None else [True] * n, dtype=bool)
    if mask.sum() < X.shape[1] + 2:
        mask = np.ones(n, dtype=bool)
    beta, *_ = np.linalg.lstsq(X[mask], np.asarray(y, dtype=float)[mask], rcond=None)
    return [float(v) for v in X @ beta]


def row_findings(kind: str, params: dict, rows: list[dict], value: str, group: str | None = None, key: str | None = None, cap: int = 200) -> tuple[list[dict], dict]:
    """Findings on rows. row_iqr judges each row against its group's quartiles (at least 8 rows per group)."""
    def num(r):
        try:
            return None if r.get(value) in (None, "") else float(r.get(value))
        except (TypeError, ValueError):
            return None
    out, bounds = [], {}
    if kind == "row_rule":
        op, lim = params["op"], params["value"]
        for r in rows:
            v = num(r)
            if v is not None and OPS[op](v, lim):
                out.append({"at": str(r.get(key) if key else ""), "row": r, "value": v, "expected": f"not {op} {fmt(lim)}", "score": None,
                            "reason": f"{value} {fmt(v)} is {op} {fmt(lim)}" + (f" ({group} {r.get(group)})" if group else "")})
        return out[:cap], {"op": op, "value": lim}
    k = params["k"]
    groups: dict = {}
    for r in rows:
        v = num(r)
        if v is not None:
            groups.setdefault(str(r.get(group)) if group else "all", []).append((r, v))
    for g, items in groups.items():
        vals = [v for _, v in items]
        if len(vals) < 8:
            continue
        q1, q3 = _q(vals, 0.25), _q(vals, 0.75)
        lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        bounds[g] = {"low": lo, "high": hi}
        for r, v in items:
            if v < lo or v > hi:
                out.append({"at": str(r.get(key) if key else ""), "row": r, "value": v, "expected": f"{fmt(lo)} to {fmt(hi)}", "score": None,
                            "reason": f"{value} {fmt(v)} is outside {('the usual range for ' + group + ' ' + g) if group else 'the usual range'}: {fmt(lo)} to {fmt(hi)}"})
    return out[:cap], bounds


def noise(findings: int, points: int) -> float:
    return round(100.0 * findings / points, 1) if points else 0.0
