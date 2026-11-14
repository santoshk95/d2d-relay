"""Which Claude models can this login use? Builds config/models.json, the catalog the agent and the web app read.

Sends each candidate name one tiny request through Claude Code (one-line system prompt, no tools). Names the login
cannot use fail without cost; each usable one costs a fraction of a cent. Claude Code's cost for that request gives
the model's price per token relative to Sonnet (latest), assuming the usual price ratios between token types
(cache write 2x input, cache read 0.1x, output 5x); probes without cache reads are used for this.

Run inside the agent container (the result goes to stdout):
    docker compose exec agent python /opt/genbi/probe_models.py > config/models.json
    docker compose exec agent python /opt/genbi/probe_models.py --report      # raw results, one per name
"""
import json
import re
import subprocess
import sys
import tempfile
import time

ALIASES = ["fable", "opus", "sonnet", "haiku"]           # Claude Code aliases: always the newest version
CANDIDATES = [
    "claude-fable-5-1", "claude-fable-5",
    "claude-opus-5-5", "claude-opus-5-1", "claude-opus-5",
    "claude-sonnet-5-5", "claude-sonnet-5-1", "claude-sonnet-5",
    "claude-haiku-5-5", "claude-haiku-5-1", "claude-haiku-5",
    "claude-opus-4-6", "claude-sonnet-4-6",
    "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
    "claude-opus-4-1", "claude-opus-4-0", "claude-sonnet-4-0",
    "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022", "claude-3-haiku-20240307",
]
FAMILIES = {"fable": "Top-tier family; the highest cost.", "opus": "Large and highly capable.",
            "sonnet": "Balanced speed and quality.", "haiku": "Fastest and cheapest; best for small edits."}
DEFAULT = "claude-opus-5-5"            # item 47: the Relay Model's own model, the default


def probe(name: str, cwd: str) -> dict:
    cmd = ["claude", "-p", "--output-format", "json", "--model", name, "--max-turns", "1", "--tools", "",
           "--strict-mcp-config", "--system-prompt", "Reply with the single word OK.", "OK?"]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        r = json.loads(p.stdout)
    except (subprocess.TimeoutExpired, ValueError) as e:
        return {"name": name, "ok": False, "error": str(e)[:200]}
    usage = r.get("modelUsage") or {}
    if r.get("is_error") or not usage:
        return {"name": name, "ok": False, "error": str(r.get("result") or p.stderr)[:200]}
    model, u = max(usage.items(), key=lambda kv: kv[1].get("costUSD") or 0)
    return {"name": name, "ok": True, "model": model, "input": u.get("inputTokens") or 0,
            "output": u.get("outputTokens") or 0, "cache_read": u.get("cacheReadInputTokens") or 0,
            "cache_write": u.get("cacheCreationInputTokens") or 0, "cost_usd": u.get("costUSD") or 0}


def parse(model_id: str) -> tuple[str | None, str | None]:
    """claude-opus-4-5-20251101 -> ("opus", "4.5")"""
    m = re.match(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$", model_id or "")
    return (m.group(1), m.group(2) + (f".{m.group(3)}" if m.group(3) else "")) if m else (None, None)


def input_price(r: dict) -> float | None:
    weight = r["input"] + 2 * r["cache_write"] + 0.1 * r["cache_read"] + 5 * r["output"]
    return r["cost_usd"] / weight if weight and r["cost_usd"] else None


def catalog(results: list[dict]) -> dict:
    ok = [r for r in results if r["ok"]]
    prices = {}
    for r in sorted(ok, key=lambda r: r["cache_read"]):         # prefer probes without cache reads
        prices.setdefault(r["model"], input_price(r))
    base = prices.get(next((r["model"] for r in ok if r["name"] == DEFAULT), None))
    rel = lambda model: round(prices[model] / base, 2) if base and prices.get(model) else None
    entries, seen = [], set()
    for r in ok:                                                # always-latest aliases first
        if r["name"] in ALIASES:
            fam, ver = parse(r["model"])
            entries.append({"id": r["name"], "label": f"{r['name'].title()} (latest)", "model": r["model"],
                            "family": r["name"], "version": ver, "latest": True, "relative_cost": rel(r["model"]),
                            "note": FAMILIES.get(r["name"], "")})
    pinned = []
    for r in ok:                                                # pinned versions the login really serves
        fam, ver = parse(r["model"])
        if r["name"] in ALIASES or r["model"] != r["name"] or not fam or (fam, ver) in seen:
            continue                                            # redirected names and dated duplicates
        seen.add((fam, ver))
        pinned.append({"id": r["name"], "label": f"{fam.title()} {ver}", "model": r["model"], "family": fam,
                       "version": ver, "latest": False, "relative_cost": rel(r["model"]), "note": FAMILIES.get(fam, "")})
    order = list(FAMILIES)
    newest_first = lambda ver: tuple(-int(x) for x in (ver.split(".") + ["0"])[:2])     # 5.5, 5.1, 5, 4.6 ...
    pinned.sort(key=lambda e: (order.index(e["family"]) if e["family"] in order else 99, newest_first(e["version"])))
    return {"checked": time.strftime("%Y-%m-%d"), "default": DEFAULT,
            "about": "Models this Claude login can use (agent/probe_models.py). relative_cost: price per token vs "
                     "Sonnet (latest), from Claude Code's own price table.",
            "models": entries + pinned}


def main() -> None:
    args = sys.argv[1:]
    report = "--report" in args
    names = [a for a in args if not a.startswith("--")] or ALIASES + CANDIDATES
    if "--from" in args:                                        # rebuild the catalog from a saved --report
        results = json.load(open(args[args.index("--from") + 1], encoding="utf-8"))
    else:
        results = []
        with tempfile.TemporaryDirectory() as cwd:
            for name in names:
                r = probe(name, cwd)
                results.append(r)
                print(("OK  " if r["ok"] else "--  ") + name + (f"  -> {r['model']}" if r["ok"] else f"  {r['error'][:80]}"),
                      file=sys.stderr)
    print(json.dumps(results if report else catalog(results), indent=1))


if __name__ == "__main__":
    main()
