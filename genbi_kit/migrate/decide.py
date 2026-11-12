"""Decide what to keep: the user's rules with the system defaults beside them, a live preview, a reason per object,
decisions signed by name.

  Retire   not run for N days - never run and older than N days - personal folders (retire unless shared) -
           never when owned by ...
  Merge    at least N % the same (weights: dataset, attributes, metrics, filters) - keep the most used / most recent
  Review   failed in the last N days, or used but not convertible, or its package is missing

Similarity is computed once per estate (pairs within the same package / data module that share items) and cached;
the preview then only re-applies weights and thresholds, so it answers as the person types.
"""
from __future__ import annotations

import datetime as dt

from . import expr, model

DEFAULTS = {"retire_days": 365, "never_age": 180, "personal": "retire unless shared", "protect": "", "sim_pct": 90, "w_dataset": 40, "w_attr": 20,
            "w_metric": 30, "w_filter": 10, "keep": "most used", "review_days": 30}
LABELS = {"keep": "Keep", "merge": "Merge", "retire": "Retire", "review": "Needs a decision"}
MIN_PAIR = 0.45                               # pairs below this plain average similarity are not kept (sim_pct is never that low)


def clean_rules(given: dict | None) -> dict:
    r = dict(DEFAULTS)
    for k, v in (given or {}).items():
        if k not in DEFAULTS:
            continue
        if k in ("personal", "keep", "protect"):
            r[k] = str(v or "") if k == "protect" else (str(v) if str(v) in (("retire unless shared", "treat like team content") if k == "personal" else ("most used", "most recent")) else DEFAULTS[k])
        else:
            try:
                r[k] = max(0, int(v))
            except (TypeError, ValueError):
                r[k] = DEFAULTS[k]
    r["sim_pct"] = max(50, min(100, r["sim_pct"]))
    return r


def _age_days(report: dict, as_of: dt.date) -> int | None:
    c = report.get("created")
    if not c:
        return None
    try:
        return (as_of - dt.date.fromisoformat(str(c)[:10])).days
    except ValueError:
        return None


def decide_one(r: dict, rules: dict, prediction: dict | None, as_of: dt.date) -> tuple[str, str]:
    """The decision for one object from the retire and review rules (merge comes after, between kept objects)."""
    u = r.get("usage") or {}
    last = u.get("last_run_days")
    protect = {p.strip().lower() for p in (rules.get("protect") or "").split(",") if p.strip()}
    owner = (r.get("owner") or "").lower()
    protected = owner in protect or any(p and p in owner for p in protect)
    if not protected:
        if last is not None and last > rules["retire_days"]:
            return "retire", f"not run for {last} days (rule: {rules['retire_days']})"
        age = _age_days(r, as_of)
        if last is None and age is not None and age > rules["never_age"]:
            return "retire", f"never run, {age} days old (rule: {rules['never_age']})"
        if r.get("personal") and not r.get("shared") and rules["personal"] == "retire unless shared":
            return "retire", "personal folder, not shared"
    if r.get("missing_dataset"):
        return "review", f"its package \"{r['missing_dataset']}\" no longer exists"
    fd = u.get("failed_days")
    if fd is not None and fd <= rules["review_days"]:
        return "review", f"failed {fd} days ago (rule: {rules['review_days']})"
    if prediction and prediction.get("convert") == "no" and last is not None:
        return "review", f"used, but {prediction.get('reason')}"
    if protected and last is None:
        return "keep", f"never run, but owned by {r.get('owner')} (never retired)"
    return "keep", "used and convertible" if (prediction or {}).get("convert") != "no" else "kept; nothing converts it yet"


# ------------------------------------------------------------------ similarity

def signature(report: dict) -> dict:
    attrs, metrics, filters = set(), set(), set()
    agg_words = ("total(", "average(", "avg(", "count(", "sum(", "minimum(", "maximum(", "min(", "max(", "percentage(", "running-", "rank(", "moving-", "percentile(")
    for q in report.get("queries") or []:
        for it in q.get("items") or []:
            pat, refs = expr.normalise(it.get("expression") or "")
            key = pat
            for i, ref in enumerate(refs):
                key = key.replace("{" + str(i) + "}", ref.lower())
            arithmetic = any(op in pat for op in (" + ", " - ", " * ", " / "))
            if not it.get("aggregate") and not any(f in pat for f in agg_words) and not arithmetic:
                attrs.add(key)                  # a column or a row-level function of columns: what the report groups by
            else:
                metrics.add(key)
        for f in q.get("filters") or []:
            pat, refs = expr.normalise(f.get("expression") or "")
            key = pat
            for i, ref in enumerate(refs):
                key = key.replace("{" + str(i) + "}", ref.lower())
            filters.add(key)
    return {"dataset": report.get("dataset"), "attrs": frozenset(attrs), "metrics": frozenset(metrics), "filters": frozenset(filters)}


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity_pairs(estate: dict) -> list[list]:
    """[a_id, b_id, same_dataset, j_attr, j_metric, j_filter] for every pair worth looking at (same package or
    data module, sharing items, plain average similarity >= MIN_PAIR)."""
    sigs = {r["id"]: signature(r) for r in estate["reports"]}
    buckets: dict[str, list[str]] = {}
    for rid, s in sigs.items():
        if s["dataset"]:
            buckets.setdefault(s["dataset"], []).append(rid)
    out = []
    for ds, ids in buckets.items():
        index: dict[str, set[str]] = {}
        for rid in ids:
            for key in sigs[rid]["attrs"] | sigs[rid]["metrics"]:
                index.setdefault(key, set()).add(rid)
        seen: set[tuple] = set()
        for rid in ids:
            s = sigs[rid]
            cands: set[str] = set()
            for key in s["attrs"] | s["metrics"]:
                cands |= index.get(key, set())
            for other in cands:
                if other <= rid:
                    continue
                pair = (rid, other)
                if pair in seen:
                    continue
                seen.add(pair)
                o = sigs[other]
                ja, jm, jf = _jaccard(s["attrs"], o["attrs"]), _jaccard(s["metrics"], o["metrics"]), _jaccard(s["filters"], o["filters"])
                if (ja + jm + jf) / 3 >= MIN_PAIR:
                    out.append([rid, other, 1, round(ja, 4), round(jm, 4), round(jf, 4)])
    return out


