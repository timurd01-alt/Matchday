"""social_publish.py: nothing is ever sent twice, late, or blind.

Every test runs against a recording fake transport; no request leaves the
machine. The suite is standard library only, like the module.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import social_publish as sp

NOW = dt.datetime(2026, 11, 5, 15, 0, tzinfo=dt.timezone.utc)


def _post(key="k1", kind="slate_preview", hours=10, media=None, platform="x"):
    expires = (NOW + dt.timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return sp.Post(platform, key, kind, f"text for {key}", media, expires)


class FakeTransport:
    """Answers by (method, path); records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        path = url.split("?")[0]
        for (m, suffix), answer in self.routes.items():
            if m == method and path.endswith(suffix):
                if isinstance(answer, Exception):
                    raise answer
                if callable(answer):
                    answer = answer()
                status, payload = answer
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                return sp.Response(status, {}, raw)
        raise AssertionError(f"unexpected {method} {url}")


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.ledger = sp.Ledger("x", self.dir)

    def tearDown(self):
        self._tmp.cleanup()


class Selection(Workspace):
    def test_first_eligible_post_only(self):
        chosen, _ = sp.select([_post("a"), _post("b")], self.ledger, NOW)
        self.assertEqual([p.key for p in chosen], ["a"])

    def test_a_sent_key_is_never_sent_again(self):
        self.ledger.record("a", "slate_preview", "success", NOW - dt.timedelta(days=3), post_id="1")
        chosen, _ = sp.select([_post("a"), _post("b")], self.ledger, NOW)
        self.assertEqual([p.key for p in chosen], ["b"])

    def test_an_unknown_outcome_stops_the_platform(self):
        self.ledger.record("a", "slate_preview", "ambiguous", NOW - dt.timedelta(days=2))
        chosen, reasons = sp.select([_post("b")], self.ledger, NOW)
        self.assertEqual(chosen, [])
        self.assertIn("--resolve", reasons[0])

    def test_a_failed_attempt_may_be_retried(self):
        self.ledger.record("a", "slate_preview", "failed", NOW - dt.timedelta(days=2))
        chosen, _ = sp.select([_post("a")], self.ledger, NOW)
        self.assertEqual([p.key for p in chosen], ["a"])

    def test_items_about_to_expire_are_held(self):
        chosen, reasons = sp.select([_post("soon", hours=0.25), _post("later")], self.ledger, NOW)
        self.assertEqual([p.key for p in chosen], ["later"])
        self.assertIn("expires too soon", reasons[0])

    def test_daily_cap(self):
        for i in range(sp.DAILY_CAP["x"]):
            self.ledger.record(f"s{i}", "k", "success", NOW - dt.timedelta(hours=4 + i * 4), post_id=str(i))
        chosen, reasons = sp.select([_post("new")], self.ledger, NOW)
        self.assertEqual(chosen, [])
        self.assertIn("daily cap", reasons[0])

    def test_minimum_gap(self):
        self.ledger.record("s", "k", "success", NOW - dt.timedelta(hours=1), post_id="1")
        chosen, reasons = sp.select([_post("new")], self.ledger, NOW)
        self.assertEqual(chosen, [])
        self.assertIn("ago", reasons[0])

    def test_nothing_to_send_is_silent(self):
        self.assertEqual(sp.select([], self.ledger, NOW), ([], []))

    def test_time_sensitive_kinds_come_first(self):
        queue = {"items": [
            {"kind": "power_top25", "key": "p", "caption": "c", "expires_at": "2026-11-08T00:00:00Z"},
            {"kind": "upset_watch", "key": "u", "caption": "c", "expires_at": "2026-11-07T00:00:00Z"},
        ]}
        self.assertEqual([p.key for p in sp.candidates("x", queue)], ["u", "p"])


class Candidates(Workspace):
    def test_x_attaches_the_items_graphic(self):
        (self.dir / "rankings.png").write_bytes(b"png")
        (self.dir / "manifest.json").write_text(json.dumps(
            {"images": [{"item_key": "p", "file": "rankings.png"}]}), encoding="utf-8")
        queue = {"items": [
            {"kind": "power_top25", "key": "p", "caption": "c", "expires_at": "2026-11-08T00:00:00Z"},
            {"kind": "scorecard", "key": "s", "caption": "c", "expires_at": "2026-11-08T00:00:00Z"}]}
        posts = {p.key: p for p in sp.candidates("x", queue, graphics=self.dir)}
        self.assertEqual(posts["p"].media.name, "rankings.png")
        self.assertIsNone(posts["s"].media)

    def test_tiktok_only_posts_items_with_a_video(self):
        (self.dir / "a.mp4").write_bytes(b"mp4")
        (self.dir / "manifest.json").write_text(json.dumps({"videos": [
            {"item_key": "a", "file": "a.mp4", "tiktok_caption": "tt caption"}]}), encoding="utf-8")
        queue = {"items": [
            {"kind": "scorecard", "key": "a", "caption": "x caption", "expires_at": "2026-11-08T00:00:00Z"},
            {"kind": "article", "key": "b", "caption": "x caption", "expires_at": "2026-11-08T00:00:00Z"}]}
        posts = sp.candidates("tiktok", queue, videos=self.dir)
        self.assertEqual([(p.key, p.text) for p in posts], [("a", "tt caption")])


