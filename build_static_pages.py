"""build_static_pages.py -- crawlable pages for teams, games and the field guide.

The app is one document: every view is `/?view=...`, and the HTML a crawler
receives is the welcome copy followed by "Loading...". Nothing on the site had
an address of its own, so a search engine or an assistant had no page to send
anyone to for a team, a game or a term.

This writes a plain HTML page for each of those at deploy time:

    /learn/                               Learn: the lessons
    /learn/glossary/                      every term, each with an anchor
    /college-football/                    hub, plus /teams/ and /games/
    /college-football/teams/<team>/       one page per rated team
    /college-football/games/<game>/       upcoming forecasts and graded picks
    /college-basketball/...               the same for men's basketball

It forecasts nothing. Every number is read from `matchday-cfb-snapshot.js`,
the same file the app renders, so a page can never disagree with the app. The
lesson and glossary copy is read from `app-learn.js` for the same reason: one
place to edit, two places it shows.

Game pages exist for two kinds of game only: one with a live forecast, and one
with a locked, graded pick. Both carry something to read. A finished game that
was never graded gets no page, because the results window in the snapshot
slides and its address would stop working within days.

    python build_static_pages.py _site
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import sys
import unicodedata

from post_layout import BASE_URL, SOCIAL_IMAGE_URL, _esc

SNAPSHOT = pathlib.Path("matchday-cfb-snapshot.js")
LEARN_SOURCE = pathlib.Path("app-learn.js")
STYLESHEET = pathlib.Path("pages.css")

SPORTS = {
    "ncaaf": {
        "path": "college-football",
        "label": "College football",
        "rankings": "MATCHDAY_CFB_RANKINGS",
        "profiles": "MATCHDAY_TRDLAB_TEAM_PROFILES",
        "average": "an average FBS team",
        "start": "kickoff",
    },
    "ncaam": {
        "path": "college-basketball",
        "label": "Men's college basketball",
        "rankings": "MATCHDAY_NCAAM_RANKINGS",
        "profiles": "MATCHDAY_TRDLAB_NCAAM_PROFILES",
        "average": "an average Division I team",
        "start": "tipoff",
    },
}

NOT_ADVICE = ("Matchday compares against the market as a test of the model, "
              "not as betting advice.")


# --------------------------------------------------------------------------
# Reading the two sources
# --------------------------------------------------------------------------

def load_snapshot(path: pathlib.Path = SNAPSHOT) -> dict:
    """Every `const NAME=<json>` block in the snapshot, by name."""
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    out: dict = {}
    for match in re.finditer(r"^\s*const ([A-Z][A-Z0-9_]*)\s*=\s*", text, re.M):
        try:
            out[match.group(1)], _ = decoder.raw_decode(text, match.end())
        except ValueError:
            continue
    return out


def _js_string(raw: str) -> str:
    return raw.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


_QUOTED = r"'((?:[^'\\]|\\.)*)'"


def load_learn(path: pathlib.Path = LEARN_SOURCE) -> tuple[list[dict], list[tuple[str, str]]]:
    """Lessons and glossary as written in app-learn.js.

    Only sections whose body is a plain string are taken; the ones the app
    builds from live data are rebuilt here by `_lesson_data`.
    """
    text = path.read_text(encoding="utf-8")
    start, glossary_at = text.index("const LESSONS=["), text.index("const GLOSSARY=[")
    body = text[start:glossary_at]
    heads = list(re.finditer(r"\{id:'(\w+)',title:" + _QUOTED + r",hook:" + _QUOTED, body))
    lessons = []
    for i, head in enumerate(heads):
        span = body[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        sections = [(_js_string(t), _js_string(b))
                    for t, b in re.findall(r"\[" + _QUOTED + r"," + _QUOTED + r"\]", span) if t and b]
        lessons.append({"id": head.group(1), "title": _js_string(head.group(2)),
                        "hook": _js_string(head.group(3)), "sections": sections})
    glossary_body = text[glossary_at:text.index("];", glossary_at)]
    glossary = [(_js_string(t), _js_string(d))
                for t, d in re.findall(r"\[" + _QUOTED + r"," + _QUOTED + r"\]", glossary_body)]
    return lessons, glossary


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def slug(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"['’.&]", "", text.lower())
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def eastern(value: str) -> dt.datetime | None:
    """A provider UTC timestamp as US Eastern wall time.

    Done by hand so the build needs no time-zone database: daylight time runs
    from 07:00 UTC on March's second Sunday to 06:00 UTC on November's first.
    """
    match = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)", str(value or ""))
    if not match:
        return None
    utc = dt.datetime(*map(int, match.groups()))
    begins = dt.datetime.combine(_nth_sunday(utc.year, 3, 2), dt.time(7))
    ends = dt.datetime.combine(_nth_sunday(utc.year, 11, 1), dt.time(6))
    return utc - dt.timedelta(hours=4 if begins <= utc < ends else 5)


def _day(when: dt.datetime) -> str:
    return f"{when:%a}, {when:%b} {when.day}, {when.year}"


def _short_day(when: dt.datetime) -> str:
    return f"{when:%a}, {when:%b} {when.day}"


def _clock(when: dt.datetime) -> str:
    return f"{(when.hour % 12) or 12}:{when:%M} {'AM' if when.hour < 12 else 'PM'} ET"


def _num(value, places: int = 1, sign: bool = False) -> str:
    if value is None:
        return "–"
    return f"{float(value):{'+' if sign else ''}.{places}f}"


def _pct(value, places: int = 1) -> str:
    return "–" if value is None else f"{float(value):.{places}f}%"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _ranks(rows: list[dict], key: str, high_is_first: bool = True) -> dict[str, int]:
    have = [r for r in rows if r.get(key) is not None]
    have.sort(key=lambda r: r[key], reverse=high_is_first)
    return {r["name"]: i + 1 for i, r in enumerate(have)}


# --------------------------------------------------------------------------
# The page shell
# --------------------------------------------------------------------------

class Site:
    def __init__(self, out: pathlib.Path, build: str, keep: bool = False):
        self.out, self.build, self.urls = out, build, []
        # path -> html, held only when asked, so tests can read the pages
        # without re-opening two thousand files.
        self.pages: dict[str, str] | None = {} if keep else None

    def write(self, path: str, *, title: str, description: str, crumbs: list[tuple[str, str]],
              heading: str, tag: str, body: str, schema: list[dict] | None = None, app: str = "/",
              lastmod: str = "", changefreq: str = "daily", priority: str = "0.6") -> None:
        url = BASE_URL + path
        trail = [("Matchday", "")] + crumbs
        graph = [{
            "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": name,
                                 "item": BASE_URL + href} for i, (name, href) in enumerate(trail)],
        }] + (schema or [])
        ld = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")
        crumb_html = " <span aria-hidden=\"true\">/</span> ".join(
            f'<a href="/{_esc(href)}">{_esc(name)}</a>' for name, href in trail[:-1])
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{_esc(title)} | Matchday Terminal</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Matchday Terminal">
<meta property="og:url" content="{_esc(url)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:image" content="{SOCIAL_IMAGE_URL}">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#070a0f">
<link rel="icon" href="/favicon.ico?v=4" sizes="any">
<link rel="apple-touch-icon" href="/icon-180.png?v=4">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&amp;family=Inter:wght@400;500;600;700&amp;family=JetBrains+Mono:wght@400;500;600;700&amp;display=swap" rel="stylesheet">
<link rel="stylesheet" href="/pages.css?v={_esc(self.build)}">
<script type="application/ld+json">{ld}</script>
</head>
<body>
<header class="pgTop">
  <a class="pgBrand" href="/"><img src="/icon-192.png?v=4" alt="" width="22" height="22">Matchday Terminal</a>
  <nav class="pgNav" aria-label="Site">
    <a href="/college-football/">College football</a>
    <a href="/college-basketball/">College basketball</a>
    <a href="/learn/">Learn</a>
    <a class="pgOpen" href="{_esc(app)}">Open the app</a>
  </nav>
</header>
<main class="pgMain">
  <nav class="pgCrumbs" aria-label="Breadcrumb">{crumb_html}</nav>
  <div class="pgHead"><h1>{_esc(heading)}</h1><span class="pgTag">{_esc(tag)}</span></div>
{body}
</main>
<footer class="pgFoot">
  <p>Free · No account · No ads. {_esc(NOT_ADVICE)}</p>
  <nav aria-label="More"><a href="/qa.html">How it works</a><a href="/roadmap.html">Roadmap</a><a href="/legal.html">Legal &amp; data sources</a></nav>
</footer>
</body>
</html>
"""
        target = self.out / path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8", newline="\n")
        if self.pages is not None:
            self.pages[f"/{path}"] = html
        self.urls.append((url, lastmod, changefreq, priority))


