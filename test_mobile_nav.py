import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class MobileNavigationTests(unittest.TestCase):
    def test_more_trigger_is_available_on_phone_and_desktop(self):
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.navMore\s*\{\s*display:none\s*\}")
        phone_rules = re.findall(
            r"@media\(max-width:700px\)\s*\{(.*?)(?=\n\})",
            css,
            flags=re.DOTALL,
        )
        self.assertTrue(
            any(re.search(r"\.sidebar\s+\.navMore\s*\{\s*display:flex\s*\}", block)
                for block in phone_rules),
            "the More trigger must remain available in the phone navigation",
        )
        desktop_rules = re.findall(
            r"@media\(min-width:701px\)\s*\{(.*?)(?=\n\})",
            css,
            flags=re.DOTALL,
        )
        self.assertTrue(
            any(re.search(r"\.sidebar\s+\.navMore\s*\{\s*display:flex\s*\}", block)
                for block in desktop_rules),
            "the More trigger must also own secondary desktop destinations",
        )

    def test_primary_navigation_is_games_rankings_results_research(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        primary = re.findall(
            r'<button class="navbtn" data-primary data-v="([^"]+)"[^>]*>.*?'
            r'<span class="lbl">([^<]+)</span>',
            html,
            flags=re.DOTALL,
        )
        self.assertEqual(
            primary,
            [("matches", "Games"), ("groups", "Rankings"),
             ("results", "Results"), ("news", "Research")],
        )
        self.assertEqual(html.count('class="navbtn navMore"'), 1)
        self.assertNotIn('data-primary data-v="score"', html)

    def test_secondary_tools_stay_behind_more(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for view in ("score", "bracket", "community"):
            self.assertIn(f'data-v="{view}"', html)
            self.assertNotIn(f'data-primary data-v="{view}"', html)
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertIn("games:'matches'", core)
        self.assertIn("rankings:'groups'", core)
        self.assertIn("research:'news'", core)
        self.assertIn("document.querySelector('#nav .navMore')?.focus()", core)

    def test_public_navigation_urls_support_history(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        features = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        self.assertIn("matches:'games',groups:'rankings',news:'research'", panels)
        self.assertIn("window.history[mode==='replace'?'replaceState':'pushState']", panels)
        self.assertIn("window.addEventListener('popstate'", features)
        self.assertIn("setView(target,{history:false})", features)

    def test_stale_sport_load_cannot_replace_current_board(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("const loadSequence=++LOAD_SEQUENCE,requestedFile=DATA_FILE", panels)
        self.assertIn("requestedFile!==DATA_FILE", panels)


if __name__ == "__main__":
    unittest.main()
