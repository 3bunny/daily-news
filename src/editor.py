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


_DEDUP_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "from", "at", "as", "by", "is", "are", "was", "were", "be", "been",
    "new", "says", "say", "amid", "after", "over", "into", "could", "will",
    "plan", "plans", "its", "his", "her", "their", "that", "this", "but",
    "how", "why", "what", "more", "than", "out", "set", "get", "via",
}


def _title_tokens(title):
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _DEDUP_STOP}


def _heuristic_dedupe(stories, threshold=0.34):
    """No-LLM fallback: cluster by title token overlap, keep best-scored."""
    kept = []
    for s in sorted(stories, key=lambda x: x.score, reverse=True):
        st = _title_tokens(s.title)
        dup = False
        for k in kept:
            kt = _title_tokens(k.title)
            if not st or not kt:
                continue
            inter = st & kt
            jac = len(inter) / len(st | kt)
            sig = sum(1 for w in inter if len(w) >= 4)
            if jac >= threshold or sig >= 3:
                dup = True
                break
        if not dup:
            kept.append(s)
    return kept


def dedupe_topic(topic_title, stories):
    """Collapse stories reporting the SAME underlying event, keeping the
    best-scored version. Uses Gemini when available, heuristic otherwise."""
    if len(stories) < 2:
        return stories
    if not gemini_client.available():
        return _heuristic_dedupe(stories)

    items = [{"id": i, "title": s.title, "source": s.source}
             for i, s in enumerate(stories)]
    prompt = (
        f"These are candidate '{topic_title}' news items. Group items that report "
        "the SAME underlying event or story (same companies/people and the same "
        "development), even if from different outlets or worded differently. Items "
        "about genuinely different events must each be in their own group.\n"
        "Return JSON: an array of arrays of ids; every id must appear exactly once.\n\n"
        f"ITEMS:\n{items}"
    )
    r = gemini_client.generate_json(prompt)
    if isinstance(r, list):
        groups, seen, ok = [], set(), True
        for g in r:
            if not isinstance(g, list):
                ok = False
                break
            ids = []
            for x in g:
                try:
                    i = int(x)
                except (ValueError, TypeError):
                    ok = False
                    break
                if i < 0 or i >= len(stories) or i in seen:
                    ok = False
                    break
                seen.add(i)
                ids.append(i)
            if not ok:
                break
            if ids:
                groups.append(ids)
        if ok and seen == set(range(len(stories))):
            kept = []
            for ids in groups:
                best = max((stories[i] for i in ids),
                           key=lambda s: (s.score, len(s.summary or "")))
                kept.append(best)
            return kept
    return _heuristic_dedupe(stories)


def select(scanned, config):
    """Filter by score, collapse duplicate stories, cap per section."""
    min_score = float(config.get("min_score", 6))
    cap = int(config.get("max_stories_per_section", 5))
    out = {}
    for topic in sorted(config["topics"], key=lambda t: t.get("priority", 99)):
        key = topic["key"]
        good = [s for s in scanned.get(key, []) if s.score >= min_score]
        good = dedupe_topic(topic["title"], good)
        good.sort(key=lambda s: (s.wow, s.score), reverse=True)
        out[key] = good[:cap]
    return out
