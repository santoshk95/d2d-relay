"""The review's rules: one KPI, one meaning, one value.

review(models, dictionary, extra=None) reads every measure of every model (dax.describe), matches measures to the
KPI dictionary by name (kpis.Matcher; extra adds matches found by the meaning check), and applies the rules:

  KPI meaning (the point of the review)
    conflict               one KPI calculated more than one way (in one model, or across models)
    differs                a KPI's measure does not compute what the dictionary's DAX computes
    aggregation            the dictionary says sum / average / count / distinct count / ratio / last, the measure does otherwise
    average_of_ratios      an average of row-level ratios where the KPI is a ratio of totals
    variant_drift          Revenue YTD, Revenue LY ... not built on Revenue's own calculation
    time_basis             a year to date on another year end than the KPI's (or two year ends in one model)
    unit                   a percentage KPI not shown as a percentage (or the other way), one KPI shown in different formats
    title                  a visual titled with one KPI that shows another KPI's measure
    implicit_visual        visuals that add up a column themselves where a KPI's measure exists for it
  DAX that gives a wrong or unstable number
    broken                 cannot be read, refers to something not in the model, or refers to itself
    frozen_variable        CALCULATE around a variable: its filters do nothing
    iterator_aggregate     SUMX(Customer, SUM(...)) without CALCULATE: the same total on every row
    filter_override        ALL / REMOVEFILTERS on a KPI: the number ignores the report's filters
    duplicate              two names for one number
    base_not_reused        a variant that repeats its KPI's formula instead of using its measure
    implicit_sum           ids, years, rates or prices that visuals add up by default
    constant               numbers written into a KPI's formula (rates, targets)
    unsafe_division        "/" where DIVIDE() is safe
    bidirectional          relationships that filter both ways
  For the dictionary
    missing                dictionary KPIs no model has; undocumented: measures not in the dictionary; description

Every finding: {id, rule, severity (high | medium | low | info), title, detail, kpi, measures: [{model, model_name,
table, name}], dax: [text], fix: text | None, source: rules | ai}. Text is plain keyboard characters.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import dax as D
from .kpis import Matcher, norm

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
RATIO_COL = re.compile(r"(%|pct|percent|rate|ratio|margin|share|yield)", re.I)
INTENT_ALL = re.compile(r"(share|% of|pct of|percent of|of total|contribution|rank|grand total|\ball\b|overall|benchmark|"
                        r"company total|mix|portion|weight|index|baseline|denominator|history|\bhist\b|trend|all time|"
                        r"lifetime|since|ever|max date|last date|latest)", re.I)
TARGET_WORDS = {"budget", "target", "plan", "forecast", "fcst", "goal", "bp", "objective", "quota"}
COMPARE_WORDS = {"vs", "variance", "var", "gap", "achievement", "attainment", "diff", "difference", "delta", "change"}
IDLIKE = re.compile(r"(^|[\s_-])(id|key|code|no|nr|number|num|sk|guid|zip|postcode|pin|phone)$|[a-z]Id$|_id$|ID$")
TIME_COL = re.compile(r"^(year|month|quarter|week|day|fiscal ?year|fy|month ?(number|no|num)|year ?(number|no)|period|weekday|"
                      r"hour|day of week|week ?(number|no)|calendar ?year)$", re.I)
RATE_COL = re.compile(r"(rate|ratio|pct|percent|%|price|tariff|cost per|per unit|unit cost|\bage\b|score|"
                      r"rating|latitude|longitude|\blat\b|\blon\b|probability)", re.I)
NUMERIC = {"int64", "double", "decimal", "currency", "number"}
YTD_FNS = {"DATESYTD", "PREVIOUSYEAR", "NEXTYEAR", "STARTOFYEAR", "ENDOFYEAR", "OPENINGBALANCEYEAR", "CLOSINGBALANCEYEAR"}
LAST_FNS = {"LASTDATE", "LASTNONBLANK", "LASTNONBLANKVALUE", "CLOSINGBALANCEMONTH", "CLOSINGBALANCEQUARTER",
            "CLOSINGBALANCEYEAR", "ENDOFMONTH", "ENDOFQUARTER", "ENDOFYEAR"}
FN_WORDS = {"SUM": "adds up", "AVERAGE": "averages", "AVERAGEA": "averages", "MIN": "takes the lowest", "MAX": "takes the highest",
            "COUNT": "counts the values of", "COUNTA": "counts the values of", "COUNTBLANK": "counts the blanks of",
            "COUNTROWS": "counts the rows of", "DISTINCTCOUNT": "counts the different values of",
            "DISTINCTCOUNTNOBLANK": "counts the different values of", "APPROXIMATEDISTINCTCOUNT": "estimates the different values of",
            "MEDIAN": "takes the median of", "SUMX": "adds up, row by row over", "AVERAGEX": "averages, row by row over",
            "COUNTX": "counts, row by row over", "MINX": "takes the lowest, row by row over", "MAXX": "takes the highest, row by row over",
            "PRODUCT": "multiplies", "PRODUCTX": "multiplies, row by row over", "MEDIANX": "takes the median, row by row over"}
MAX_LIST = 25


def _label(it: dict, multi: bool) -> str:
    return f"[{it['m']['name']}]" + (f" ({it['model_name']})" if multi else "")


def _agg_words(a: dict) -> str:
    return f"{FN_WORDS.get(a['fn'], a['fn'].lower() + ' of')} {a['of']}"


def _shape_words(sig: dict) -> str:
    s = sig.get("shape") or "other"
    if s == "ratio":
        r = sig.get("ratio") or {}
        num, den = (r.get("numerator") or {}).get("dax"), (r.get("denominator") or {}).get("dax")
        cut = lambda t: t if len(t) <= 70 else t[:67] + "..."              # noqa: E731
        return "a ratio" + (f" ({cut(num)} divided by {cut(den)})" if num and den else "")
    if s.startswith("aggregate:"):
        return {"SUM": "a total", "AVERAGE": "an average", "COUNTROWS": "a count of rows", "DISTINCTCOUNT": "a count of different values",
                "COUNT": "a count", "MIN": "a lowest value", "MAX": "a highest value"}.get(s.split(":")[1], "an aggregate")
    if s.startswith("iterate:"):
        fn = s.split(":")[1]
        return {"SUMX": "a total worked out row by row", "AVERAGEX": "an average of row-level values"}.get(fn, f"an iterator ({fn})")
    return {"difference": "a difference", "sum": "a sum of several parts", "product": "a product", "conditional": "conditional (IF or SWITCH)",
            "constant": "a fixed number", "time": "a date calculation", "negative": "a negative of another value"}.get(s, "another kind of calculation")


def _filter_words(f: dict) -> str:
    k = f.get("kind")
    if k == "predicate":
        return f"keeps only rows where {f['dax']}"
    if k == "remove":
        return f"ignores the report's filters ({f['dax']})"
    if k == "relationship":
        return f"uses another relationship ({f['dax']})"
    if k == "time":
        return f"moves the dates ({f['dax']})"
    return f"filters with {f['dax']}"


def explain(a: dict, b: dict, la: str, lb: str) -> list[str]:
    """How two formulas differ, in words (a and b are signatures)."""
    out = []
    A = {(x["fn"], x["loose"]): x for x in a.get("aggs") or []}
    B = {(x["fn"], x["loose"]): x for x in b.get("aggs") or []}
    only_a = [A[k] for k in A if k not in B][:3]
    only_b = [B[k] for k in B if k not in A][:3]
    if only_a and only_b:
        out.append(f"{la} {', '.join(_agg_words(x) for x in only_a)}, where {lb} {', '.join(_agg_words(x) for x in only_b)}.")
    elif only_a:
        out.append(f"{la} also {', '.join(_agg_words(x) for x in only_a)}; {lb} does not.")
    elif only_b:
        out.append(f"{lb} also {', '.join(_agg_words(x) for x in only_b)}; {la} does not.")
    if a.get("shape") != b.get("shape"):
        out.append(f"{la} is {_shape_words(a)}, {lb} is {_shape_words(b)}.")
    fa = {f["key"]: f for f in a.get("filters") or [] if f.get("kind") != "time"}
    fb = {f["key"]: f for f in b.get("filters") or [] if f.get("kind") != "time"}
    for k in list(fa)[:6]:
        if k not in fb:
            out.append(f"{la} {_filter_words(fa[k])}; {lb} does not.")
    for k in list(fb)[:6]:
        if k not in fa:
            out.append(f"{lb} {_filter_words(fb[k])}; {la} does not.")
    ta = {(t["fn"], t.get("year_end"), t.get("shift")) for t in a.get("time") or []}
    tb = {(t["fn"], t.get("year_end"), t.get("shift")) for t in b.get("time") or []}
    if ta != tb:
        out.append(f"Their dates differ: {la} {_time_words(a)}, {lb} {_time_words(b)}.")
    ca, cb = set(a.get("constants") or []), set(b.get("constants") or [])
    if ca != cb:
        out.append(f"Fixed numbers in the formulas differ: {la} has {', '.join(sorted(ca)) or 'none'}, {lb} has {', '.join(sorted(cb)) or 'none'}.")
    if not out:
        out.append("The formulas differ in their details: compare the DAX below.")
    return [x[:1].upper() + x[1:] for x in out]


def _time_words(sig: dict) -> str:
    ts = sig.get("time") or []
    if not ts:
        return "uses the dates as they are"
    parts = []
    for t in ts[:3]:
        fn = t["fn"]
        w = {"DATESYTD": "year to date", "DATESQTD": "quarter to date", "DATESMTD": "month to date",
             "SAMEPERIODLASTYEAR": "the same period last year", "PREVIOUSYEAR": "the previous year",
             "PREVIOUSMONTH": "the previous month", "PREVIOUSQUARTER": "the previous quarter"}.get(fn, fn)
        if t.get("year_end"):
            w += " (year ending " + ("31 December" if t["year_end"] == "12-31" else t["year_end"]) + ")"
        if t.get("shift"):
            w += f" (shifted {t['shift']})"
        parts.append(w)
    return "uses " + ", ".join(parts)


def _fmt_class(fmt: str | None) -> str:
    f = str(fmt or "")
    if "%" in f:
        return "percent"
    if re.search(r"[$€£¥₹]|\\\$|\[\$", f):
        return "currency"
    return "number" if f.strip() else "general"


# ---------------------------------------------------------------- the review

class _Review:
    def __init__(self, models: list[dict], dictionary: list[dict], extra: dict | None = None):
        self.models = models
        self.dict = dictionary or []
        self.extra = extra or {}                     # (model index, measure name lower) -> KPI index (the meaning check's matches)
        self.matcher = Matcher(self.dict) if self.dict else None
        self.multi = len(models) > 1
        self.items: list[dict] = []
        self.findings: list[dict] = []
        self.dict_desc: dict[int, dict] = {}
        self.groups: dict[str, list] = defaultdict(list)
        self.variants: dict[str, list] = defaultdict(list)
        self.group_name: dict[str, str] = {}

    # ---- reading and matching

    def read(self) -> None:
        for mi, m in enumerate(self.models):
            measures = {x["name"]: x.get("expression") or "" for x in m.get("measures") or []}
            cols = [(t["name"], c["name"]) for t in m.get("tables") or [] for c in t.get("columns") or []]
            res = D.Resolver(measures, cols, [t["name"] for t in m.get("tables") or []])
            usage = ((m.get("usage") or {}).get("measures")) or {}
            for x in m.get("measures") or []:
                d = D.describe(x["name"], res)
                self.items.append({"mi": mi, "model_name": m.get("name") or f"Model {mi + 1}", "m": x, "d": d,
                                   "uses": usage.get(x["name"]) or [], "id": f"m{len(self.items) + 1}"})
        self.dict_dax: dict[str, str] = {}
        if self.dict:
            for e in self.dict:
                if e.get("dax"):
                    self.dict_dax[e["name"]] = e["dax"]
                    for s in e.get("synonyms") or []:
                        self.dict_dax.setdefault(s, e["dax"])
            res = D.Resolver(self.dict_dax)
            for i, e in enumerate(self.dict):
                if e.get("dax"):
                    self.dict_desc[i] = D.describe(e["name"], res)      # the dictionary on its own: only to see it reads
        self._hybrid: dict[int, D.Resolver] = {}
        self._ref: dict[tuple[int, int], dict | None] = {}

    def ref_desc(self, k: int | None, mi: int) -> dict | None:
        """The dictionary's DAX for KPI k, read in model mi: its [KPI] references are the dictionary's own definitions,
        any other [name] the model's measure or column of that name (a KPI defined as DIVIDE ( [Gross Profit],
        [Revenue] ) uses the model's Gross Profit), so a measure that computes the same thing compares equal."""
        if k is None or not self.dict[k].get("dax"):
            return None
        key = (k, mi)
        if key not in self._ref:
            if mi not in self._hybrid:
                m = self.models[mi]
                measures = {x["name"]: x.get("expression") or "" for x in m.get("measures") or []}
                defined = {n.lower() for n in self.dict_dax}
                for name in list(measures):                   # the dictionary's definitions win over the model's same names
                    if name.lower() in defined:
                        del measures[name]
                measures.update(self.dict_dax)
                cols = [(t["name"], c["name"]) for t in m.get("tables") or [] for c in t.get("columns") or []]
                self._hybrid[mi] = D.Resolver(measures, cols, [t["name"] for t in m.get("tables") or []])
            self._ref[key] = D.describe(self.dict[k]["name"], self._hybrid[mi])
        out = self._ref[key]
        return out if out and "fp" in out else None

    def match(self) -> None:
        unmatched = []
        for it in self.items:
            key = (it["mi"], it["m"]["name"].lower())
            i, how, var = self.matcher.match(it["m"]["name"]) if self.matcher else (None, None, None)
            if key in self.extra and (i is None or how == "similar"):
                i, how, var = self.extra[key], "ai", None
            it.update(kpi=i, how=how, variant=var)
            if i is None:
                unmatched.append(it)
            elif how == "variant":
                self.variants[f"k:{i}"].append(it)
            else:
                self.groups[f"k:{i}"].append(it)
        for i, e in enumerate(self.dict):
            self.group_name[f"k:{i}"] = e["name"]
        # measures that are in no dictionary entry: grouped by their names, so "Revenue" in two models (or "Revenue"
        # and "Total Revenue" in one) are still compared, and "Revenue YTD" is still Revenue's variant
        names: dict[str, str] = {}
        for it in unmatched:
            names.setdefault(norm(it["m"]["name"]), it["m"]["name"])
        inferred = Matcher([{"name": v} for v in names.values()])
        keys = list(names)
        for it in unmatched:
            i, how, var = inferred.match(it["m"]["name"], variants_only=True)
            if how == "variant":
                g = "n:" + keys[i]
                it.update(variant=var, how="variant")
                self.variants[g].append(it)
                self.group_name.setdefault(g, names[keys[i]])
            else:
                g = "n:" + norm(it["m"]["name"])
                self.groups[g].append(it)
                self.group_name.setdefault(g, names.get(norm(it["m"]["name"]), it["m"]["name"]))
            it["group"] = g
        for g, its in self.groups.items():
            for it in its:
                it["group"] = g
        for g, its in self.variants.items():
            for it in its:
                it["variant_of"] = g

    # ---- helpers

    def add(self, rule: str, severity: str, title: str, detail: str | list[str], items: list[dict] = (), kpi: str | None = None,
            fix: str | None = None, dax: list[str] | None = None, fix_dax: str | None = None) -> dict:
        f = {"id": f"f{len(self.findings) + 1}", "rule": rule, "severity": severity, "title": title,
             "detail": " ".join(detail) if isinstance(detail, list) else detail, "kpi": kpi,
             "measures": [{"model": it["mi"], "model_name": it["model_name"], "table": it["m"].get("table"), "name": it["m"]["name"]}
                          for it in list(items)[:MAX_LIST]],
             "dax": dax if dax is not None else [f"{it['m']['name']} = {(it['m'].get('expression') or '').strip()}"[:3000]
                                                 for it in list(items)[:4]],
             "fix": fix, "fix_dax": fix_dax, "source": "rules"}
        self.findings.append(f)
        return f

    @staticmethod
    def ok(it: dict) -> bool:
        return "fp" in it["d"]

    def versions(self, its: list[dict]) -> list[list[dict]]:
        """Implementations that compute the same thing, together: in one model by the strict fingerprint, across
        models by the loose one (table names may differ between models)."""
        its = [it for it in its if self.ok(it)]
        parent = list(range(len(its)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a in range(len(its)):
            for b in range(a + 1, len(its)):
                x, y = its[a], its[b]
                same = x["d"]["fp"] == y["d"]["fp"] if x["mi"] == y["mi"] else x["d"]["fp_loose"] == y["d"]["fp_loose"]
                if same:
                    parent[find(a)] = find(b)
        out: dict[int, list] = defaultdict(list)
        for i, it in enumerate(its):
            out[find(i)].append(it)
        return sorted(out.values(), key=lambda v: (-len(v), min(0 if x["how"] == "name" else 1 for x in v)))

    def kpi_entry(self, g: str) -> dict | None:
        return self.dict[int(g[2:])] if g.startswith("k:") else None

    # ---- the rules

    def rules(self) -> None:
        self.kpi_rows = []
        for g in list(self.group_name):
            its = self.groups.get(g, [])
            entry = self.kpi_entry(g)
            if not entry and len(its) < 2:
                continue
            self.kpi_rows.append(self.check_kpi(g, its, entry))
        self.check_variants()
        self.check_measures()
        self.check_models()
        self.check_dictionary()

    def check_kpi(self, g: str, its: list[dict], entry: dict | None) -> dict:
        name = entry["name"] if entry else self.group_name[g]
        row = {"group": g, "name": name, "defined": entry is not None, "implementations": [], "versions": 0,
               "status": "missing", "findings": [],
               "variants": [{"id": v["id"], "measure": v["m"]["name"], "model_name": v["model_name"], "variant": v.get("variant")}
                            for v in self.variants.get(g, [])][:20]}
        before = len(self.findings)
        vers = self.versions(its)
        k = int(g[2:]) if entry else None
        defined = bool(entry and entry.get("dax"))

        def as_defined(x) -> bool:                    # computes what the dictionary defines, read in its own model
            r = self.ref_desc(k, x["mi"])
            return bool(r) and x["d"]["fp_loose"] == r["fp_loose"]
        row["versions"] = len(vers)
        for vi, v in enumerate(vers):
            for it in v:
                row["implementations"].append({"id": it["id"], "model": it["mi"], "model_name": it["model_name"],
                                               "table": it["m"].get("table"), "measure": it["m"]["name"], "how": it["how"],
                                               "version": vi + 1, "format": it["m"].get("format"), "shows": len(it["uses"]),
                                               "dax": (it["m"].get("expression") or "")[:4000]})
        for it in its:
            if not self.ok(it):
                row["implementations"].append({"id": it["id"], "model": it["mi"], "model_name": it["model_name"],
                                               "table": it["m"].get("table"), "measure": it["m"]["name"], "how": it["how"],
                                               "version": None, "format": it["m"].get("format"), "shows": len(it["uses"]),
                                               "dax": (it["m"].get("expression") or "")[:4000], "error": it["d"].get("error")})
        if not its:
            if row["variants"]:
                row["status"] = "variants_only"
            return row
        # the version to compare the others with: the dictionary's own, else the most common (an exact name first)
        ref = next((v for v in vers if any(as_defined(x) for x in v)), None) if defined else None
        ref_is_dict = ref is not None
        ref = ref or (vers[0] if vers else None)
        if len(vers) > 1 and ref is not None:
            members = lambda v: ", ".join(_label(x, self.multi) for x in v[:4]) + (" and more" if len(v) > 4 else "")   # noqa: E731
            ri = vers.index(ref) + 1
            lines = [" ".join(f"Version {i + 1}: {members(v)}." for i, v in enumerate(vers))]
            for i, v in enumerate(vers):
                if v is not ref:
                    lines += explain(v[0]["d"]["sig"], ref[0]["d"]["sig"], f"version {i + 1}", f"version {ri}"
                                     + (" (the dictionary's)" if ref_is_dict else ""))
            ref_names = ", ".join(_label(x, self.multi) for x in ref[:2])
            fix = (f"Agree one calculation for {name}" + (" (your dictionary's)" if defined else f", for example {ref_names}")
                   + ", keep it in one measure and make every other measure for this KPI refer to it"
                   + (f" (for example [{vers[1][0]['m']['name']}] = [{ref[0]['m']['name']}])" if vers[1][0]["mi"] == ref[0]["mi"] else "")
                   + ", so every report shows the same number.")
            sev = "high"
            if all(self._only_hygiene(v[0]["d"]["sig"], ref[0]["d"]["sig"]) for v in vers if v is not ref):
                sev = "medium"
            self.add("conflict", sev, f"{name} is calculated {len(vers)} different ways",
                     [f"One KPI should have one meaning and one value, but these measures for {name} compute different numbers."] + lines,
                     [x for v in vers for x in v], kpi=name, fix=fix,
                     dax=[f"{v[0]['m']['name']} = {(v[0]['m'].get('expression') or '').strip()}"[:3000] for v in vers[:4]])
        if entry:
            self.check_against_entry(k, its, entry)
        self.check_formats(name, its)
        row["findings"] = [f["id"] for f in self.findings[before:]]
        sevs = {f["severity"] for f in self.findings[before:]}
        rules = {f["rule"] for f in self.findings[before:]}
        row["status"] = ("conflict" if len(vers) > 1 else "differs" if (rules & {"differs", "aggregation", "average_of_ratios"} and "high" in sevs)
                         else "consistent" if vers else "unreadable")
        return row

    @staticmethod
    def _only_hygiene(a: dict, b: dict) -> bool:
        """Two formulas whose difference is not the number itself (a "/" for DIVIDE ...): same aggregations, filters,
        dates, shape."""
        keys = lambda s: ({(x["fn"], x["loose"]) for x in s.get("aggs") or []}, {f["key"] for f in s.get("filters") or []},  # noqa: E731
                          {(t["fn"], t.get("year_end")) for t in s.get("time") or []}, s.get("shape"), tuple(s.get("constants") or []))
        return keys(a) == keys(b)

    def check_against_entry(self, k: int, its: list[dict], e: dict) -> None:
        name = e["name"]
        alone = self.dict_desc.get(k)
        if e.get("dax") and alone and "error" in alone:
            self.add("dictionary", "info", f"The dictionary's DAX for {name} cannot be read",
                     f"{alone['error']}. The review could not compare the models with it.", kpi=name, dax=[e["dax"][:2000]])
        for it in its:
            if not self.ok(it):
                continue
            sig, label = it["d"]["sig"], _label(it, self.multi)
            ref_desc = self.ref_desc(k, it["mi"])
            if ref_desc and it["d"]["fp_loose"] != ref_desc["fp_loose"]:
                lines = explain(sig, ref_desc["sig"], label, "the dictionary")
                wrong = self.wrong_dependencies(it)
                if wrong:
                    lines.append(f"It uses {', '.join(wrong[:3])}, which {'is' if len(wrong) == 1 else 'are'} not calculated as the dictionary "
                                 f"says either: fixing {'that' if len(wrong) == 1 else 'those'} may fix this one.")
                adapted, unmapped = self.adapt(e["dax"], it)
                fix, fix_dax = "Use the dictionary's definition, written for this model.", None
                if adapted and not unmapped:
                    fix_dax = f"{it['m']['name']} = {adapted}"
                elif adapted:
                    fix = (f"Use the dictionary's definition. {', '.join(unmapped[:3])} {'is' if len(unmapped) == 1 else 'are'} not in this "
                           f"model under that name: put this model's column{'' if len(unmapped) == 1 else 's'} in {'its' if len(unmapped) == 1 else 'their'} place.")
                    fix_dax = f"{it['m']['name']} = {e['dax']}"
                self.add("differs", "high", f"{label} does not compute {name} as your dictionary defines it", lines, [it], kpi=name, fix=fix,
                         fix_dax=fix_dax,
                         dax=[f"{it['m']['name']} = {(it['m'].get('expression') or '').strip()}"[:3000], f"Dictionary: {e['dax']}"[:3000]])
            agg = e.get("aggregation")
            if agg and agg != "custom":
                why = self.aggregation_problem(agg, sig)
                if why:
                    self.add("aggregation", "high", f"{label} is not {_agg_name(agg)} as {name} should be", why, [it], kpi=name)
            if e.get("year_end"):
                yes = {t.get("year_end") for t in sig.get("time") or [] if t["fn"] in YTD_FNS}
                bad = sorted(y for y in yes if y and y != e["year_end"])
                if bad:
                    self.add("time_basis", "medium", f"{label} uses another year end than {name}'s",
                             f"{label} works out the year to date with a year ending {', '.join(bad)}; your dictionary says {name}'s year ends "
                             f"{e['year_end']} ({e.get('time') or 'fiscal year'}).", [it], kpi=name,
                             fix=f'Give DATESYTD / TOTALYTD the year end "{_ye_text(e["year_end"])}".')
            unit = e.get("unit")
            fc = _fmt_class(it["m"].get("format"))
            if unit == "percent" and fc != "percent":
                self.add("unit", "medium", f"{label} is a percentage but is not shown as one",
                         f"{name} is a percentage, but {label} is formatted \"{it['m'].get('format') or 'General'}\": 0.25 shows as 0.25, not 25%.",
                         [it], kpi=name, fix='Set its format string to a percentage, for example 0.0%.')
            elif unit in ("currency", "count", "number", "duration") and fc == "percent":
                self.add("unit", "medium", f"{label} is shown as a percentage, but {name} is not one",
                         f"{name} is a {unit} in your dictionary, but {label} is formatted as a percentage.", [it], kpi=name)

    def wrong_dependencies(self, it: dict) -> list[str]:
        """The KPI measures this measure uses (in its model) that do not compute their KPI as the dictionary defines it."""
        uses = {m.lower() for m in it["d"]["sig"].get("measures") or []}
        out = []
        for other in self.items:
            if other["mi"] != it["mi"] or other is it or other["m"]["name"].lower() not in uses or not self.ok(other):
                continue
            k = other.get("kpi")
            ref = self.ref_desc(k, other["mi"]) if k is not None and other.get("how") not in ("variant",) else None
            if ref and other["d"]["fp_loose"] != ref["fp_loose"]:
                out.append(f"[{other['m']['name']}]")
        return out

    def aggregation_problem(self, agg: str, sig: dict) -> str | None:
        shape = sig.get("shape") or ""
        fn = shape.split(":", 1)[1] if ":" in shape else ""
        if agg == "sum" and ((shape.startswith("aggregate:") and fn != "SUM") or (shape.startswith("iterate:") and fn != "SUMX")):
            return f"It is {_shape_words(sig)}, where the dictionary says the KPI is a sum."
        if agg == "average" and shape in ("aggregate:SUM", "iterate:SUMX"):
            return "It adds the values up, where the dictionary says the KPI is an average."
        if agg == "count" and shape in ("aggregate:DISTINCTCOUNT", "aggregate:DISTINCTCOUNTNOBLANK"):
            return "It counts the different values, where the dictionary says the KPI counts every row (or value)."
        if agg == "distinct_count" and shape in ("aggregate:COUNT", "aggregate:COUNTROWS", "aggregate:COUNTA"):
            return "It counts every row (or value), so a customer or product appears as often as it has rows; the dictionary says the KPI counts the different values."
        if agg == "ratio" and shape.startswith("aggregate:") and fn not in ("AVERAGE",):
            return f"It is {_shape_words(sig)}, not a ratio of two totals as the dictionary says."
        if agg == "last" and shape in ("aggregate:SUM", "iterate:SUMX") and not any(t["fn"] in LAST_FNS for t in sig.get("time") or []) \
                and not any(a["fn"] in ("LASTNONBLANK", "LASTNONBLANKVALUE") for a in sig.get("aggs") or []):
            return "It adds up every date in the period; a balance (a closing or last value) takes the last date only (LASTDATE, LASTNONBLANK or CLOSINGBALANCEMONTH)."
        return None

    def check_formats(self, name: str, its: list[dict]) -> None:
        classes = defaultdict(list)
        for it in its:
            classes[_fmt_class(it["m"].get("format"))].append(it)
        shown = {k: v for k, v in classes.items() if k != "general"}
        if len(shown) > 1:
            parts = [f"{', '.join(_label(x, self.multi) for x in v[:3])} as {k}" for k, v in shown.items()]
            self.add("unit", "medium", f"{name} is shown in different formats", f"The same KPI is formatted differently: {'; '.join(parts)}. "
                     "One KPI should look the same in every report (0.25 in one and 25% in another reads as two numbers).", its, kpi=name)

    def adapt(self, dax_text: str, it: dict) -> tuple[str | None, list[str]]:
        """The dictionary's DAX written for this model: its columns on the model's tables (by a unique column name), its
        [KPI] references on the model's measures for those KPIs. Also the columns it could not place."""
        try:
            tree = D.parse(dax_text)
        except D.DaxError:
            return None, []
        unmapped: list[str] = []
        model = self.models[it["mi"]]
        cols: dict[str, list] = defaultdict(list)
        for t in model.get("tables") or []:
            for c in t.get("columns") or []:
                cols[c["name"].lower()].append((t["name"], c["name"]))
        names = {x["name"].lower(): x["name"] for x in model.get("measures") or []}
        by_kpi = {}
        for other in self.items:
            if other["mi"] == it["mi"] and other.get("kpi") is not None and other["how"] in ("name", "synonym", "similar", "ai"):
                by_kpi.setdefault(other["kpi"], other["m"]["name"])

        def rw(n):
            k = n[0]
            if k == "col":
                hits = cols.get(n[2].lower()) or []
                same = [h for h in hits if D.loose_table(h[0]) == D.loose_table(n[1])]
                if len(same) == 1 or len(hits) == 1:
                    h = (same or hits)[0]
                    return ("col", h[0], h[1])
                unmapped.append(D.show(n))
                return n
            if k == "ref":
                if n[1].lower() in names:
                    return ("ref", names[n[1].lower()])
                i, how, _ = self.matcher.match(n[1]) if self.matcher else (None, None, None)
                if i is not None and how in ("name", "synonym") and i in by_kpi:
                    return ("ref", by_kpi[i])
                return n
            if k == "call":
                return ("call", n[1], [rw(a) for a in n[2]])
            if k == "bin":
                return ("bin", n[1], rw(n[2]), rw(n[3]))
            if k == "un":
                return ("un", n[1], rw(n[2]))
            if k == "not":
                return ("not", rw(n[1]))
            if k == "in":
                return ("in", rw(n[1]), rw(n[2]))
            if k in ("ctor", "tuple"):
                return (k, [rw(x) for x in n[1]])
            if k == "var":
                return ("var", [(nm, rw(e)) for nm, e in n[1]], rw(n[2]))
            return n
        out = D.show(rw(tree))
        return out, sorted(set(unmapped))

    def ratio_average(self, it: dict) -> dict | None:
        """An average of row-level ratios: AVERAGE(T[margin_pct]) or AVERAGEX(T, a / b). Returns {what, fix}."""
        if not self.ok(it):
            return None
        tree = it["d"]["tree"]
        for x in D.walk(tree):
            if x[0] != "call":
                continue
            if x[1] == "AVERAGE" and x[2] and x[2][0][0] == "col" and RATIO_COL.search(x[2][0][2] or ""):
                return {"what": f"averages the column {D.show(x[2][0])}, a ratio worked out row by row", "fix": None}
            if x[1] == "AVERAGEX" and len(x[2]) == 2:
                body = x[2][1]
                if body[0] == "bin" and body[1] == "/":
                    num, den = body[2], body[3]
                elif body[0] == "call" and body[1] == "DIVIDE" and len(body[2]) >= 2:
                    num, den = body[2][0], body[2][1]
                else:
                    continue
                t = x[2][0]
                fix = D.show(("call", "DIVIDE", [("call", "SUMX", [t, num]), ("call", "SUMX", [t, den])]))
                return {"what": f"averages {D.show(body)} row by row", "fix": fix}
        return None

    def check_variants(self) -> None:
        """Revenue YTD, Revenue LY, Revenue vs Budget % ...: built on Revenue's own calculation. A variant that uses its
        model's Revenue measure is fine here (if that measure is wrong, it has findings of its own); one that writes its
        own formula must at least add up what Revenue adds up and keep Revenue's filters."""
        for g, vits in self.variants.items():
            base = [b for b in self.groups.get(g, []) if self.ok(b)]
            entry = self.kpi_entry(g)
            name = entry["name"] if entry else self.group_name.get(g, g[2:])
            for it in vits:
                ref_desc = self.ref_desc(int(g[2:]), it["mi"]) if entry else None
                if not self.ok(it):
                    continue
                label, sig = _label(it, self.multi), it["d"]["sig"]
                vw = set((it.get("variant") or "").split())
                if vw and vw <= TARGET_WORDS | {"pct"} and not vw & COMPARE_WORDS:
                    continue                                   # Revenue Budget, Revenue Target: the KPI's target, a number of its own
                words = " ".join(w.upper() if len(w) <= 3 and w not in ("vs", "to", "per") else w for w in (it.get("variant") or "").split())
                if entry and entry.get("year_end"):
                    yes = sorted({t.get("year_end") for t in sig.get("time") or [] if t["fn"] in YTD_FNS and t.get("year_end")} - {entry["year_end"]})
                    if yes:
                        self.add("time_basis", "medium", f"{label} uses another year end than {name}'s",
                                 f"{label} works out the year to date with a {_ye_words(yes[0])}; your dictionary says {name}'s year is a "
                                 f"{_ye_words(entry['year_end'])} ({entry.get('time') or 'fiscal year'}).", [it], kpi=name,
                                 fix=f'Give DATESYTD / TOTALYTD the year end "{_ye_text(entry["year_end"])}".')
                same = sorted([b for b in base if b["mi"] == it["mi"]], key=lambda b: 0 if b["how"] == "name" else 1)
                uses = {m.lower() for m in sig.get("measures") or []}
                if same and ({b["m"]["name"].lower() for b in same} & uses):
                    continue                                       # built on its model's own KPI measure
                ref_sig = (same[0]["d"]["sig"] if same else ref_desc["sig"] if ref_desc and "sig" in ref_desc
                           else base[0]["d"]["sig"] if base else None)
                if not ref_sig:
                    continue
                base_aggs = {(a["fn"], a["loose"]) for a in ref_sig.get("aggs") or [] if a["kind"] != "iterator"}
                var_aggs = {(a["fn"], a["loose"]) for a in sig.get("aggs") or [] if a["kind"] != "iterator"}
                base_preds = {f["key"]: f for f in ref_sig.get("filters") or [] if f["kind"] == "predicate"}
                var_preds = {f["key"] for f in sig.get("filters") or []}
                lost = [f for k, f in base_preds.items() if k not in var_preds]
                base_label = f"[{same[0]['m']['name']}]" if same else (f"{name} (your dictionary's)" if ref_desc else name)
                if base_aggs and not base_aggs <= var_aggs:
                    missing = [a for a in ref_sig["aggs"] if (a["fn"], a["loose"]) in base_aggs - var_aggs]
                    has = [a for a in sig.get("aggs") or [] if (a["fn"], a["loose"]) not in base_aggs and a["kind"] != "iterator"]
                    self.add("variant_drift", "high" if (entry or same) else "medium", f"{label} is not built on {name}",
                             f"{label} is a variant of {name}{f' ({words})' if words else ''}, but it does not use {name}'s calculation: "
                             f"{base_label} {', '.join(_agg_words(a) for a in missing[:3])}"
                             + (f", where {label} {', '.join(_agg_words(a) for a in has[:3])}" if has else f", and {label} does not")
                             + f". Its number will not match {name}'s.", [it] + same[:1], kpi=name,
                             fix=f"Build it on the KPI's measure, for example CALCULATE ( [{same[0]['m']['name'] if same else name}], <the time or target filter> ).")
                    continue
                if lost:
                    self.add("variant_drift", "medium", f"{label} leaves out a filter of {name}",
                             f"{base_label} {_filter_words(lost[0])}; {label} does not, so it counts rows {name} leaves out.", [it] + same[:1], kpi=name,
                             fix=f"Build it on [{same[0]['m']['name']}]." if same else None)
                    continue
                if same and base_aggs:
                    self.add("base_not_reused", "low", f"{label} repeats {name}'s formula instead of using [{same[0]['m']['name']}]",
                             f"It gives the same number today, but a change to [{same[0]['m']['name']}] will not reach {label}.",
                             [it, same[0]], kpi=name, fix=f"Refer to [{same[0]['m']['name']}] inside {label}.")

    def check_measures(self) -> None:
        by_model = defaultdict(list)
        for it in self.items:
            by_model[it["mi"]].append(it)
        for mi, its in by_model.items():
            divisions = []
            for it in its:
                d, label = it["d"], _label(it, self.multi)
                kpi_name = self._kpi_of(it)
                if "error" in d:
                    self.add("broken", "high", f"{label} cannot be read", f"Its DAX could not be read: {d['error']}.", [it], kpi=kpi_name)
                    continue
                notes = d.get("notes") or {}
                if notes.get("missing"):
                    miss = notes["missing"][:5]
                    self.add("broken", "high", f"{label} refers to something not in the model",
                             f"It refers to {', '.join(miss)}, which {'is' if len(miss) == 1 else 'are'} not in this model (a renamed or "
                             "deleted measure, column or table): Power BI shows an error instead of the number.", [it], kpi=kpi_name)
                if notes.get("cycle"):
                    self.add("broken", "high", f"{label} refers to itself", f"Its references go round in a circle ({', '.join(notes['cycle'][:4])}).", [it], kpi=kpi_name)
                if notes.get("frozen"):
                    self.add("frozen_variable", "high", f"CALCULATE in {label} cannot change a variable",
                             f"The variable{'s' if len(notes['frozen']) > 1 else ''} {', '.join(notes['frozen'][:4])} "
                             f"{'are' if len(notes['frozen']) > 1 else 'is'} worked out before CALCULATE applies its filters, so the filters do "
                             "nothing to it: the measure returns the unfiltered number.", [it], kpi=kpi_name,
                             fix="Put the calculation (or a measure) inside CALCULATE, not a variable.")
                sig = d["sig"]
                if sig.get("iterator_aggregates"):
                    self.add("iterator_aggregate", "medium", f"{label} repeats one total on every row",
                             f"{sig['iterator_aggregates'][0]} inside an iterator ignores the row it is on (there is no CALCULATE), so every row "
                             "gets the same total.", [it], kpi=kpi_name, fix="Wrap the inner aggregation in CALCULATE ( ... ), or use a measure there.")
                ra = self.ratio_average(it)
                if ra:
                    entry = self.dict[it["kpi"]] if it.get("kpi") is not None and it["how"] != "variant" else None
                    strong = bool(entry and (entry.get("unit") in ("percent", "ratio") or entry.get("aggregation") == "ratio")) \
                        or bool(RATIO_COL.search(it["m"]["name"]))
                    self.add("average_of_ratios", "high" if strong else "medium", f"{label} averages ratios",
                             f"It {ra['what']}. An average of ratios gives small rows the same weight as big ones, so the total does not "
                             "match the ratio of the totals (what the KPI means).", [it], kpi=kpi_name,
                             fix="Divide the two totals instead of averaging the row-level ratios"
                                 + ("." if ra["fix"] else ": DIVIDE ( SUM ( <top column> ), SUM ( <bottom column> ) )."),
                             fix_dax=f"{it['m']['name']} = {ra['fix']}" if ra["fix"] else None)
                rem = [r for r in sig.get("removers") or [] if r.get("own") and r.get("in_filter") and r.get("whole_table")]
                if sig.get("time"):
                    rem = [r for r in rem if not any(re.search(r"date|calendar|time|period", x, re.I) for x in r["of"] or ["x"])]
                on_kpi = (kpi_name or self._builds_on_kpi(it)) if rem else None
                if on_kpi and not INTENT_ALL.search(it["m"]["name"]):
                    if rem:
                        targets = ", ".join(f"{r['fn']} ( {', '.join(r['of'])} )" for r in rem[:3])
                        self.add("filter_override", "medium" if kpi_name else "low", f"{label} ignores the report's filters",
                                 f"It uses {targets}, so the number stays the same whatever is selected on those tables: a slicer on them "
                                 f"changes every visual but this one{'' if kpi_name else f', which is built on {on_kpi}'}.", [it], kpi=kpi_name or on_kpi,
                                 fix="Remove only the filters the KPI's definition asks to remove, or name the measure for what it is (for example \"... of total\").")
                if kpi_name and sig.get("constants"):
                    self.add("constant", "low", f"{label} has fixed numbers written into it",
                             f"It uses {', '.join(sig['constants'][:5])}. If that is a rate, a target or an exchange rate, keep it in one table "
                             "or parameter so every report uses the same value, and it changes in one place.", [it], kpi=kpi_name)
                if sig.get("divisions"):
                    divisions.append(it)
            if divisions:
                names = ", ".join(_label(x, False) for x in divisions[:MAX_LIST])
                self.add("unsafe_division", "low", f"{len(divisions)} measure{'s divide' if len(divisions) > 1 else ' divides'} with \"/\""
                         + (f" in {self.models[mi].get('name') or 'the model'}" if self.multi else ""),
                         f"{names}{' and more' if len(divisions) > MAX_LIST else ''}. A \"/\" shows an error or infinity when the bottom is zero "
                         "or blank; DIVIDE ( top, bottom ) shows a blank instead.", divisions,
                         fix="Write DIVIDE ( top, bottom ) instead of top / bottom.")
            self.check_duplicates(its)
        self.check_duplicates_across()

    def _builds_on_kpi(self, it: dict) -> str | None:
        """The KPI a measure in no KPI is built on (it refers to that KPI's measure), if any."""
        if not self.ok(it):
            return None
        uses = {m.lower() for m in it["d"]["sig"].get("measures") or []}
        for other in self.items:
            if other["mi"] == it["mi"] and other is not it and other["m"]["name"].lower() in uses and other.get("how") not in (None, "variant"):
                k = self._kpi_of(other)
                if k:
                    return k
        return None

    def _kpi_of(self, it: dict) -> str | None:
        g = it.get("group") if it.get("how") != "variant" else it.get("variant_of")
        if it.get("kpi") is not None:
            return self.dict[it["kpi"]]["name"]
        if g and (len(self.groups.get(g, [])) > 1 or it.get("how") == "variant"):
            return self.group_name.get(g)
        return None

    def check_duplicates(self, its: list[dict]) -> None:
        by_fp = defaultdict(list)
        for it in its:
            if self.ok(it) and (it["d"]["sig"].get("shape") not in ("constant",)) and (it["d"]["sig"].get("aggs") or it["d"]["sig"].get("measures")):
                by_fp[it["d"]["fp"]].append(it)
        for fp, same in by_fp.items():
            if len(same) < 2:
                continue
            groups = {x.get("group") for x in same}
            if len(groups) == 1 and next(iter(groups)) is not None and next(iter(groups)).startswith("k:"):
                kpi = self.group_name[next(iter(groups))]
                self.add("duplicate", "low", f"{len(same)} measures compute {kpi} the same way",
                         f"{', '.join(_label(x, False) for x in same[:6])} give the same number. Keep one and remove the others, "
                         "or make them refer to it.", same, kpi=kpi)
                continue
            aliases = [x for x in same if x["d"]["tree"][0] == "ref"]
            what = (f"{', '.join(_label(x, False) for x in aliases[:3])} only refer{'s' if len(aliases) == 1 else ''} to another measure. "
                    if aliases else "")
            self.add("duplicate", "medium", f"{len(same)} names for one number",
                     f"{', '.join(_label(x, False) for x in same[:6])} compute the same thing. {what}People will read them as different KPIs; "
                     "keep one name, or list the others as its synonyms in the KPI dictionary.", same)

    def check_duplicates_across(self) -> None:
        if not self.multi:
            return
        by_fp = defaultdict(list)
        for it in self.items:
            if self.ok(it) and it["d"]["sig"].get("aggs") and it["d"]["sig"].get("shape") != "constant":
                by_fp[it["d"]["fp_loose"]].append(it)
        for fp, same in by_fp.items():
            strict = defaultdict(set)
            for x in same:
                strict[x["mi"]].add(x["d"]["fp"])
            same = [x for x in same if len(strict[x["mi"]]) == 1]      # a model where the loose form is not one formula: left out
            models = {x["mi"] for x in same}
            names = {norm(x["m"]["name"]) for x in same}
            groups = {x.get("group") for x in same}
            if len(models) > 1 and len(names) > 1 and not (len(groups) == 1 and None not in groups):
                self.add("duplicate", "low", "The same number has different names in different models",
                         f"{', '.join(_label(x, True) for x in same[:6])} compute the same thing. Use one name everywhere, or list the "
                         "others as synonyms in the KPI dictionary.", same)

    def check_models(self) -> None:
        for mi, m in enumerate(self.models):
            label = f" in {m.get('name') or 'the model'}" if self.multi else ""
            its = [it for it in self.items if it["mi"] == mi]
            # columns visuals add up by default though adding them up means nothing (ids, years, rates, prices)
            risky = []
            used = ((m.get("usage") or {}).get("columns")) or {}
            for t in m.get("tables") or []:
                for c in t.get("columns") or []:
                    sb = str(c.get("summarize") or "").lower()
                    numeric = str(c.get("type") or "").lower() in NUMERIC
                    adds = sb in ("sum", "average", "min", "max", "count") or (sb in ("default", "") and numeric)
                    if not adds or c.get("hidden") or not numeric and sb in ("default", ""):
                        continue
                    n = c["name"]
                    why = ("an id or code" if IDLIKE.search(n) else "a date part" if TIME_COL.match(n)
                           else "a coordinate" if re.search(r"latitude|longitude|\blat\b|\blon\b", n, re.I)
                           else "a price or unit cost" if re.search(r"price|tariff|cost per|per unit|unit cost", n, re.I)
                           else "a rate or percentage" if re.search(r"rate|ratio|pct|percent|%", n, re.I)
                           else "a score or age" if RATE_COL.search(n) else None)
                    if why:
                        key = f"{t['name']}[{n}]"
                        risky.append((key, why, sum(1 for u in used.get(key, []) if u.get("agg"))))
            if risky:
                txt = "; ".join(f"{k} ({w}{', added up in ' + str(u) + ' visual' + ('s' if u > 1 else '') if u else ''})" for k, w, u in risky[:MAX_LIST])
                self.add("implicit_sum", "medium" if any(u for _, _, u in risky) else "low",
                         f"{len(risky)} column{'s' if len(risky) > 1 else ''} that visuals add up by default{label}",
                         f"{txt}. Adding these up gives a number that means nothing (or a wrong total). Set their summarisation to "
                         "\"Don't summarize\" and use a measure for the KPI.", [], dax=[])
            # visuals that aggregate a column themselves where a KPI's measure covers that column
            if used:
                kpi_cols = defaultdict(list)
                for it in its:
                    if not self.ok(it) or not self._kpi_of(it):
                        continue
                    for a in it["d"]["sig"].get("aggs") or []:
                        if a["kind"] == "column":
                            kpi_cols[a["of"].lower()].append(it)
                hits = []
                for key, uses in used.items():
                    aggd = [u for u in uses if u.get("agg")]
                    if aggd and key.lower() in kpi_cols:
                        hits.append((key, aggd, kpi_cols[key.lower()][0]))
                for key, aggd, it in hits[:10]:
                    pages = sorted({u.get("page") or "" for u in aggd})
                    self.add("implicit_visual", "medium", f"Visuals work out {key} themselves instead of using [{it['m']['name']}]",
                             f"{len(aggd)} visual{'s' if len(aggd) > 1 else ''} (on {', '.join(p for p in pages[:4] if p) or 'the report'}) "
                             f"show{'' if len(aggd) > 1 else 's'} "
                             f"{aggd[0].get('agg', 'an aggregate')} of {key} directly. [{it['m']['name']}] is the KPI's measure for it; the visuals "
                             "will not follow its definition (filters, exclusions) and can show another number.", [it], kpi=self._kpi_of(it),
                             fix=f"Put [{it['m']['name']}] in those visuals instead of the column.")
            # titles that name one KPI over another KPI's measure
            if self.matcher:
                for it in its:
                    if it.get("kpi") is None or it["how"] == "variant":
                        continue
                    for u in it["uses"]:
                        title = (u.get("title") or "").strip()
                        if not title or u.get("measures", 1) != 1:     # a title over several measures names none of them alone
                            continue
                        ti, how, _ = self.matcher.match(title)
                        if ti is not None and how in ("name", "synonym") and ti != it["kpi"]:
                            self.add("title", "medium", f"A visual titled \"{title}\" shows {self.dict[it['kpi']]['name']}",
                                     f"On the page \"{u.get('page') or ''}\" the {u.get('visual') or 'visual'} titled \"{title}\" (the KPI "
                                     f"{self.dict[ti]['name']}) shows [{it['m']['name']}], which is {self.dict[it['kpi']]['name']}.",
                                     [it], kpi=self.dict[ti]["name"])
                            break
            ytd = defaultdict(list)
            for it in its:
                if self.ok(it):
                    for t in it["d"]["sig"].get("time") or []:
                        if t["fn"] in YTD_FNS and t.get("year_end"):
                            ytd[t["year_end"]].append(it)
            if len(ytd) > 1:
                parts = [f"{_ye_words(y)}: {', '.join(_label(x, False) for x in v[:4])}" for y, v in sorted(ytd.items())]
                self.add("time_basis", "medium", f"Two year ends in one model{label}",
                         f"Year-to-date measures here use different year ends ({'; '.join(parts)}). A year to date should mean one "
                         "thing in a model.", [x for v in ytd.values() for x in v][:MAX_LIST])
            both = [r for r in m.get("relationships") or [] if r.get("cross") == "both"]
            if both:
                rl = "; ".join(f"{r['from'][0]}[{r['from'][1]}] - {r['to'][0]}[{r['to'][1]}]" for r in both[:8])
                self.add("bidirectional", "low", f"{len(both)} relationship{'s filter' if len(both) > 1 else ' filters'} both ways{label}",
                         f"{rl}. A filter on one table then changes KPIs on unrelated tables too, and totals can depend on what else is "
                         "on the page.", [], dax=[])
            if m.get("calc_groups"):
                names = ", ".join(f"{g['table']} ({', '.join(i['name'] for i in g['items'][:5])})" for g in m["calc_groups"][:4])
                self.add("calc_groups", "info", f"Calculation groups change what measures return{label}",
                         f"{names}. The review reads each measure's own formula; in visuals these groups can change it.", [], dax=[])

    def check_dictionary(self) -> None:
        if not self.dict:
            self.add("undocumented", "info", "No KPI dictionary yet",
                     "The models were compared with themselves only (the same names, the same numbers). Add your KPI definitions under "
                     "KPI dictionary, or start one from this review, to check what each KPI means.", [], dax=[])
            return
        found = {int(g[2:]) for g in list(self.groups) + list(self.variants) if g.startswith("k:") and (self.groups.get(g) or self.variants.get(g))}
        missing = [e["name"] for i, e in enumerate(self.dict) if i not in found]
        if missing:
            self.add("missing", "info", f"{len(missing)} KPI{'s' if len(missing) > 1 else ''} of your dictionary {'are' if len(missing) > 1 else 'is'} in no model",
                     f"{', '.join(missing[:40])}{' and more' if len(missing) > 40 else ''}. Either the models do not report them, or "
                     "their measures have other names: add those names as synonyms.", [], dax=[])
        loose = [it for it in self.items if it.get("kpi") is None and it.get("how") != "variant" and not it["m"].get("hidden")]
        if loose:
            self.add("undocumented", "info", f"{len(loose)} measure{'s are' if len(loose) > 1 else ' is'} not in your KPI dictionary",
                     f"{', '.join(_label(x, self.multi) for x in loose[:30])}{' and more' if len(loose) > 30 else ''}. Add the ones that are "
                     "KPIs (or their names as synonyms), so the review can hold them to a definition.", loose[:MAX_LIST], dax=[])
        nodesc = [it for it in self.items if it.get("kpi") is not None and it["how"] != "variant" and not (it["m"].get("description") or "").strip()]
        if nodesc:
            self.add("description", "low", f"{len(nodesc)} KPI measure{'s have' if len(nodesc) > 1 else ' has'} no description",
                     f"{', '.join(_label(x, self.multi) for x in nodesc[:20])}. A description (from the dictionary) shows in Power BI when "
                     "someone points at the field: it tells them what the number means.", nodesc[:MAX_LIST], dax=[])

    # ---- the result

    def result(self) -> dict:
        self.findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["rule"], f["title"]))
        for i, f in enumerate(self.findings, 1):
            f["id"] = f"f{i}"
        counts = {s: sum(1 for f in self.findings if f["severity"] == s) for s in SEVERITY_ORDER}
        rows = self.kpi_rows
        for r in rows:
            r["findings"] = [f["id"] for f in self.findings if f.get("kpi") == r["name"]]
        checked = [r for r in rows if r["status"] in ("consistent", "conflict", "differs")]
        consistent = sum(1 for r in checked if r["status"] == "consistent")
        rows.sort(key=lambda r: ({"conflict": 0, "differs": 1, "unreadable": 2, "consistent": 3, "variants_only": 4, "missing": 5}.get(r["status"], 6),
                                 r["name"].lower()))
        measures = []
        for it in self.items:
            x = it["m"]
            measures.append({"id": it["id"], "model": it["mi"], "table": x.get("table"), "name": x["name"],
                             "kpi": self._kpi_of(it), "defined": it.get("kpi") is not None, "how": it.get("how"), "variant": it.get("variant"),
                             "format": x.get("format"), "folder": x.get("folder"), "hidden": bool(x.get("hidden")),
                             "description": (x.get("description") or "")[:500] or None, "shows": len(it["uses"]),
                             "dax": (x.get("expression") or "")[:4000], "error": it["d"].get("error"),
                             "fp": it["d"].get("fp")})
        models = []
        for m in self.models:
            u = m.get("usage") or {}
            models.append({"name": m.get("name"), "source": m.get("source") or {}, "tables": len(m.get("tables") or []),
                           "measures": len(m.get("measures") or []), "relationships": len(m.get("relationships") or []),
                           "pages": u.get("pages"), "visuals": u.get("visuals")})
        return {"summary": {"models": len(self.models), "measures": len(self.items), "kpis_defined": len(self.dict),
                            "kpis_checked": len(checked), "kpis_consistent": consistent,
                            "kpis_conflicting": sum(1 for r in rows if r["status"] == "conflict"),
                            "kpis_differing": sum(1 for r in rows if r["status"] == "differs"),
                            "kpis_missing": sum(1 for r in rows if r["status"] in ("missing", "variants_only")),
                            "score": round(100 * consistent / len(checked)) if checked else None, "findings": counts},
                "models": models, "kpis": rows, "findings": self.findings, "measures": measures}