CREDS = {name: "v-" + name for name in sp.X_CREDENTIALS}


class XFlow(Workspace):
    def test_oauth_signs_the_query_but_not_the_body(self):
        sig = lambda url: sp.oauth1_header("GET", url, "k", "s", "t", "ts", nonce="n", timestamp=1)
        self.assertEqual(sig("https://api.x.com/2/media/upload?a=1"), sig("https://api.x.com/2/media/upload?a=1"))
        self.assertNotEqual(sig("https://api.x.com/2/media/upload?a=1"), sig("https://api.x.com/2/media/upload?a=2"))
        self.assertTrue(sig("https://api.x.com/2/tweets").startswith("OAuth "))

    def test_upload_then_post_with_media(self):
        image = self.dir / "rankings.png"
        image.write_bytes(b"\x89PNG" + b"0" * 100)
        polls = iter([(200, {"data": {"processing_info": {"state": "succeeded"}}})])
        fake = FakeTransport({
            ("POST", "/media/upload/initialize"): (200, {"data": {"id": "777"}}),
            ("POST", "/media/upload/777/append"): (204, b""),
            ("POST", "/media/upload/777/finalize"): (200, {"data": {"id": "777",
                "processing_info": {"state": "pending", "check_after_secs": 1}}}),
            ("GET", "/media/upload"): lambda: next(polls),
            ("POST", "/tweets"): (201, {"data": {"id": "9001", "text": "t"}}),
        })
        client = sp.XClient(CREDS, transport=fake, sleep=lambda s: None)
        code = sp.publish("x", [_post("p", media=image)], self.ledger, client, NOW)
        self.assertEqual(code, 0)
        init = json.loads(fake.calls[0][3])
        self.assertEqual(init, {"media_type": "image/png", "total_bytes": 104, "media_category": "tweet_image"})
        self.assertIn(b'name="segment_index"\r\n\r\n0', fake.calls[1][3])
        self.assertIn("multipart/form-data; boundary=", fake.calls[1][2]["Content-Type"])
        self.assertIn("command=STATUS", fake.calls[3][1])
        tweet = json.loads(fake.calls[4][3])
        self.assertEqual(tweet["media"], {"media_ids": ["777"]})
        for _method, _url, headers, _body in fake.calls:
            self.assertTrue(headers["Authorization"].startswith("OAuth "))
        latest = self.ledger.latest()["p"]
        self.assertEqual((latest["status"], latest["post_id"]), ("success", "9001"))

    def test_rejection_is_recorded_as_failed(self):
        fake = FakeTransport({("POST", "/tweets"): (403, {"detail": "nope"})})
        code = sp.publish("x", [_post("p")], self.ledger, sp.XClient(CREDS, transport=fake), NOW)
        self.assertEqual(code, 1)
        self.assertEqual(self.ledger.latest()["p"]["status"], "failed")

    def test_no_response_is_ambiguous_and_blocks_the_next_run(self):
        fake = FakeTransport({("POST", "/tweets"): sp.AmbiguousError("timed out")})
        code = sp.publish("x", [_post("p")], self.ledger, sp.XClient(CREDS, transport=fake), NOW)
        self.assertEqual(code, 2)
        self.assertEqual(self.ledger.unresolved(), ["p"])
        chosen, _ = sp.select([_post("q")], self.ledger, NOW + dt.timedelta(days=1))
        self.assertEqual(chosen, [])

    def test_missing_credentials_refuse_before_any_request(self):
        with self.assertRaises(sp.DefinitiveError):
            sp.XClient({})

    def test_ledger_never_holds_text_or_credentials(self):
        fake = FakeTransport({("POST", "/tweets"): (201, {"data": {"id": "1"}})})
        sp.publish("x", [_post("p")], self.ledger, sp.XClient(CREDS, transport=fake), NOW)
        raw = self.ledger.path.read_text(encoding="utf-8")
        self.assertNotIn("text for p", raw)
        for value in CREDS.values():
            self.assertNotIn(value, raw)


