"""render_reels.py -- this week's TikTok videos, drawn from the content queue.

Phase 3 of the X/TikTok content bot. Each postable content item that suits
video becomes a 1080x1920, 30 fps H.264 MP4 of roughly 15-30 seconds:

    power_top25       Top 25 countdown (football and basketball)
    slate_preview     Top 5 games of the week, model read vs market
    upset_watch       the underdogs the model rates above the market
    game_of_the_week  one matchup, model read vs market
    scorecard         the receipts: record, expected rate, versus the market,
                      plus last week's graded upset calls when they are settled

Every number comes from content_engine's items, so a video carries the same
facts, source hash and expiry as the post it belongs to, and expires with it.
Text is drawn into the frames (most people watch muted). There is no audio:
TikTok's API cannot attach its licensed sounds, so the plan is to upload as a
draft and pick a sound in the app.

The frames come from social/studio/reel.js, a canvas page in the studio's
look where every frame is a pure function of time, captured in a headless
browser and piped to ffmpeg (imageio-ffmpeg's bundled build, the same binary
locally and in CI).

Silence is a valid result: no postable items, no videos, exit 0.

Usage:
    python render_reels.py --out out/videos
    python render_reels.py --out out/videos --only power_top25 --fps 30
    python render_reels.py --out out/videos --channel msedge
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import content_engine
import render_social

ROOT = Path(__file__).resolve().parent
STUDIO = render_social.STUDIO_DIR
REEL_FILES = ("reel.html", "reel.js", "team-colors.json", "brand.png", "matchday.ttf")
FPS = 30
BATCH = 15
HASHTAGS = {"ncaaf": "#CollegeFootball #CFB", "ncaam": "#CollegeBasketball #MarchMadness"}
SPORT_TAG = {"ncaaf": "CFB", "ncaam": "HOOPS"}
SPORT_NAME = {"ncaaf": "College football", "ncaam": "College basketball"}
# The fine print each video ends on. Written for viewers: an item's own
# `caveat` is written for whoever handles the data (the scorecard's names JSON
# fields), so it stays in the manifest and never reaches a frame.
NOTES = {
    "power_top25": "Our own opponent-adjusted rating, built from game results. Not the AP or CFP poll.",
    "slate_preview": "Ranked for stakes, not by the model. Model reads are live and can move before kickoff.",
    "upset_watch": "Forecasting, not betting advice. Model reads are live and can move before kickoff.",
    "game_of_the_week": "Chosen for how strong and how close the two teams are. The model read is live and can move before kickoff.",
    "scorecard": "Most picks are favorites, so a hit rate only means something next to the expected rate and the market comparison.",
}
LIVE_NOTE = "Live model read. It can move before kickoff."


# --------------------------------------------------------------------------- teams

class Teams:
    """Team name -> {team: logo key, name: display name} using the studio's artwork."""

    def __init__(self) -> None:
        self.index = content_engine._logo_index(content_engine.LOGO_DIR,
                                                content_engine.LOGO_OVERRIDE_DIR)
        self.missing: set[str] = set()

    def __call__(self, name: object, **extra: Any) -> dict[str, Any]:
        full = str(name or "")
        path = content_engine.logo_for(full, self.index)
        if path is None:
            self.missing.add(full)
        side = {"team": path.stem if path else None,
                "name": content_engine.short(full).upper()}
        side.update({k: v for k, v in extra.items() if v not in (None, "")})
        return side


def _pct(value: object) -> float | None:
    return round(float(value), 1) if isinstance(value, (int, float)) else None


def _movement(value: object) -> str:
    if not isinstance(value, (int, float)) or value == 0:
        return ""
    return ("▲ up %d" if value > 0 else "▼ down %d") % abs(value)


# --------------------------------------------------------------------------- specs

