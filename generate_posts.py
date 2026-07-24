"""generate_posts.py — Matchday's own auto-generated weekly recap posts.

Turns data every competition already computes (update_scorecard's hit rate,
calibration and signal quality; build_weekly_awards' storylines) into short,
original recap posts. No manual writing, no third-party content — this is
Matchday's own model performance reported on itself.

Each post gets a real static HTML page under posts/<slug>.html (its own URL,
its own meta tags, Article JSON-LD) so it's independently indexable, plus an
entry in posts.json that the in-app Insights tab reads to list them.

Called from fetch_data.py (per competition, after update_scorecard) and from
multi_fetch.py (once, after every competition has had a chance to publish,
to regenerate the sitemap with whatever's new).
"""
import datetime
import json
import os

BASE_URL = "https://matchdayterminal.com/"
POSTS_FILE = "posts.json"
STATE_FILE = "posts_state.json"
POSTS_DIR = "posts"
MIN_GRADED_FOR_FIRST_POST = 5
MIN_NEW_GRADED_SINCE_LAST_POST = 5
MIN_DAYS_SINCE_LAST_POST = 7

FACTOR_LABELS = {
    "class": "team class/power rating", "form": "recent form", "gd": "goal difference",
    "rest": "rest advantage", "pts": "points on the table", "record": "season record",
    "margin": "scoring margin", "rank": "poll rank", "srs": "opponent-adjusted rating",
    "elo": "Elo rating",
}


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_posts():
    return _load_json(POSTS_FILE, [])


def load_state():
    return _load_json(STATE_FILE, {})


def should_publish(comp_key, scorecard):
    graded = int((scorecard or {}).get("graded") or 0)
    state = load_state()
    rec = state.get(comp_key)
    if rec is None:
        return graded >= MIN_GRADED_FOR_FIRST_POST
    try:
        last = datetime.date.fromisoformat(rec.get("last_post_date", ""))
    except Exception:
        return graded >= MIN_GRADED_FOR_FIRST_POST
    days_since = (datetime.date.today() - last).days
    new_graded = graded - int(rec.get("graded_at_post") or 0)
    return days_since >= MIN_DAYS_SINCE_LAST_POST and new_graded >= MIN_NEW_GRADED_SINCE_LAST_POST


def _hit_rate_paragraph(comp_label, scorecard):
    graded, hits = scorecard.get("graded") or 0, scorecard.get("model_hits") or 0
    pct = round(100 * hits / graded) if graded else 0
    line = f"Matchday's model graded {graded} {comp_label} pick{'s' if graded != 1 else ''} this stretch, hitting on {hits} of them ({pct}%)."
    mk_graded, mk_hits = scorecard.get("market_graded") or 0, scorecard.get("market_hits") or 0
    if mk_graded >= 5:
        mk_pct = round(100 * mk_hits / mk_graded)
        line += f" Over the same {mk_graded} games with a market line, the betting market favorite hit {mk_pct}% of the time."
    return line


def _calibration_paragraph(scorecard):
    bands = [b for b in (scorecard.get("calibration") or []) if b.get("n", 0) >= 3]
    if not bands:
        return None
    parts = []
    for b in bands:
        actual = round(100 * b["hits"] / b["n"])
        parts.append(f"picks stated at {b['band']}% hit {actual}% of the time ({b['n']} games)")
    return "On calibration: " + "; ".join(parts) + \
        ". A well-calibrated model's stated confidence should roughly match its actual hit rate in each band."


def _signal_paragraph(scorecard):
    signals = scorecard.get("signal_quality") or {}
    rated = [(k, v) for k, v in signals.items() if v.get("n", 0) >= 5]
    if not rated:
        return None
    rated.sort(key=lambda kv: -(kv[1]["hits"] / kv[1]["n"]))
    best_k, best_v = rated[0]
    best_label = FACTOR_LABELS.get(best_k, best_k)
    best_pct = round(100 * best_v["hits"] / best_v["n"])
    line = f"The strongest signal lately has been {best_label}: when it favored a side, that side won {best_pct}% of the time ({best_v['n']} games)."
    if len(rated) > 1:
        worst_k, worst_v = rated[-1]
        worst_pct = round(100 * worst_v["hits"] / worst_v["n"])
        if worst_pct < 50 and worst_k != best_k:
            worst_label = FACTOR_LABELS.get(worst_k, worst_k)
            line += f" {worst_label.capitalize()} has been the weakest, at {worst_pct}% ({worst_v['n']} games) — a reminder no single factor is decisive on its own."
    return line


