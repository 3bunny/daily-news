"""
Thin wrapper around Google's free Gemini API (AI Studio key).

Set the key via the GEMINI_API_KEY environment variable. If it is missing,
`available()` returns False and the pipeline falls back to simple heuristics.
"""

import json
import os
import time
import urllib.error
import urllib.request

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


# Health tracking so logs can prove the key actually worked.
STATUS = {"ok": 0, "fail": 0, "last_error": None}

# Pace calls so we stay under the free-tier per-minute limit (~15 RPM).
MIN_INTERVAL = float(os.environ.get("GEMINI_MIN_INTERVAL", "4.5"))
_LAST_CALL = [0.0]


def _pace():
    gap = time.time() - _LAST_CALL[0]
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _LAST_CALL[0] = time.time()


def ping() -> dict:
    """Make one minimal call to confirm the key is valid."""
    if not available():
        return {"key_present": False, "working": False, "detail": "No GEMINI_API_KEY set."}
    r = generate_json('Return JSON {"ok": true}. Nothing else.')
    if isinstance(r, dict) and r.get("ok") is True:
        return {"key_present": True, "working": True, "detail": "Gemini responded correctly."}
    return {"key_present": True, "working": False,
            "detail": STATUS["last_error"] or "No valid response from Gemini."}


def generate_json(prompt: str, retries: int = 3, max_output_tokens: int = 8192):
    """Call Gemini and parse the reply as JSON. Returns parsed object or None.

    Captures a descriptive last_error (HTTP code, safety block, truncation, or
    JSON parse failure) so callers/logs can see exactly what went wrong.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
            "maxOutputTokens": max_output_tokens,
        },
    }
    url = ENDPOINT.format(model=MODEL) + "?key=" + key
    data = json.dumps(body).encode("utf-8")

    for attempt in range(retries):
        try:
            _pace()
            req = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            cands = payload.get("candidates")
            if not cands:
                raise RuntimeError(f"no candidates; promptFeedback={payload.get('promptFeedback')}")
            c0 = cands[0]
            parts = (c0.get("content") or {}).get("parts")
            if not parts:
                raise RuntimeError(f"empty content; finishReason={c0.get('finishReason')}")
            text = parts[0].get("text", "")
            try:
                result = json.loads(text)
            except json.JSONDecodeError as je:
                raise RuntimeError(
                    f"JSON parse failed (finishReason={c0.get('finishReason')}, "
                    f"len={len(text)}): {je}")
            STATUS["ok"] += 1
            return result
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(30 * (attempt + 1))
                continue
            detail = f"HTTP {e.code}: {e.read()[:200]!r}"
            print(f"[gemini] {detail}")
            STATUS["fail"] += 1
            STATUS["last_error"] = detail
            return None
        except Exception as e:  # noqa: BLE001
            detail = f"{type(e).__name__}: {e}"
            print(f"[gemini] error: {detail}")
            if attempt < retries - 1:
                time.sleep(5)
                continue
            STATUS["fail"] += 1
            STATUS["last_error"] = detail
            return None
    return None