def top25_spec(item: dict, teams: Teams) -> dict[str, Any]:
    facts, sport = item["facts"], item["sport"]
    rows = facts["rows"]

    def row(r: dict) -> dict:
        sub = " · ".join(x for x in (r.get("record"), r.get("conference")) if x)
        return teams(r["team"], rank=r["rank"], value="%.2f" % r["rating"], sub=sub)

    scenes: list[dict] = [{
        "type": "intro", "dur": 2.4, "title": "TOP 25",
        "subtitle": f"{SPORT_NAME[sport]} power ratings",
        "kicker": f"Published {facts['published_on']}",
    }]
    for hi in (25, 20, 15, 10):
        batch = [r for r in rows if hi - 4 <= r["rank"] <= hi]
        batch.sort(key=lambda r: -r["rank"])
        scenes.append({"type": "rank_batch", "dur": 2.6, "heading": f"{hi} – {hi - 4}",
                       "subheading": facts.get("basis") or "", "rows": [row(r) for r in batch]})
    for r in sorted((r for r in rows if r["rank"] <= 5), key=lambda r: -r["rank"]):
        sub = " · ".join(x for x in (r.get("record"), _movement(r.get("movement"))) if x)
        scenes.append(dict(teams(r["team"]), type="rank_hero", dur=2.0, rank=r["rank"],
                           value="RATING %.2f" % r["rating"], sub=sub))
    scenes.append({"type": "outro", "dur": 3.2, "headline": "WHO'S TOO HIGH?",
                   "subline": "Our own rating. Not the AP poll.", "note": NOTES["power_top25"]})
    return {"label": f"{SPORT_TAG[sport]} · POWER RATINGS", "scenes": scenes}


def _matchup(game: dict, teams: Teams, heading: str, note: str | None) -> dict:
    pick = game.get("pick") or game.get("model_pick")
    scene = {
        "type": "matchup", "heading": heading, "kickoff": game.get("kickoff_et"),
        "away": teams(game["away"], rank=game.get("away_rank"), sub=game.get("away_record")),
        "home": teams(game["home"], rank=game.get("home_rank"), sub=game.get("home_record")),
        "note": note,
    }
    if pick and _pct(game.get("model_pct")) is not None:
        scene.update(pick="1", pick_label="Model pick: " + content_engine.short(pick),
                     model_pct=_pct(game.get("model_pct")), market_pct=_pct(game.get("market_pct")))
    return scene


def slate_spec(item: dict, teams: Teams) -> dict[str, Any]:
    games = item["facts"]["games"]
    note = LIVE_NOTE
    scenes = [{"type": "intro", "dur": 2.2, "title": f"TOP {len(games)} GAMES",
               "subtitle": "This week in college football",
               "kicker": "Ranked for stakes, not by the model"}]
    scenes += [dict(_matchup(g, teams, f"GAME {i} OF {len(games)}", note), dur=3.4)
               for i, g in enumerate(games, 1)]
    scenes.append({"type": "outro", "dur": 3.2, "headline": "WHICH ONE ARE YOU WATCHING?",
                   "note": NOTES["slate_preview"]})
    return {"label": "CFB · THIS WEEK", "scenes": scenes}


def upset_spec(item: dict, teams: Teams) -> dict[str, Any]:
    games = item["facts"]["games"]
    scenes: list[dict] = [{"type": "intro", "dur": 2.2, "title": "UPSET WATCH",
                           "subtitle": "Underdogs the model likes",
                           "kicker": "Model vs market, same team"}]
    for i, g in enumerate(games, 1):
        dog = g["underdog"]
        fav = g["home"] if dog == g["away"] else g["away"]
        fav_rank = g["home_rank"] if fav == g["home"] else g["away_rank"]
        scenes.append({"type": "upset", "dur": 4.2,
                       "heading": "UPSET WATCH" + (f" {i}/{len(games)}" if len(games) > 1 else ""),
                       "kickoff": g.get("kickoff_et"), "dog": teams(dog),
                       "favorite": teams(fav, rank=fav_rank),
                       "model_pct": _pct(g["underdog_model_pct"]),
                       "market_pct": _pct(g["underdog_market_pct"]),
                       "gap": float(g["disagreement_points"])})
    scenes.append({"type": "outro", "dur": 3.2, "headline": "WOULD YOU TAKE THE DOG?",
                   "note": NOTES["upset_watch"]})
    return {"label": "CFB · UPSET WATCH", "scenes": scenes}


