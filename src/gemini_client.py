"""
Thin wrapper around Google's free Gemini API (AI Studio key).

Why REST instead of an SDK: zero heavy dependencies, easy to read, and it
works the same locally and inside GitHub Actions.

Set the key via the GEMINI_API_KEY environment variable. If it is missing,
`available()` returns False and the rest of the pipeline falls back to simple
heuristics so the paper still gets produced.
"""

import json
import os
import time
import urllib.error
import urllib.request

# Flash is on the free tier (1,500 requests/day) and is plenty for a daily paper.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def generate_json(prompt: str, retries: int = 3):
    """Call Gemini and parse the reply as JSON.

    Returns the parsed object, or None on any failure (caller should fall back).
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }
    url = ENDPOINT.format(model=MODEL) + "?key=" + key
    data = json.dumps(body).encode("utf-8")

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except urllib.error.HTTPError as e:
            # 429 = rate limited; back off and retry.
            if e.code == 429 and attempt < retries - 1:
                time.sleep(20 * (attempt + 1))
                continue
            print(f"[gemini] HTTP {e.code}: {e.read()[:200]!r}")
            return None
        except Exception as e:  # noqa: BLE001
            print(f"[gemini] error: {type(e).__name__}: {e}")
            if attempt < retries - 1:
                time.sleep(5)
                continue
            return None
    return None