def _agg_name(a: str) -> str:
    return {"sum": "a sum", "average": "an average", "count": "a count", "distinct_count": "a count of different values",
            "ratio": "a ratio", "min": "a lowest value", "max": "a highest value", "last": "a closing (last) value"}.get(a, a)


def _ye_text(ye: str) -> str:
    m, d = ye.split("-")
    return f"{int(m)}/{int(d)}"


def _ye_words(ye: str) -> str:
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    try:
        m, d = (int(x) for x in ye.split("-"))
        return f"year ending {d} {months[m - 1]}"
    except (ValueError, IndexError):
        return f"year ending {ye}"


def review(models: list[dict], dictionary: list[dict], extra: dict | None = None) -> dict:
    """The review of one or more models against a KPI dictionary (see the module's docstring)."""
    r = _Review(models, dictionary, extra)
    r.read()
    r.match()
    r.rules()
    return r.result()


# ---------------------------------------------------------------- the meaning check (Claude): what it is sent, what it may say

AI_VERDICTS = ("matches", "differs", "unclear")


def ai_cases(models: list[dict], dictionary: list[dict], result: dict, max_chars: int = 60000) -> list[dict]:
    """Batches for the meaning check, each under max_chars of JSON: the dictionary's KPIs that have a definition or a
    formula in words, each with the measures found for it; and (first batch) the measures in no KPI, for Claude to
    say which KPI any of them is."""
    import json
    by_id = {m["id"]: m for m in result["measures"]}
    cases = []
    for r in result["kpis"]:
        if not r["defined"]:
            continue
        e = next((x for x in dictionary if x["name"] == r["name"]), None)
        if not e or not (e.get("definition") or e.get("formula") or e.get("filters")):
            continue
        impls = []
        for im in r["implementations"][:8]:
            m = by_id.get(im["id"]) or {}
            impls.append({"id": im["id"], "model": im["model_name"], "measure": im["measure"], "format": im.get("format"),
                          "description": m.get("description"), "dax": (im.get("dax") or "")[:1500]})
        cases.append({"kpi": {k: e[k] for k in ("name", "synonyms", "definition", "formula", "dax", "unit", "aggregation", "filters", "time")
                              if e.get(k)}, "measures": impls})
    loose = [{"id": m["id"], "measure": m["name"], "dax": (m["dax"] or "")[:300]} for m in result["measures"]
             if not m.get("defined") and m.get("how") != "variant" and not m["hidden"]][:200]
    batches, cur, size = [], [], 0
    for c in cases:
        n = len(json.dumps(c))
        if cur and size + n > max_chars:
            batches.append({"cases": cur, "unmatched": []})
            cur, size = [], 0
        cur.append(c)
        size += n
    if cur or loose:
        batches.append({"cases": cur, "unmatched": []})
    if batches and loose and dictionary:
        batches[0]["unmatched"] = loose
        batches[0]["kpi_names"] = [e["name"] for e in dictionary][:400]
    return [b for b in batches if b["cases"] or b.get("unmatched")]