def gotw_spec(item: dict, teams: Teams) -> dict[str, Any]:
    f = item["facts"]
    sport = item["sport"]
    title = "%s at %s" % (content_engine.short(f["away"]), content_engine.short(f["home"]))
    scenes = [
        {"type": "intro", "dur": 2.2, "title": "GAME OF THE WEEK", "subtitle": title,
         "kicker": f.get("kickoff_et")},
        dict(_matchup(f, teams, "GAME OF THE WEEK", LIVE_NOTE), dur=6.0),
        {"type": "outro", "dur": 3.2, "headline": "WHO YOU GOT?",
         "note": NOTES["game_of_the_week"]},
    ]
    return {"label": f"{SPORT_TAG[sport]} · GAME OF THE WEEK", "scenes": scenes}


def scorecard_spec(item: dict, teams: Teams, results: dict | None = None) -> dict[str, Any]:
    f, sport = item["facts"], item["sport"]
    beat = f["beat_market_pct"]
    scenes: list[dict] = [
        {"type": "intro", "dur": 2.2, "title": "THE RECEIPTS",
         "subtitle": f"{SPORT_NAME[sport]} picks, graded",
         "kicker": "Locked before kickoff. Never rewritten."},
        {"type": "stat", "dur": 6.5, "heading": "THE RECORD",
         "subheading": f"{f['picks']} locked picks",
         "rows": [
             {"label": "Wins – losses", "value": f"{f['wins']}–{f['losses']}",
              "sub": "Picks frozen an hour before kickoff"},
             {"label": "Hit rate", "value": "%.1f%%" % f["hit_rate_pct"],
              "sub": "The model expected %.1f%%" % f["expected_hit_rate_pct"]},
             {"label": "Closer than the market price", "value": "%.1f%%" % beat,
              "sub": "of %s priced picks" % f.get("beat_market_picks"),
              "color": "#defa10" if beat >= 50 else None},
         ]},
    ]
    if results:
        rf = results["facts"]
        rows = []
        for call in rf["calls"]:
            picked_away = call["selection"] == call["away"]
            opp = call["home"] if picked_away else call["away"]
            score = ""
            if call.get("home_score") is not None and call.get("away_score") is not None:
                # The called team's score first, whichever side it played on.
                ours, theirs = ((call["away_score"], call["home_score"]) if picked_away
                                else (call["home_score"], call["away_score"]))
                score = " · %d–%d" % (ours, theirs)
            rows.append(teams(call["selection"], result=call["result"],
                              sub="vs " + content_engine.short(opp) + score))
        scenes.append({"type": "results", "dur": 1.6 + 0.9 * len(rows),
                       "heading": "LAST WEEK'S UPSET CALLS",
                       "subheading": f"{rf['won']} of {rf['won'] + rf['lost']} came in",
                       "rows": rows[:4]})
    scenes.append({"type": "outro", "dur": 3.2, "headline": "EVERY MISS STAYS PUBLIC",
                   "note": NOTES["scorecard"]})
    return {"label": f"{SPORT_TAG[sport]} · RECEIPTS", "scenes": scenes}


BUILDERS: dict[str, Callable[..., dict]] = {
    "power_top25": top25_spec,
    "slate_preview": slate_spec,
    "upset_watch": upset_spec,
    "game_of_the_week": gotw_spec,
    "scorecard": scorecard_spec,
}


def build_specs(queue: dict[str, Any], only: set[str] | None = None) -> list[dict[str, Any]]:
    """One video spec per item that suits video, in queue order."""
    teams = Teams()
    results = {i["sport"]: i for i in queue["items"] if i["kind"] == "upset_results"}
    specs = []
    for item in queue["items"]:
        builder = BUILDERS.get(item["kind"])
        if builder is None or (only and item["kind"] not in only):
            continue
        extra = (results.get(item["sport"]),) if item["kind"] == "scorecard" else ()
        spec = builder(item, teams, *extra)
        spec.update(name=f"{item['kind']}-{item['sport']}", item=item)
        specs.append(spec)
    for spec in specs:
        spec["missing_logos"] = sorted(teams.missing)
    return specs


def duration(spec: dict[str, Any]) -> float:
    return round(sum(s["dur"] for s in spec["scenes"]), 3)


def tiktok_caption(item: dict[str, Any]) -> str:
    """The X caption without its link (TikTok captions do not link) plus tags."""
    text = re.sub(r"\s*https?://\S+\s*$", "", item["caption"]).rstrip(" :")
    return f"{text} matchdayterminal.com {HASHTAGS.get(item['sport'], '')}".strip()


# --------------------------------------------------------------------------- render