def _section(label: str, inner: str) -> str:
    return f'  <section class="pgSection"><h2 class="seclbl">{_esc(label)}</h2>{inner}</section>\n' if inner else ""


def _tiles(items: list[tuple[str, str, str]]) -> str:
    """(label, value, note) cards; `value` may carry markup."""
    cells = "".join(
        f'<div class="pgTile"><span>{_esc(label)}</span><b>{value}</b>{f"<em>{_esc(note)}</em>" if note else ""}</div>'
        for label, value, note in items if value not in (None, "", "–"))
    return f'<div class="pgTiles">{cells}</div>' if cells else ""


def _table(head: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    if not rows:
        return ""
    cls = lambda i: ' class="n"' if i in numeric else ""
    thead = "".join(f"<th scope=\"col\"{cls(i)}>{_esc(h)}</th>" for i, h in enumerate(head))
    tbody = "".join("<tr>" + "".join(f"<td{cls(i)}>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="pgScroll"><table class="pgTable"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>'


def _explain(summary: str, paragraphs: list[str]) -> str:
    inner = "".join(f"<p>{p}</p>" for p in paragraphs if p)
    return f'  <details class="pgExplain"><summary>{_esc(summary)}</summary>{inner}</details>\n' if inner else ""


def _green(text: str) -> str:
    return f'<span class="pct">{_esc(text)}</span>'


# --------------------------------------------------------------------------
# One sport's data, joined once
# --------------------------------------------------------------------------

class Sport:
    def __init__(self, key: str, snap: dict, now: dt.datetime | None = None):
        self.key, self.cfg = key, SPORTS[key]
        # Eastern wall time of this build. The snapshot is only as new as the
        # engine's last push, so some of its "upcoming" games have started.
        self.now = now or eastern(dt.datetime.now(dt.timezone.utc).isoformat())
        self.path = self.cfg["path"]
        table = snap.get(self.cfg["rankings"]) or {}
        self.table = table
        self.teams = [t for t in table.get("rankings") or [] if t.get("name")]
        self.by_name = {t["name"]: t for t in self.teams}
        self.slugs = {t["name"]: slug(t["name"]) for t in self.teams}
        self.profiles = (snap.get(self.cfg["profiles"]) or {}).get("teams") or {}
        self.card = ((snap.get("MATCHDAY_TRDLAB_SCORECARD") or {}).get("sports") or {}).get(key) or {}
        self.results = [r for r in snap.get("MATCHDAY_TRDLAB_RESULTS") or [] if r.get("sport") == key]
        self.rank = {k: _ranks(self.teams, k, hi) for k, hi in
                     (("sos", True), ("adj_o", True), ("adj_d", False))}
        self.app = f"/?view=home&sport={key}"
        self.games = self._games(snap)
        self._upcoming = sorted((g for g in self.games.values() if "pick" in g and g["when"] > self.now),
                                key=lambda g: g["when"])
        self._graded = sorted((g for g in self.games.values() if "locked" in g),
                              key=lambda g: g["when"], reverse=True)

    def team_link(self, name: str) -> str:
        if name in self.slugs:
            return f'<a href="/{self.path}/teams/{self.slugs[name]}/">{_esc(name)}</a>'
        return _esc(name)

    def _games(self, snap: dict) -> dict[str, dict]:
        """Every game that earns a page, by slug. A locked pick outranks a live read."""
        games: dict[str, dict] = {}
        result_by_key = {(r.get("home"), r.get("away"), r.get("played_on")): r for r in self.results}
        for row in self.card.get("recent") or []:
            away, sep, home = str(row.get("event_name") or "").partition(" at ")
            when = eastern(row.get("starts_at"))
            if not sep or not when:
                continue
            key = f"{when:%Y-%m-%d}-{slug(away)}-at-{slug(home)}"
            games.setdefault(key, {"slug": key, "home": home, "away": away, "when": when, "locked": row,
                                   "result": result_by_key.get((home, away, f"{when:%Y-%m-%d}"))})
        for pick in snap.get("MATCHDAY_TRDLAB_PICKS") or []:
            when = eastern(pick.get("kickoff"))
            if pick.get("sport") != self.key or not when or pick.get("model_pct") is None:
                continue
            key = f"{when:%Y-%m-%d}-{slug(pick.get('away'))}-at-{slug(pick.get('home'))}"
            games.setdefault(key, {"slug": key, "home": pick.get("home"), "away": pick.get("away"),
                                   "when": when, "pick": pick})
        return games

    def game_link(self, game: dict, text: str) -> str:
        return f'<a href="/{self.path}/games/{game["slug"]}/">{text}</a>'

    def upcoming(self) -> list[dict]:
        return self._upcoming

    def graded(self) -> list[dict]:
        return self._graded

    def side_pct(self, pick: dict, name: str):
        for side in pick.get("sides") or []:
            if side.get("selection") == name:
                return side.get("model_pct")
        return None

    def market_pct(self, pick: dict, name: str):
        market = pick.get("market_pct")
        if market is None:
            return None
        return market if pick.get("pick_name") == name else round(100 - market, 1)


# --------------------------------------------------------------------------
# Team pages
# --------------------------------------------------------------------------

def _team_page(site: Site, sport: Sport) -> None:
    total, edition = len(sport.teams), sport.table.get("published_on") or ""
    season = sport.table.get("season")
    for team in sport.teams:
        name, path = team["name"], f"{sport.path}/teams/{sport.slugs[team['name']]}/"
        rank, rating = team.get("rank"), team.get("rating")
        move = team.get("movement")
        moved = "" if not move else (f"up {move} this week" if move > 0 else f"down {-move} this week")
        tiles = _tiles([
            ("Power rating", _esc(_num(rating, 2)), ""),
            ("Rank", f"#{rank}", f"of {total}" + (f" · {moved}" if moved else "")),
            ("Record", _esc(team.get("record") or ""), ""),
            ("Strength of schedule", _esc(_num(team.get("sos"), 2)),
             f"{_ordinal(sport.rank['sos'][name])} toughest" if name in sport.rank["sos"] else ""),
            ("Adj. offense", _esc(_num(team.get("adj_o"))),
             f"{_ordinal(sport.rank['adj_o'][name])}" if name in sport.rank["adj_o"] else ""),
            ("Adj. defense", _esc(_num(team.get("adj_d"))),
             f"{_ordinal(sport.rank['adj_d'][name])}" if name in sport.rank["adj_d"] else ""),
        ])
        body = "  " + tiles + "\n"

        ahead = [g for g in sport.upcoming() if name in (g["home"], g["away"])]
        rows = []
        for game in ahead:
            pick, home = game["pick"], game["home"] == name
            other = game["away"] if home else game["home"]
            rows.append([
                sport.game_link(game, _esc(_short_day(game["when"]))),
                ("vs " if home else "at ") + sport.team_link(other),
                _green(_pct(sport.side_pct(pick, name))),
                _esc(_pct(sport.market_pct(pick, name))),
            ])
        body += _section("Upcoming games", _table(["Date", "Opponent", "Model win chance", "Market"], rows, {2, 3}))

        played = sorted((r for r in sport.results if name in (r.get("home"), r.get("away"))),
                        key=lambda r: r.get("played_on") or "", reverse=True)
        rows = []
        for res in played:
            home = res["home"] == name
            mine, theirs = (res["home_score"], res["away_score"]) if home else (res["away_score"], res["home_score"])
            won = res.get("winner") == name
            when = eastern(res.get("kickoff"))
            rows.append([
                _esc(_short_day(when) if when else res.get("played_on") or ""),
                ("vs " if home or res.get("neutral") else "at ") + sport.team_link(res["away"] if home else res["home"]),
                f'<span class="{"win" if won else "loss"}">{"W" if won else "L"}</span> {int(mine)}–{int(theirs)}',
            ])
        body += _section("Recent results", _table(["Date", "Opponent", "Result"], rows, {2}))

        prof = sport.profiles.get(name) or {}
        if sport.key == "ncaaf" and prof.get("ppa_adj") is not None:
            body += _section("Efficiency, opponent-adjusted", _tiles([
                ("EPA per play", _esc(_num(prof.get("ppa_adj"), 3, sign=True)), "offense"),
                ("EPA allowed per play", _esc(_num(prof.get("def_ppa_allowed_adj"), 3, sign=True)), "defense"),
                ("Success rate", _green(_pct((prof.get("success_rate_adj") or 0) * 100)), "offense"),
                ("Success rate allowed", _green(_pct((prof.get("def_success_rate_allowed_adj") or 0) * 100)), "defense"),
            ]))
        if sport.key == "ncaam" and prof.get("efg") is not None:
            factor = lambda k: _green(_pct((prof.get(k) or 0) * 100))
            body += _section("Four factors", _table(
                ["", "Shooting (eFG%)", "Turnover rate", "Off. rebound rate", "Free-throw rate"],
                [["Offense", factor("efg"), factor("tov_rate"), factor("orb_rate"), factor("ft_rate")],
                 ["Defense", factor("def_efg"), factor("def_tov_rate"), factor("def_orb_rate"), factor("def_ft_rate")]],
                {1, 2, 3, 4}) + (f'<p class="pgNote">Tempo {_esc(_num(prof.get("tempo")))} possessions per game, '
                                 f'over {int(prof.get("games") or 0)} games.</p>' if prof.get("tempo") else ""))

        margin = abs(float(rating or 0))
        verb = "beat" if (rating or 0) >= 0 else "lose to"
        body += _explain("What these numbers mean", [
            f"A rating of {_esc(_num(rating, 2))} means {_esc(name)} would be expected to {verb} "
            f"{sport.cfg['average']} by about {margin:.0f} points on a neutral field. "
            f'<a href="/learn/what-a-rating-is/">What a rating is</a>.',
            (f"Its opponents so far average a rating of {_esc(_num(team.get('sos'), 2))}, the "
             f"{_ordinal(sport.rank['sos'][name])} toughest schedule of {total}. "
             f'<a href="/learn/strength-of-schedule/">Why schedule matters</a>.') if name in sport.rank["sos"] else "",
            (f"Against an average opponent it would be expected to score about {_esc(_num(team.get('adj_o')))} "
             f"points and allow about {_esc(_num(team.get('adj_d')))}.") if team.get("adj_o") is not None else "",
            (f"It started the season ranked {_ordinal(team['preseason_rank'])}. "
             f'<a href="/learn/preseason-ratings/">How preseason ratings are built</a>.')
            if team.get("preseason_rank") else "",
            'A win chance is how often a team would win the same game played many times. '
            '<a href="/learn/win-probability/">Reading a win probability</a>.',
        ])
        body += (f'  <p class="pgNote">Ratings edition {_esc(edition)}. '
                 f'<a href="/?view=rankings&amp;sport={sport.key}">See every team in the app</a>.</p>\n')

        conf = team.get("conference") or ""
        site.write(
            path,
            title=f"{name}: {season} power rating, schedule and win probabilities",
            description=(f"{name} are rated {_num(rating, 2)}, #{rank} of {total}, at {team.get('record') or 'no record yet'}. "
                         f"Strength of schedule, offense and defense ratings, and a win probability for every upcoming game."),
            crumbs=[(sport.cfg["label"], f"{sport.path}/"), ("Teams", f"{sport.path}/teams/"), (name, path)],
            heading=name,
            tag=" · ".join(x for x in (conf, f"{season} team rating") if x),
            body=body,
            schema=[{"@type": "SportsTeam", "name": name, "sport": sport.cfg["label"],
                     **({"memberOf": {"@type": "SportsOrganization", "name": conf}} if conf else {})}],
            lastmod=edition, priority="0.7", app=f"/?view=rankings&sport={sport.key}",
        )


# --------------------------------------------------------------------------
# Game pages
# --------------------------------------------------------------------------

def _compare(sport: Sport, game: dict) -> str:
    rows = []
    for name in (game["away"], game["home"]):
        team = sport.by_name.get(name)
        if team:
            rows.append([sport.team_link(name), f"#{team.get('rank')}", _esc(_num(team.get("rating"), 2)),
                         _esc(team.get("record") or ""), _esc(_num(team.get("adj_o"))),
                         _esc(_num(team.get("adj_d"))), _esc(_num(team.get("sos"), 2))])
    return _table(["Team", "Rank", "Rating", "Record", "Adj. offense", "Adj. defense", "Schedule"], rows,
                  {1, 2, 3, 4, 5, 6})


def _game_page(site: Site, sport: Sport, game: dict, generated: str) -> None:
    home, away, when = game["home"], game["away"], game["when"]
    path = f"{sport.path}/games/{game['slug']}/"
    crumbs = [(sport.cfg["label"], f"{sport.path}/"), ("Games", f"{sport.path}/games/"),
              (f"{away} at {home}", path)]
    lock_rule = (sport.card.get("lock_policy") or {}).get("rule") or ""

    if "locked" in game:
        row, res = game["locked"], game.get("result")
        pending = row.get("result") not in ("win", "loss")
        won = row.get("result") == "win"
        home_score, _, away_score = str(row.get("score") or "").partition("–")
        final = (f"{_esc(away)} {_esc(away_score)}, {_esc(home)} {_esc(home_score)}"
                 if home_score and away_score and not pending else "")
        tiles = _tiles([
            ("Locked pick", _esc(row.get("selection") or ""), "frozen an hour before the start"),
            ("Model win chance", _green(_pct(row.get("probability_pct"))), "at the lock"),
            ("Market", _esc(_pct(row.get("market_probability_pct"))), "no-vig price at the lock"),
            ("Result", "Awaiting final" if pending else
             f'<span class="{"win" if won else "loss"}">{"Won" if won else "Lost"}</span>', ""),
        ])
        body = (f'  <p class="pgFinal">{final}</p>\n' if final else "") + "  " + tiles + "\n"
        metrics = (res or {}).get("play_metrics") or {}
        if metrics.get("home") and metrics.get("away"):
            rows = [[sport.team_link(n), str(m.get("plays") or ""), _esc(_num(m.get("epa_per_play"), 3, sign=True)),
                     _green(_pct((m.get("success_rate") or 0) * 100))]
                    for n, m in ((away, metrics["away"]), (home, metrics["home"]))]
            body += _section("How it played", _table(["Team", "Plays", "EPA per play", "Success rate"], rows, {1, 2, 3}))
        body += _section("The two teams today", _compare(sport, game))
        body += _explain("How a pick is locked and graded", [
            _esc(lock_rule),
            'The pick is graded on one question: did the team the model favoured win. '
            '<a href="/learn/reading-the-scorecard/">Reading the scorecard</a>.',
            'EPA per play is how much each play changed the expected score; success rate is the share of plays '
            'that kept the offense on schedule. <a href="/learn/football-efficiency/">Football efficiency</a>.'
            if metrics else "",
        ])
        body += (f'  <p class="pgNote"><a href="/?view=score&amp;sport={sport.key}">'
                 f'See the full graded record in the app</a>.</p>\n')
        outcome = "awaiting a final score" if pending else ("won" if won else "lost")
        site.write(
            path,
            title=f"{away} at {home}, {_day(when)}: locked pick and result",
            description=(f"Matchday locked {row.get('selection')} at {_pct(row.get('probability_pct'))} before "
                         f"{away} at {home}. The pick {outcome}." + (f" Final: {away} {away_score}, {home} {home_score}." if final else "")),
            crumbs=crumbs, heading=f"{away} at {home}",
            tag=f"{_day(when)} · {'locked' if pending else 'final'}",
            body=body, lastmod=f"{when:%Y-%m-%d}", changefreq="monthly" if not pending else "daily", priority="0.4",
            app=f"/?view=score&sport={sport.key}",
        )
        return

    pick = game["pick"]
    favourite = pick.get("pick_name") or ""
    line, score = pick.get("model_line") or {}, pick.get("projected_score") or {}
    margin = line.get("home_margin")
    tiles = _tiles([
        (f"{away} win chance", _green(_pct(sport.side_pct(pick, away))), "model"),
        (f"{home} win chance", _green(_pct(sport.side_pct(pick, home))), "model"),
        ("Market", _esc(_pct(pick.get("market_pct"))), f"{favourite}, no-vig price" if pick.get("market_pct") is not None else ""),
        ("Projected score", _esc(f"{score.get('away')}–{score.get('home')}") if score.get("home") is not None else "",
         f"{away} – {home}"),
        ("Projected margin", _esc(f"{home if margin >= 0 else away} by {abs(margin):.1f}") if margin is not None else "", ""),
        ("Projected total", _esc(_num(line.get("total"))), "points"),
    ])
    body = "  " + tiles + "\n"
    body += f'  <p class="pgNote">{_esc(pick.get("integrity_note") or "")}</p>\n' if pick.get("integrity_note") else ""
    body += _section("The two teams", _compare(sport, game))
    body += _explain("How to read this forecast", [
        f"A win chance is how often a team would win if this game were played many times. It is not a promise. "
        f'<a href="/learn/win-probability/">Reading a win probability</a>.',
        "The market number is the sportsbook price with the bookmaker's margin removed, read as a win probability. "
        f'{_esc(NOT_ADVICE)} <a href="/learn/model-vs-market/">Model vs market</a>.',
        _esc(lock_rule),
    ])
    body += (f'  <p class="pgNote">Forecast generated {_esc(str(pick.get("generated_at") or generated)[:16].replace("T", " "))} UTC. '
             f'<a href="/?view=games&amp;sport={sport.key}">See this week\'s games in the app</a>.</p>\n')
    site.write(
        path,
        title=f"{away} at {home} prediction, {_day(when)}: win probability and projected score",
        description=(f"Matchday's live forecast for {away} at {home} on {_day(when)}: {favourite} "
                     f"{_pct(pick.get('model_pct'))} to win" +
                     (f", against a market price of {_pct(pick.get('market_pct'))}" if pick.get("market_pct") is not None else "") +
                     ". Projected score, margin and both teams' ratings."),
        crumbs=crumbs, heading=f"{away} at {home}",
        tag=f"{_day(when)} · {_clock(when)} · " + ("live forecast" if when > sport.now else "forecast, awaiting result"),
        body=body, lastmod=generated[:10], changefreq="hourly", priority="0.6",
        app=f"/?view=games&sport={sport.key}",
    )


# --------------------------------------------------------------------------
# Hubs and lists
# --------------------------------------------------------------------------

def _ratings_rows(sport: Sport, teams: list[dict]) -> list[list[str]]:
    return [[f"{t.get('rank')}", sport.team_link(t["name"]), _esc(t.get("conference") or ""),
             _esc(_num(t.get("rating"), 2)), _esc(t.get("record") or ""), _esc(_num(t.get("sos"), 2))] for t in teams]


def _upcoming_rows(sport: Sport, games: list[dict]) -> list[list[str]]:
    return [[_esc(f"{_short_day(g['when'])} · {_clock(g['when'])}"),
             sport.game_link(g, f"{_esc(g['away'])} at {_esc(g['home'])}"),
             _esc(g["pick"].get("pick_name") or ""), _green(_pct(g["pick"].get("model_pct"))),
             _esc(_pct(g["pick"].get("market_pct")))] for g in games]


def _graded_rows(sport: Sport, games: list[dict]) -> list[list[str]]:
    rows = []
    for g in games:
        row = g["locked"]
        state = row.get("result")
        mark = (f'<span class="{state}">{"Won" if state == "win" else "Lost"}</span>'
                if state in ("win", "loss") else "Awaiting final")
        rows.append([_esc(_short_day(g["when"])), sport.game_link(g, f"{_esc(g['away'])} at {_esc(g['home'])}"),
                     _esc(row.get("selection") or ""), _green(_pct(row.get("probability_pct"))), mark])
    return rows


def _record_tiles(sport: Sport) -> str:
    rec = sport.card.get("record") or {}
    if not rec.get("picks"):
        return ""
    # Never the hit rate alone: the cards are mostly favourites, so it is read
    # next to what the model's own probabilities expected.
    return _tiles([
        ("Graded picks", f"{rec.get('wins')}–{rec.get('losses')}", "wins–losses"),
        ("Hit rate", _green(_pct(rec.get("hit_rate_pct"))), f"{_pct(rec.get('expected_hit_rate_pct'))} expected"),
    ])


def _sport_pages(site: Site, sport: Sport, generated: str) -> None:
    label, season = sport.cfg["label"], sport.table.get("season")
    edition = sport.table.get("published_on") or ""
    head = ["#", "Team", "Conference", "Rating", "Record", "Schedule"]
    up, graded = sport.upcoming(), sport.graded()

    body = "  " + _tiles([
        ("Teams rated", str(len(sport.teams)), ""),
        ("Games with a forecast", str(len(up)), ""),
    ]) + "\n"
    body += _section("Next games", _table(["When", "Game", "Model pick", "Win chance", "Market"],
                                          _upcoming_rows(sport, up[:12]), {3, 4})
                     + f'<p class="pgMore"><a href="/{sport.path}/games/">All games and graded picks</a></p>')
    body += _section("Top 25 by power rating", _table(head, _ratings_rows(sport, sport.teams[:25]), {0, 3, 4, 5})
                     + f'<p class="pgMore"><a href="/{sport.path}/teams/">All {len(sport.teams)} teams</a></p>')
    body += _section("The public record", _record_tiles(sport))
    body += _explain("What a power rating is", [
        f"A rating is how many points a team is better than {sport.cfg['average']} on a neutral field, "
        f"adjusted for the opponents it has played. <a href=\"/learn/what-a-rating-is/\">What a rating is</a>.",
        _esc(str(sport.table.get("note") or "").replace("`", "")),
    ])
    site.write(
        f"{sport.path}/",
        title=f"{label}: {season} power ratings, predictions and graded picks",
        description=(f"Free {label.lower()} research: power ratings for {len(sport.teams)} teams, a win probability "
                     f"for every upcoming game, and every locked pick graded in public."),
        crumbs=[(label, f"{sport.path}/")], heading=label, tag=f"{season} ratings · predictions",
        body=body, lastmod=generated[:10], changefreq="hourly", priority="0.9", app=sport.app,
    )

    site.write(
        f"{sport.path}/teams/",
        title=f"{label} power ratings: all {len(sport.teams)} teams, {season}",
        description=(f"Every {label.lower()} team ranked by opponent-adjusted power rating, with record and "
                     f"strength of schedule. Each team links to its own page."),
        crumbs=[(label, f"{sport.path}/"), ("Teams", f"{sport.path}/teams/")],
        heading=f"{label} teams", tag=f"power ratings · edition {edition}",
        body=_section("Power ratings", _table(head, _ratings_rows(sport, sport.teams), {0, 3, 4, 5})),
        lastmod=edition, priority="0.8", app=f"/?view=rankings&sport={sport.key}",
    )

    body = _section("Upcoming", _table(["When", "Game", "Model pick", "Win chance", "Market"],
                                       _upcoming_rows(sport, up), {3, 4}))
    body += _section("Graded picks", _record_tiles(sport) + _table(
        ["Date", "Game", "Locked pick", "Win chance", "Result"], _graded_rows(sport, graded), {3}))
    site.write(
        f"{sport.path}/games/",
        title=f"{label} predictions and graded picks, {season}",
        description=(f"A win probability for every upcoming {label.lower()} game, and the result of every pick "
                     f"Matchday locked before the start."),
        crumbs=[(label, f"{sport.path}/"), ("Games", f"{sport.path}/games/")],
        heading=f"{label} games", tag="forecasts · graded picks",
        body=body, lastmod=generated[:10], changefreq="hourly", priority="0.8",
        app=f"/?view=games&sport={sport.key}",
    )


# --------------------------------------------------------------------------
# The field guide
# --------------------------------------------------------------------------

def _lesson_data(lesson_id: str, sports: dict[str, Sport]) -> list[tuple[str, str]]:
    """The sections the app draws from live data, as tables."""
    cfb, hoops = sports["ncaaf"], sports["ncaam"]
    rated = lambda sport, rows: _table(["#", "Team", "Rating"], [
        [str(t.get("rank")), sport.team_link(t["name"]), _esc(_num(t.get("rating"), 2))] for t in rows], {0, 2})
    if lesson_id == "rating" and len(cfb.teams) >= 25:
        a, b = cfb.teams[0], cfb.teams[24]
        return [("The top of the board right now", rated(cfb, cfb.teams[:10])),
                ("Reading two ratings together",
                 f"<p>Subtract one rating from another to get the expected margin on a neutral field. "
                 f"{_esc(a['name'])} ({_num(a['rating'], 1)}) against {_esc(b['name'])} ({_num(b['rating'], 1)}) "
                 f"works out to about {_num(a['rating'] - b['rating'], 1)} points.</p>")]
    if lesson_id == "sos":
        have = sorted((t for t in cfb.teams if t.get("sos") is not None), key=lambda t: t["sos"], reverse=True)
        sched = lambda rows: _table(["Team", "Schedule strength"], [
            [cfb.team_link(t["name"]), _esc(_num(t["sos"], 2))] for t in rows], {1})
        return [("Toughest schedules so far", sched(have[:5])), ("Easiest schedules so far", sched(have[-5:][::-1]))] if have else []
    if lesson_id == "probability":
        bands = cfb.card.get("by_confidence") or []
        return [("Did the model mean what it said?", _table(
            ["Model said", "Picks", "Won", "Expected"],
            [[_esc(b.get("band") or ""), str(b.get("picks") or ""), _green(_pct(b.get("hit_rate_pct"), 0)),
              _esc(_pct(b.get("expected_hit_rate_pct"), 0))] for b in bands], {1, 2, 3})
            + '<p class="pgNote">College football picks this season. Rows where "won" sits near "expected" mean '
              'the probabilities can be taken at face value. This is called calibration.</p>')] if bands else []
    if lesson_id == "market":
        rows = []
        for sport in (cfb, hoops):
            vm = sport.card.get("versus_market") or {}
            for name, key in (("agreed with the market", "agreed_with_market"),
                              ("disagreed with the market", "disagreed_with_market")):
                block = vm.get(key) or {}
                if block.get("picks"):
                    rows.append([_esc(f"{sport.cfg['label']}, {name}"), f"{block.get('wins')}–{block.get('losses')}",
                                 _green(_pct(block.get("hit_rate_pct"), 0)), _esc(_pct(block.get("expected_hit_rate_pct"), 0))])
        return [("The record so far", _table(["Picks", "Record", "Won", "Expected"], rows, {1, 2, 3}))] if rows else []
    if lesson_id == "efficiency":
        have = sorted(((n, p) for n, p in cfb.profiles.items() if n in cfb.by_name and p.get("ppa_adj") is not None),
                      key=lambda x: x[1]["ppa_adj"], reverse=True)[:8]
        return [("The most efficient offenses right now", _table(
            ["Team", "EPA per play", "Success rate"],
            [[cfb.team_link(n), _esc(_num(p["ppa_adj"], 3, sign=True)), _green(_pct((p.get("success_rate_adj") or 0) * 100))]
             for n, p in have], {1, 2}) + '<p class="pgNote">Opponent-adjusted.</p>')] if have else []
    if lesson_id == "basketball":
        have = sorted(((n, p) for n, p in hoops.profiles.items() if p.get("tempo")), key=lambda x: x[1]["tempo"], reverse=True)
        if len(have) < 8:
            return []
        pace = lambda rows: _table(["Team", "Possessions per game"], [
            [hoops.team_link(n), _esc(_num(p["tempo"]))] for n, p in rows], {1})
        return [("Fastest teams", pace(have[:4])), ("Slowest teams", pace(have[-4:][::-1]))]
    if lesson_id == "preseason" and hoops.teams:
        return [("The basketball top eight today", rated(hoops, hoops.teams[:8]))]
    if lesson_id == "scorecard":
        return [(f"{s.cfg['label']}, the season so far", _record_tiles(s)) for s in (cfb, hoops) if _record_tiles(s)]
    return []


CURRENT = ' aria-current="page"'


def _learn_pages(site: Site, sports: dict[str, Sport], generated: str) -> None:
    lessons, glossary = load_learn()
    for lesson in lessons:
        lesson["slug"] = slug(lesson["title"])
    today = generated[:10]

    cards = "".join(
        f'<a class="pgCard" href="/learn/{l["slug"]}/"><strong>{_esc(l["title"])}</strong><span>{_esc(l["hook"])}</span></a>'
        for l in lessons)
    body = f'  <div class="pgCards">{cards}</div>\n'
    body += _section("Glossary", f'<p class="pgMore"><a href="/learn/glossary/">All {len(glossary)} terms, defined in a sentence each</a></p>')
    site.write(
        "learn/",
        title="Learn: ratings, win probability and efficiency explained",
        description=("Plain-language lessons on the numbers behind college football and basketball: power ratings, "
                     "strength of schedule, win probability, EPA, tempo and how a prediction is graded."),
        crumbs=[("Learn", "learn/")], heading="Learn", tag="the Matchday field guide",
        body=body, lastmod=today, changefreq="weekly", priority="0.8", app="/?view=learn",
    )

    for i, lesson in enumerate(lessons):
        # The lesson reads down the left; every lesson is listed on the right,
        # so the page uses its width and the next read is one click away.
        body = '  <div class="pgLessonWrap">\n  <div class="pgLesson">\n'
        body += "".join(_section(t, f"<p>{_esc(b)}</p>") for t, b in lesson["sections"])
        body += "".join(_section(t, b) for t, b in _lesson_data(lesson["id"], sports))
        prev, nxt = (lessons[i - 1] if i else None), (lessons[i + 1] if i + 1 < len(lessons) else None)
        body += '  <nav class="pgPager" aria-label="Previous and next lesson">' + (
            f'<a href="/learn/{prev["slug"]}/">← {_esc(prev["title"])}</a>' if prev else "<span></span>") + (
            f'<a href="/learn/{nxt["slug"]}/">{_esc(nxt["title"])} →</a>' if nxt else "") + "</nav>\n  </div>\n"
        rail = "".join(
            f'<li><a href="/learn/{l["slug"]}/"{CURRENT if j == i else ""}>'
            f'<span>{j + 1}</span><strong>{_esc(l["title"])}</strong></a></li>'
            for j, l in enumerate(lessons))
        body += (f'  <aside class="pgRail" aria-label="All lessons"><h2 class="seclbl">All lessons</h2><ol>{rail}</ol>'
                 f'<p class="pgMore"><a href="/learn/glossary/">Glossary: {len(glossary)} terms</a></p></aside>\n  </div>\n')
        site.write(
            f"learn/{lesson['slug']}/",
            title=f"{lesson['title']}: {lesson['hook']}",
            description=(lesson["sections"][0][1] if lesson["sections"] else lesson["hook"])[:300],
            crumbs=[("Learn", "learn/"), (lesson["title"], f"learn/{lesson['slug']}/")],
            heading=lesson["title"], tag=f"lesson {i + 1} of {len(lessons)}",
            body=body, lastmod=today, changefreq="weekly", priority="0.7", app="/?view=learn",
        )

    terms = "".join(f'<div id="{slug(t)}"><dt>{_esc(t)}</dt><dd>{_esc(d)}</dd></div>' for t, d in glossary)
    site.write(
        "learn/glossary/",
        title="College sports analytics glossary: every term on Matchday, defined",
        description=("Short definitions of the terms used across Matchday: rating, strength of schedule, EPA per play, "
                     "success rate, tempo, the four factors, calibration, lock, bubble and more."),
        crumbs=[("Learn", "learn/"), ("Glossary", "learn/glossary/")],
        heading="Glossary", tag=f"{len(glossary)} terms",
        body=f'  <dl class="pgGlossary">{terms}</dl>\n',
        schema=[{"@type": "DefinedTermSet", "name": "Matchday glossary", "hasDefinedTerm": [
            {"@type": "DefinedTerm", "name": t, "description": d,
             "url": f"{BASE_URL}learn/glossary/#{slug(t)}"} for t, d in glossary]}],
        lastmod=today, changefreq="monthly", priority="0.6", app="/?view=learn",
    )


# --------------------------------------------------------------------------
# Sitemap and entry point
# --------------------------------------------------------------------------

def _write_sitemap(site: Site) -> int:
    """Add these pages to the sitemap the deploy copied in, keeping its entries."""
    target = site.out / "sitemap.xml"
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    if target.is_file():
        # Entries for these pages from an earlier build into the same folder
        # are dropped, so building twice never lists a page twice.
        mine = {url for url, *_ in site.urls}
        for block in re.findall(r"[ \t]*<url>.*?</url>", target.read_text(encoding="utf-8"), re.S):
            loc = re.search(r"<loc>([^<]+)</loc>", block)
            if loc and loc.group(1) not in mine:
                lines.append(block)
    for url, lastmod, changefreq, priority in site.urls:
        lines += ["  <url>", f"    <loc>{_esc(url)}</loc>"]
        if lastmod:
            lines.append(f"    <lastmod>{_esc(lastmod)}</lastmod>")
        lines += [f"    <changefreq>{changefreq}</changefreq>", f"    <priority>{priority}</priority>", "  </url>"]
    lines.append("</urlset>")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(site.urls)


def build(out: str | pathlib.Path, build_id: str | None = None) -> int:
    return len(render(out, build_id).urls)


def render(out: str | pathlib.Path, build_id: str | None = None, keep: bool = False) -> Site:
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    snap = load_snapshot()
    generated = str(snap.get("MATCHDAY_TRDLAB_GENERATED_AT") or dt.datetime.now(dt.timezone.utc).isoformat())
    site = Site(out, build_id or os.environ.get("GITHUB_SHA", "dev")[:8], keep)
    sports = {key: Sport(key, snap) for key in SPORTS}
    _learn_pages(site, sports, generated)
    for sport in sports.values():
        if not sport.teams:
            continue
        _sport_pages(site, sport, generated)
        _team_page(site, sport)
        for game in sport.games.values():
            _game_page(site, sport, game, generated)
    if STYLESHEET.is_file():
        shutil.copy2(STYLESHEET, out / STYLESHEET.name)
    _write_sitemap(site)
    return site


if __name__ == "__main__":
    count = build(sys.argv[1] if len(sys.argv) > 1 else "_site")
    print(f"static pages: {count}")
