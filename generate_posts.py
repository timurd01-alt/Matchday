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

# Re-exported: defined here until build_research_posts needed them too,
# which made the two modules import each other. See post_layout.
from post_layout import BASE_URL, POST_CSS, SOCIAL_IMAGE_URL, _esc
from build_research_posts import build_research_posts

POSTS_FILE = "posts.json"
STATE_FILE = "posts_state.json"
POSTS_DIR = "posts"
CONTENT_FEED_FILE = "content-feed.json"
MIN_GRADED_FOR_FIRST_POST = 5
MIN_NEW_GRADED_SINCE_LAST_POST = 5
MIN_DAYS_SINCE_LAST_POST = 7

PUBLIC_CONTENT_COMPETITIONS = (
    ("wc", "World Cup", "soccer"),
    ("ucl", "Champions League", "soccer"),
    ("epl", "Premier League", "soccer"),
    ("laliga", "La Liga", "soccer"),
    ("seriea", "Serie A", "soccer"),
    ("bundesliga", "Bundesliga", "soccer"),
    ("ligue1", "Ligue 1", "soccer"),
    ("nfl", "NFL", "nfl"),
    ("ncaaf", "College Football", "ncaaf"),
    ("ncaam", "Men's College Basketball", "basketball"),
    ("nba", "NBA", "basketball"),
    ("nhl", "NHL", "hockey"),
    ("mlb", "MLB", "baseball"),
)
PUBLIC_CONTENT_KEYS = {key for key, _, _ in PUBLIC_CONTENT_COMPETITIONS}
MLB_FORECAST_PAUSE_MESSAGE = (
    "MLB forecasts paused while calibration and starting-pitcher coverage are being fixed."
)

FACTOR_LABELS = {
    "class": "talent or squad quality", "market_power": "championship market power",
    "form": "recent form", "gd": "goal difference",
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


def _is_public_comp(comp_key):
    return str(comp_key or "").lower() in PUBLIC_CONTENT_KEYS


def _publication_state(data, match):
    def value(candidate):
        if isinstance(candidate, str):
            return candidate
        if isinstance(candidate, dict):
            return (candidate.get("state") or candidate.get("status")
                    or candidate.get("publication_state") or "")
        return ""

    prediction = match.get("prediction") or {}
    candidates = (
        match.get("forecast_publication_state"),
        match.get("prediction_publication_state"), match.get("publication_state"),
        match.get("forecast_publication"), prediction.get("publication_state"),
        data.get("forecast_publication_state"),
        data.get("prediction_publication_state"), data.get("publication_state"),
        data.get("forecast_publication"), data.get("prediction_publication"),
    )
    states = [str(value(item)).lower() for item in candidates if value(item)]
    if "paused" in states:
        return "paused"
    dataset = str(value(data.get("forecast_publication")) or
                  value(data.get("prediction_publication")) or "").lower()
    return "eligible" if dataset == "eligible" else (states[0] if states else "")


def _forecast_is_paused(data, match):
    comp = str(match.get("_comp") or data.get("comp_key") or "").upper()
    # Fail closed: MLB is publishable only when the canonical backend payload
    # explicitly says eligible. Missing/stale payloads cannot resurrect picks.
    return (comp == "MLB" and match.get("status") == "UPCOMING"
            and _publication_state(data, match) != "eligible")


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
        "This is Matchday's own model reporting on itself for anyone to use. "
        "Every pick is locked before kickoff and graded automatically once the game finishes; "
        "none are rewritten after the fact. See the Q&A page for how the model works."
    )
    return {
        "id": slug, "comp": comp_key, "comp_label": comp_label, "slug": slug,
        "title": f"{comp_label} model recap — {today}",
        "date": today,
        "summary": f"The model went {hits}/{graded} ({pct}%) on graded {comp_label} picks.",
        "record": {"hits": hits, "graded": graded, "pct": pct},
        "highlights": awards or {},
        "body": paragraphs,
    }






def _content_sport(comp_key):
    key = str(comp_key or "").lower()
    if key in {"wc", "ucl", "epl", "laliga", "seriea", "bundesliga", "ligue1"}:
        return "soccer"
    if key in {"ncaam", "nba"}:
        return "basketball"
    return {"nfl": "nfl", "ncaaf": "ncaaf", "nhl": "hockey",
            "mlb": "baseball"}.get(key, "all")


def _compact_content_match(match, official_pick=None):
    """Keep only fields the public content hub renders.

    The full competition files can be several megabytes. This projection keeps
    the content page useful without shipping standings, news, rosters, or other
    dashboard-only data to every reader.
    """
    prediction = match.get("prediction") or {}
    score = match.get("score") or {}
    return {
        "id": match.get("id"),
        "kickoff": match.get("kickoff"),
        "status": match.get("status"),
        "stage": match.get("stage"),
        "venue": match.get("venue"),
        "home": {"name": (match.get("home") or {}).get("name")},
        "away": {"name": (match.get("away") or {}).get("name")},
        "score": {key: score.get(key) for key in ("home", "away", "winner")},
        "prediction": {
            key: prediction.get(key)
            for key in ("pick", "pick_name", "confidence", "note", "why")
        } if prediction else None,
        "official_pick": ({
            key: official_pick.get(key)
            for key in ("pick", "pick_name", "confidence", "model_hit", "result",
                        "factor_snapshot", "locked_at")
        } if isinstance(official_pick, dict) else None),
        "watchability": match.get("watchability"),
    }


