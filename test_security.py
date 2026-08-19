import pathlib
import re
import tempfile
import unittest

import security_check


ROOT = pathlib.Path(__file__).resolve().parent


class SecretScannerTests(unittest.TestCase):
    def scan_text(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "sample.txt"
            path.write_text(text, encoding="utf-8")
            return security_check.scan(path)

    def test_detects_literal_secret_assignment_without_echoing_value(self):
        findings = self.scan_text('SERVICE_API_' + 'KEY = "abcdefghijklmnopqrstuvwxyz123456"')
        self.assertEqual(findings, [(1, "literal credential assignment")])

    def test_allows_placeholders_and_environment_references(self):
        self.assertEqual(self.scan_text('SERVICE_API_KEY = "PASTE_SERVICE_API_KEY"'), [])
        self.assertEqual(self.scan_text('SERVICE_API_KEY = "${SERVICE_API_KEY}"'), [])

    def test_detects_private_key_material(self):
        findings = self.scan_text("-----BEGIN " + "PRIVATE KEY-----\nnot-real\n")
        self.assertEqual(findings, [(1, "private key")])


class DeploymentSecurityTests(unittest.TestCase):
    def test_release_notes_render_without_an_html_sink(self):
        source = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        renderer = source[source.index("function renderSystemUpdates"):
                          source.index("function renderStatus")]
        self.assertNotIn("innerHTML", renderer)
        self.assertIn("textContent", renderer)
        self.assertIn("replaceChildren", renderer)

    def test_score_plain_text_does_not_strip_tags_with_a_regex(self):
        for name in ("app-1-core.js", "app-3-panels.js", "app-4-features.js"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"replace\(/<\[\^>\]\+>/g")
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertIn("function scorePlainText", core)

    def test_round_labels_do_not_replace_text_with_itself(self):
        source = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        self.assertNotIn("replace('Round of 32','Round of 32')", source)
        self.assertNotIn("replace('Round of 16','Round of 16')", source)

    def test_leaderboard_uses_verified_pick_rows_not_client_totals(self):
        source = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")
        self.assertIn("verified_picks", source)
        self.assertIn('action === "pick"', source)
        self.assertIn('action === "sync"', source)
        self.assertNotIn('action === "score"', source)
        self.assertNotRegex(source, r"const\s*\{[^}]*hits[^}]*graded")

    def test_leaderboard_reads_public_data_and_allows_the_production_site(self):
        """The origin allowlist moved to _accounts.js when accounts were added;
        this follows it there rather than being deleted.

        The assertion is about a security property -- which origins the API
        trusts -- not about which file holds the constant, so a refactor that
        preserves the property should keep the test, pointed at the new
        location. Worth noting this test is not in deploy.yml's suite list, so
        CI never ran it and the stale assertion sat green in every PR."""
        accounts = (ROOT / "api" / "_accounts.js").read_text(encoding="utf-8")
        self.assertIn(
            'process.env.PUBLIC_SITE_ORIGIN || "https://matchdayterminal.com"',
            accounts,
        )
        self.assertIn("process.env.PUBLIC_DATA_ORIGIN || PUBLIC_SITE_ORIGIN", accounts)
        safe_origins = accounts[accounts.index("const SAFE_ORIGINS"):
                                accounts.index("export const HANDLE_POOL")]
        self.assertIn("PUBLIC_SITE_ORIGIN", safe_origins)
        self.assertIn("PUBLIC_DATA_ORIGIN", safe_origins)
        # And the endpoint must actually consume them rather than defining its
        # own origin, which is the way this property would quietly regress.
        leaderboard = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")
        self.assertIn("PUBLIC_DATA_ORIGIN", leaderboard)
        self.assertNotIn("matchdayterminal.com", leaderboard)

    def test_security_headers_are_configured(self):
        config = (ROOT / "vercel.json").read_text(encoding="utf-8")
        for header in ("Content-Security-Policy", "X-Content-Type-Options",
                       "Referrer-Policy", "Permissions-Policy"):
            self.assertIn(header, config)

    def test_workflow_actions_are_immutable(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        refs = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", workflow)
        self.assertTrue(refs)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs))

    def test_rate_limit_key_has_no_guessable_fallback(self):
        """Rate-limit buckets are keyed by an HMAC so the table never stores a
        raw IP or device id. A literal fallback secret defeats that: anyone
        could compute the bucket key for an identifier that is not theirs and
        spend that victim's allowance, locking them out with the limiter
        working exactly as designed."""
        source = (ROOT / "api" / "_accounts.js").read_text(encoding="utf-8")
        signature = source[source.index("export function opaqueKey"):]
        signature = signature[:signature.index("\n}")]
        self.assertIn("process.env.RATE_LIMIT_SECRET", signature)
        self.assertNotRegex(
            signature,
            r"process\.env\.\w+\s*\|\|\s*[\"'][^\"']+[\"']",
            "opaqueKey must not fall back to a literal secret",
        )
        self.assertIn("throw new Error", signature)


if __name__ == "__main__":
    unittest.main()