def stage(build: Path) -> None:
    for name in REEL_FILES:
        shutil.copy2(STUDIO / name, build / name)
    (build / "logos").mkdir()
    for directory in (content_engine.LOGO_DIR, content_engine.LOGO_OVERRIDE_DIR):
        for path in directory.glob("*.png"):
            shutil.copy2(path, build / "logos" / path.name)


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def encode_command(path: Path, fps: int) -> list[str]:
    return [ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
            # JPEG frames are full-range; players expect TV range, so convert
            # rather than tag (a yuvj420p stream looks washed out on some phones).
            "-vf", "scale=in_range=full:out_range=tv,format=yuv420p", "-color_range", "tv",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-r", str(fps), "-movflags", "+faststart", str(path)]


def render(url: str, specs: list[dict[str, Any]], out: Path, fps: int = FPS,
           channel: str | None = None) -> dict[str, Path]:
    from playwright.sync_api import sync_playwright

    written: dict[str, Path] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**({"channel": channel} if channel else {}))
        try:
            for spec in specs:
                page = browser.new_page(viewport={"width": 600, "height": 1000})
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(url)
                payload = {k: v for k, v in spec.items() if k not in ("item", "missing_logos")}
                info = page.evaluate("spec => REEL.load(spec)", payload)
                total = int(round(info["duration"] * fps))
                path = out / f"{spec['name']}.mp4"
                proc = subprocess.Popen(encode_command(path, fps), stdin=subprocess.PIPE)
                try:
                    for first in range(0, total, BATCH):
                        times = [i / fps for i in range(first, min(first + BATCH, total))]
                        for data_url in page.evaluate("t => REEL.frames(t)", times):
                            proc.stdin.write(base64.b64decode(data_url.split(",", 1)[1]))
                finally:
                    proc.stdin.close()
                    code = proc.wait()
                page.close()
                if errors:
                    raise RuntimeError(f"{spec['name']}: reel page raised: " + "; ".join(errors))
                if code != 0:
                    raise RuntimeError(f"{spec['name']}: ffmpeg exited {code}")
                written[spec["name"]] = path
        finally:
            browser.close()
    return written


def manifest(queue: dict[str, Any], specs: list[dict[str, Any]],
             videos: dict[str, Path]) -> dict[str, Any]:
    entries = []
    for spec in specs:
        path = videos.get(spec["name"])
        if path is None:
            continue
        item = spec["item"]
        entries.append({
            "file": path.name,
            "mp4_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "seconds": duration(spec),
            "item_key": item["key"],
            "tiktok_caption": tiktok_caption(item),
            "x_caption": item["caption"],
            "expires_at": item["expires_at"],
            "source_sha256": item["source"]["sha256"],
            "caveat": item.get("caveat"),
        })
    return {
        "generated_at": queue["generated_at"],
        "handoff_generated_at": queue.get("handoff_generated_at"),
        "missing_logos": specs[0]["missing_logos"] if specs else [],
        "videos": entries,
        "note": "No audio track: upload to TikTok as a draft and add a sound in the app.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True, help="folder for the MP4s and manifest.json")
    parser.add_argument("--now", help="evaluate as of this UTC time (ISO 8601)")
    parser.add_argument("--only", action="append", choices=sorted(BUILDERS),
                        help="render only this kind (repeatable)")
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--channel", help="Playwright browser channel, e.g. msedge or chrome")
    args = parser.parse_args(argv)
    now = content_engine.parse_time(args.now) if args.now else None
    if args.now and now is None:
        parser.error("--now must be an ISO 8601 time")

    queue = content_engine.build_queue(now, ROOT)
    specs = build_specs(queue, set(args.only) if args.only else None)
    if not specs:
        reasons = "; ".join(w["reason"] for w in queue["withheld"]) or "no video-ready items"
        print(f"Nothing to render: {reasons}.")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        stage(build)
        with render_social.serve(build) as index_url:
            url = index_url.rsplit("/", 1)[0] + "/reel.html"
            videos = render(url, specs, out, args.fps, args.channel)
    report = manifest(queue, specs, videos)
    (out / "manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    for entry in report["videos"]:
        print(f"{entry['file']} ({entry['seconds']}s): {entry['tiktok_caption']}")
    if report["missing_logos"]:
        print("missing logos (drawn as initials): " + ", ".join(report["missing_logos"]))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
