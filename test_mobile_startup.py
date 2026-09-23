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
            self.html.index('src="app-1-core.js'),
        )
        self.assertIn(
            '<button class="welcomeEnter" type="button" onclick="matchdayEnterNow()">',
            self.html,
        )
        self.assertNotIn('class="welcomeEnter" href=', self.html)
        self.assertIn("if(gate)gate.hidden=true", self.html)
        self.assertIn("window.scrollTo(0,0)", self.html)
        self.assertIn("document.documentElement.scrollTop=0", self.html)
        self.assertIn("'welcomeOpen','welcomeExiting','navSheetOpen'", self.html)
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
        self.assertIn('.welcomeGate:not([hidden]) .welcomeActions,', css)
        self.assertIn('animation:none!important;opacity:1!important;transform:none!important', css)

    def test_large_scripts_do_not_block_html_parsing(self):
        for filename in (
            "translations.js", "updates.js", "matchday-cfb-snapshot.js",
            "app-1-core.js", "app-2-views.js", "app-3-panels.js",
            "app-4-features.js", "research-signals.js",
        ):
            self.assertRegex(self.html, rf'<script src="{filename}[^>]*\bdefer\b')

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
