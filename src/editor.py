"""
Editor agent: the quality brain of the paper.

Responsibilities
  1. Score every candidate story 0-10 on novelty + "wow factor", flag standouts.
  2. Drop filler below the configured threshold, cap per-section counts.
     => A weak news day yields a shorter (or empty) section, never padding.
  3. Grade the whole issue and write a short editor's note.
  4. Propose new/better outlets for thin sections (logged; validated before any
     are appended to sources.yaml, and curated feeds are never removed).

Falls back to transparent heuristics when no Gemini key is present.
"""

import datetime as _dt
import re

import gemini_client

# Words that tend to mark genuinely new / impressive developments.
_WOW = re.compile(
    r"\b(first|breakthrough|record|unveil|launch|reveal|new|prototype|"
    r"world'?s|fastest|largest|hypersonic|autonomous|quantum|stealth|"
    r"milestone|debut|never)\b",
    re.I,
)


def _heuristic_score(story) -> tuple[float, bool, str]:
    text = f"{story.title} {story.raw_summary}"
    hits = len(set(m.group(0).lower() for m in _WOW.finditer(text)))
    score = min(10.0, 5.0 + 1.3 * hits)
    return score, score >= 8.0, f"{hits} novelty signal(s) in headline/summary."


def evaluate_topic(topic_title: str, stories: list) -> None:
    """Fill score / wow / reason for each story in-place."""
    if not stories:
        return

    if not gemini_client.available():
        for s in stories:
            s.score, s.wow, s.reason = _heuristic_score(s)
        return

    items = [
        {"id": i, "title": s.title, "source": s.source, "text": s.raw_summary}
        for i, s in enumerate(stories)
    ]
    prompt = (
        f"You are the editor of a daily briefing, judging the '{topic_title}' "
        "section. Rate each item for a reader who wants genuinely NEW and "
        "impressive developments — real advances, inventions, launches, records "
        "— not routine commentary, opinion, or recycled news.\n\n"
        "Score 0-10 where:\n"
        "  9-10 = remarkable, clearly new, high 'wow'.\n"
        "  6-8  = solid, worth reading.\n"
        "  0-5  = routine, opinion, vague, or not really news. \n"
        "Set wow=true only for the standout 9-10 items.\n\n"
        "Return JSON: array of {\"id\": int, \"score\": number, \"wow\": bool, "
        "\"reason\": str(<=12 words)}.\n\n"
        f"ITEMS:\n{items}"
    )
    result = gemini_client.generate_json(prompt)
    by_id = {}
    if isinstance(result, list):
        for r in result:
            try:
                by_id[int(r["id"])] = r
            except (KeyError, ValueError, TypeError):
                continue

    for i, s in enumerate(stories):
        r = by_id.get(i)
        if r:
            try:
                s.score = float(r.get("score", 0))
                s.wow = bool(r.get("wow", False))
                s.reason = str(r.get("reason", "")).strip()
                continue
            except (ValueError, TypeError):
                pass
        s.score, s.wow, s.reason = _heuristic_score(s)


def curate(selected: dict, config: dict) -> list[str]:
    """Suggest better/more outlets for thin sections. Returns a list of
    human-readable suggestions for the editor log. (Validation + appending to
    sources.yaml happens in main, conservatively.)"""
    thin = [t["title"] for t in config["topics"]
            if len(selected.get(t["key"], [])) < 2]
    if not thin or not gemini_client.available():
        return [f"Thin section: {t}" for t in thin]

    prompt = (
        "These sections of a daily world-news briefing had few good stories "
        f"today: {thin}. Suggest up to 3 high-quality, reputable RSS feed URLs "
        "per thin section that would improve coverage of NEW developments. "
        "Only well-known outlets with real public RSS feeds.\n"
        "Return JSON: array of {\"section\": str, \"name\": str, \"rss\": str}."
    )
    result = gemini_client.generate_json(prompt)
    out = []
    if isinstance(result, list):
        for r in result:
            out.append(f"{r.get('section')}: {r.get('name')} -> {r.get('rss')}")
    return out or [f"Thin section: {t}" for t in thin]


def grade_issue(selected: dict, config: dict) -> dict:
    """Return {'grade': 'A-', 'note': '...'} summarising the day's paper."""
    counts = {k: len(v) for k, v in selected.items()}
    total = sum(counts.values())
    wow = sum(1 for v in selected.values() for s in v if s.wow)

    if gemini_client.available():
        digest = {
            k: [{"title": s.title, "score": s.score} for s in v]
            for k, v in selected.items()
        }
        prompt = (
            "You are the editor-in-chief grading today's edition of a world-news "
            "briefing (military, business, crypto, economics). Consider how much "
            "genuinely new and notable material it contains. Give a letter grade "
            "(A+ to D) and a 1-2 sentence editor's note for the reader.\n"
            "Return JSON: {\"grade\": str, \"note\": str}.\n\n"
            f"TODAY: {digest}"
        )
        r = gemini_client.generate_json(prompt)
        if isinstance(r, dict) and r.get("grade"):
            r.setdefault("note", "")
            r["counts"] = counts
            r["wow"] = wow
            return r

    # Heuristic grade.
    if total == 0:
        grade, note = "—", "A quiet news day — nothing met the bar for print."
    elif total >= 12:
        grade, note = "A", f"A strong edition with {wow} standout item(s)."
    elif total >= 7:
        grade, note = "B", f"A solid edition with {wow} standout item(s)."
    else:
        grade, note = "C", "A light news day; only the strongest stories ran."
    return {"grade": grade, "note": note, "counts": counts, "wow": wow}


def select(scanned: dict, config: dict) -> dict:
    """Apply thresholds + per-section caps. Returns {topic_key: [Story,...]}."""
    min_score = float(config.get("min_score", 6))
    cap = int(config.get("max_stories_per_section", 5))
    out = {}
    for topic in sorted(config["topics"], key=lambda t: t.get("priority", 99)):
        key = topic["key"]
        good = [s for s in scanned.get(key, []) if s.score >= min_score]
        good.sort(key=lambda s: (s.wow, s.score), reverse=True)
        out[key] = good[:cap]
    return out
