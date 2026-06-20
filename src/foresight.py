"""
Weekly Foresight — dual-use technology deep-dive.

Looks back over the past week's military + business technology, then for the
most significant developments explains the enabling technologies, the pioneers,
a commercial-spillover forecast, and an informational watchlist.

Strategy: TWO-STEP Gemini calls (pick themes, then one focused call per theme)
so a single failure or truncation can't blank the whole report. Falls back to a
plain roundup when no key / all calls fail. Diagnostics are saved into the report.

    python src/foresight.py                 # live (network needed)
    python src/foresight.py --mock FILE     # offline render from a JSON fixture
"""

import argparse
import copy
import datetime as dt
import glob
import json
import os
import re
import sys
from datetime import timezone, timedelta

import yaml

sys.path.insert(0, os.path.dirname(__file__))
import scanner          # noqa: E402
import gemini_client    # noqa: E402
import publisher        # noqa: E402

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOCUS = ["military", "business"]
MAX_CORPUS = 40


def load_config():
    with open(os.path.join(ROOT, "config", "sources.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:60]


def gather(config, days=7, mock_path=None):
    """De-duplicated corpus of the week's focus-topic stories."""
    corpus, seen = [], set()

    def add(topic, title, source, text):
        n = _norm(title)
        if not title or n in seen:
            return
        seen.add(n)
        corpus.append({"topic": topic, "title": title, "source": source,
                       "text": (text or "")[:700]})

    if mock_path:
        raw = json.load(open(mock_path, encoding="utf-8"))
        for key in FOCUS:
            for it in raw.get(key, []):
                add(key, it["title"], it.get("source", ""), it.get("raw_summary", ""))
        return corpus

    cfg = copy.deepcopy(config)
    cfg["lookback_hours"] = days * 24
    cfg["topics"] = [t for t in cfg["topics"] if t["key"] in FOCUS]
    scanned = scanner.collect(cfg)
    for key in FOCUS:
        for s in scanned.get(key, []):
            add(key, s.title, s.source, s.raw_summary)

    cutoff = dt.datetime.now(KST) - timedelta(days=days)
    for fp in glob.glob(os.path.join(ROOT, "data", "stories", "*.json")):
        try:
            base = os.path.basename(fp)[:-5]
            if dt.datetime.strptime(base, "%Y-%m-%d").replace(tzinfo=KST) < cutoff:
                continue
            for it in json.load(open(fp, encoding="utf-8")):
                if it.get("topic") in FOCUS:
                    add(it["topic"], it.get("title"), it.get("source", ""), it.get("summary", ""))
        except (ValueError, KeyError, json.JSONDecodeError):
            continue

    return corpus[:MAX_CORPUS]


def _fallback(corpus, reason):
    return {
        "intro": ("A plain roundup of the week's notable military and business "
                  "technology (full analysis was unavailable this run)."),
        "deep_dives": [
            {"title": c["title"], "what_happened": c["text"], "enabling_tech": [],
             "pioneers": [{"name": c["source"], "role": "reporting outlet"}],
             "spillover": "", "watchlist": []}
            for c in corpus[:8]
        ] or [{"title": "No stories gathered this week", "what_happened":
               "No items were available from the sources.", "enabling_tech": [],
               "pioneers": [], "spillover": "", "watchlist": []}],
        "disclaimer": "The watchlist is informational only and not financial advice.",
        "_fallback_reason": reason,
    }


def analyze(corpus):
    """Return (report, diagnostics)."""
    diag = {"key_present": gemini_client.available(), "corpus": len(corpus), "steps": []}
    if not corpus or not gemini_client.available():
        diag["steps"].append("no key or empty corpus -> fallback")
        return _fallback(corpus, "no key or empty corpus"), diag

    # Step 1 — pick the 3-4 most significant tech themes.
    idx_items = [{"id": i, "topic": c["topic"], "title": c["title"]}
                 for i, c in enumerate(corpus)]
    sel_prompt = (
        "From these news items of the past week, pick the 3-4 most significant items "
        "about ACTUAL useful technologies being built, invented, or fielded — real "
        "advances, inventions, devices, or capabilities (e.g. new chips, sensors, "
        "batteries, materials, robotics, AI systems, energy, comms, space). Favour "
        "things with strong future or everyday/commercial potential. IGNORE pure "
        "politics, troop movements, budgets, contracts, and battle/strike news that "
        "has no real technology to explain.\n"
        'Return JSON: {"intro": "2-3 sentence framing of the week", '
        '"themes": [{"title": str, "ids": [int, ...]}]}\n\n'
        f"ITEMS:\n{idx_items}"
    )
    sel = gemini_client.generate_json(sel_prompt, max_output_tokens=2048)
    diag["steps"].append({"select": "ok" if sel else gemini_client.STATUS["last_error"]})
    if not (isinstance(sel, dict) and isinstance(sel.get("themes"), list) and sel["themes"]):
        return _fallback(corpus, "theme selection failed"), diag

    intro = str(sel.get("intro", "")).strip()
    dives = []
    for th in sel["themes"][:4]:
        ids = [i for i in th.get("ids", []) if isinstance(i, int) and 0 <= i < len(corpus)]
        ctx = [{"title": corpus[i]["title"], "source": corpus[i]["source"],
                "text": corpus[i]["text"]} for i in ids] or [{"title": th.get("title", "")}]
        dive_prompt = (
            "Write a deep dive on this technology development for a smart non-expert. "
            "Balanced tone: briefly explain jargon when first used. Theme: dual-use "
            "technology — how military/advanced tech becomes commercial (like GPS, the "
            "internet, GPUs). Emphasise what the technology is actually USEFUL for and its "
            "realistic future/everyday potential.\n"
            'Return JSON: {"title": str, "what_happened": str (2-4 sentences), '
            '"enabling_tech": [{"name": str, "why": str}], '
            '"pioneers": [{"name": str, "role": str}], '
            '"spillover": str (where/when it likely reaches commercial use; rough timeline), '
            '"watchlist": [{"name": str, "note": str}]}\n\n'
            f"THEME: {th.get('title','')}\nSOURCES:\n{ctx}"
        )
        dv = gemini_client.generate_json(dive_prompt, max_output_tokens=2048)
        if isinstance(dv, dict) and dv.get("what_happened"):
            dv.setdefault("title", th.get("title", ""))
            dives.append(dv)
        else:
            diag["steps"].append({"dive_failed": th.get("title", ""),
                                  "err": gemini_client.STATUS["last_error"]})

    if not dives:
        return _fallback(corpus, "all deep-dive calls failed"), diag

    report = {"intro": intro, "deep_dives": dives,
              "disclaimer": "The watchlist is informational only and not financial advice."}
    return report, diag


# ----------------------------------------------------------------- rendering ---
EXTRA_CSS = ""  # foresight styles now live in publisher.CSS


def _kv_list(items, kfield, vfield):
    if not items:
        return ""
    return "".join(
        f"<div class='kv'><b>{publisher._esc(str(i.get(kfield,'')))}</b> — "
        f"{publisher._esc(str(i.get(vfield,'')))}</div>" for i in items)


def _dive_html(d):
    parts = [f"<div class='dive'><h2>{publisher._esc(d.get('title',''))}</h2>"]
    if d.get("what_happened"):
        parts.append(f"<p class='happened'>{publisher._esc(d['what_happened'])}</p>")
    if d.get("enabling_tech"):
        parts.append("<div class='block'><div class='h'>Enabling technologies</div>"
                     + _kv_list(d["enabling_tech"], "name", "why") + "</div>")
    if d.get("pioneers"):
        parts.append("<div class='block'><div class='h'>Pioneers &amp; players</div>"
                     + _kv_list(d["pioneers"], "name", "role") + "</div>")
    if d.get("spillover"):
        parts.append("<div class='block'><div class='h'>Commercial spillover forecast</div>"
                     f"<div class='spill'>{publisher._esc(d['spillover'])}</div></div>")
    if d.get("watchlist"):
        items = "".join(
            f"<li><b>{publisher._esc(str(w.get('name','')))}</b> — "
            f"{publisher._esc(str(w.get('note','')))}</li>" for w in d["watchlist"])
        parts.append("<div class='block'><div class='h'>Watchlist (informational)</div>"
                     f"<ul class='watch'>{items}</ul></div>")
    parts.append("</div>")
    return "".join(parts)


def render_fragment(report):
    """Inner HTML (intro + dives + disclaimer) for embedding in the daily paper."""
    intro = f"<p class='fs-intro'>{publisher._esc(report.get('intro',''))}</p>"
    dives = "".join(_dive_html(d) for d in report.get("deep_dives", []))
    disc = f"<div class='disclaimer'>{publisher._esc(report.get('disclaimer',''))}</div>"
    return intro + dives + disc


def render(report, date):
    week = date.strftime("Week of %B %d, %Y")
    head = (f"<header class='masthead'><h1>FORESIGHT</h1>"
            f"<div class='tagline'>Weekly dual-use technology briefing — "
            f"what the military builds today, the world uses tomorrow</div>"
            f"<div class='dateline'><span>Seoul · {week}</span>"
            f"<span><a href='../index.html'>← Daily paper</a></span></div></header>")
    foot = "<div class='foot'><a href='index.html'>Past Foresight reports →</a></div>"
    body = head + render_fragment(report) + foot
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Foresight — {publisher._esc(week)}</title>{publisher.FONTS}"
            f"<style>{publisher.CSS}</style></head>"
            f"<body><div class='wrap'>{body}</div>{publisher.BIONIC_JS}</body></html>")


def render_index(manifest):
    head = ("<header class='masthead'><h1>Foresight Archive</h1>"
            "<div class='tagline'>Every weekly dual-use technology briefing</div></header>")
    items = "".join(
        f"<li><a href='{publisher._esc(m['file'])}'>{publisher._esc(m['week'])}</a></li>"
        for m in sorted(manifest, key=lambda m: m["id"], reverse=True))
    body = (head + f"<ul class='archive-list'>{items or '<li>No reports yet.</li>'}</ul>"
            "<div class='foot'><a href='../index.html'>← Daily paper</a></div>")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Foresight — Archive</title>{publisher.FONTS}"
            f"<style>{publisher.CSS}</style></head>"
            f"<body><div class='wrap'>{body}</div>{publisher.BIONIC_JS}</body></html>")