def score(pair: list, rules: dict) -> float:
    w = [rules["w_dataset"], rules["w_attr"], rules["w_metric"], rules["w_filter"]]
    total = sum(w) or 1
    return 100.0 * (w[0] * pair[2] + w[1] * pair[3] + w[2] * pair[4] + w[3] * pair[5]) / total


# ------------------------------------------------------------------ the preview

def preview(estate: dict, rules: dict | None, pairs: list[list], predictions: dict | None = None, overrides: dict | None = None, as_of: dt.date | None = None) -> dict:
    """Every object's decision and reason under these rules, the tiles, "before N -> after M", merge groups.
    overrides: {id: {"decision": "keep" | "retire" | "review", "by": name, "at": ts, "note": ...}} - a person's call wins."""
    rules = clean_rules(rules)
    predictions = predictions or {}
    overrides = overrides or {}
    as_of = as_of or (dt.date.fromisoformat(estate["usage"]["as_of"]) if (estate.get("usage") or {}).get("as_of") else dt.date.today())
    decisions: dict[str, dict] = {}
    for r in estate["reports"]:
        d, why = decide_one(r, rules, predictions.get(r["id"]), as_of)
        decisions[r["id"]] = {"decision": d, "reason": why, "merged_into": None, "similarity": None}
    by_id = model.by_id(estate)
    # merge among the kept objects
    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    best: dict[tuple, float] = {}
    for p in pairs:
        if decisions[p[0]]["decision"] != "keep" or decisions[p[1]]["decision"] != "keep":
            continue
        s = score(p, rules)
        if s >= rules["sim_pct"]:
            a, b = find(p[0]), find(p[1])
            if a != b:
                parent[a] = b
            best[(p[0], p[1])] = s
    groups: dict[str, list[str]] = {}
    for rid in decisions:
        if decisions[rid]["decision"] == "keep" and (rid in parent or any(rid in k for k in best)):
            groups.setdefault(find(rid), []).append(rid)
    kept_groups = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        kept_groups += 1
        if rules["keep"] == "most used":
            members.sort(key=lambda i: (-(by_id[i]["usage"].get("runs_365") or 0), by_id[i]["usage"].get("last_run_days") if by_id[i]["usage"].get("last_run_days") is not None else 10 ** 6, i))
        else:
            members.sort(key=lambda i: (by_id[i]["usage"].get("last_run_days") if by_id[i]["usage"].get("last_run_days") is not None else 10 ** 6, -(by_id[i]["usage"].get("runs_365") or 0), i))
        keep = members[0]
        for other in members[1:]:
            sim = max((s for (a, b), s in best.items() if {a, b} == {keep, other}), default=None)
            if sim is None:
                sim = max((s for (a, b), s in best.items() if other in (a, b)), default=rules["sim_pct"])
            decisions[other].update(decision="merge", merged_into=keep, similarity=round(sim),
                                    reason=f"{round(sim)} % the same as \"{by_id[keep]['name']}\" - keeping the {rules['keep']}")
    for rid, o in overrides.items():
        if rid in decisions and o.get("decision") in ("keep", "retire", "review"):
            decisions[rid].update(decision=o["decision"], merged_into=None, reason=f"your decision ({o.get('by') or 'unsigned'}): {o.get('note') or LABELS[o['decision']].lower()}")
    counts = {k: 0 for k in LABELS}
    for d in decisions.values():
        counts[d["decision"]] += 1
    after = counts["keep"] + counts["review"]
    return {"rules": rules, "defaults": DEFAULTS, "counts": counts, "kept_groups": kept_groups, "before": len(estate["reports"]), "after": after,
            "reduction_pct": round(100 * (len(estate["reports"]) - after) / len(estate["reports"]), 1) if estate["reports"] else 0, "decisions": decisions,
            "changed": {k: rules[k] for k in rules if rules[k] != DEFAULTS[k]}}


def top_rows(estate: dict, pv: dict, decision: str, n: int = 8) -> list[dict]:
    rows = [{"id": r["id"], "name": r["name"], "type": r["type"], "folder": r["folder"], "owner": r.get("owner"), "runs": r["usage"].get("runs_365", 0),
             "last_run_days": r["usage"].get("last_run_days"), "reason": pv["decisions"][r["id"]]["reason"], "merged_into": pv["decisions"][r["id"]].get("merged_into")}
            for r in estate["reports"] if pv["decisions"][r["id"]]["decision"] == decision]
    rows.sort(key=lambda x: -x["runs"])
    return rows[:n]