def _awards_paragraph(comp_label, awards):
    if not awards:
        return None
    bits = []
    bu = awards.get("biggest_upset")
    if bu:
        bits.append(f"the biggest upset was {bu['winner']} winning {bu['score_line']} against {bu['home'] if bu['winner'] != bu['home'] else bu['away']} "
                     f"(the market gave that result only about {round(bu.get('market_pct') or 0)}%)")
    bc = awards.get("best_call")
    if bc:
        bits.append(f"the model's best call was {bc['pick']} in {bc['home']} vs {bc['away']} at {bc['confidence']}% confidence")
    bm = awards.get("biggest_miss")
    if bm:
        bits.append(f"its biggest miss was picking {bm['pick']} in {bm['home']} vs {bm['away']}, but {bm['actual']} won instead")
    if not bits:
        return None
    return f"Among this week's {comp_label} storylines: " + "; ".join(bits) + "."


def build_recap_post(comp_key, comp_label, scorecard, awards):
    graded = int((scorecard or {}).get("graded") or 0)
    if graded == 0:
        return None
    today = datetime.date.today().isoformat()
    slug = f"{comp_key.lower()}-{today}"
    hits = scorecard.get("model_hits") or 0
    pct = round(100 * hits / graded) if graded else 0
    paragraphs = [_hit_rate_paragraph(comp_label, scorecard)]
    for para in (_calibration_paragraph(scorecard), _signal_paragraph(scorecard), _awards_paragraph(comp_label, awards)):
        if para:
            paragraphs.append(para)
    paragraphs.append(
        "This is Matchday's own model reporting on itself — not betting advice. "
        "Every pick is locked before kickoff and graded automatically once the game finishes; "
        "none are rewritten after the fact. See the Q&A page for how the model works."
    )
    return {
        "id": slug, "comp": comp_key, "comp_label": comp_label, "slug": slug,
        "title": f"{comp_label} model recap — {today}",
        "date": today,
        "summary": f"The model went {hits}/{graded} ({pct}%) on graded {comp_label} picks.",
        "body": paragraphs,
    }


def _esc(s):
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


POST_CSS = """:root{--bg:#070a0f;--panel:#111822;--text:#eef2f8;--muted:#9ba8b8;--faint:#647184;--line:#263244;--signal:#3ad17a;--link:#76caff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,rgba(58,209,122,.1),transparent 30%),var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;line-height:1.65}.wrap{width:min(760px,calc(100% - 40px));margin:auto;padding:44px 0 76px}.back{color:var(--muted);font-family:"JetBrains Mono",monospace;font-size:.75rem;text-decoration:none}.back:hover{color:var(--signal)}.eyebrow{margin:36px 0 12px;color:var(--signal);font:700 .68rem "JetBrains Mono",monospace;letter-spacing:.14em}h1{font-family:Archivo,sans-serif;font-size:clamp(1.8rem,5vw,2.8rem);letter-spacing:-.04em;line-height:1.05;margin:0 0 10px}.meta{display:flex;flex-wrap:wrap;gap:10px;color:var(--faint);font:500 .7rem "JetBrains Mono",monospace;margin-bottom:26px}.meta span{border:1px solid var(--line);border-radius:999px;padding:5px 9px}p{color:#c9d2de;margin:0 0 16px;font-size:1.02rem}a{color:var(--link)}.notice{border-left:3px solid var(--signal);background:rgba(58,209,122,.07);border-radius:7px;padding:12px 14px;color:#d8dde5;font-size:.85rem;margin-top:30px}.foot{margin-top:34px;color:var(--faint);font-size:.75rem}"""


