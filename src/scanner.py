"""
Scanner: pull stories from the RSS feeds in config/sources.yaml.

Output is a dict: { topic_key: [Story, ...] }, newest first, de-duplicated,
limited to the configured lookback window. The summarizer and editor run later.
"""

import html
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

import feedparser
from dateutil import parser as dateparser

KST = timezone(timedelta(hours=9))

# Some feeds (e.g. SEC EDGAR) reject the default UA; identify ourselves politely.
USER_AGENT = "DailyDispatch/1.0 (personal news aggregator; eelcchrisyoo@gmail.com)"


@dataclass
class Story:
    topic: str
    title: str
    link: str
    source: str
    published: str               # ISO string (KST)
    raw_summary: str             # plain text from the feed
    summary: str = ""            # filled by summarizer
    score: float = 0.0           # filled by editor (0-10)
    wow: bool = False            # editor flag for standout items
    reason: str = ""             # editor's one-line justification
    detail: str = ""             # ~300-word "read more" explainer
    tag: str = ""                # short keyword for the Top Ten

    def to_dict(self):
        return asdict(self)


def _clean(text: str) -> str:
    """Strip HTML tags / entities from a feed summary."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _source_name(parsed, link: str) -> str:
    title = parsed.feed.get("title") if parsed and parsed.feed else None
    if title:
        return title.strip()
    m = re.search(r"https?://(?:www\.)?([^/]+)", link or "")
    return m.group(1) if m else "Unknown"


def _published(entry) -> datetime | None:
    for attr in ("published", "updated", "created"):
        val = entry.get(attr)
        if val:
            try:
                dt = dateparser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(KST)
            except (ValueError, TypeError):
                continue
    return None


def collect(config: dict, mock_path: str | None = None) -> dict:
    """Return {topic_key: [Story,...]}. If mock_path is given, load from JSON
    instead of the network (used for offline sample generation)."""
    if mock_path:
        return _collect_mock(mock_path)

    lookback = int(config.get("lookback_hours", 28))
    cutoff = datetime.now(KST) - timedelta(hours=lookback)
    out: dict[str, list[Story]] = {}

    topics = sorted(config["topics"], key=lambda t: t.get("priority", 99))
    auto_added = {a["key"]: a.get("feeds", []) for a in config.get("auto_added", []) if a.get("key")}

    for topic in topics:
        key = topic["key"]
        feeds = list(topic.get("feeds", [])) + auto_added.get(key, [])
        seen_titles: set[str] = set()
        stories: list[Story] = []

        for url in feeds:
            try:
                parsed = feedparser.parse(url, agent=USER_AGENT)
            except Exception as e:  # noqa: BLE001
                print(f"[scanner] {key}: failed {url}: {e}")
                continue
            src = _source_name(parsed, url)
            for entry in parsed.entries:
                pub = _published(entry)
                if pub and pub < cutoff:
                    continue
                title = _clean(entry.get("title", ""))
                if not title:
                    continue
                norm = re.sub(r"[^a-z0-9]", "", title.lower())[:60]
                if norm in seen_titles:
                    continue
                seen_titles.add(norm)
                stories.append(Story(
                    topic=key,
                    title=title,
                    link=entry.get("link", ""),
                    source=src,
                    published=(pub or datetime.now(KST)).isoformat(),
                    raw_summary=_clean(entry.get("summary", ""))[:1200],
                ))

        stories.sort(key=lambda s: s.published, reverse=True)
        out[key] = stories
        print(f"[scanner] {key}: {len(stories)} candidate stories")

    return out


def _collect_mock(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, list[Story]] = {}
    for key, items in raw.items():
        out[key] = [Story(topic=key, summary="", **it) for it in items]
    return out
