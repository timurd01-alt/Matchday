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


if __name__ == "__main__":
    unittest.main()
