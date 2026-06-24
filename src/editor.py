"""
Editor agent: the quality brain of the paper.

  1. Score every candidate 0-10 on novelty + "wow", flag standouts.
  2. Summarize each story (combined into the same call to save API quota).
  3. De-duplicate stories that report the same event (keep the best).
  4. Drop filler below threshold, cap per-section counts.
  5. Grade the issue and curate sources for thin sections.

To respect the free Gemini tier, the per-story work (summarize + score + dedupe)
is done in ONE call per section via process_topic(). Falls back to transparent
heuristics when no key is present or a call fails.
"""

import re

import gemini_client

_WOW = re.compile(
    r"\b(first|breakthrough|record|unveil|launch|reveal|new|prototype|"
    r"world'?s|fastest|largest|hypersonic|autonomous|quantum|stealth|"
    r"milestone|debut|never)\b",
    re.I,
)


def letter_grade(score):
    """Map a 0-10 story score to a letter grade for the Top Ten chips."""
    s = float(score or 0)
    if s >= 9.5: return "A+"
    if s >= 9:   return "A"
    if s >= 8.5: return "A-"
    if s >= 8:   return "B+"
    if s >= 7:   return "B"
    if s >= 6:   return "B-"
    return "C"


def _heuristic_score(story):
    text = f"{story.title} {story.raw_summary}"
    hits = len(set(m.group(0).lower() for m in _WOW.finditer(text)))
    score = min(10.0, 5.0 + 1.3 * hits)
    return score, score >= 8.0, f"{hits} novelty signal(s) in headline/summary."


# ----------------------------------------------------------------- de-dupe ----
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


def _apply_groups(stories, groups):
    """Keep the best-scored story per duplicate group. Returns deduped list, or
    None if the grouping is invalid (caller falls back to heuristic)."""
    if not isinstance(groups, list):
        return None
    seen, out = set(), []
    for g in groups:
        if not isinstance(g, list):
            return None
        ids = []
        for x in g:
            try:
                i = int(x)
            except (ValueError, TypeError):
                return None
            if i < 0 or i >= len(stories) or i in seen:
                return None
            seen.add(i)
            ids.append(i)
        if ids:
            best = max((stories[i] for i in ids),
                       key=lambda s: (s.score, len(s.summary or "")))
            out.append(best)
    if seen != set(range(len(stories))):
        return None
    return out


# ------------------------------------------------- combined per-section call --
def process_topic(topic_title, stories):
    """ONE Gemini call per section: summarize + score + flag + de-dupe.
    Returns a de-duplicated, scored, summarized list (not yet capped)."""
    import summarizer
    if not stories:
        return []

    if not gemini_client.available():
        for s in stories:
            s.summary = summarizer._fallback(s.raw_summary)
            s.score, s.wow, s.reason = _heuristic_score(s)
        return _heuristic_dedupe(stories)

    items = [{"id": i, "title": s.title, "source": s.source, "text": s.raw_summary}
             for i, s in enumerate(stories)]
    prompt = (
        f"You are the editor of the '{topic_title}' section of a daily world-news "
        "briefing for a smart general reader in Korea. For the items below do ALL of:\n"
        "1) Write a clear factual summary (2-4 sentences) of each (no hype, no first person).\n"
        "2) Score each 0-10 for genuinely NEW and impressive developments (real "
        "advances, inventions, launches, records). 9-10 remarkable/high-wow; 6-8 "
        "solid; 0-5 routine/opinion/not news. Set wow true only for 9-10 items.\n"
        "3) Group items that report the SAME underlying event (even across outlets).\n\n"
        'Return JSON: {"items": [{"id": int, "summary": str, "score": number, '
        '"wow": bool, "reason": str, "tag": str (1-3 word topic keyword, e.g. '
        '"AI chips", "funding", "drones", "biotech")}], "groups": [[int, ...]]}. '
        "Every id must appear exactly once across the groups.\n\n"
        f"ITEMS:\n{items}"
    )
    r = gemini_client.generate_json(prompt)
    if isinstance(r, dict) and isinstance(r.get("items"), list):
        by = {}
        for it in r["items"]:
            try:
                by[int(it["id"])] = it
            except (KeyError, ValueError, TypeError):
                continue
        for i, s in enumerate(stories):
            it = by.get(i)
            if it:
                s.summary = str(it.get("summary", "")).strip() or summarizer._fallback(s.raw_summary)
                try:
                    s.score = float(it.get("score", 0))
                except (ValueError, TypeError):
                    s.score = 0.0
                s.wow = bool(it.get("wow", False))
                s.reason = str(it.get("reason", "")).strip()
                s.tag = str(it.get("tag", "")).strip()
            else:
                s.summary = summarizer._fallback(s.raw_summary)
                s.score, s.wow, s.reason = _heuristic_score(s)
        deduped = _apply_groups(stories, r.get("groups"))
        return deduped if deduped is not None else _heuristic_dedupe(stories)

    for s in stories:
        s.summary = summarizer._fallback(s.raw_summary)
        s.score, s.wow, s.reason = _heuristic_score(s)
    return _heuristic_dedupe(stories)


