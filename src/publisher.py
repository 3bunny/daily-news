"""
Publisher: render the selected stories into a clean, self-contained HTML issue,
archive it by date, and maintain a browsable index — all under docs/ so GitHub
Pages can serve it directly.

Layout produced:
    docs/index.html            -> latest issue (your daily bookmark)
    docs/archive/YYYY-MM-DD.html
    docs/archive.html          -> list of every past issue
    docs/issues.json           -> machine-readable manifest
"""

import html
import json
import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

PAPER_NAME = "THE DAILY DISPATCH"
TAGLINE = "World news, scanned at dawn — military · business · crypto · economics"

# ---------------------------------------------------------------- CSS ----------
CSS = """
:root{
  --paper:#f7f3ea; --ink:#1c1a17; --muted:#6b6358; --rule:#d8cfbf;
  --accent:#8a1f1f; --accent2:#2a3d54; --pill:#efe8da; --wow:#b8860b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:Georgia,'Times New Roman',serif;line-height:1.6;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:32px 22px 80px}
a{color:inherit}
/* Masthead */
.masthead{text-align:center;border-bottom:3px double var(--ink);padding-bottom:14px}
.masthead h1{font-family:'Playfair Display',Georgia,serif;font-weight:900;
  letter-spacing:.04em;margin:.1em 0;font-size:clamp(34px,7vw,58px);line-height:1}
.tagline{font-style:italic;color:var(--muted);font-size:15px;margin-top:6px}
.dateline{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;
  font-size:12.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);
  margin-top:12px}
/* Editor's note */
.ednote{background:#fff;border:1px solid var(--rule);border-left:4px solid var(--accent);
  padding:14px 18px;margin:26px 0;border-radius:3px}
.ednote .lbl{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);
  font-family:Helvetica,Arial,sans-serif;font-weight:700}
.ednote .grade{float:right;font-family:'Playfair Display',Georgia,serif;font-weight:900;
  font-size:34px;line-height:1;color:var(--accent)}
.ednote p{margin:.4em 0 0;font-style:italic}
/* Sections */
.section{margin-top:40px}
.section-head{display:flex;align-items:baseline;gap:12px;border-bottom:2px solid var(--ink);
  padding-bottom:6px}
.section-head h2{font-family:'Playfair Display',Georgia,serif;margin:0;font-size:25px;font-weight:800}
.section-head .blurb{color:var(--muted);font-style:italic;font-size:13.5px}
.section.lead .section-head h2{color:var(--accent)}
/* Stories */
.story{padding:20px 0;border-bottom:1px solid var(--rule)}
.story:last-child{border-bottom:none}
.story h3{margin:0 0 6px;font-size:20px;line-height:1.3;font-weight:700}
.story h3 a{text-decoration:none}
.story h3 a:hover{text-decoration:underline;text-decoration-color:var(--accent)}
.meta{font-size:12px;color:var(--muted);font-family:Helvetica,Arial,sans-serif;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.pill{background:var(--pill);border:1px solid var(--rule);border-radius:20px;
  padding:2px 10px;letter-spacing:.04em}
.wow{background:var(--wow);color:#fff;border-color:var(--wow);font-weight:700}
.story p{margin:0;font-size:16.5px}
.empty{color:var(--muted);font-style:italic;padding:14px 0}
/* Footer / nav */
.foot{margin-top:54px;border-top:3px double var(--ink);padding-top:16px;
  font-size:13px;color:var(--muted);text-align:center}
.foot a{color:var(--accent2);font-weight:700}
.archive-list{list-style:none;padding:0}
.archive-list li{border-bottom:1px solid var(--rule);padding:12px 2px}
.archive-list a{text-decoration:none;font-size:18px;font-weight:700}
.archive-list .g{float:right;color:var(--accent);font-weight:700}
@media print{body{background:#fff}.foot a{color:#000}}
/* Foresight (embedded in daily paper + standalone pages) */
.fs-section{margin-top:50px}
.fs-section .section-head h2{color:var(--accent2)}
.fs-intro{font-size:17px;font-style:italic;color:var(--muted);margin:18px 0 8px}
.dive{margin-top:34px;border-top:1px solid var(--rule);padding-top:16px}
.dive h2{font-family:'Playfair Display',Georgia,serif;font-size:22px;margin:0 0 8px;color:var(--accent2)}
.dive .happened{font-size:16.5px;margin:0 0 14px}
.block{margin:13px 0}
.block .h{font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:700;
  font-family:Helvetica,Arial,sans-serif;color:var(--accent);margin-bottom:6px}
.kv{margin:5px 0;font-size:15.5px}
.kv b{color:var(--ink)}
.spill{background:#fff;border:1px solid var(--rule);border-left:4px solid var(--accent2);
  padding:10px 14px;border-radius:3px;font-size:15.5px}
.watch{margin:0;padding-left:18px}
.watch li{margin:5px 0;font-size:15.5px}
.disclaimer{margin-top:24px;font-size:12.5px;color:var(--muted);font-style:italic;
  border-top:1px solid var(--rule);padding-top:12px}
.fs-more{margin-top:18px;font-size:13px}
.fs-more a{color:var(--accent2);font-weight:700}
/* Read more */
details.readmore-d{margin-top:10px}
details.readmore-d summary{cursor:pointer;list-style:none;font-family:Helvetica,Arial,sans-serif;
  font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--accent2)}
details.readmore-d summary::-webkit-details-marker{display:none}
details.readmore-d summary::after{content:" \25B8"}
details.readmore-d[open] summary::after{content:" \25BE"}
.readmore{margin-top:8px;font-size:15.5px;color:var(--ink)}
/* Bionic reading toggle */
#bionic-toggle{position:fixed;right:14px;bottom:14px;z-index:60;font-family:Helvetica,Arial,sans-serif;
  font-size:12px;font-weight:700;letter-spacing:.04em;background:var(--accent2);color:#fff;border:none;
  border-radius:20px;padding:9px 15px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.25);opacity:.85}
#bionic-toggle:hover{opacity:1}
@media print{#bionic-toggle{display:none}}
/* Top Ten Today */
.topten{margin:26px 0 8px;background:#fff;border:1px solid var(--rule);border-radius:4px;padding:16px 18px 12px}
.topten h2{font-family:'Playfair Display',Georgia,serif;font-size:21px;margin:0;color:var(--accent)}
.topten .sub{font-size:12px;color:var(--muted);font-style:italic;margin:2px 0 10px}
.topten ol{margin:0;padding:0;list-style:none;counter-reset:tt}
.topten li{counter-increment:tt;display:flex;gap:9px;align-items:baseline;
  padding:7px 0;border-bottom:1px dotted var(--rule)}
.topten li:last-child{border-bottom:none}
.topten li::before{content:counter(tt);font-family:'Playfair Display',Georgia,serif;
  font-weight:900;color:var(--accent);min-width:20px;font-size:15px}
.topten a{font-weight:700;text-decoration:none;font-size:15.5px;flex:1}
.topten a:hover{text-decoration:underline;text-decoration-color:var(--accent)}
.tt-grade{font-family:Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;color:#fff;
  background:var(--accent2);border-radius:4px;padding:1px 6px;white-space:nowrap}
.tt-tag{font-family:Helvetica,Arial,sans-serif;font-size:10px;letter-spacing:.05em;
  text-transform:uppercase;color:var(--muted);background:var(--pill);border:1px solid var(--rule);
  border-radius:20px;padding:1px 8px;white-space:nowrap}
.pill.tag{background:#edf0f7;border-color:#cfd8ea;color:var(--accent2)}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?'
         'family=Playfair+Display:wght@800;900&display=swap" rel="stylesheet">')

BIONIC_JS = r"""
<script>
(function(){
  var SEL='.story p, .readmore, .fs-intro, .dive .happened, .spill';
  var KEY='bionicOn';
  function bw(w){var m=w.match(/^([^A-Za-z0-9]*)([A-Za-z0-9]+)([\s\S]*)$/);if(!m)return w;
    var n=Math.max(1,Math.round(m[2].length*0.45));
    return m[1]+'<b>'+m[2].slice(0,n)+'</b>'+m[2].slice(n)+m[3];}
  function apply(){document.querySelectorAll(SEL).forEach(function(el){
    if(el.dataset.bd)return; el.dataset.bd='1'; el.dataset.orig=el.innerHTML;
    var wk=document.createTreeWalker(el,NodeFilter.SHOW_TEXT,null),ns=[];
    while(wk.nextNode())ns.push(wk.currentNode);
    ns.forEach(function(t){ if(!t.nodeValue.trim())return;
      var sp=document.createElement('span');
      sp.innerHTML=t.nodeValue.split(/(\s+)/).map(function(tok){return tok.trim()?bw(tok):tok;}).join('');
      t.parentNode.replaceChild(sp,t);});
  });}
  function unapply(){document.querySelectorAll(SEL).forEach(function(el){
    if(el.dataset.orig!==undefined){el.innerHTML=el.dataset.orig;delete el.dataset.bd;delete el.dataset.orig;}});}
  var on; try{var v=localStorage.getItem(KEY); on=(v===null)?true:(v==='1');}catch(e){on=true;}
  var btn=document.createElement('button'); btn.id='bionic-toggle';
  function render(){ if(on)apply(); else unapply(); btn.textContent='\u26A1 Faster reading: '+(on?'ON':'OFF'); }
  btn.onclick=function(){on=!on; try{localStorage.setItem(KEY,on?'1':'0');}catch(e){} render();};
  if(document.readyState!=='loading'){document.body.appendChild(btn);render();}
  else document.addEventListener('DOMContentLoaded',function(){document.body.appendChild(btn);render();});
})();
</script>
"""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(title)}</title>{FONTS}<style>{CSS}</style></head>"
            f"<body><div class='wrap'>{body}</div>{BIONIC_JS}</body></html>")


def _lg(score):
    s = float(score or 0)
    return ("A+" if s >= 9.5 else "A" if s >= 9 else "A-" if s >= 8.5 else
            "B+" if s >= 8 else "B" if s >= 7 else "B-" if s >= 6 else "C")


def _story_html(s, sid="") -> str:
    try:
        when = datetime.fromisoformat(s.published).strftime("%b %d, %H:%M KST")
    except (ValueError, TypeError):
        when = ""
    wow = "<span class='pill wow'>★ Standout</span>" if s.wow else ""
    tag = f"<span class='pill tag'>{_esc(s.tag)}</span>" if getattr(s, "tag", "") else ""
    link = _esc(s.link)
    title = (f"<a href='{link}' target='_blank' rel='noopener'>{_esc(s.title)}</a>"
             if s.link else _esc(s.title))
    idattr = f" id='{sid}'" if sid else ""
    return (
        f"<article class='story'{idattr}>"
        f"<h3>{title}</h3>"
        f"<div class='meta'>{wow}{tag}"
        f"<span class='pill'>{_esc(s.source)}</span>"
        f"<span>{when}</span></div>"
        f"<p>{_esc(s.summary)}</p>"
        f"{_readmore_html(s)}"
        "</article>"
    )


def _topten_html(selected, topics, id_map) -> str:
    title_by_key = {t["key"]: t["title"] for t in topics}
    alls = [s for t in topics for s in selected.get(t["key"], [])]
    if not alls:
        return ""
    ranked = sorted(alls, key=lambda s: (s.wow, s.score), reverse=True)[:10]
    lis = []
    for s in ranked:
        sid = id_map.get(id(s), "")
        href = f"#{sid}" if sid else (_esc(s.link) or "#")
        tag = getattr(s, "tag", "") or title_by_key.get(s.topic, "")
        lis.append(
            f"<li><span class='tt-grade'>{_lg(s.score)}</span>"
            f"<a href='{href}'>{_esc(s.title)}</a>"
            f"<span class='tt-tag'>{_esc(tag)}</span></li>"
        )
    return ("<section class='topten'><h2>Top Ten Today</h2>"
            "<div class='sub'>The day's highest-graded finds across every desk \u2014 "
            "tap to jump to the full story.</div>"
            f"<ol>{''.join(lis)}</ol></section>")


def _readmore_html(s) -> str:
    detail = getattr(s, "detail", "") or getattr(s, "raw_summary", "")
    if not detail or detail.strip() == (s.summary or "").strip():
        return ""
    return ("<details class='readmore-d'><summary>Read more</summary>"
            f"<div class='readmore'>{_esc(detail)}</div></details>")


def _section_html(topic: dict, stories: list, lead: bool, id_map: dict) -> str:
    head = (f"<div class='section-head'><h2>{_esc(topic['title'])}</h2>"
            f"<span class='blurb'>{_esc(topic.get('blurb',''))}</span></div>")
    if stories:
        body = "".join(_story_html(s, id_map.get(id(s), "")) for s in stories)
    else:
        body = "<div class='empty'>Nothing met the bar today. We'd rather run nothing than filler.</div>"
    cls = "section lead" if lead else "section"
    return f"<section class='{cls}'>{head}{body}</section>"


def render_issue(selected: dict, grade: dict, config: dict, date: datetime, foresight_fragment: str = "") -> str:
    long_date = date.strftime("%A, %B %-d, %Y") if os.name != "nt" else date.strftime("%A, %B %d, %Y")
    masthead = (
        f"<header class='masthead'><h1>{PAPER_NAME}</h1>"
        f"<div class='tagline'>{TAGLINE}</div>"
        f"<div class='dateline'><span>Seoul · {long_date}</span>"
        f"<span>Edition {date.strftime('%Y.%m.%d')}</span></div></header>"
    )
    g = _esc(grade.get("grade", "—"))
    note = _esc(grade.get("note", ""))
    ednote = (f"<div class='ednote'><span class='grade'>{g}</span>"
              f"<span class='lbl'>Editor's Note</span><p>{note}</p></div>")

    topics = sorted(config["topics"], key=lambda t: t.get("priority", 99))
    id_map, _n = {}, 0
    for t in topics:
        for st in selected.get(t["key"], []):
            _n += 1
            id_map[id(st)] = f"s{_n}"
    topten = _topten_html(selected, topics, id_map)
    sections = "".join(
        _section_html(t, selected.get(t["key"], []), (i == 0), id_map)
        for i, t in enumerate(topics)
    )
    fs = ""
    if foresight_fragment:
        fs = (
            "<section class='fs-section'>"
            "<div class='section-head'><h2>Weekly Foresight</h2>"
            "<span class='blurb'>Dual-use tech — what the military builds today, the world uses tomorrow</span></div>"
            f"{foresight_fragment}"
            "<div class='fs-more'><a href='foresight/index.html'>Past Foresight reports →</a></div>"
            "</section>"
        )
    foot = ("<div class='foot'>Compiled automatically by the Daily Dispatch bot · "
            "<a href='archive.html'>Past editions →</a> · <a href='foresight/index.html'>Weekly Foresight →</a><br>"
            "Sources are independent outlets; tap any headline to read the original.</div>")
    return _page(f"{PAPER_NAME} — {long_date}", masthead + ednote + topten + sections + fs + foot)


def _load_manifest(docs: str) -> list:
    p = os.path.join(docs, "issues.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return []


def render_archive(docs: str, manifest: list) -> str:
    head = ("<header class='masthead'><h1>Archive</h1>"
            "<div class='tagline'>Every past edition of the Daily Dispatch</div></header>")
    items = "".join(
        f"<li><a href='archive/{_esc(m['date'])}.html'>{_esc(m['long'])}</a>"
        f"<span class='g'>{_esc(m.get('grade','—'))}</span></li>"
        for m in sorted(manifest, key=lambda m: m["date"], reverse=True)
    )
    body = (head + f"<ul class='archive-list'>{items or '<li>No editions yet.</li>'}</ul>"
            "<div class='foot'><a href='index.html'>← Latest edition</a></div>")
    return _page("Daily Dispatch — Archive", body)


def publish(selected: dict, grade: dict, config: dict, root: str,
            date: datetime | None = None) -> dict:
    """Write the issue + archive + index. Returns paths written."""
    date = date or datetime.now(KST)
    docs = os.path.join(root, "docs")
    arch = os.path.join(docs, "archive")
    os.makedirs(arch, exist_ok=True)

    frag_path = os.path.join(docs, "foresight", "latest_fragment.html")
    fragment = ""
    if os.path.exists(frag_path):
        with open(frag_path, encoding="utf-8") as ff:
            fragment = ff.read()
    issue_html = render_issue(selected, grade, config, date, foresight_fragment=fragment)
    dstr = date.strftime("%Y-%m-%d")
    long = date.strftime("%A, %B %d, %Y")

    index_path = os.path.join(docs, "index.html")
    archive_issue = os.path.join(arch, f"{dstr}.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(issue_html)
    with open(archive_issue, "w", encoding="utf-8") as f:
        f.write(issue_html)

    # Update manifest (replace same-day entry if re-run).
    manifest = [m for m in _load_manifest(docs) if m["date"] != dstr]
    manifest.append({
        "date": dstr, "long": long, "grade": grade.get("grade", "—"),
        "counts": grade.get("counts", {}),
    })
    with open(os.path.join(docs, "issues.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(docs, "archive.html"), "w", encoding="utf-8") as f:
        f.write(render_archive(docs, manifest))

    # Prevent Jekyll from interfering with the static files on Pages.
    open(os.path.join(docs, ".nojekyll"), "w").close()

    return {"index": index_path, "archive_issue": archive_issue}