class MemoryStore(sp.TokenStore):
    def __init__(self, token, fail=False):
        self.token, self.fail, self.saved = token, fail, []

    def load(self):
        return self.token

    def save(self, token):
        if self.fail:
            raise sp.DefinitiveError("cannot save")
        self.saved.append(token)
        self.token = token


def _tiktok_routes(status_sequence=("SEND_TO_USER_INBOX",)):
    statuses = iter(status_sequence)
    return {
        ("POST", "/oauth/token/"): (200, {"access_token": "AT", "refresh_token": "R2",
                                          "expires_in": 7200, "scope": "video.upload"}),
        ("POST", "/post/publish/inbox/video/init/"): (200, {"data": {
            "publish_id": "v_inbox_1", "upload_url": "https://open-upload.tiktokapis.com/upload/?t=1"},
            "error": {"code": "ok"}}),
        ("PUT", "/upload/"): (201, b""),
        ("POST", "/post/publish/status/fetch/"): lambda: (200, {"data": {"status": next(statuses)},
                                                               "error": {"code": "ok"}}),
    }


class TikTokFlow(Workspace):
    def setUp(self):
        super().setUp()
        self.ledger = sp.Ledger("tiktok", self.dir)
        self.video = self.dir / "v.mp4"
        self.video.write_bytes(b"0" * 1000)

    def test_rotated_token_is_saved_before_it_is_used(self):
        store = MemoryStore("R1")
        fake = FakeTransport(_tiktok_routes(("PROCESSING_UPLOAD", "SEND_TO_USER_INBOX")))
        client = sp.TikTokClient("ck", "cs", store, transport=fake, sleep=lambda s: None)
        code = sp.publish("tiktok", [_post("v", media=self.video, platform="tiktok")],
                          self.ledger, client, NOW)
        self.assertEqual(code, 0)
        self.assertEqual(store.saved, ["R2"])
        self.assertIn(b"refresh_token=R1", fake.calls[0][3])
        put = next(c for c in fake.calls if c[0] == "PUT")
        self.assertEqual(put[2]["Content-Range"], "bytes 0-999/1000")
        self.assertEqual(put[1], "https://open-upload.tiktokapis.com/upload/?t=1")
        init = json.loads(fake.calls[1][3])
        self.assertEqual(init["source_info"], {"source": "FILE_UPLOAD", "video_size": 1000,
                                               "chunk_size": 1000, "total_chunk_count": 1})
        latest = self.ledger.latest()["v"]
        self.assertEqual((latest["publish_id"], latest["state"]), ("v_inbox_1", "SEND_TO_USER_INBOX"))

    def test_unsaveable_token_stops_before_any_upload(self):
        fake = FakeTransport(_tiktok_routes())
        client = sp.TikTokClient("ck", "cs", MemoryStore("R1", fail=True), transport=fake)
        code = sp.publish("tiktok", [_post("v", media=self.video, platform="tiktok")],
                          self.ledger, client, NOW)
        self.assertEqual(code, 1)
        self.assertEqual([c[1].split("/v2")[-1] for c in fake.calls], ["/oauth/token/"])

    def test_processing_failure_is_definitive(self):
        fake = FakeTransport(_tiktok_routes(("FAILED",)))
        client = sp.TikTokClient("ck", "cs", MemoryStore("R1"), transport=fake, sleep=lambda s: None)
        self.assertEqual(sp.publish("tiktok", [_post("v", media=self.video, platform="tiktok")],
                                    self.ledger, client, NOW), 1)

    def test_chunking_rules(self):
        self.assertEqual(sp.TikTokClient.chunks(4_000_000), (4_000_000, 1))
        self.assertEqual(sp.TikTokClient.chunks(64 * 1024 * 1024), (64 * 1024 * 1024, 1))
        size = 105 * 1024 * 1024
        chunk, count = sp.TikTokClient.chunks(size)
        self.assertEqual((chunk, count), (sp.TIKTOK_CHUNK, size // sp.TIKTOK_CHUNK))
        self.assertLessEqual(size - chunk * (count - 1), 128 * 1024 * 1024)

    def test_authorize_url_asks_only_for_upload(self):
        url = sp.tiktok_authorize_url("ck", "https://example.com/cb", "st")
        self.assertIn("scope=user.info.basic%2Cvideo.upload", url)
        self.assertNotIn("video.publish", url)
        self.assertTrue(url.startswith("https://www.tiktok.com/v2/auth/authorize/?"))


class TokenStores(unittest.TestCase):
    def test_file_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = sp.FileTokenStore(Path(tmp) / "t.json")
            self.assertIsNone(store.load())
            store.save("R9")
            self.assertEqual(store.load(), "R9")

    def test_github_store_passes_the_token_on_stdin_only(self):
        import os
        seen = []

        def runner(args, **kwargs):
            seen.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "", "")

        previous = os.environ.get("GH_TOKEN")
        os.environ["GH_TOKEN"] = "gh"
        try:
            sp.GitHubSecretTokenStore(runner=runner).save("R3")
        finally:
            if previous is None:
                del os.environ["GH_TOKEN"]
            else:
                os.environ["GH_TOKEN"] = previous
        args, kwargs = seen[0]
        self.assertEqual(args, ["gh", "secret", "set", "TIKTOK_REFRESH_TOKEN"])
        self.assertEqual(kwargs["input"], "R3")
        self.assertNotIn("R3", " ".join(args))


class Cli(Workspace):
    def test_dry_run_sends_nothing_and_writes_nothing(self):
        code = sp.main(["x", "--now", "2026-11-05T15:00:00Z", "--ledger-dir", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_resolve_settles_an_ambiguous_attempt(self):
        self.ledger.record("p", "slate_preview", "ambiguous", NOW)
        code = sp.main(["x", "--resolve", "p", "--resolution", "success", "--post-id", "55",
                        "--ledger-dir", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertEqual(self.ledger.unresolved(), [])
        self.assertEqual(self.ledger.sent(), {"p"})

    def test_tiktok_token_file_is_gitignored(self):
        ignore = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn(".tiktok_token.json", ignore)


class Thread(Workspace):
    ITEM = {"kind": "power_top25", "key": "p", "caption": "c", "expires_at": "2026-11-08T00:00:00Z",
            "facts": {"rows": [{"rank": i, "team": f"Team Number {i} Fighting Things", "rating": 40 - i}
                               for i in range(1, 26)]}}

    def test_thread_covers_all_25_under_the_limit(self):
        replies = sp.top25_thread(self.ITEM)
        self.assertGreaterEqual(len(replies), 2)
        self.assertTrue(all(len(r) <= sp.THREAD_LIMIT for r in replies))
        joined = "\n".join(replies)
        for rank in range(1, 26):
            self.assertIn(f"{rank}. Team Number {rank}", joined)
        self.assertNotIn("http", joined)

    def test_only_the_top_25_gets_a_thread(self):
        queue = {"items": [self.ITEM, {"kind": "scorecard", "key": "s", "caption": "c",
                                       "expires_at": "2026-11-08T00:00:00Z", "facts": {}}]}
        posts = {p.key: p for p in sp.candidates("x", queue)}
        self.assertTrue(posts["p"].thread)
        self.assertEqual(posts["s"].thread, ())

    def test_replies_chain_and_do_not_count_against_the_cap(self):
        ids = (str(n) for n in range(100, 200))
        fake = FakeTransport({("POST", "/tweets"): lambda: (201, {"data": {"id": next(ids)}})})
        post = sp.candidates("x", {"items": [self.ITEM]})[0]
        code = sp.publish("x", [post], self.ledger, sp.XClient(CREDS, transport=fake), NOW)
        self.assertEqual(code, 0)
        bodies = [json.loads(c[3]) for c in fake.calls]
        self.assertNotIn("reply", bodies[0])
        self.assertEqual(bodies[1]["reply"], {"in_reply_to_tweet_id": "100"})
        self.assertEqual(bodies[2]["reply"], {"in_reply_to_tweet_id": "101"})
        self.assertEqual(len(self.ledger.successes_since(NOW - dt.timedelta(days=1))), 1)

    def test_a_failed_reply_leaves_the_post_standing(self):
        answers = iter([(201, {"data": {"id": "100"}}), (403, {"detail": "no"})])
        fake = FakeTransport({("POST", "/tweets"): lambda: next(answers)})
        post = sp.candidates("x", {"items": [self.ITEM]})[0]
        code = sp.publish("x", [post], self.ledger, sp.XClient(CREDS, transport=fake), NOW)
        self.assertEqual(code, 1)
        latest = self.ledger.latest()
        self.assertEqual(latest["p"]["status"], "success")
        self.assertEqual(latest["p#1"]["status"], "failed")
        self.assertEqual(self.ledger.unresolved(), [])


class Planning(Workspace):
    def test_plan_names_a_video_kind_without_any_video_on_disk(self):
        queue = {"items": [
            {"kind": "article", "key": "a", "caption": "c", "expires_at": "2026-11-08T00:00:00Z"},
            {"kind": "slate_preview", "key": "s", "caption": "c", "expires_at": "2026-11-08T00:00:00Z"}]}
        posts = sp.candidates("tiktok", queue, assume_videos=True)
        self.assertEqual([p.kind for p in posts], ["slate_preview"])

    def test_outside_a_slot_the_cli_sends_nothing(self):
        code = sp.main(["x", "--now", "2026-11-05T08:00:00Z", "--ledger-dir", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertEqual(list(self.dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