def publish(report, date):
    out = os.path.join(ROOT, "docs", "foresight")
    os.makedirs(out, exist_ok=True)
    wid = date.strftime("%G-W%V")
    fname = f"{wid}.html"
    with open(os.path.join(out, fname), "w", encoding="utf-8") as f:
        f.write(render(report, date))

    man_path = os.path.join(out, "manifest.json")
    manifest = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else []
    manifest = [m for m in manifest if m["id"] != wid]
    manifest.append({"id": wid, "file": fname, "week": date.strftime("Week of %B %d, %Y")})
    json.dump(manifest, open(man_path, "w", encoding="utf-8"), indent=2)

    with open(os.path.join(out, "latest_fragment.html"), "w", encoding="utf-8") as f:
        f.write(render_fragment(report))
    with open(os.path.join(out, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(manifest))
    return os.path.join(out, fname)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", help="JSON fixture for offline render.")
    args = ap.parse_args()

    date = dt.datetime.now(KST)
    print(f"[foresight] Building {date.strftime('%G-W%V')} "
          f"(LLM={'on' if gemini_client.available() else 'off'})")
    print(f"[foresight] Gemini health: {gemini_client.ping()}")

    config = load_config()
    corpus = gather(config, days=7, mock_path=args.mock)
    print(f"[foresight] corpus: {len(corpus)} stories")
    report, diag = analyze(corpus)
    report["_diagnostics"] = diag
    print(f"[foresight] diagnostics: {diag}")
    path = publish(report, date)
    print(f"[foresight] wrote {path} ({len(report.get('deep_dives', []))} deep dives)")


if __name__ == "__main__":
    main()
