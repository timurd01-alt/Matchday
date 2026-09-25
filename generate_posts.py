"""generate_posts.py — static pages and the sitemap for Matchday's posts.

Each post in posts.json gets a real static HTML page under posts/<slug>.html
(its own URL, meta tags and Article JSON-LD) so it is independently indexable;
the in-app Insights tab lists posts.json. Called once per run from
multi_fetch.py to re-render the pages and rebuild sitemap.xml.

The weekly model recaps this module used to write were graded from the retired
in-house model and were removed with it.
"""
import json
import os

from post_layout import BASE_URL, POST_CSS, SOCIAL_IMAGE_URL, _esc

POSTS_FILE = "posts.json"
POSTS_DIR = "posts"
PUBLIC_CONTENT_COMPETITIONS = (
    # College only. The hourly job was still writing Serie A recaps for a site
    # that no longer publishes Serie A.
    ("ncaaf", "College Football", "ncaaf"),
    ("ncaam", "Men's College Basketball", "basketball"),
)
PUBLIC_CONTENT_KEYS = {key for key, _, _ in PUBLIC_CONTENT_COMPETITIONS}

def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _is_public_comp(comp_key):
    return str(comp_key or "").lower() in PUBLIC_CONTENT_KEYS


# Whether an ALREADY-PUBLISHED post may stay in posts.json. Deliberately wider
# than _is_public_comp: that answers "may this competition publish a recap",
# where "all" is not a competition and must stay rejected. Editorial desk posts
# (weekly scorecards, market audits, availability trackers, methodology notes)
# cover the whole board and are stored with comp "all", so reusing the
# competition gate as a retention filter silently deleted 9 of 13 published
# posts the first time any competition published a recap -- posts.json is
# rewritten from this filtered list, so the drop was permanent, and it took
# out refining-the-record-2026-07-26, which test_analysis_mode pins by id via
# next(...) -> StopIteration -> "Run required test suite" fails -> the hourly
# refresh/deploy fails. It presented as intermittent only because whether a
# given CI run saw a culled posts.json depended on what the actions/cache
# restore handed it. deploy.yml's site-assembly step already carries this exact
# allowlist ({"all", "wc", ...}); this is the same rule at the source.
EDITORIAL_CONTENT_KEY = "all"


def _is_public_post(post):
    comp = str((post or {}).get("comp") or "").lower()
    return comp == EDITORIAL_CONTENT_KEY or _is_public_comp(comp)


def load_posts():
    return _load_json(POSTS_FILE, [])


def render_post_html(post):
    url = f"{BASE_URL}posts/{post['slug']}.html"
    title = f"{post['title']} · Matchday"
    comp_key = str(post.get("comp") or "").lower()
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
<nav class="postNav"><a href="../index.html">&larr; Back to Matchday</a></nav>
<p class="eyebrow">MATCHDAY MODEL RECAP</p>
<h1>{_esc(post['title'])}</h1>
<div class="meta"><span>{_esc(post['date'])}</span><span>{_esc(post['comp_label'])}</span><span>Auto-generated</span></div>
{body_html}
<nav class="articleActions" aria-label="Continue exploring">
<a href="../index.html?sport={_esc(comp_key)}&amp;view=matches">View matchup</a>
<a href="../index.html?sport={_esc(comp_key)}&amp;view=score">Open scorecard</a>
</nav>
<div class="notice"><strong>Use the information your way.</strong> Matchday publishes probabilities, market context, and a public track record. See the <a href="../qa.html">Q&amp;A page</a> for how predictions are built and the <a href="../legal.html">data sources and legal notice</a>.</div>
<p class="foot"><a href="../index.html">Matchday</a> — pregame predictions, market context and postgame grading.</p>
</div>
</body>
</html>
"""


def rewrite_all_post_files():
    """Re-render every post's static HTML from posts.json — keeps pages in
    sync if the template changes, without needing to regenerate content."""
    posts = [post for post in load_posts() if _is_public_post(post)]
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
    posts = [post for post in load_posts() if _is_public_post(post)]
    urls = [
        (BASE_URL, "hourly", "1.0", None),
        (BASE_URL + "legal.html", "monthly", "0.3", None),
        (BASE_URL + "qa.html", "monthly", "0.5", None),
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
