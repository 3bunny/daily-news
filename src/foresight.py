"""
Weekly Foresight — dual-use technology deep-dive.

Looks back over the past week's military + business technology, then for the
most significant developments explains:
  - the ENABLING TECHNOLOGIES underneath them (chips, sensors, comms, etc.),
  - the PIONEERS (companies, labs, agencies) building them,
  - a COMMERCIAL-SPILLOVER forecast with a rough timeline,
  - an informational WATCHLIST of sectors/companies in the space
    (informational only — not financial advice).

Runs weekly. Uses free Gemini when available; otherwise emits a plain roundup.

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
MAX_CORPUS = 45


def load_config():
    with open(os.path.join(ROOT, "config", "sources.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:60]


def gather(config, days=7, mock_path=None):
    """Build a de-duplicated corpus of the week's focus-topic stories."""
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

    # 1) fresh scan with a 7-day lookback
    cfg = copy.deepcopy(config)
    cfg["lookback_hours"] = days * 24
    cfg["topics"] = [t for t in cfg["topics"] if t["key"] in FOCUS]
    scanned = scanner.collect(cfg)
    for key in FOCUS:
        for s in scanned.get(key, []):
            add(key, s.title, s.source, s.raw_summary)

    # 2) merge durable daily dumps from data/stories/
    cutoff = dt.datetime.now(KST) - timedelta(days=days)
    for fp in glob.glob(os.path.join(ROOT, "data", "stories", "*.json")):
        try:
            base = os.path.basename(fp)[:-5]
            if dt.datetime.strptime(base, "%Y-%m-%d").replace(tzinfo=KST) < cutoff:
                continue
            for it in json.load(open(fp, encoding="utf-8")):
                if it.get("topic") in FOCUS:
                    add(it["topic"], it.get("title"), it.get("source", ""),
                        it.get("summary", ""))
        except (ValueError, KeyError, json.JSONDecodeError):
            continue

    return corpus[:MAX_CORPUS]


def analyze(corpus):
    """Return the report dict via Gemini, or a fallback roundup."""
    if corpus and gemini_client.available():
        prompt = (
            "You are a technology-foresight analyst writing a WEEKLY briefing for a "
            "curious reader who is not a technical expert but is sharp and wants to "
            "anticipate where technology is heading. Theme: dual-use technology — how "
            "military/advanced tech becomes commercial (like GPS, the internet, GPUs).\n\n"
            "From the week's items below, pick the 3-4 MOST SIGNIFICANT developments "
            "or themes. For each, write a deep dive. Use a balanced tone: explain "
            "jargon briefly when first used, but keep momentum.\n\n"
            "Return JSON with this exact shape:\n"
            "{\n"
            '  "intro": "2-3 sentences framing the week",\n'
            '  "deep_dives": [\n'
            "    {\n"
            '      "title": "short headline for the development/theme",\n'
            '      "what_happened": "2-4 sentences on the development this week",\n'
            '      "enabling_tech": [{"name": "tech", "why": "plain-language why it is needed"}],\n'
            '      "pioneers": [{"name": "company/lab/agency", "role": "what they do here"}],\n'
            '      "spillover": "where/when this likely reaches commercial use; rough timeline",\n'
            '      "watchlist": [{"name": "sector or company", "note": "why it is positioned"}]\n'
            "    }\n"
            "  ],\n"
            '  "disclaimer": "one line noting the watchlist is informational, not financial advice"\n'
            "}\n\n"
            f"WEEK'S ITEMS:\n{corpus}"
        )
        r = gemini_client.generate_json(prompt)
        if isinstance(r, dict) and r.get("deep_dives"):
            r.setdefault("disclaimer",
                         "The watchlist is informational only and not financial advice.")
            return r

    # Fallback: simple roundup so the report still builds.
    return {
        "intro": ("Automated deep analysis was unavailable this week, so here is a "
                  "plain roundup of the week's notable military and business technology."),
        "deep_dives": [
            {"title": c["title"], "what_happened": c["text"], "enabling_tech": [],
             "pioneers": [{"name": c["source"], "role": "reporting outlet"}],
             "spillover": "", "watchlist": []}
            for c in corpus[:8]
        ] or [{"title": "No stories gathered this week", "what_happened":
               "No items were available from the sources.", "enabling_tech": [],
               "pioneers": [], "spillover": "", "watchlist": []}],
        "disclaimer": "The watchlist is informational only and not financial advice.",
    }


# ----------------------------------------------------------------- rendering ---
EXTRA_CSS = ""  # foresight styles now live in publisher.CSS


def _kv_list(items, kfield, vfield):
    if not items:
        return ""
    rows = "".join(
        f"<div class='kv'><b>{publisher._esc(str(i.get(kfield,'')))}</b> — "
        f"{publisher._esc(str(i.get(vfield,'')))}</div>" for i in items)
    return rows


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
    """Inner HTML (intro + deep dives + disclaimer) for embedding in the daily paper."""
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
    foot = ("<div class='foot'><a href='index.html'>Past Foresight reports →</a></div>")
    body = head + render_fragment(report) + foot
    html = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Foresight — {publisher._esc(week)}</title>{publisher.FONTS}"
            f"<style>{publisher.CSS}{EXTRA_CSS}</style></head>"
            f"<body><div class='wrap'>{body}</div></body></html>")
    return html


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
            f"<style>{publisher.CSS}{EXTRA_CSS}</style></head>"
            f"<body><div class='wrap'>{body}</div></body></html>")


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

    # Embeddable fragment + machine copy used by the daily paper.
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
    print(f"[foresight] Building weekly report {date.strftime('%G-W%V')} "
          f"(LLM={'on' if gemini_client.available() else 'off'})")
    config = load_config()
    corpus = gather(config, days=7, mock_path=args.mock)
    print(f"[foresight] corpus: {len(corpus)} stories")
    report = analyze(corpus)
    path = publish(report, date)
    print(f"[foresight] wrote {path} ({len(report.get('deep_dives', []))} deep dives)")


if __name__ == "__main__":
    main()
