"""render_social.py: the studio staging, the silent case, and one real render.

Everything but the last class is standard library. The render test needs
Playwright and a browser; it is skipped where Playwright is not installed (the
hourly deploy) and runs in social-graphics.yml, which installs both, so a
studio change that breaks headless rendering fails the week's graphics run
before it can quietly produce nothing.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

import content_engine
import render_social

STUDIO = render_social.STUDIO_DIR


class VendoredStudio(unittest.TestCase):
    def test_every_file_the_page_loads_is_committed(self):
        for name in render_social.STUDIO_FILES + ("logo-names.json",):
            self.assertTrue((STUDIO / name).is_file(), name)

    def test_page_loads_logos_from_a_file_not_inline(self):
        html = (STUDIO / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="logos.js"></script>', html)
        self.assertIn("const LOGOS=window.STUDIO_LOGOS", html)
        self.assertNotIn("base64,", html, "assets belong beside the page, not inlined")

    def test_studio_is_not_on_the_public_allowlist(self):
        deploy = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
        self.assertNotIn("social/studio", deploy)

    def test_every_studio_team_has_artwork(self):
        names = json.loads((STUDIO / "logo-names.json").read_text(encoding="utf-8"))
        _script, files = render_social.logos_js(
            content_engine.LOGO_DIR, content_engine.LOGO_OVERRIDE_DIR, names)
        self.assertEqual(sorted(set(names) - set(files)), [])


class Staging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_override_wins_and_names_carry_through(self):
        base, override = self.root / "base", self.root / "over"
        base.mkdir()
        override.mkdir()
        (base / "iowa.png").write_bytes(b"black")
        (base / "ohio.png").write_bytes(b"ohio")
        (override / "iowa.png").write_bytes(b"gold")
        script, files = render_social.logos_js(base, override, {"iowa": "Iowa"})
        self.assertEqual(files["iowa"].read_bytes(), b"gold")
        table = json.loads(script.split("=", 1)[1].rstrip(";\n"))
        self.assertEqual(table["iowa"], {"name": "Iowa", "src": "logos/iowa.png"})
        self.assertEqual(table["ohio"]["name"], "ohio")

    def test_stage_writes_a_servable_directory(self):
        edition = {"version": 2, "mode": "rankings"}
        path = render_social.stage(self.root, edition)
        for name in render_social.STUDIO_FILES + ("logos.js",):
            self.assertTrue((self.root / name).is_file(), name)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), edition)
        self.assertTrue((self.root / "logos" / "iowa.png").is_file())


class Modes(unittest.TestCase):
    def test_required_modes_always_optional_ones_only_when_filled(self):
        self.assertEqual(render_social.modes_for({}), ["rankings", "matchups"])
        self.assertEqual(render_social.modes_for({"ballot": [1], "upsets": [1]}),
                         ["rankings", "ballot", "matchups", "upset"])

    def test_every_mode_maps_to_a_content_kind(self):
        for kind, _sport in render_social.MODE_ITEMS.values():
            self.assertIn(kind, content_engine.KINDS)

    def test_manifest_ties_each_image_to_its_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "rankings.png"
            png.write_bytes(b"png")
            queue = {"generated_at": "now", "items": [{
                "kind": "power_top25", "sport": "ncaaf", "key": "k", "caption": "c",
                "expires_at": "e", "source": {"sha256": "s"}, "caveat": None}]}
            report = render_social.manifest(queue, {"edition": "NOV 1, 2026"}, {"rankings": png})
        entry = report["images"][0]
        self.assertEqual((entry["item_key"], entry["caption"], entry["source_sha256"]),
                         ("k", "c", "s"))
        self.assertEqual(len(entry["png_sha256"]), 64)


class SaysNothing(unittest.TestCase):
    def test_no_edition_renders_nothing_and_succeeds(self):
        """A stale week must not reach the browser at all."""
        far_future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=400)).isoformat()
        with tempfile.TemporaryDirectory() as out:
            code = render_social.main(["--out", out, "--now", far_future])
            self.assertEqual(code, 0)
            self.assertEqual(os.listdir(out), [])


def _png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as handle:
        head = handle.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright is not installed")
class RealRender(unittest.TestCase):
    """Load a full edition through the studio's own input and export every mode."""

    def test_studio_renders_every_mode_at_full_resolution(self):
        names = json.loads((STUDIO / "logo-names.json").read_text(encoding="utf-8"))
        keys = sorted(names)[:25]
        index = content_engine._logo_index(content_engine.LOGO_DIR,
                                           content_engine.LOGO_OVERRIDE_DIR)
        team = lambda k: content_engine._studio_team(names[k], index, [])
        pair = lambda a, b: {"left": team(a), "right": team(b), "detail": "SAT · 7:30 PM ET"}
        edition = {
            "version": 2, "mode": "rankings", "edition": "NOV 1, 2026",
            "footer": "WHO MAKES YOUR LIST?",
            "rankings": [dict(team(k), detail="30.00") for k in keys],
            "ballot": [dict(team(k), detail="") for k in reversed(keys)],
            "ballotEdition": "NOV 1, 2026", "ballotFooter": "AGREE OR DISAGREE?",
            "matchups": [pair(keys[i], keys[i + 1]) for i in range(0, 10, 2)],
            "upsets": [pair(keys[i], keys[i + 1]) for i in range(10, 16, 2)],
            "upsetFooter": "WHICH FAVORITE GOES DOWN?",
        }
        channel = os.environ.get("MATCHDAY_RENDER_CHANNEL") or None
        with tempfile.TemporaryDirectory() as build, tempfile.TemporaryDirectory() as out:
            path = render_social.stage(Path(build), edition)
            with render_social.serve(Path(build)) as url:
                images = render_social.render(url, path, render_social.modes_for(edition),
                                              Path(out), channel)
            self.assertEqual(sorted(images), ["ballot", "matchups", "rankings", "upset"])
            for image in images.values():
                self.assertEqual(_png_size(image), (2160, 3840))
            sizes = {image.stat().st_size for image in images.values()}
            self.assertEqual(len(sizes), 4, "each mode must draw a different graphic")


if __name__ == "__main__":
    unittest.main()