# ------------------------------------------------------------- issue assembly -
def select(scanned, config):
    """Filter by score and cap per section (dedup already done upstream)."""
    min_score = float(config.get("min_score", 6))
    cap = int(config.get("max_stories_per_section", 5))
    out = {}
    for topic in sorted(config["topics"], key=lambda t: t.get("priority", 99)):
        key = topic["key"]
        good = [s for s in scanned.get(key, []) if s.score >= min_score]
        good.sort(key=lambda s: (s.wow, s.score), reverse=True)
        out[key] = good[:cap]
    return out


def curate(selected, config):
    """Suggest better/more outlets for thin sections (logged; validated in main)."""
    thin = [t["title"] for t in config["topics"]
            if len(selected.get(t["key"], [])) < 2]
    if not thin or not gemini_client.available():
        return [f"Thin section: {t}" for t in thin]
    prompt = (
        "These sections of a daily world-news briefing had few good stories today: "
        f"{thin}. Suggest up to 3 high-quality reputable RSS feed URLs per thin "
        "section that would improve coverage of NEW developments. Only well-known "
        "outlets with real public RSS feeds.\n"
        'Return JSON: array of {"section": str, "name": str, "rss": str}.'
    )
    result = gemini_client.generate_json(prompt)
    out = []
    if isinstance(result, list):
        for r in result:
            out.append(f"{r.get('section')}: {r.get('name')} -> {r.get('rss')}")
    return out or [f"Thin section: {t}" for t in thin]


def grade_issue(selected, config):
    """Return {'grade','note','counts','wow'} summarising the day's paper."""
    counts = {k: len(v) for k, v in selected.items()}
    total = sum(counts.values())
    wow = sum(1 for v in selected.values() for s in v if s.wow)

    if gemini_client.available():
        digest = {k: [{"title": s.title, "score": s.score} for s in v]
                  for k, v in selected.items()}
        prompt = (
            "You are the editor-in-chief grading today's edition of a world-news "
            "briefing (military, business, crypto, economics). Consider how much "
            "genuinely new and notable material it contains. Give a letter grade "
            "(A+ to D) and a 1-2 sentence editor's note for the reader.\n"
            'Return JSON: {"grade": str, "note": str}.\n\n'
            f"TODAY: {digest}"
        )
        r = gemini_client.generate_json(prompt)
        if isinstance(r, dict) and r.get("grade"):
            r.setdefault("note", "")
            r["counts"] = counts
            r["wow"] = wow
            return r

    if total == 0:
        grade, note = "—", "A quiet news day — nothing met the bar for print."
    elif total >= 12:
        grade, note = "A", f"A strong edition with {wow} standout item(s)."
    elif total >= 7:
        grade, note = "B", f"A solid edition with {wow} standout item(s)."
    else:
        grade, note = "C", "A light news day; only the strongest stories ran."
    return {"grade": grade, "note": note, "counts": counts, "wow": wow}


def expand_selected(selected):
    """Generate a concise (<=300 word) 'read more' explainer for each PRINTED
    story, one batched call per section. Without a key, detail stays empty and
    the publisher falls back to the feed's own text."""
    if not gemini_client.available():
        return
    for key, stories in selected.items():
        if not stories:
            continue
        items = [{"id": i, "title": s.title, "source": s.source, "text": s.raw_summary}
                 for i, s in enumerate(stories)]
        prompt = (
            "For EACH news item below, write a concise deeper explainer of at most "
            "300 words for a curious general reader: what happened, why it matters, "
            "and the useful context or background. Factual, clear, no hype, no first "
            "person.\n"
            'Return JSON: array of {"id": int, "detail": str}.\n\n'
            f"ITEMS:\n{items}"
        )
        r = gemini_client.generate_json(prompt)
        if isinstance(r, list):
            by = {}
            for it in r:
                try:
                    by[int(it["id"])] = str(it.get("detail", "")).strip()
                except (KeyError, ValueError, TypeError):
                    continue
            for i, s in enumerate(stories):
                if by.get(i):
                    s.detail = by[i]
