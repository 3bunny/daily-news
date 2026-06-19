"""
Summarizer: turns each raw feed item into a tight, standard-depth paragraph.

Uses free Gemini Flash when a key is present; otherwise falls back to a clean
trim of the feed's own summary so the paper still builds.
"""

import textwrap

import gemini_client


def _fallback(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "Summary unavailable."
    # First ~2 sentences, capped, as a graceful no-LLM fallback.
    cut = textwrap.shorten(raw, width=320, placeholder=" …")
    return cut


def summarize_topic(topic_title: str, stories: list) -> None:
    """Fill story.summary for every story in-place (one batched LLM call)."""
    if not stories:
        return

    if not gemini_client.available():
        for s in stories:
            s.summary = _fallback(s.raw_summary)
        return

    items = [
        {"id": i, "title": s.title, "source": s.source, "text": s.raw_summary}
        for i, s in enumerate(stories)
    ]
    prompt = (
        f"You are a news editor writing the '{topic_title}' section of a daily "
        "world-news briefing for a smart general reader in Korea.\n"
        "For EACH item below, write one clear, factual paragraph (2-4 sentences) "
        "that explains what happened and why it matters. No hype, no marketing "
        "language, no first person. If the source text is thin, summarise only "
        "what is actually stated.\n\n"
        "Return JSON: an array of objects {\"id\": int, \"summary\": str}.\n\n"
        f"ITEMS:\n{items}"
    )
    result = gemini_client.generate_json(prompt)
    by_id = {}
    if isinstance(result, list):
        for r in result:
            try:
                by_id[int(r["id"])] = str(r["summary"]).strip()
            except (KeyError, ValueError, TypeError):
                continue

    for i, s in enumerate(stories):
        s.summary = by_id.get(i) or _fallback(s.raw_summary)