def render_post_html(post):
    url = f"{BASE_URL}posts/{post['slug']}.html"
    title = f"{post['title']} · Matchday"
    ld = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": post["title"], "datePublished": post["date"],
        "author": {"@type": "Organization", "name": "Matchday"},
        "publisher": {"@type": "Organization", "name": "Matchday"},
        "mainEntityOfPage": url,
        "description": post["summary"],
    }
    body_html = "\n".join(f"<p>{_esc(p)}</p>" for p in post["body"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(post['summary'])}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Matchday">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{_esc(post['title'])}">
<meta property="og:description" content="{_esc(post['summary'])}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{_esc(post['title'])}">
<meta name="twitter:description" content="{_esc(post['summary'])}">
<meta name="theme-color" content="#070a0f">
<link rel="icon" href="../favicon.ico" sizes="any">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>{POST_CSS}</style>
<script type="application/ld+json">
{json.dumps(ld, ensure_ascii=False, indent=1)}
</script>
</head>
<body>
<div class="wrap">
<a class="back" href="../index.html">&larr; Back to Matchday</a>
<p class="eyebrow">MATCHDAY MODEL RECAP</p>
<h1>{_esc(post['title'])}</h1>
<div class="meta"><span>{_esc(post['date'])}</span><span>{_esc(post['comp_label'])}</span><span>Auto-generated</span></div>
{body_html}
<div class="notice"><strong>Analytics only.</strong> Matchday does not offer betting advice. See the <a href="../qa.html">Q&amp;A page</a> for how predictions are built and the <a href="../legal.html">data sources and legal notice</a>.</div>
<p class="foot"><a href="../index.html">Matchday</a> — live scores, odds and model-based predictions.</p>
</div>
</body>
</html>
"""


def publish_recap_if_due(comp_key, comp_label, scorecard, awards):
    """Called once per competition per fetch. Publishes at most one post per
    call, gated by should_publish's weekly-and-enough-new-results check."""
    if not should_publish(comp_key, scorecard):
        return None
    post = build_recap_post(comp_key, comp_label, scorecard, awards)
    if not post:
        return None
    posts = load_posts()
    if any(p.get("id") == post["id"] for p in posts):
        return None  # already published today for this competition
    posts.insert(0, post)
    _save_json(POSTS_FILE, posts)
    os.makedirs(POSTS_DIR, exist_ok=True)
    with open(os.path.join(POSTS_DIR, f"{post['slug']}.html"), "w", encoding="utf-8") as f:
        f.write(render_post_html(post))
    state = load_state()
    state[comp_key] = {"last_post_date": post["date"], "graded_at_post": int(scorecard.get("graded") or 0)}
    _save_json(STATE_FILE, state)
    return post


def rewrite_all_post_files():
    """Re-render every post's static HTML from posts.json — keeps pages in
    sync if the template changes, without needing to regenerate content."""
    posts = load_posts()
    if not posts:
        return 0
    os.makedirs(POSTS_DIR, exist_ok=True)
    for post in posts:
        with open(os.path.join(POSTS_DIR, f"{post['slug']}.html"), "w", encoding="utf-8") as f:
            f.write(render_post_html(post))
    return len(posts)


def regenerate_sitemap():
    """Rebuild sitemap.xml from every static page: the app shell, legal, qa,
    and every currently-published post. Called once after all competitions
    have had a chance to publish (see multi_fetch.py)."""
    rewrite_all_post_files()
    posts = load_posts()
    urls = [
        (BASE_URL, "hourly", "1.0", None),
        (BASE_URL + "legal.html", "monthly", "0.3", None),
        (BASE_URL + "qa.html", "monthly", "0.5", None),
        (BASE_URL + "content.html", "weekly", "0.5", None),
        (BASE_URL + "tactics-soccer.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-football.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-basketball.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-baseball.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-hockey.html", "monthly", "0.5", None),
    ]
    for post in posts:
        urls.append((f"{BASE_URL}posts/{post['slug']}.html", "never", "0.6", post.get("date")))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq, priority, lastmod in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{_esc(loc)}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{_esc(lastmod)}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(urls)
