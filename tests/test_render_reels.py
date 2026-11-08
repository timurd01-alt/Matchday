"""render_reels.py: the video specs carry the queue's facts, nothing more.

Spec building is pure Python and runs everywhere. The end-to-end encode needs
Playwright and imageio-ffmpeg; it is skipped where they are not installed (the
hourly deploy) and runs in social-graphics.yml, which installs both.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import content_engine
import render_reels
import render_social
import trdlab_handoff
from tests.test_content_engine import NOW, _handoff
from tests.test_render_social import _browser_available

STUDIO = render_social.STUDIO_DIR


def _queue(document=None, now=NOW):
    with tempfile.TemporaryDirectory() as root:
        if document is not None:
            (Path(root) / trdlab_handoff.DEFAULT_HANDOFF_PATH).write_text(
                json.dumps(document), encoding="utf-8")
        return content_engine.build_queue(now, root)


class Specs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = _queue(_handoff())
        cls.specs = {s["name"]: s for s in render_reels.build_specs(cls.queue)}

    def test_one_video_per_video_ready_item(self):
        self.assertEqual(sorted(self.specs), [
            "game_of_the_week-ncaaf", "power_top25-ncaaf", "scorecard-ncaaf",
            "slate_preview-ncaaf", "upset_watch-ncaaf"])

    def test_every_video_fits_tiktok_short_form(self):
        for name, spec in self.specs.items():
            self.assertGreaterEqual(render_reels.duration(spec), 8, name)
            self.assertLessEqual(render_reels.duration(spec), 30, name)

    def test_countdown_covers_all_25_in_order(self):
        scenes = self.specs["power_top25-ncaaf"]["scenes"]
        ranks = [r["rank"] for s in scenes if s["type"] == "rank_batch" for r in s["rows"]]
        ranks += [s["rank"] for s in scenes if s["type"] == "rank_hero"]
        self.assertEqual(ranks, list(range(25, 0, -1)))

    def test_upset_numbers_are_the_items_numbers(self):
        item = next(i for i in self.queue["items"] if i["kind"] == "upset_watch")
        scene = next(s for s in self.specs["upset_watch-ncaaf"]["scenes"] if s["type"] == "upset")
        game = item["facts"]["games"][0]
        self.assertEqual(scene["model_pct"], game["underdog_model_pct"])
        self.assertEqual(scene["market_pct"], game["underdog_market_pct"])
        self.assertEqual(scene["dog"]["name"], "TULSA")
        self.assertEqual(scene["favorite"]["name"], "OKLAHOMA STATE")

    def test_scorecard_never_shows_the_hit_rate_alone(self):
        stat = next(s for s in self.specs["scorecard-ncaaf"]["scenes"] if s["type"] == "stat")
        labels = [r["label"] for r in stat["rows"]]
        self.assertIn("Hit rate", labels)
        self.assertIn("Closer than the market price", labels)
        hit = stat["rows"][labels.index("Hit rate")]
        self.assertIn("expected 73.4%", hit["sub"])

    def test_settled_upset_calls_ride_with_the_scorecard_score_first(self):
        results = next(s for s in self.specs["scorecard-ncaaf"]["scenes"] if s["type"] == "results")
        self.assertEqual(results["subheading"], "1 of 2 came in")
        rows = {r["name"]: r for r in results["rows"]}
        self.assertEqual(rows["UCLA"]["sub"], "vs Utah · 24–20")   # away underdog
        self.assertEqual(rows["IOWA"]["sub"], "vs Texas · 10–31")  # its own score first

    def test_frames_never_show_data_side_wording(self):
        """Item caveats are written for whoever handles the data; frames get NOTES."""
        for name, spec in self.specs.items():
            text = json.dumps(spec["scenes"])
            self.assertNotRegex(text, r"[a-z]+_[a-z]+_pct", name)
            self.assertNotIn("shadow", text.lower(), name)
            outro = spec["scenes"][-1]
            self.assertEqual(outro["type"], "outro")
            self.assertIn(outro["note"], render_reels.NOTES.values(), name)

    def test_tiktok_caption_drops_the_link_and_adds_tags(self):
        for spec in self.specs.values():
            caption = render_reels.tiktok_caption(spec["item"])
            self.assertNotRegex(caption, r"https?://")
            self.assertIn("matchdayterminal.com", caption)
            self.assertIn("#CollegeFootball", caption)

    def test_only_filters_kinds(self):
        specs = render_reels.build_specs(self.queue, {"scorecard"})
        self.assertEqual([s["name"] for s in specs], ["scorecard-ncaaf"])

    def test_every_scene_type_is_drawn_by_the_page(self):
        js = (STUDIO / "reel.js").read_text(encoding="utf-8")
        types = {s["type"] for spec in self.specs.values() for s in spec["scenes"]}
        for kind in types:
            self.assertRegex(js, r"\n    %s\(s, u\) \{" % kind, kind)


class SaysNothing(unittest.TestCase):
    def test_empty_queue_builds_no_specs(self):
        self.assertEqual(render_reels.build_specs(_queue()), [])

    def test_main_exits_cleanly_with_nothing_to_render(self):
        with tempfile.TemporaryDirectory() as out:
            code = render_reels.main(["--out", out, "--now", "2099-01-01T00:00:00Z"])
            self.assertEqual(code, 0)
            self.assertEqual(list(Path(out).iterdir()), [])


class StudioAssets(unittest.TestCase):
    def test_reel_files_are_committed(self):
        for name in render_reels.REEL_FILES:
            self.assertTrue((STUDIO / name).is_file(), name)

    def test_team_colors_match_the_studio(self):
        """reel.js reads team-colors.json; the studio keeps its own copy inline."""
        js = (STUDIO / "collections.js").read_text(encoding="utf-8")
        start = js.index("const teamColors=") + len("const teamColors=")
        inline, _ = json.JSONDecoder().raw_decode(js[start:])
        stored = json.loads((STUDIO / "team-colors.json").read_text(encoding="utf-8"))
        self.assertEqual(inline, stored)

    def test_encoder_writes_tv_range_h264(self):
        command = render_reels.encode_command(Path("x.mp4"), 30) if importlib.util.find_spec(
            "imageio_ffmpeg") else None
        if command is None:
            self.skipTest("imageio-ffmpeg is not installed")
        joined = " ".join(command)
        self.assertIn("libx264", joined)
        self.assertIn("out_range=tv,format=yuv420p", joined)
        self.assertIn("+faststart", joined)


@unittest.skipUnless(_browser_available() and importlib.util.find_spec("imageio_ffmpeg"),
                     "Playwright, its browser, or imageio-ffmpeg is not installed")
class RealEncode(unittest.TestCase):
    def test_renders_a_playable_vertical_mp4(self):
        import os

        queue = _queue(_handoff())
        specs = render_reels.build_specs(queue, {"upset_watch"})
        channel = os.environ.get("MATCHDAY_RENDER_CHANNEL") or None
        with tempfile.TemporaryDirectory() as build, tempfile.TemporaryDirectory() as out:
            render_reels.stage(Path(build))
            with render_social.serve(Path(build)) as url:
                videos = render_reels.render(url.rsplit("/", 1)[0] + "/reel.html", specs,
                                             Path(out), fps=6, channel=channel)
            path = videos["upset_watch-ncaaf"]
            probe = subprocess.run([render_reels.ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                                   capture_output=True, text=True).stderr
        # yuv420p, never full-range yuvj420p/"(pc". The Windows ffmpeg build tags
        # the range "(tv"; the Linux one leaves it untagged, which players read
        # as TV range too, so only the full-range forms are refused.
        self.assertRegex(probe, r"Video: h264 \(High\).*\byuv420p\(")
        self.assertNotIn("yuvj420p", probe)
        self.assertNotIn("yuv420p(pc", probe)
        self.assertIn("1080x1920", probe)
        seconds = render_reels.duration(specs[0])
        match = re.search(r"Duration: 00:00:(\d+\.\d+)", probe)
        self.assertAlmostEqual(float(match.group(1)), seconds, delta=0.5)


if __name__ == "__main__":
    unittest.main()
