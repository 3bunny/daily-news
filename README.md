# The Daily Dispatch 📰

An autonomous daily newspaper. Every morning at **07:00 KST** a cloud job scans
world news across four beats — **military first**, then business, crypto, and
economics — summarizes the best of it, has an **editor agent** grade and curate
the issue, and publishes a clean HTML edition you can read from any device. Past
editions are archived automatically.

It runs on **GitHub Actions** (free, in the cloud) so it works whether or not
your computer is on. The "brain" is **Google's free Gemini API**.

---

## How it works

```
scan RSS feeds → summarize (Gemini) → editor scores & filters → grade & curate → publish HTML
```

| Piece | File | Job |
|---|---|---|
| Scanner | `src/scanner.py` | Pulls & de-dupes stories from the feeds in `config/sources.yaml` |
| Summarizer | `src/summarizer.py` | One tight paragraph per story (Gemini Flash) |
| Editor agent | `src/editor.py` | Scores novelty/"wow", drops filler, grades the issue, suggests better outlets |
| Publisher | `src/publisher.py` | Renders the HTML edition + archive + index |
| Orchestrator | `src/main.py` | Runs the whole pipeline |
| Schedule | `.github/workflows/daily.yml` | Fires daily at 07:00 KST in the cloud |

**Quality rule:** a story must clear a score threshold (`min_score` in the
config) to print. On a quiet day, a section can be short or empty — the paper
never pads itself with filler.

---

## One-time setup (~10 minutes)

1. **Get a free Gemini API key**
   Go to <https://aistudio.google.com/apikey>, sign in with your Google
   account, click *Create API key*, copy it. (Free tier: 1,500 requests/day —
   far more than this needs. No credit card.)

2. **Create the GitHub repo**
   Put this folder in a new GitHub repository (public is fine — it's just news).

3. **Add the key as a secret**
   In the repo: *Settings → Secrets and variables → Actions → New repository
   secret*. Name it exactly `GEMINI_API_KEY`, paste your key.

4. **Turn on GitHub Pages**
   *Settings → Pages → Build and deployment → Source: Deploy from a branch →
   Branch: `main`, Folder: `/docs`*. Save. Your paper will live at
   `https://<your-username>.github.io/<repo>/`.

5. **Test it**
   *Actions tab → Daily Dispatch → Run workflow.* In a minute or two it builds
   today's edition and commits it. Open your Pages URL — bookmark it.

After that it runs itself every morning.

---

## Reading it

- **Latest edition:** your GitHub Pages URL (`docs/index.html`).
- **Past editions:** the *Archive* link in the footer (`docs/archive.html`).

---

## Tuning it

Everything lives in `config/sources.yaml`:

- `max_stories_per_section` — how many stories per beat (currently 5).
- `min_score` — the quality bar (0-10). Raise it for a stricter, shorter paper.
- `lookback_hours` — how far back to look (currently 28h).
- `topics` / `feeds` — add or remove outlets. Military is `priority: 1`.

The editor agent also appends outlets it discovers under `auto_added:` (only
after validating the feed works; it never deletes your curated feeds). Its daily
report — grade, counts, source suggestions — is saved in `editor_log/`.

---

## Run it locally (optional)

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your_key        # omit to use simple fallback summaries
python src/main.py                    # builds docs/index.html

# Offline preview with sample data (no network/key needed):
python src/main.py --mock config/mock_stories.json
```

No key? The pipeline still runs using transparent keyword heuristics and the
feeds' own summaries, so you always get a paper.
