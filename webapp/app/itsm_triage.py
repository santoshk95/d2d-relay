"""Service desk triage (build-plan v2, P12): per ticket a plain-English summary and a category; duplicates and
same-cause tickets grouped ("clubbed") by title + description similarity (TF-IDF over words and word pairs, cosine,
average-linkage) with domain rules (same kind of problem, same report or metric); a priority from business impact
with the reason; a route (an agent can handle it, or a person); and the module the work should go to.

No external model: the rules run in milliseconds on hundreds of tickets and are deterministic, which is what the
precision / recall check in tests/p12_itsm_test.py measures. An optional LLM pass (`refine`, behind ITSM_LLM) can
rewrite summaries and adjust priorities through the sequential agent lane; it never changes the groups.
"""
from __future__ import annotations

import math
import re
import time

NEAR_SLA_H = 4.0            # "near SLA breach": due within this many hours (and not past)
THRESHOLD = 0.26            # average-linkage similarity needed to merge two clusters (tuned on the mock lab fixture)
TITLE_WEIGHT = 3            # the title says what it is about; the description repeats templates
DESC_CHARS = 320            # how much of the description joins the vector
ENTITY_BONUS = 0.10         # the same report / feed named in both
ENTITY_PENALTY = 0.50       # both name a report, and not the same one
RESIDUAL_PENALTY = 0.30     # same report, but the titles name a different metric or topic
CUT = set("""on in for of to with from at by the a an and or is was has have not no new slow wrong missing refresh refreshed failure failed
error access permission request data numbers number shows show since keeps keep stuck scheduled please share grant need needs can cannot
gap export subscription filter bookmark layout tooltip very slowly""".split())

STOP = set("""a an and are as at be been by can could did do does for from get has have he her his how i if in into is it its just
me my no not of on or our please should so that the their them then there these they this to us very was we were what when which who why
will with would you your yours yourself am also about again all any because before being between both but each few more most other
our out over own same some such than too under until up while hi hello thanks thank team regards kindly morning today yesterday
since every keeps keep again still now asap urgent one two three four five""".split())
THINGS = {"dashboard", "report", "pack", "feed", "snapshot", "cube", "model", "forecast", "scorecard", "sync", "reconciliation", "dive",
          "pipeline", "dataset", "workspace", "analysis", "page", "view", "extract", "alert", "subscription"}
CATEGORIES = [
    ("access", r"\b(access|permission|permissions|grant|share|viewer|joiner|cannot open|can't open|unable to open|log ?in|licen[cs]e)\b"),
    ("refresh", r"\b(refresh|refreshed|refreshing|gateway|credential|credentials expired|data ?source error|timed? ?out after|refresh (failed|failure|error))\b"),
    ("missing", r"\b(missing|blank|not (loaded|updated)|no (data|rows)|gap in|backfill|rows missing|stops at|skipped)\b"),
    ("wrong", r"\b(wrong|differs?|different|mismatch|does not match|doesn't match|not match|reconcile|off vs|incorrect|looks wrong|is off|lower than|higher than)\b"),
    ("slow", r"\b(slow|slowly|slower|performance of|poor performance|takes \d+ (minutes|min)|time ?out|times out|unusabl|spins)\b"),
    ("new", r"\b(new (report|kpi|view|page|measure)|request:|report request|can we (get|have|add)|please add|need .* on|add .* to|would like .* added)\b"),
]
CATEGORY_LABEL = {"access": "Access request", "refresh": "Refresh failure", "missing": "Data missing", "wrong": "Numbers wrong", "slow": "Slow report",
                  "new": "New report or KPI request", "other": "Report problem"}
# Where the work goes once a person decides (the target modules' real creation comes with their phases; D2D is live).
TARGET = {"refresh": ("heal", "Self-healing"), "missing": ("heal", "Self-healing"), "wrong": ("semantics", "Ontology & semantics"),
          "new": ("d2d", "D2D · Dashboards"), "slow": ("d2d", "D2D · Dashboards"), "access": ("govern", "Govern"), "other": ("d2d", "D2D · Dashboards")}
