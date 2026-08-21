"""build_research_posts.py — Matchday's public Research/Insights write-ups.

Phase 11 of the 2026-08-01 product roadmap: a public record of what the
model-experiment framework has actually found, generated from real data
already computed elsewhere rather than hand-typed numbers that can drift
stale. Each post states its methodology and cites the real source file it
was computed from, and every claim below is either read straight out of
docs/experiments.json (the Phase 4 experiment ledger) or computed fresh from
a real picks_log_<comp>.json.

This is a small, separate pipeline from generate_posts.py's weekly recaps --
those are auto-published on a schedule from live scorecards; these research
posts are authored write-ups republished whenever this script reruns, so
they stay in sync with the source data without being auto-generated garbage.
Run manually: `python build_research_posts.py`
"""
import datetime
import json
import os

from post_layout import POST_CSS, SOCIAL_IMAGE_URL, BASE_URL, _esc

RESEARCH_POSTS_FILE = "research_posts.json"
POSTS_DIR = "posts"
EXPERIMENTS_FILE = os.path.join("docs", "experiments.json")

DECISION_LABELS = {
    "keep_production": "kept, in capped production",
    "keep_shadow": "kept as shadow-only research",
    "reject": "rejected",
    "continue_testing": "still collecting evidence",
    "not_yet_run": "not yet run",
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


def _experiments_post():
    exp = _load_json(EXPERIMENTS_FILE, {})
    entries = exp.get("experiments") or []
    if not entries:
        return None
    by_decision = {}
    for e in entries:
        by_decision.setdefault(e.get("decision"), []).append(e)
    today = datetime.date.today().isoformat()
    paragraphs = [
        f"Matchday tests every proposed model feature against a real out-of-sample "
        f"baseline before it's allowed anywhere near a live pick — no feature ships "
        f"just because it sounds sophisticated. As of {today}, {len(entries)} "
        f"feature experiments have a recorded decision.",
    ]
    order = ["keep_production", "keep_shadow", "continue_testing", "reject", "not_yet_run"]
    for decision in order:
        group = by_decision.get(decision) or []
        if not group:
            continue
        label = DECISION_LABELS.get(decision, decision)
        lines = []
        for e in group:
            detail = e.get("decision_detail") or e.get("evaluation") or ""
            lines.append(f"{e.get('feature_family')} ({e.get('sport')}) — {detail}")
        paragraphs.append(f"{label.capitalize()} ({len(group)}): " + " | ".join(lines))
    paragraphs.append(
        "Full methodology, evaluation numbers, and citations for every row above "
        "are public in this repository's docs/experiments.json and "
        "docs/PREDICTION_RESEARCH_ROADMAP.md — nothing here is summarized from a "
        "private dataset."
    )
    slug = "research-001-model-experiments"
    return {
        "id": slug, "slug": slug, "kind": "research",
        "title": "Research #001 — What Matchday's model experiments have found so far",
        "date": today,
        "summary": f"{len(entries)} model-feature experiments, tracked openly: what got kept, "
                   f"what got rejected, and what's still being tested.",
        "body": paragraphs,
    }


def _calibration_post(comp_key="mlb", comp_label="MLB"):
    picks = _load_json(f"picks_log_{comp_key}.json", {})
    graded = [p for p in picks.values()
              if isinstance(p, dict) and p.get("result")
              and not str(p.get("fixture_id") or "").startswith("legacy")]
    if len(graded) < 10:
        return None
    bands = [("50-60", 50, 60), ("60-70", 60, 70), ("70-80", 70, 80),
             ("80-90", 80, 90), ("90+", 90, 101)]
    rows = []
    for lbl, lo, hi in bands:
        grp = [p for p in graded if lo <= (p.get("confidence") or 0) < hi]
        if grp:
            hits = sum(1 for p in grp if p.get("model_hit"))
            rows.append((lbl, len(grp), hits, round(100 * hits / len(grp))))
    if not rows:
        return None
    today = datetime.date.today().isoformat()
    lines = [f"When Matchday said {lbl}%, the pick actually won {actual}% of the time ({hits}/{n})."
             for lbl, n, hits, actual in rows]
    paragraphs = [
        f"A model's probabilities are only useful if they mean what they say — a pick "
        f"made at 70% confidence should win close to 70% of the time, not 90% or 50%. "
        f"This checks Matchday's {comp_label} picks against that bar, computed from the "
        f"complete verified {comp_label} pick log ({len(graded)} graded, pregame-locked "
        f"picks as of {today}), not a cherry-picked subset.",
    ] + lines + [
        f"Sample size note: {len(graded)} graded picks is small — any single band can "
        f"easily be off by 10-15 points from noise alone. This is an early read, not a "
        f"settled result, and will be revisited as the verified sample grows. See the "
        f"in-app Scorecard for the always-current version of this same table.",
    ]
    slug = f"research-002-calibration-{comp_key}"
    return {
        "id": slug, "slug": slug, "kind": "research",
        "title": f"Research #002 — How well-calibrated are Matchday's {comp_label} picks?",
        "date": today,
        "summary": f"Checking {len(graded)} verified, graded {comp_label} picks: when the "
                   f"model says X%, does it happen X% of the time?",
        "body": paragraphs,
    }


def render_research_post_html(post):
    url = f"{BASE_URL}posts/{post['slug']}.html"
    title = f"{post['title']} · Matchday"
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
<p class="eyebrow">MATCHDAY RESEARCH</p>
<h1>{_esc(post['title'])}</h1>
<div class="meta"><span>{_esc(post['date'])}</span><span>Research</span></div>
{body_html}
<nav class="articleActions" aria-label="Continue exploring">
<a href="../index.html?view=score">Open scorecard</a>
<a href="../index.html?view=insights">More Insights</a>
</nav>
<div class="notice"><strong>Use the information your way.</strong> Matchday publishes probabilities, market context, and a public track record. See the <a href="../qa.html">Q&amp;A page</a> for how predictions are built and the <a href="../legal.html">data sources and legal notice</a>.</div>
<p class="foot"><a href="../index.html">Matchday</a> — pregame predictions, market context and postgame grading.</p>
</div>
</body>
</html>
"""


def build_research_posts():
    posts = [p for p in (_experiments_post(), _calibration_post()) if p]
    if not posts:
        return []
    os.makedirs(POSTS_DIR, exist_ok=True)
    for post in posts:
        with open(os.path.join(POSTS_DIR, f"{post['slug']}.html"), "w", encoding="utf-8") as f:
            f.write(render_research_post_html(post))
    _save_json(RESEARCH_POSTS_FILE, posts)
    return posts


if __name__ == "__main__":
    built = build_research_posts()
    print(f"Built {len(built)} research post(s): " + ", ".join(p["slug"] for p in built))
