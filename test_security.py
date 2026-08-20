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

    def label_id(self, label):
        """scan() addresses labels by index into the fixed LABELS table rather
        than returning their text. Resolve the index here so these tests still
        read by name and stay correct if the table is ever reordered."""
        return security_check.LABELS.index(label)

    def test_detects_literal_secret_assignment_without_echoing_value(self):
        findings = self.scan_text('SERVICE_API_' + 'KEY = "abcdefghijklmnopqrstuvwxyz123456"')
        self.assertEqual(findings, [(1, self.label_id("literal credential assignment"))])

    def test_allows_placeholders_and_environment_references(self):
        self.assertEqual(self.scan_text('SERVICE_API_KEY = "PASTE_SERVICE_API_KEY"'), [])
        self.assertEqual(self.scan_text('SERVICE_API_KEY = "${SERVICE_API_KEY}"'), [])

    def test_detects_private_key_material(self):
        findings = self.scan_text("-----BEGIN " + "PRIVATE KEY-----\nnot-real\n")
        self.assertEqual(findings, [(1, self.label_id("private key"))])

    def test_findings_never_carry_text_read_out_of_the_scanned_file(self):
        """The point of indexing labels: main() prints LABELS[label_id], so a
        finding cannot smuggle a matched substring -- part of the secret
        itself, or anything else an attacker put in a scanned file -- into the
        report. Returning a plain string here would quietly reopen that path,
        so pin the shape rather than trusting the convention to hold."""
        findings = self.scan_text(
            'SERVICE_API_' + 'KEY = "abcdefghijklmnopqrstuvwxyz123456"')
        self.assertTrue(findings)
        for line_no, label_id in findings:
            self.assertIsInstance(line_no, int)
            self.assertIsInstance(label_id, int)
            self.assertNotIsInstance(label_id, bool)
            self.assertIn(label_id, range(len(security_check.LABELS)))

    def test_every_pattern_has_a_printable_label(self):
        """main() indexes LABELS with an id scan() produced. If a pattern were
        added to KNOWN_SECRET_PATTERNS without extending LABELS in step, that
        lookup would raise mid-scan -- and it would raise on the one file that
        actually held a secret, turning a fail-closed check into a crash."""
        self.assertEqual(
            len(security_check.LABELS),
            len(security_check.KNOWN_SECRET_PATTERNS) + 1,
        )
        self.assertEqual(
            security_check.LABELS[security_check.ASSIGNMENT_LABEL_ID],
            security_check.ASSIGNMENT_LABEL,
        )


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


class PrivacyPromiseTests(unittest.TestCase):
    """The privacy policy is a promise users and Google's OAuth review rely on,
    and it is the one artefact in this repo that can be wrong without anything
    failing. It already went stale once: it claimed the leaderboard was
    "disabled in the current release" for as long as the live endpoint was
    shipping picks to a server. These tests tie the claims to the code."""

    def setUp(self):
        self.legal = (ROOT / "legal.html").read_text(encoding="utf-8")
        self.accounts = (ROOT / "api" / "_accounts.js").read_text(encoding="utf-8")
        self.core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")

    def test_policy_does_not_claim_the_leaderboard_is_off_while_it_is_on(self):
        live = re.search(r'LEADERBOARD_URL\s*=\s*"([^"]*)"', self.core)
        self.assertIsNotNone(live, "LEADERBOARD_URL not found")
        if live.group(1):
            self.assertNotIn("disabled in the current release", self.legal)
            self.assertIn("The leaderboard is live", self.legal)

    def test_policy_names_every_provider_the_api_offers(self):
        for provider in re.findall(r"^  (\w+): \{$", self.accounts, re.M):
            self.assertRegex(
                self.legal, f"(?i){provider}",
                f"{provider} sign-in is offered but the policy never names it",
            )

    def test_policy_does_not_promise_narrower_scopes_than_the_code_requests(self):
        """The policy says Google is asked for `openid` and GitHub for nothing.
        Widening a scope without revising that sentence turns it into a false
        statement about data we then receive."""
        scopes = dict(re.findall(r'^  (\w+): \{.*?scope: "([^"]*)"', self.accounts, re.M | re.S))
        self.assertEqual(scopes.get("google"), "openid")
        self.assertEqual(scopes.get("github"), "")
        self.assertIn("<code>openid</code> permission and nothing further", self.legal)
        self.assertIn("asks GitHub for no permissions at all", self.legal)

    def test_policy_does_not_promise_a_deletion_route_that_does_not_exist(self):
        self.assertIn("Delete account", self.legal)
        leaderboard = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")
        self.assertIn('action === "delete-account"', leaderboard)
        self.assertIn("export async function deleteAccount", self.accounts)

    def test_stated_retention_window_matches_the_purge(self):
        window = re.search(r"RETENTION_MS = (\d+) \* 86400000", self.accounts)
        self.assertIsNotNone(window, "RETENTION_MS not found")
        months = round(int(window.group(1)) / 30)
        self.assertIn(f"{months} months", self.legal)

    def test_deletion_removes_every_table_that_holds_the_account(self):
        """A deletion that leaves the identity row behind would let the same
        provider login return to a hollow account, and would not be erasure."""
        body = self.accounts[self.accounts.index("export async function deleteAccount"):]
        body = body[:body.index("\n}")]
        for table in ("verified_picks", "sessions", "signin_codes",
                      "account_identities", "accounts"):
            self.assertIn(f"FROM {table}", body, f"{table} survives deletion")
        self.assertIn("BEGIN", body)
        self.assertIn("ROLLBACK", body)


if __name__ == "__main__":
    unittest.main()
