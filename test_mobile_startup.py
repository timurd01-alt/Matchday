import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class MobileStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")

    def test_enter_action_exists_before_application_bundles(self):
        self.assertLess(
            self.html.index("window.matchdayEnterNow=function"),
            self.html.index('<body>'),
        )
        self.assertLess(
            self.html.index("window.matchdayEnterNow=function"),
            self.html.index("window.startMatchdayApp=function()"),
        )
        # The button belongs in the brand column beside the rest of the copy.
        # It was briefly pinned to the bottom of the viewport to work around an
        # entry bug that turned out to be a blocked main thread; floating it
        # detached it from the page.
        enter_button = '<button class="welcomeEnter" type="button" onclick="matchdayEnterNow()">'
        self.assertIn(enter_button, self.html)
        self.assertNotIn('welcomeEnterFast', self.html)
        self.assertLess(self.html.index('<div class="welcomeActions">'), self.html.index(enter_button))
        # The stadium scene is the welcome page's artwork, not a startup cost.
        self.assertIn('<div class="welcomeScene"', self.html)
        self.assertNotIn('id="retiredWelcomeScene"', self.html)
        self.assertNotIn('class="welcomeEnter" href=', self.html)
        self.assertIn("if(gate)gate.hidden=true", self.html)
        self.assertIn("window.scrollTo(0,0)", self.html)
        self.assertIn("document.documentElement.scrollTop=0", self.html)
        self.assertIn("'welcomeOpen','welcomeExiting','navSheetOpen'", self.html)
        self.assertIn("document.addEventListener('click',function(event)", self.html)
        self.assertIn("event.target.closest('.welcomeEnter')", self.html)
        self.assertIn('<section class="welcomeGate" id="welcomeGate" aria-labelledby="welcomeTitle">', self.html)
        self.assertNotIn('id="welcomeGate" aria-labelledby="welcomeTitle" hidden', self.html)
        self.assertNotIn('id="welcomeGate" role="dialog"', self.html)

    def test_welcome_uses_session_entry_state(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertIn("sessionStorage.getItem('matchday.welcome.entered')==='1'", core)
        self.assertIn("sessionStorage.removeItem('matchday.welcome.entered')", core)
        self.assertNotIn("MATCHDAY_SHOW_WELCOME", core)

    def test_welcome_is_not_a_fullscreen_scroll_trap(self):
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('.welcomeGate:not([hidden]){position:relative;inset:auto', css)
        self.assertIn('body.welcomeOpen{height:auto;min-height:100vh;overflow-y:auto}', css)
        self.assertIn('.welcomeOpen .app{visibility:visible;display:grid}', css)
        self.assertIn('min-height:52px', css)
        self.assertIn('touch-action:manipulation', css)
        self.assertIn('.welcomeActions{position:relative;z-index:20;pointer-events:auto}', css)
        self.assertIn('.welcomeEnter{position:relative;z-index:21;', css)
        self.assertIn('.welcomeEnter::after{content:"";position:absolute;inset:0;pointer-events:none', css)
        self.assertNotIn('.welcomeEnterFast', css)
        self.assertIn('.welcomeGate:not([hidden]) .welcomeActions,', css)
        self.assertIn('animation:none!important;opacity:1!important;transform:none!important', css)

    def test_large_scripts_do_not_block_welcome_interaction(self):
        for filename in (
            "translations.js", "updates.js", "matchday-cfb-snapshot.js",
            "app-1-core.js", "app-2-views.js", "app-3-panels.js",
            "app-4-features.js", "research-signals.js",
        ):
            self.assertNotIn(f'<script src="{filename}', self.html)
            self.assertIn(f"'{filename}'", self.html)
        self.assertIn("window.startMatchdayApp=function()", self.html)
        # Entry starts the application immediately. A fixed delay was added to
        # hide a two-minute snapshot merge; the merge is fixed, and the delay
        # was pure latency.
        self.assertIn("window.startMatchdayApp()", self.html)
        self.assertNotIn("window.setTimeout(window.startMatchdayApp", self.html)
        # The bundles download in parallel and execute in order. Chaining each
        # file's load to the next cost one network round trip per file.
        self.assertIn("script.async=false", self.html)
        self.assertNotIn("files.reduce(function(chain,file)", self.html)
        # The welcome page warms the bundles into cache without executing them.
        self.assertIn("link.rel='preload'", self.html)
        self.assertIn("window.warmMatchdayApp", self.html)

    def test_snapshot_merge_is_not_quadratic(self):
        """The CFB snapshot merge locked the main thread for ~163s on load.

        Every fixture was compared against every other one, and each comparison
        rebuilt the team-logo candidate list from scratch -- 2.8 million calls.
        Fixtures are now bucketed by kickoff day and the pure name helpers are
        memoized, which took the same merge (identical output) to well under a
        second.
        """
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        # Pure per-name helpers keep their answers.
        self.assertIn("_LOGO_CANDIDATE_CACHE", core)
        self.assertIn("_TEAM_KEY_CACHE", core)
        self.assertIn("_INFERRED_LOGO_CACHE", core)
        # The logo table is built once, not rebuilt and re-sorted per call.
        self.assertIn("_TEAM_LOGO_ENTRIES", core)
        self.assertNotIn("Object.entries(TEAM_LOGO_FILES)\n    .filter", core)
        # A no-copy accessor for the comparison hot path.
        self.assertIn("function primaryTeamLogo(name)", core)

        self.assertIn("function makeCfbFixtureIndex()", self.panels)
        self.assertIn("_BB_NAME_KEY_CACHE", self.panels)
        self.assertIn("_BB_QUALIFIER_CACHE", self.panels)
        # The two whole-board scans the index replaced.
        self.assertNotIn("[...payload.matches||[],...added].some", self.panels)
        self.assertNotIn("unique.findIndex(other=>sameCfbFixture(other,m))", self.panels)

    def test_web_fonts_do_not_block_first_render(self):
        font_line = next(line for line in self.html.splitlines()
                         if "fonts.googleapis.com/css2" in line and "noscript" not in line)
        self.assertIn('media="print"', font_line)
        self.assertIn("onload=", font_line)

    def test_mobile_does_not_prefetch_other_multi_megabyte_sport(self):
        self.assertIn("connection?.saveData", self.panels)
        self.assertIn("matchMedia('(max-width:760px)').matches", self.panels)
        self.assertIn("requestIdleCallback", self.panels)


if __name__ == "__main__":
    unittest.main()
