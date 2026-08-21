"""Presentation primitives shared by every generated post page.

Extracted from generate_posts so build_research_posts can use them without an
import cycle. build_research_posts needed exactly four names from
generate_posts -- the site URL, the social card image, the HTML escaper and the
post stylesheet -- while generate_posts needed build_research_posts() to
regenerate the sitemap. Four presentation constants were the whole reason those
two modules imported each other, and generate_posts had to defer its import
into a function body to break the loop at runtime.

Nothing here knows about posting schedules, ledgers or providers. It is layout,
and both pipelines are free to depend on it.
"""

BASE_URL = "https://matchdayterminal.com/"
SOCIAL_IMAGE_URL = "https://matchdayterminal.com/icon-512.png"


def _esc(s):
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


POST_CSS = """:root{--bg:#070a0f;--panel:#111822;--text:#eef2f8;--muted:#9ba8b8;--faint:#647184;--line:#263244;--signal:#3ad17a;--link:#76caff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,rgba(58,209,122,.1),transparent 30%),var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;line-height:1.65}.wrap{width:min(760px,calc(100% - 40px));margin:auto;padding:44px 0 76px}.postNav{display:flex;align-items:center;justify-content:space-between;gap:16px}.postNav a{color:var(--muted);font-family:"JetBrains Mono",monospace;font-size:.75rem;text-decoration:none}.postNav a:hover{color:var(--signal)}.eyebrow{margin:36px 0 12px;color:var(--signal);font:700 .68rem "JetBrains Mono",monospace;letter-spacing:.14em}h1{font-family:Archivo,sans-serif;font-size:clamp(1.8rem,5vw,2.8rem);letter-spacing:-.04em;line-height:1.05;margin:0 0 10px}.meta{display:flex;flex-wrap:wrap;gap:10px;color:var(--faint);font:500 .7rem "JetBrains Mono",monospace;margin-bottom:26px}.meta span{border:1px solid var(--line);border-radius:999px;padding:5px 9px}p{color:#c9d2de;margin:0 0 16px;font-size:1.02rem}a{color:var(--link)}.articleActions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:28px 0}.articleActions a{padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);font:700 .7rem/1.25 "JetBrains Mono",monospace;text-decoration:none}.articleActions a:hover{border-color:var(--signal);color:var(--signal)}.notice{border-left:3px solid var(--signal);background:rgba(58,209,122,.07);border-radius:7px;padding:12px 14px;color:#d8dde5;font-size:.85rem;margin-top:30px}.foot{margin-top:34px;color:var(--faint);font-size:.75rem}@media(max-width:560px){.articleActions{grid-template-columns:1fr}}"""