def generate_public_content_feed():
    """Build one compact input file for every public content competition."""
    datasets = []
    for key, label, sport in PUBLIC_CONTENT_COMPETITIONS:
        data = _load_json(f"data_{key}.json", None)
        if not isinstance(data, dict):
            continue
        scorecard = data.get("scorecard") or {}
        verified_picks = {
            str(pick.get("fixture_id")): pick
            for pick in (scorecard.get("picks") or [])
            if pick.get("fixture_id") is not None
            and pick.get("integrity_eligible") is True
            and pick.get("integrity_status") == "verified"
            and pick.get("legacy") is not True
        }
        matches = [match for match in (data.get("matches") or [])
                   if isinstance(match, dict)]
        active = sorted(
            (match for match in matches
             if match.get("status") == "UPCOMING" and match.get("prediction")
             and not _forecast_is_paused(data, match)),
            key=lambda match: str(match.get("kickoff") or ""),
        )[:12]
        finished = sorted(
            (match for match in matches
             if match.get("status") == "FINISHED"
             and str(match.get("id")) in verified_picks),
            key=lambda match: str(match.get("kickoff") or ""), reverse=True,
        )[:12]
        datasets.append({
            "compKey": key,
            "competition": data.get("competition") or label,
            "sport": sport,
            "updated": data.get("updated"),
            "scorecard": {
                field: scorecard.get(field)
                for field in ("graded", "model_hits")
            } | {
                "verified_fixture_ids": sorted({
                    str(pick.get("fixture_id"))
                    for pick in verified_picks.values()
                })
            },
            "matches": [
                _compact_content_match(match, verified_picks.get(str(match.get("id"))))
                for match in active + finished
            ],
        })
    _save_json(CONTENT_FEED_FILE, {"datasets": datasets})
    return len(datasets)


def render_post_html(post):
    url = f"{BASE_URL}posts/{post['slug']}.html"
    title = f"{post['title']} · Matchday"
    comp_key = str(post.get("comp") or "").lower()
    content_sport = _content_sport(comp_key)
    ld = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": post["title"], "datePublished": post["date"],
        "author": {"@type": "Organization", "name": "Matchday"},
        "publisher": {"@type": "Organization", "name": "Matchday",
                      "logo": {"@type": "ImageObject", "url": SOCIAL_IMAGE_URL}},
        "mainEntityOfPage": url,
        "description": post["summary"],
        "image": SOCIAL_IMAGE_URL,
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
<meta property="og:image" content="{SOCIAL_IMAGE_URL}">
<meta property="og:image:width" content="512">
<meta property="og:image:height" content="512">
<meta property="og:image:alt" content="Matchday logo">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{_esc(post['title'])}">
<meta name="twitter:description" content="{_esc(post['summary'])}">
<meta name="twitter:image" content="{SOCIAL_IMAGE_URL}">
<meta name="twitter:image:alt" content="Matchday logo">
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
<nav class="postNav"><a href="../content.html">&larr; Back to Content</a><a href="../index.html">Dashboard</a></nav>
<p class="eyebrow">MATCHDAY MODEL RECAP</p>
<h1>{_esc(post['title'])}</h1>
<div class="meta"><span>{_esc(post['date'])}</span><span>{_esc(post['comp_label'])}</span><span>Auto-generated</span></div>
{body_html}
<nav class="articleActions" aria-label="Continue exploring">
<a href="../index.html?sport={_esc(comp_key)}&amp;view=matches">View matchup</a>
<a href="../index.html?sport={_esc(comp_key)}&amp;view=edge">See model prediction</a>
<a href="../index.html?sport={_esc(comp_key)}&amp;view=score">Open scorecard</a>
<a href="../content.html?sport={_esc(content_sport)}#latest">Explore similar games</a>
</nav>
<div class="notice"><strong>Use the information your way.</strong> Matchday publishes probabilities, market context, and a public track record. See the <a href="../qa.html">Q&amp;A page</a> for how predictions are built and the <a href="../legal.html">data sources and legal notice</a>.</div>
<p class="foot"><a href="../index.html">Matchday</a> — pregame predictions, market context and postgame grading.</p>
</div>
</body>
</html>
"""


def publish_recap_if_due(comp_key, comp_label, scorecard, awards):
    """Called once per competition per fetch. Publishes at most one post per
    call, gated by should_publish's weekly-and-enough-new-results check."""
    if not _is_public_comp(comp_key) or not should_publish(comp_key, scorecard):
        return None
    post = build_recap_post(comp_key, comp_label, scorecard, awards)
    if not post:
        return None
    posts = [post for post in load_posts() if _is_public_comp(post.get("comp"))]
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
    posts = [post for post in load_posts() if _is_public_comp(post.get("comp"))]
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
    generate_public_content_feed()
    try:
        research_posts = build_research_posts()
    except Exception as e:
        print(f"  research posts regen skipped: {e}")
        research_posts = []
    posts = [post for post in load_posts() if _is_public_comp(post.get("comp"))]
    urls = [
        (BASE_URL, "hourly", "1.0", None),
        (BASE_URL + "legal.html", "monthly", "0.3", None),
        (BASE_URL + "qa.html", "monthly", "0.5", None),
        (BASE_URL + "content.html", "weekly", "0.5", None),
        (BASE_URL + "tactics-soccer.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-football.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-basketball.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-hockey.html", "monthly", "0.5", None),
        (BASE_URL + "tactics-baseball.html", "monthly", "0.5", None),
    ]
    for post in posts:
        urls.append((f"{BASE_URL}posts/{post['slug']}.html", "never", "0.6", post.get("date")))
    for post in research_posts:
        urls.append((f"{BASE_URL}posts/{post['slug']}.html", "monthly", "0.6", post.get("date")))
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
