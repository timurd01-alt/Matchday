import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class MobileNavigationTests(unittest.TestCase):
    def test_more_trigger_is_phone_only(self):
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
        self.assertTrue(any(".sidebar .navMore{display:none!important}" in block
                            for block in desktop_rules))

    def test_primary_navigation_includes_summary_home(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        primary = re.findall(
            r'<button class="navbtn" data-primary(?: data-mobile-primary)? data-v="([^"]+)"[^>]*>.*?'
            r'<span class="lbl">([^<]+)</span>',
            html,
            flags=re.DOTALL,
        )
        self.assertEqual(
            primary,
            [("home", "Home"), ("matches", "Games"), ("groups", "Rankings"),
             ("results", "Results"), ("news", "Research")],
        )
        self.assertEqual(html.count('class="navbtn navMore"'), 1)
        self.assertNotIn('data-primary data-v="score"', html)

    def test_secondary_tools_are_direct_on_desktop_and_behind_more_on_phones(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for view in ("score", "bracket", "community"):
            self.assertIn(f'data-v="{view}"', html)
            self.assertNotIn(f'data-primary data-v="{view}"', html)
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".sidebar .navbtn:not([data-mobile-primary]):not(.navMore){display:none}", css)
        self.assertIn(".sidebar.navSheet .navbtn:not(.navMore){display:flex}", css)
        self.assertIn("games:'matches'", core)
        self.assertIn("rankings:'groups'", core)
        self.assertIn("research:'news'", core)
        self.assertIn("document.querySelector('#nav .navMore')?.focus()", core)

    def test_desktop_full_width_grid_cannot_override_the_phone_layout(self):
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        desktop = css[css.rindex("@media(min-width:701px){"):]
        # Inspect the app grid, not whichever component happens to declare
        # the last phone breakpoint (the CFP row has its own two-column grid).
        phone_grids = re.findall(
            r"@media\(max-width:700px\)\s*\{\s*(\.app,\.app\.noinsight,\.app\.gamesWide\{[^}]+\})",
            css,
        )
        self.assertTrue(phone_grids, "The app's phone grid rule is missing")
        phone = phone_grids[-1]
        self.assertIn("grid-template-columns:62px minmax(0,1fr)", desktop)
        self.assertIn("grid-template-columns:1fr", phone)
        self.assertIn('grid-template-areas:"strip" "main" "side"', phone)

    def test_wide_desktop_grid_reserves_the_full_navigation_width(self):
        """The rail's grid track must widen at the same breakpoint the rail does.

        This asserted the track at min-width:1400px while the rail widens to
        112px at min-width:1181px, so between those two widths -- 1280 and 1366
        among them -- the rail sat 112px wide in a 62px track and covered the
        first 50px of the content beside it. Pinning the literal breakpoint is
        what let the two drift apart, so the relationship is checked instead.
        """
        import re
        css = (ROOT / "styles.css").read_text(encoding="utf-8")

        def breakpoints(declaration):
            found = []
            for match in re.finditer(r"@media\(min-width:(\d+)px\)\{", css):
                start = match.end()
                depth, i = 1, start
                while i < len(css) and depth:
                    if css[i] == "{":
                        depth += 1
                    elif css[i] == "}":
                        depth -= 1
                    i += 1
                if declaration in css[start:i]:
                    found.append(int(match.group(1)))
            return found

        # The two-column rule is the one that wins: a later min-width:701px
        # block collapses the three-column layout for every desktop width, so
        # matching the bare declaration would also hit the three-column rule
        # that block overrides -- and pass whatever the two-column one says.
        rail = breakpoints(".sidebar{width:112px")
        track = breakpoints(
            ".app,.app.noinsight,.app.gamesWide{grid-template-columns:112px minmax(0,1fr)}"
        )
        self.assertTrue(rail, "no breakpoint widens the rail to 112px")
        self.assertTrue(track, "no breakpoint widens the rail's grid track to 112px")
        self.assertLessEqual(
            min(track), min(rail),
            f"the rail widens to 112px at {min(rail)}px but its grid track only "
            f"grows at {min(track)}px, so between those widths it covers the content",
        )

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