# What an agent can do on its own today (access with an existing role, known refresh fixes, known issues with a runbook).
AGENT_RULES = {"access": ("the role already exists; granting access is a standard, reversible step", r"\b(role|standard|usual|same access|already exists)\b"),
               "refresh": ("a known refresh fix: expired credential or a gateway time-out, re-run after the fix", r"\b(credential|credentials|gateway|timed out|time ?out|503|service unavailable)\b"),
               "other": ("a known issue with a runbook (subscriptions, exports, bookmarks)", r"\b(subscription|export|bookmark)\b")}
IMPACT_WORDS = r"\b(board|statutory|audit|gst|return|month[- ]end|close|regulator|steering|exec|cfo|ceo|payroll|tax)\b"
PRIORITY_LABEL = {"P1": "Critical", "P2": "High", "P3": "Medium", "P4": "Low"}

_word = re.compile(r"[a-z0-9][a-z0-9%&'./-]*")


def stem(w: str) -> str:
    for suf in ("ings", "ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    out = []
    for w in _word.findall((text or "").lower()):
        w = w.strip("'./-")
        if not w or w in STOP or w.startswith("fx-") or (w.isdigit() and len(w) > 2):
            continue
        out.append(stem(w))
    return out


def grams(toks: list[str]) -> list[str]:
    return toks + [a + " " + b for a, b in zip(toks, toks[1:])]


def category(t: dict) -> str:
    """The kind of problem, from the title first (weight 2) then the description; 'other' when nothing matches."""
    title, desc = (t.get("title") or "").lower(), (t.get("description") or "").lower()
    best, score = "other", 0
    for cat, pat in CATEGORIES:
        s = 2 * len(re.findall(pat, title)) + len(re.findall(pat, desc[:400]))
        if s > score:
            best, score = cat, s
    return best


def entities(t: dict) -> set[str]:
    """The report, dashboard, feed … a ticket is about: up to three words ending in a 'thing' word, from the title and
    the first lines of the description; plus capitalised runs (product and report names)."""
    out = set()
    text = (t.get("title") or "") + ". " + (t.get("description") or "")[:300]
    words = re.findall(r"[A-Za-z&%'][A-Za-z&%'-]*|[.:;,!?()]", text)
    for i, w in enumerate(words):
        if w.lower().rstrip("s'") in THINGS or w.lower() in THINGS:
            phrase = [w.lower()]
            for back in range(i - 1, max(-1, i - 4), -1):
                prev = words[back]
                if not prev[0].isalpha() or prev.lower() in CUT or prev.lower() in STOP:
                    break
                phrase.insert(0, prev.lower())
            if len(phrase) >= 2:
                out.add(" ".join(phrase))
    for m in re.finditer(r"\b([A-Z][A-Za-z&-]+(?: [A-Z&][A-Za-z&-]*){1,3})\b", text):
        p = m.group(1)
        if p.split()[0].lower() not in STOP and p.split()[0].lower() not in CUT:
            out.add(p.lower())
    return out


def things(ents: set[str]) -> set[str]:
    """Only the report / feed / pack names (a system name like 'Oracle Fusion' is not what a ticket is about)."""
    return {e for e in ents if e.split()[-1].rstrip("s") in THINGS or e.split()[-1] in THINGS}


def best_entity(ents: set[str]) -> str:
    """The report / feed / pack the ticket names, else the longest capitalised name."""
    pool = things(ents) or ents
    return sorted(pool, key=lambda e: (-len(e.split()), -len(e)))[0] if pool else ""


def vectorise(docs: list[list[str]]) -> list[dict[str, float]]:
    df: dict[str, int] = {}
    for d in docs:
        for g in set(d):
            df[g] = df.get(g, 0) + 1
    n = max(1, len(docs))
    out = []
    for d in docs:
        tf: dict[str, float] = {}
        for g in d:
            tf[g] = tf.get(g, 0.0) + (1.6 if " " in g else 1.0)
        v = {g: (1 + math.log(c)) * math.log((n + 1) / (df[g] + 0.5)) for g, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        out.append({g: x / norm for g, x in v.items()})
    return out


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b[g] for g, x in a.items() if g in b)


SUBJECT_CATS = ("wrong", "new")      # where the metric / topic in the title tells two groups about one report apart
CATWORDS = set("""refresh fail failur error gateway stuck schedul again morning overnight access permiss grant share viewer joiner open
wrong differ differs mismatch match off incorrect look number numbers slow perform time load unusabl spin filter request kpi view page
add need get can miss blank gap row updat backfill data figur day report dashboard than between shows show""".split())


def residual(t: dict, ents: set[str]) -> set[str]:
    """What the title says beyond the report name and the kind of problem: the metric, topic or symptom words."""
    drop = set(CATWORDS)
    for e in ents:
        drop.update(tokens(e))
    return {w for w in tokens(t.get("title") or "") if stem(w) not in drop and w not in drop and not w.isdigit()}


def subject(members: list[dict], about: str) -> str:
    """The metric or topic a 'numbers wrong' / 'new request' group is about: the title words (beyond the report name
    and the kind of problem) that at least half of the tickets share, in the oldest ticket's own spelling."""
    drop = set(CATWORDS) | set(tokens(about)) | STOP
    counts: dict[str, int] = {}
    for m in members:
        words = {w for w in _word.findall((m.get("title") or "").lower()) if stem(w) not in drop and w not in drop and not w.isdigit() and len(w) > 1}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
    keep = {w for w, c in counts.items() if c * 2 >= len(members)}
    if not keep:
        return ""
    oldest = sorted(members, key=lambda m: m.get("created") or 0)[0].get("title") or ""
    found = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9%&'./-]*", oldest) if w.lower() in keep]     # original spelling (DSO, OTIF %)
    out: list[str] = []
    for w in found:
        if w.lower() not in [x.lower() for x in out]:
            out.append(w)
    return " ".join(out[:2])


def similarity(i: int, j: int, vec: list[dict], cats: list[str], ents: list[set[str]], res: list[set[str]] | None = None) -> float:
    if cats[i] != cats[j]:
        return 0.0
    s = cosine(vec[i], vec[j])
    if ents[i] and ents[j]:
        s += ENTITY_BONUS if ents[i] & ents[j] else -ENTITY_PENALTY
    if res is not None and cats[i] in SUBJECT_CATS and res[i] and res[j]:
        jac = len(res[i] & res[j]) / len(res[i] | res[j])
        s += 0.08 if jac >= 0.5 else -RESIDUAL_PENALTY if jac < 0.25 else 0.0
    return s


def cluster(tickets: list[dict], threshold: float = THRESHOLD) -> list[list[int]]:
    """Average-linkage agglomerative clustering over the similarity above; O(n²) is fine for a queue of hundreds."""
    n = len(tickets)
    docs = [grams(tokens(t.get("title") or "")) * TITLE_WEIGHT + grams(tokens((t.get("description") or "")[:DESC_CHARS])) for t in tickets]
    vec, cats = vectorise(docs), [t.get("category") or category(t) for t in tickets]
    ents = [things(entities({"title": t.get("title") or ""})) for t in tickets]       # the title names the subject
    res = [residual(t, ents[i]) for i, t in enumerate(tickets)]
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            sim[i][j] = sim[j][i] = similarity(i, j, vec, cats, ents, res)
    clusters = [[i] for i in range(n)]
    link = {(i, j): sim[i][j] for i in range(n) for j in range(i + 1, n) if sim[i][j] >= threshold}
    while link:
        (a, b), best = max(link.items(), key=lambda kv: kv[1])
        if best < threshold:
            break
        ca, cb = clusters[a], clusters[b]
        merged = ca + cb
        clusters[a] = merged
        clusters[b] = []
        for k in range(n):
            link.pop((min(a, k), max(a, k)), None)
            link.pop((min(b, k), max(b, k)), None)
        for k in range(n):
            if k == a or not clusters[k]:
                continue
            s = sum(sim[x][y] for x in merged for y in clusters[k]) / (len(merged) * len(clusters[k]))
            if s >= threshold:
                link[(min(a, k), max(a, k))] = s
    return [sorted(c) for c in clusters if c]


# ------------------------------------------------------------------ summaries, priority, route

def _facts(t: dict) -> list[str]:
    d = t.get("description") or ""
    facts = []
    m = re.search(r"\bsince (\d{1,2} \w{3,9})\b", d)
    if m:
        facts.append(f"since {m.group(1)}")
    m = re.search(r"\b(\d+) (people|users)\b", d)
    if m:
        facts.append(f"{m.group(1)} people affected")
    m = re.search(r"(DataSource\.Error[^.]*|Credentials[^.]*expired|OLE DB[^.]*|Memory limit[^.]*|\(503\)[^.]*|Column '[^']+' not found[^.]*)", d)
    if m:
        facts.append("error: " + m.group(1).strip()[:90])
    m = re.search(r"\b(board pack|statutory return|month[- ]end|audit|GST return)\b", d, re.I)
    if m:
        facts.append("used for the " + m.group(1).lower())
    return facts


def summarise(t: dict, cat: str | None = None, ents: set[str] | None = None) -> str:
    """Two lines at most, plain English: what kind of problem, about what, and the facts that matter."""
    cat = cat or t.get("category") or category(t)
    ents = ents if ents is not None else entities(t)
    about = best_entity(ents) or (t.get("title") or "").strip()
    head = f"{CATEGORY_LABEL[cat]}: {about}"
    facts = _facts(t)
    return head + (" — " + "; ".join(facts[:3]) if facts else "") + "."


def summarise_group(members: list[dict], cat: str, about: str) -> str:
    people = {m.get("reporter") or m.get("reporter_email") for m in members} - {"", None}
    teams = sorted({m.get("team") for m in members if m.get("team")})
    facts: list[str] = []
    for m in members:
        for f in _facts(m):
            if f not in facts:
                facts.append(f)
    n = len(members)
    who = f"{n} ticket{'s' if n != 1 else ''} from {len(people)} {'person' if len(people) == 1 else 'people'}" + (f" in {', '.join(teams[:3])}" if teams else "")
    return f"{CATEGORY_LABEL[cat]} — {about}. {who}." + (" " + "; ".join(facts[:3]).capitalize() + "." if facts else "")


def priority(members: list[dict], cat: str, now: float | None = None) -> tuple[str, str]:
    """Business impact -> P1..P4 with the reason: SLA nearest, people affected, what the report feeds, the problem kind."""
    now = now or time.time()
    text = " ".join((m.get("title") or "") + " " + (m.get("description") or "") for m in members).lower()
    people = len({m.get("reporter_email") or m.get("reporter") for m in members} - {"", None})
    teams = len({m.get("team") for m in members if m.get("team")})
    dues = [m["due"] for m in members if m.get("due")]
    nearest_h = min((d - now) / 3600 for d in dues) if dues else None
    impact = bool(re.search(IMPACT_WORDS, text))
    score = {"wrong": 2.0, "refresh": 2.0, "missing": 2.0, "slow": 1.0, "other": 0.5, "new": 0.0, "access": 0.0}[cat]
    reasons: list[str] = []
    if impact:
        score += 1.5
        reasons.append("feeds a board, statutory, month-end or payroll output")
    if people >= 3 or teams >= 2:
        score += 1.0 + (0.5 if people >= 8 else 0)
        reasons.append(f"{people} {'person' if people == 1 else 'people'} across {teams} team{'s' if teams != 1 else ''}")
    if nearest_h is not None and 0 <= nearest_h <= NEAR_SLA_H:
        score += 1.0
        reasons.append("SLA breach within " + ("the hour" if nearest_h <= 1 else f"{math.ceil(nearest_h)} h"))
    elif nearest_h is not None and nearest_h < 0 and cat not in ("new", "access"):
        score += 0.5
        reasons.append("SLA already breached")
    if cat in ("new", "access") and re.search(r"\b(review on|deadline|by \d|joined .* on)", text):
        score += 0.5
    reasons.sort(key=lambda s: 0 if s.startswith("SLA breach within") else 1)          # the clock first
    reasons.append({"refresh": "the report is stale until it refreshes", "missing": "a day of data is missing", "wrong": "numbers used for decisions differ from the source",
                    "slow": "the report is slow but usable", "access": "a routine access request", "new": "a request for new content, no outage",
                    "other": "a report problem without an outage"}[cat])
    p = "P1" if score >= 4.5 else "P2" if score >= 3.0 else "P3" if score >= 1.5 else "P4"
    return p, f"{p} ({PRIORITY_LABEL[p]}): " + "; ".join(reasons[:3]) + "."


def route(members: list[dict], cat: str) -> tuple[str, str, str, str]:
    """('agent' | 'person', reason, target module id, target label)."""
    text = " ".join((m.get("title") or "") + " " + (m.get("description") or "") for m in members).lower()
    tid, tlabel = TARGET[cat]
    rule = AGENT_RULES.get(cat)
    if rule and re.search(rule[1], text):
        return "agent", "An agent can handle it: " + rule[0] + ".", tid, tlabel
    why = {"wrong": "a person must decide which definition is right before anything changes",
           "new": "a person shapes the request before a dashboard change is made",
           "slow": "a person confirms the change that made it slow",
           "refresh": "no known fix matches the error; a person diagnoses it",
           "missing": "the pipeline owner must confirm the backfill",
           "access": "the role does not exist yet; a person decides the access",
           "other": "no runbook matches; a person looks at it"}[cat]
    return "person", "Needs a person: " + why + ".", tid, tlabel


def triage(tickets: list[dict], now: float | None = None, threshold: float = THRESHOLD) -> list[dict]:
    """tickets -> groups, each with members (indexes into `tickets`), title, summary, category, priority + reason,
    route + reason, target, team, nearest SLA, people. Every ticket also gets `category` and `summary` set."""
    now = now or time.time()
    for t in tickets:
        t["category"] = category(t)
        t["summary"] = summarise(t, t["category"])
    groups = []
    for idx in cluster(tickets, threshold):
        members = [tickets[i] for i in idx]
        members_sorted = sorted(members, key=lambda m: m.get("created") or 0)
        cat = max({m["category"] for m in members}, key=lambda c: sum(m["category"] == c for m in members) - (0.5 if c == "other" else 0))
        common = set.intersection(*(entities(m) or {""} for m in members)) - {""}
        about = best_entity(common) or best_entity(entities(members_sorted[0])) or members_sorted[0]["title"]
        p, reason = priority(members, cat, now)
        r, rreason, tid, tlabel = route(members, cat)
        dues = [m["due"] for m in members if m.get("due")]
        teams = sorted({m.get("team") for m in members if m.get("team")})
        subj = subject(members, about) if cat in SUBJECT_CATS else ""
        about_full = f"{about} — {subj}" if subj and subj.lower() not in about.lower() else about
        groups.append({"members": idx, "oldest": members_sorted[0], "title": members_sorted[0]["title"] if len(members) == 1 else f"{about_full[:1].upper()}{about_full[1:]}: {CATEGORY_LABEL[cat].lower()}",
                       "about": about_full, "category": cat, "summary": summarise_group(members, cat, about_full), "priority": p, "reason": reason, "route": r, "route_reason": rreason,
                       "target": tid, "target_label": tlabel, "team": teams[0] if len(teams) == 1 else (", ".join(teams[:2]) + (" +" + str(len(teams) - 2) if len(teams) > 2 else "")) if teams else "",
                       "sla_due": min(dues) if dues else None, "near_sla": sum(1 for d in dues if 0 <= d - now <= NEAR_SLA_H * 3600),
                       "people": len({m.get("reporter_email") or m.get("reporter") for m in members} - {"", None}), "tickets": len(members)})
    order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    groups.sort(key=lambda g: (order[g["priority"]], -g["tickets"], g["sla_due"] or 9e12))
    return groups


# ------------------------------------------------------------------ quality against a labelled fixture

def quality(tickets: list[dict], groups: list[dict], label_prefix: str = "fx-g") -> dict | None:
    """Pairwise precision / recall of the grouping against the labels the mock lab plants (`fx-g<n>`); None when the
    tickets carry no labels (a real queue)."""
    truth: dict[str, list[str]] = {}
    for t in tickets:
        for l in t.get("labels") or []:
            if str(l).startswith(label_prefix):
                truth.setdefault(l, []).append(t["key"])
    if not truth:
        return None
    pred = {str(i): [tickets[k]["key"] for k in g["members"]] for i, g in enumerate(groups)}
    return pair_scores(pred, truth)


def pair_scores(predicted: dict[str, list[str]], truth: dict[str, list[str]]) -> dict:
    def pairs(groups):
        s = set()
        for members in groups.values():
            m = sorted(members)
            for i in range(len(m)):
                for j in range(i + 1, len(m)):
                    s.add((m[i], m[j]))
        return s
    keys = {k for ms in truth.values() for k in ms}
    pred = {g: [k for k in ms if k in keys] for g, ms in predicted.items()}
    tp, pp = pairs(truth), pairs(pred)
    hit = len(tp & pp)
    p = hit / len(pp) if pp else 1.0
    r = hit / len(tp) if tp else 1.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "tickets": len(keys),
            "groups_true": len(truth), "groups_predicted": sum(1 for g in pred.values() if g), "pairs_true": len(tp), "pairs_predicted": len(pp)}
