"""
The Daily Dispatch — orchestrator.

Pipeline:  scan -> summarize -> evaluate (editor) -> select -> grade
           -> curate sources -> publish HTML + archive.

Run:
    python src/main.py                 # live (needs network; GEMINI_API_KEY optional)
    python src/main.py --mock FILE     # offline sample from a JSON fixture
"""

import argparse
import datetime as dt
import json
import os
import sys
from datetime import timezone, timedelta

import yaml

sys.path.insert(0, os.path.dirname(__file__))
import scanner          # noqa: E402
import summarizer       # noqa: E402
import editor           # noqa: E402
import publisher        # noqa: E402
import gemini_client    # noqa: E402

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config() -> dict:
    with open(os.path.join(ROOT, "config", "sources.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_feed(url: str) -> bool:
    try:
        import feedparser
        return len(feedparser.parse(url).entries) > 0
    except Exception:  # noqa: BLE001
        return False


def apply_curation(suggestions: list, config: dict) -> list:
    """Validate suggested RSS feeds and append the working ones to sources.yaml
    under auto_added. Never removes curated feeds. Returns what was added."""
    added = []
    existing = set()
    for t in config["topics"]:
        existing.update(t.get("feeds", []))
    auto = {a["key"]: a for a in config.get("auto_added", [])}

    for s in suggestions:
        # suggestions of the form "section: name -> rss"
        if "->" not in s:
            continue
        section_name, rss = s.rsplit("->", 1)
        rss = rss.strip()
        if rss in existing or not rss.startswith("http"):
            continue
        # map the section title back to a topic key
        key = next((t["key"] for t in config["topics"]
                    if t["title"].lower() in section_name.lower()), None)
        if not key or not validate_feed(rss):
            continue
        auto.setdefault(key, {"key": key, "feeds": []})
        auto[key]["feeds"].append(rss)
        existing.add(rss)
        added.append(f"{key}: {rss}")

    if added:
        config["auto_added"] = list(auto.values())
        with open(os.path.join(ROOT, "config", "sources.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
    return added


def write_log(date: dt.datetime, grade: dict, suggestions: list, added: list):
    d = os.path.join(ROOT, "editor_log")
    os.makedirs(d, exist_ok=True)
    entry = {
        "date": date.strftime("%Y-%m-%d"),
        "grade": grade.get("grade"),
        "note": grade.get("note"),
        "counts": grade.get("counts"),
        "wow": grade.get("wow"),
        "source_suggestions": suggestions,
        "sources_added": added,
        "used_llm": gemini_client.available(),
    }
    with open(os.path.join(d, f"{date.strftime('%Y-%m-%d')}.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", help="Path to a JSON fixture (offline test).")
    args = ap.parse_args()

    config = load_config()
    date = dt.datetime.now(KST)
    print(f"[main] Building edition {date:%Y-%m-%d} (LLM={'on' if gemini_client.available() else 'off'})")

    scanned = scanner.collect(config, mock_path=args.mock)
    for topic in config["topics"]:
        stories = scanned.get(topic["key"], [])
        summarizer.summarize_topic(topic["title"], stories)
        editor.evaluate_topic(topic["title"], stories)

    selected = editor.select(scanned, config)
    grade = editor.grade_issue(selected, config)

    suggestions = editor.curate(selected, config)
    added = [] if args.mock else apply_curation(suggestions, config)

    paths = publisher.publish(selected, grade, config, ROOT, date=date)
    write_log(date, grade, suggestions, added)

    printed = sum(len(v) for v in selected.values())
    print(f"[main] Grade {grade.get('grade')} · {printed} stories printed · "
          f"{grade.get('wow',0)} standouts")
    print(f"[main] Wrote {paths['index']}")


if __name__ == "__main__":
    main()