def ai_schema(models: list[dict]) -> list[dict]:
    """The models' tables and columns for the meaning check (names and types only), trimmed."""
    out = []
    for m in models:
        for t in (m.get("tables") or [])[:80]:
            out.append({"model": m.get("name"), "table": t["name"],
                        "columns": [f"{c['name']} ({c.get('type') or '?'})" for c in (t.get("columns") or [])[:60]]})
    return out[:200]


def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def _dicts(x) -> list[dict]:
    """The AI's list, only its objects (it is model output: anything else in it is passed over)."""
    return [v for v in x if isinstance(v, dict)] if isinstance(x, list) else []


def merge_ai(result: dict, replies: list[dict], dictionary: list[dict], human=lambda s: s) -> dict:
    """The meaning check's answers into the result, checked: only verdicts on measures and KPIs the review sent,
    text trimmed and made plain (human), severities from the allowed set. Adds findings with source "ai"."""
    known = {m["id"]: m for m in result["measures"]}
    names = {e["name"].lower(): e["name"] for e in dictionary}
    seq = len(result["findings"])
    added = 0
    for rep in replies:
        for c in _dicts(_dict(rep).get("kpis")):
            kpi = names.get(str(c.get("kpi") or "").lower())
            if not kpi:
                continue
            for v in _dicts(c.get("measures") or c.get("implementations"))[:12]:
                m = known.get(str(v.get("id") or ""))
                verdict = str(v.get("verdict") or "").lower()
                if not m or verdict not in AI_VERDICTS or verdict == "matches":
                    continue
                sev = str(v.get("severity") or "").lower()
                sev = sev if sev in ("high", "medium", "low") else ("medium" if verdict == "differs" else "low")
                seq += 1
                added += 1
                fix = str(v.get("fix_dax") or "").strip()[:2000] or None
                result["findings"].append({
                    "id": f"f{seq}", "rule": "meaning", "severity": sev if verdict == "differs" else "low", "source": "ai",
                    "title": human(f"[{m['name']}] {'does not match' if verdict == 'differs' else 'may not match'} the definition of {kpi}"),
                    "detail": human(str(v.get("why") or "")[:1200]), "kpi": kpi,
                    "measures": [{"model": m["model"], "model_name": result["models"][m["model"]]["name"], "table": m["table"], "name": m["name"]}],
                    "dax": [f"{m['name']} = {m['dax']}"[:3000]], "fix": "Relay's AI suggests this DAX: check it before you use it." if fix else None,
                    "fix_dax": (f"{m['name']} = {fix}" if not fix.lower().startswith(m["name"].lower()) else fix) if fix else None})
        for mt in _dicts(_dict(rep).get("matches")):
            m = known.get(str(mt.get("id") or ""))
            kpi = names.get(str(mt.get("kpi") or "").lower())
            if not m or not kpi or m.get("how") not in (None, "ai"):
                continue
            where = [{"model": m["model"], "model_name": result["models"][m["model"]]["name"], "table": m["table"], "name": m["name"]}]
            seq += 1
            added += 1
            result["findings"].append({
                "id": f"f{seq}", "rule": "meaning_match", "severity": "info", "source": "ai",
                "title": human(f"[{m['name']}] looks like {kpi}"),
                "detail": human(str(mt.get("why") or "")[:800]).rstrip(". ") + f". The review treats it as {kpi}; add \"{m['name']}\" to "
                          f"{kpi}'s synonyms in the dictionary if that is right.",
                "kpi": kpi, "measures": where, "dax": [f"{m['name']} = {m['dax']}"[:3000]], "fix": None, "fix_dax": None})
            if str(mt.get("verdict") or "").lower() == "differs":
                fix = str(mt.get("fix_dax") or "").strip()[:2000] or None
                seq += 1
                added += 1
                result["findings"].append({
                    "id": f"f{seq}", "rule": "meaning", "severity": "medium", "source": "ai",
                    "title": human(f"[{m['name']}] does not match the definition of {kpi}"), "detail": human(str(mt.get("why") or "")[:1200]),
                    "kpi": kpi, "measures": where, "dax": [f"{m['name']} = {m['dax']}"[:3000]],
                    "fix": "Relay's AI suggests this DAX: check it before you use it." if fix else None,
                    "fix_dax": (f"{m['name']} = {fix}" if not fix.lower().startswith(m["name"].lower()) else fix) if fix else None})
    result["findings"].sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), 0 if f.get("source") == "ai" else 1, f["rule"], f["title"]))
    remap = {}
    for i, f in enumerate(result["findings"], 1):
        remap[f["id"]] = f"f{i}"
        f["id"] = f"f{i}"
    for r in result["kpis"]:
        r["findings"] = [remap.get(x, x) for x in r["findings"]]
        r["findings"] += [f["id"] for f in result["findings"] if f.get("source") == "ai" and f.get("kpi") == r["name"] and f["id"] not in r["findings"]]
    result["summary"]["findings"] = {s: sum(1 for f in result["findings"] if f["severity"] == s) for s in SEVERITY_ORDER}
    result["summary"]["ai_findings"] = added
    return result


def ai_matches(replies: list[dict], result: dict, dictionary: list[dict]) -> dict:
    """(model index, measure name lower) -> KPI index, from the meaning check's matches of measures in no KPI."""
    known = {m["id"]: m for m in result["measures"]}
    idx = {e["name"].lower(): i for i, e in enumerate(dictionary)}
    out = {}
    for rep in replies:
        for mt in _dicts(_dict(rep).get("matches")):
            m = known.get(str(mt.get("id") or ""))
            i = idx.get(str(mt.get("kpi") or "").lower())
            if m and i is not None and not m.get("defined") and m.get("how") != "variant":
                out[(m["model"], m["name"].lower())] = i
    return out
