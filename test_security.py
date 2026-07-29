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
        self.assertEqual(findings, [(1, "literal assigned to SERVICE_API_KEY")])

    def test_allows_placeholders_and_environment_references(self):
        self.assertEqual(self.scan_text('SERVICE_API_KEY = "PASTE_SERVICE_API_KEY"'), [])
        self.assertEqual(self.scan_text('SERVICE_API_KEY = "${SERVICE_API_KEY}"'), [])

    def test_detects_private_key_material(self):
        findings = self.scan_text("-----BEGIN " + "PRIVATE KEY-----\nnot-real\n")
        self.assertEqual(findings, [(1, "private key")])


class DeploymentSecurityTests(unittest.TestCase):
    def test_leaderboard_uses_verified_pick_rows_not_client_totals(self):
        source = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")
        self.assertIn("verified_picks", source)
        self.assertIn('action === "pick"', source)
        self.assertIn('action === "sync"', source)
        self.assertNotIn('action === "score"', source)
        self.assertNotRegex(source, r"const\s*\{[^}]*hits[^}]*graded")

    def test_leaderboard_reads_public_data_and_allows_the_production_site(self):
        source = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")
        self.assertIn(
            'process.env.PUBLIC_SITE_ORIGIN || "https://matchdayterminal.com"',
            source,
        )
        self.assertIn("process.env.PUBLIC_DATA_ORIGIN || PUBLIC_SITE_ORIGIN", source)
        safe_origins = source[source.index("const SAFE_ORIGINS"):source.index("const HANDLE_POOL")]
        self.assertIn("PUBLIC_SITE_ORIGIN", safe_origins)
        self.assertIn("PUBLIC_DATA_ORIGIN", safe_origins)

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


if __name__ == "__main__":
    unittest.main()
