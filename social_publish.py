"""social_publish.py -- post the week's content to X and send videos to TikTok drafts.

Phase 4 of the content bot. Reads what the earlier phases produced -- the
content queue, the studio PNGs (render_social.py) and the MP4s
(render_reels.py) -- and publishes through the official APIs only:

    X        one post per content item, with its studio graphic attached when
             there is one (OAuth 1.0a user context, v2 media upload + POST /2/tweets)
    TikTok   one video per item, uploaded to the account's inbox as a DRAFT
             (Content Posting API, video.upload scope). A person opens TikTok,
             adds a sound and posts it. Nothing goes public from here.

Dry run is the default and needs no credentials: it prints exactly what would
be sent. `--publish` sends, and the workflow only passes it when the
repository variable SOCIAL_PUBLISHING is "on" -- that variable is the kill switch.

The rules that keep a bot honest
--------------------------------
* **A key is published once, ever.** The per-platform ledger
  (social/ledger_<platform>.jsonl) records every attempt; a successful key is
  never sent again, even if the queue offers it next week.
* **An unknown outcome stops the platform.** A request that times out may
  have posted. It is recorded as `ambiguous`, and nothing more is sent to that
  platform until someone checks the account and runs `--resolve`. Posting a
  duplicate is worse than posting late.
* **Expiring items are never sent late.** An item within EXPIRY_MARGIN of its
  expiry is skipped; the queue already withholds expired ones.
* **Pace is capped**: at most DAILY_CAP[platform] per rolling 24 hours and
  at least MIN_GAP[platform] apart, so one post per run.
* **Credentials never touch the ledger, the log or the repo.** TikTok's
  refresh token rotates on every use (the old one dies immediately), so the
  new one is saved before anything else happens -- to a local file, or back
  into the GitHub secret in CI. If it cannot be saved, the run refuses to
  refresh at all rather than strand the account.

Usage:
    python social_publish.py x --graphics out/graphics                 # dry run
    python social_publish.py x --graphics out/graphics --publish
    python social_publish.py tiktok --videos out/videos                # dry run
    python social_publish.py tiktok --videos out/videos --publish
    python social_publish.py x --resolve KEY --resolution success --post-id 123
    python social_publish.py tiktok-auth --redirect-uri https://example.com/cb
    python social_publish.py tiktok-auth --redirect-uri https://example.com/cb --code CODE

Environment:
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
    TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET
    TIKTOK_REFRESH_TOKEN + GH_TOKEN (CI: rotated token written back with `gh secret set`)
    or a token file (local: --token-file, default .tiktok_token.json, gitignored)
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import content_engine
import social_schedule

ROOT = Path(__file__).resolve().parent
LEDGER_DIR = ROOT / "social"
PLATFORMS = ("x", "tiktok")
DAILY_CAP = {"x": 3, "tiktok": 3}        # TikTok allows at most 5 pending drafts per 24h
MIN_GAP = {"x": dt.timedelta(hours=3), "tiktok": dt.timedelta(hours=1)}
EXPIRY_MARGIN = dt.timedelta(minutes=30)
# Time-sensitive items first: a preview is worthless after kickoff, a Top 25
# is still true on Wednesday.
PRIORITY = ("upset_watch", "game_of_the_week", "slate_preview", "power_top25",
            "ballot_top25", "upset_results", "scorecard", "article")
USER_AGENT = "MatchdayContentBot/1.0"
THREAD_KIND = "thread"
THREAD_LIMIT = 270

X_API = "https://api.x.com/2"
X_SEGMENT = 4 * 1024 * 1024               # under X's documented 5 MB guidance
X_PROCESSING_WAIT = 120

TIKTOK_API = "https://open.tiktokapis.com/v2"
TIKTOK_AUTHORIZE = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_SINGLE_CHUNK_MAX = 64 * 1024 * 1024
TIKTOK_CHUNK = 10 * 1024 * 1024
TIKTOK_STATUS_WAIT = 90


class DefinitiveError(RuntimeError):
    """The platform said no. Nothing was posted."""


class AmbiguousError(RuntimeError):
    """The request may or may not have posted. A person has to check."""


# --------------------------------------------------------------------------- http

@dataclasses.dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8") or "null")
        except ValueError:
            return None


Transport = Callable[[str, str, dict[str, str], bytes | None, float], Response]


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None,
                     timeout: float) -> Response:
    request = urllib.request.Request(url, data=body, method=method,
                                     headers=dict(headers, **{"User-Agent": USER_AGENT}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, dict(exc.headers or {}), exc.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AmbiguousError(f"{method} {urllib.parse.urlsplit(url).path}: no response ({exc})") from exc


# --------------------------------------------------------------------------- ledger

def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Ledger:
    """Append-only JSON lines: every attempt and its outcome, per platform."""

    def __init__(self, platform: str, directory: Path = LEDGER_DIR):
        self.platform = platform
        self.path = Path(directory) / f"ledger_{platform}.jsonl"

    def events(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("key"):
                out.append(event)
        return out

    def append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")

    def latest(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for event in self.events():
            latest[event["key"]] = event
        return latest

    def unresolved(self) -> list[str]:
        return [k for k, e in self.latest().items() if e.get("status") in ("attempting", "ambiguous")]

    def sent(self) -> set[str]:
        return {k for k, e in self.latest().items() if e.get("status") == "success"}

    def successes_since(self, moment: dt.datetime) -> list[dt.datetime]:
        """Successful posts since `moment`; a thread reply is part of its post, not one more."""
        out = []
        for event in self.events():
            at = content_engine.parse_time(event.get("at"))
            if event.get("kind") == THREAD_KIND:
                continue
            if event.get("status") == "success" and at and at >= moment:
                out.append(at)
        return out

    def record(self, key: str, kind: str, status: str, now: dt.datetime, **extra: Any) -> None:
        event = {"platform": self.platform, "key": key, "kind": kind, "status": status,
                 "at": _iso(now)}
        event.update({k: v for k, v in extra.items() if v not in (None, "")})
        if "detail" in event:
            event["detail"] = str(event["detail"])[:300]
        self.append(event)


# --------------------------------------------------------------------------- plan

@dataclasses.dataclass
class Post:
    platform: str
    key: str
    kind: str
    text: str
    media: Path | None
    expires_at: str
    thread: tuple[str, ...] = ()   # X replies posted under the main post, in order

    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def media_sha256(self) -> str | None:
        return hashlib.sha256(self.media.read_bytes()).hexdigest() if self.media else None


def _manifest(directory: Path | None) -> dict[str, Any]:
    if directory is None:
        return {}
    try:
        return json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def top25_thread(item: dict[str, Any]) -> tuple[str, ...]:
    """The full 25 as replies under the graphic, each under X's limit, no links."""
    rows = item.get("facts", {}).get("rows") or []
    lines = ["%d. %s %.2f" % (r["rank"], content_engine.short(r["team"]), r["rating"])
             for r in rows if isinstance(r.get("rating"), (int, float))]
    replies, current = [], ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > THREAD_LIMIT:
            replies.append(current)
            current = line
        else:
            current = candidate
    if current:
        replies.append(current)
    return tuple(replies)


def candidates(platform: str, queue: dict[str, Any], graphics: Path | None = None,
               videos: Path | None = None, assume_videos: bool = False) -> list[Post]:
    """Everything this platform could post now, most time-sensitive first."""
    order = {kind: i for i, kind in enumerate(PRIORITY)}
    items = sorted(queue.get("items", []),
                   key=lambda i: (order.get(i["kind"], len(order)), i["expires_at"]))
    if platform == "x":
        images = {e.get("item_key"): Path(graphics) / e["file"]
                  for e in _manifest(graphics).get("images", []) if e.get("item_key")}
        return [Post("x", item["key"], item["kind"], item["caption"],
                     images.get(item["key"]) if images.get(item["key"], Path()).is_file() else None,
                     item["expires_at"],
                     top25_thread(item) if item["kind"] == "power_top25" else ())
                for item in items]
    if platform == "tiktok" and assume_videos:
        # Planning: which item would go next if its video were rendered.
        import render_reels

        return [Post("tiktok", item["key"], item["kind"], "", None, item["expires_at"])
                for item in items if item["kind"] in render_reels.BUILDERS]
    if platform == "tiktok":
        clips = {e["item_key"]: e for e in _manifest(videos).get("videos", []) if e.get("item_key")}
        out = []
        for item in items:
            entry = clips.get(item["key"])
            path = Path(videos) / entry["file"] if entry else None
            if path is not None and path.is_file():
                out.append(Post("tiktok", item["key"], item["kind"], entry["tiktok_caption"],
                                path, item["expires_at"]))
        return out
    raise ValueError(platform)


def select(posts: list[Post], ledger: Ledger, now: dt.datetime) -> tuple[list[Post], list[str]]:
    """The one post allowed this run (MIN_GAP rules out two at once), and why others wait."""
    reasons: list[str] = []
    unresolved = ledger.unresolved()
    if unresolved:
        return [], [f"unresolved attempt(s) {unresolved}: check the account, then run --resolve"]
    sent = ledger.sent()
    recent = sorted(ledger.successes_since(now - dt.timedelta(hours=24)))
    room = DAILY_CAP[ledger.platform] - len(recent)
    if room <= 0:
        return [], [f"daily cap of {DAILY_CAP[ledger.platform]} reached"]
    if recent and now - recent[-1] < MIN_GAP[ledger.platform]:
        return [], [f"last post was under {MIN_GAP[ledger.platform]} ago"]
    for post in posts:
        expires = content_engine.parse_time(post.expires_at)
        if post.key in sent:
            continue
        if expires is None or expires - now < EXPIRY_MARGIN:
            reasons.append(f"{post.key}: expires too soon")
            continue
        return [post], reasons
    return [], reasons


# --------------------------------------------------------------------------- X

def _percent(value: object) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def oauth1_header(method: str, url: str, api_key: str, api_secret: str, access_token: str,
                  access_token_secret: str, *, nonce: str | None = None,
                  timestamp: int | None = None) -> str:
    """OAuth 1.0a HMAC-SHA1. JSON and multipart bodies are not signed; query strings are."""
    oauth = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp if timestamp is not None else int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    parsed = urllib.parse.urlsplit(url)
    parameters = list(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    parameters.extend(oauth.items())
    normalized = "&".join(f"{_percent(k)}={_percent(v)}" for k, v in
                          sorted(parameters, key=lambda kv: (_percent(kv[0]), _percent(kv[1]))))
    base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    base = "&".join((_percent(method.upper()), _percent(base_url), _percent(normalized)))
    key = f"{_percent(api_secret)}&{_percent(access_token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode("ascii")
    return "OAuth " + ", ".join(f'{_percent(k)}="{_percent(v)}"' for k, v in sorted(oauth.items()))


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "matchday" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                     f"{value}\r\n".encode("utf-8"))
    for name, (filename, data, mime) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                     f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode("utf-8")
                     + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


X_CREDENTIALS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")


class XClient:
    def __init__(self, credentials: dict[str, str], transport: Transport = urllib_transport,
                 sleep: Callable[[float], None] = time.sleep):
        missing = [name for name in X_CREDENTIALS if not credentials.get(name)]
        if missing:
            raise DefinitiveError("missing X credentials: " + ", ".join(missing))
        self.credentials = credentials
        self.transport = transport
        self.sleep = sleep

    def _call(self, method: str, url: str, body: bytes | None = None,
              content_type: str | None = None, timeout: float = 60) -> Response:
        c = self.credentials
        headers = {"Authorization": oauth1_header(method, url, c["X_API_KEY"], c["X_API_SECRET"],
                                                  c["X_ACCESS_TOKEN"], c["X_ACCESS_TOKEN_SECRET"])}
        if content_type:
            headers["Content-Type"] = content_type
        return self.transport(method, url, headers, body, timeout)

    def _ok(self, response: Response, step: str) -> dict[str, Any]:
        if response.status >= 300:
            detail = response.body.decode("utf-8", errors="replace")[:400]
            raise DefinitiveError(f"X {step} returned HTTP {response.status}: {detail}")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def upload(self, path: Path) -> str:
        """v2 chunked upload: initialize, append, finalize, then wait for processing."""
        data = path.read_bytes()
        mime = "image/png" if path.suffix.lower() == ".png" else "video/mp4"
        category = "tweet_image" if mime.startswith("image/") else "tweet_video"
        init = self._ok(self._call("POST", f"{X_API}/media/upload/initialize", json.dumps({
            "media_type": mime, "total_bytes": len(data), "media_category": category,
        }).encode(), "application/json"), "media initialize")
        media_id = str((init.get("data") or {}).get("id") or "")
        if not media_id:
            raise DefinitiveError("X media initialize returned no id")
        for index, start in enumerate(range(0, len(data), X_SEGMENT)):
            body, ctype = multipart({"segment_index": str(index)},
                                    {"media": (path.name, data[start:start + X_SEGMENT],
                                               "application/octet-stream")})
            self._ok(self._call("POST", f"{X_API}/media/upload/{media_id}/append", body, ctype,
                                timeout=120), f"media append {index}")
        final = self._ok(self._call("POST", f"{X_API}/media/upload/{media_id}/finalize"),
                         "media finalize")
        info = (final.get("data") or {}).get("processing_info")
        waited = 0.0
        while info and info.get("state") in ("pending", "in_progress"):
            delay = float(info.get("check_after_secs") or 2)
            if waited + delay > X_PROCESSING_WAIT:
                raise DefinitiveError("X media still processing after %ds" % X_PROCESSING_WAIT)
            self.sleep(delay)
            waited += delay
            query = urllib.parse.urlencode({"command": "STATUS", "media_id": media_id})
            status = self._ok(self._call("GET", f"{X_API}/media/upload?{query}"), "media status")
            info = (status.get("data") or {}).get("processing_info")
        if info and info.get("state") == "failed":
            raise DefinitiveError(f"X media processing failed: {info.get('error')}")
        return media_id

    def post(self, text: str, media_id: str | None = None, reply_to: str | None = None) -> str:
        body: dict[str, Any] = {"text": text}
        if media_id:
            body["media"] = {"media_ids": [media_id]}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        response = self._call("POST", f"{X_API}/tweets", json.dumps(body, ensure_ascii=False).encode(),
                              "application/json")
        payload = self._ok(response, "post")
        post_id = (payload.get("data") or {}).get("id")
        if not post_id:
            raise AmbiguousError("X accepted the post request but returned no post id")
        return str(post_id)


# --------------------------------------------------------------------------- TikTok

class TokenStore:
    """Where TikTok's rotating refresh token lives between runs."""

    def load(self) -> str | None:
        raise NotImplementedError

    def save(self, token: str) -> None:
        raise NotImplementedError


class FileTokenStore(TokenStore):
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> str | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("refresh_token")
        except (OSError, ValueError, AttributeError):
            return None

    def save(self, token: str) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({"refresh_token": token, "saved_at": _iso(_utc_now())}),
                             encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.path)


class GitHubSecretTokenStore(TokenStore):
    """CI: read TIKTOK_REFRESH_TOKEN, write the rotated one back with `gh secret set`."""

    def __init__(self, name: str = "TIKTOK_REFRESH_TOKEN",
                 runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.name = name
        self.runner = runner

    def load(self) -> str | None:
        return os.environ.get(self.name) or None

    def save(self, token: str) -> None:
        if not os.environ.get("GH_TOKEN"):
            raise DefinitiveError("GH_TOKEN is not set; cannot store the rotated TikTok token")
        result = self.runner(["gh", "secret", "set", self.name], input=token, text=True,
                             capture_output=True)
        if result.returncode != 0:
            raise DefinitiveError("could not store the rotated TikTok token: "
                                  + (result.stderr or "")[:200])


def _form(fields: dict[str, str]) -> bytes:
    return urllib.parse.urlencode(fields).encode()


def _tiktok_tokens(response: Response) -> dict[str, Any]:
    payload = response.json() or {}
    if response.status >= 300 or not payload.get("access_token"):
        reason = payload.get("error_description") or payload.get("error") or response.status
        raise DefinitiveError(f"TikTok token request failed: {reason}")
    return payload


class TikTokClient:
    def __init__(self, client_key: str, client_secret: str, store: TokenStore,
                 transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep):
        if not client_key or not client_secret:
            raise DefinitiveError("missing TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET")
        self.client_key, self.client_secret = client_key, client_secret
        self.store, self.transport, self.sleep = store, transport, sleep
        self.access_token: str | None = None

    def authenticate(self) -> None:
        """Refresh, and persist the replacement refresh token before anything else."""
        refresh = self.store.load()
        if not refresh:
            raise DefinitiveError("no TikTok refresh token; run `social_publish.py tiktok-auth` first")
        tokens = _tiktok_tokens(self.transport("POST", f"{TIKTOK_API}/oauth/token/", {
            "Content-Type": "application/x-www-form-urlencoded"}, _form({
                "client_key": self.client_key, "client_secret": self.client_secret,
                "grant_type": "refresh_token", "refresh_token": refresh}), 30))
        rotated = tokens.get("refresh_token")
        if rotated and rotated != refresh:
            self.store.save(rotated)
        self.access_token = tokens["access_token"]

    def _json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.transport("POST", f"{TIKTOK_API}{path}", {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8"}, json.dumps(body).encode(), 30)
        payload = response.json() or {}
        code = (payload.get("error") or {}).get("code")
        if response.status >= 300 or code not in (None, "ok"):
            message = (payload.get("error") or {}).get("message") or response.status
            raise DefinitiveError(f"TikTok {path} failed: {code}: {message}")
        return payload.get("data") or {}

    @staticmethod
    def chunks(size: int) -> tuple[int, int]:
        """(chunk_size, total_chunk_count) per TikTok's media transfer rules."""
        if size <= TIKTOK_SINGLE_CHUNK_MAX:
            return size, 1
        return TIKTOK_CHUNK, size // TIKTOK_CHUNK

    def upload_draft(self, path: Path) -> tuple[str, str]:
        if not self.access_token:
            self.authenticate()
        data = path.read_bytes()
        chunk, count = self.chunks(len(data))
        init = self._json("/post/publish/inbox/video/init/", {"source_info": {
            "source": "FILE_UPLOAD", "video_size": len(data), "chunk_size": chunk,
            "total_chunk_count": count}})
        publish_id, upload_url = init.get("publish_id"), init.get("upload_url")
        if not publish_id or not upload_url:
            raise DefinitiveError("TikTok init returned no publish_id/upload_url")
        for index in range(count):
            start = index * chunk
            end = len(data) if index == count - 1 else start + chunk
            response = self.transport("PUT", upload_url, {
                "Content-Type": "video/mp4", "Content-Length": str(end - start),
                "Content-Range": f"bytes {start}-{end - 1}/{len(data)}"}, data[start:end], 300)
            expected = 201 if index == count - 1 else 206
            if response.status != expected:
                raise AmbiguousError(f"TikTok chunk {index} returned HTTP {response.status}")
        state, waited = "PROCESSING_UPLOAD", 0
        while state in ("PROCESSING_UPLOAD",) and waited < TIKTOK_STATUS_WAIT:
            self.sleep(5)
            waited += 5
            status = self._json("/post/publish/status/fetch/", {"publish_id": publish_id})
            state = status.get("status") or state
            if state == "FAILED":
                raise DefinitiveError(f"TikTok processing failed: {status.get('fail_reason')}")
        return publish_id, state


def tiktok_authorize_url(client_key: str, redirect_uri: str, state: str) -> str:
    return TIKTOK_AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_key": client_key, "response_type": "code", "scope": "user.info.basic,video.upload",
        "redirect_uri": redirect_uri, "state": state})


# --------------------------------------------------------------------------- run

def publish(platform: str, posts: list[Post], ledger: Ledger, client: Any, now: dt.datetime) -> int:
    """Send each post; record attempting before, outcome after. Returns an exit code."""
    for post in posts:
        ledger.record(post.key, post.kind, "attempting", now,
                      text_sha256=post.text_sha256(), media_sha256=post.media_sha256())
        try:
            if platform == "x":
                media_id = client.upload(post.media) if post.media else None
                ref, state = client.post(post.text, media_id), None
            else:
                ref, state = client.upload_draft(post.media)
        except AmbiguousError as exc:
            ledger.record(post.key, post.kind, "ambiguous", _utc_now(), detail=exc)
            print(f"[{platform}] {post.key}: outcome unknown -- {exc}", file=sys.stderr)
            return 2
        except DefinitiveError as exc:
            ledger.record(post.key, post.kind, "failed", _utc_now(), detail=exc)
            print(f"[{platform}] {post.key}: failed -- {exc}", file=sys.stderr)
            return 1
        ledger.record(post.key, post.kind, "success", _utc_now(),
                      **({"post_id": ref} if platform == "x" else {"publish_id": ref, "state": state}))
        print(f"[{platform}] {post.key}: sent ({ref}{', ' + state if state else ''})")
        parent = ref
        for index, reply in enumerate(post.thread, 1):
            key = f"{post.key}#{index}"
            ledger.record(key, THREAD_KIND, "attempting", _utc_now(),
                          text_sha256=hashlib.sha256(reply.encode("utf-8")).hexdigest())
            try:
                parent = client.post(reply, reply_to=parent)
            except AmbiguousError as exc:
                ledger.record(key, THREAD_KIND, "ambiguous", _utc_now(), detail=exc)
                print(f"[{platform}] {key}: outcome unknown -- {exc}", file=sys.stderr)
                return 2
            except DefinitiveError as exc:
                # The post stands; a missing reply is noted, not retried blind.
                ledger.record(key, THREAD_KIND, "failed", _utc_now(), detail=exc)
                print(f"[{platform}] {key}: reply failed -- {exc}", file=sys.stderr)
                return 1
            ledger.record(key, THREAD_KIND, "success", _utc_now(), post_id=parent)
            print(f"[{platform}] {key}: reply sent ({parent})")
    return 0


def _client(platform: str, token_file: Path) -> Any:
    if platform == "x":
        return XClient({name: os.environ.get(name, "") for name in X_CREDENTIALS})
    store: TokenStore = (GitHubSecretTokenStore() if os.environ.get("TIKTOK_REFRESH_TOKEN")
                         else FileTokenStore(token_file))
    return TikTokClient(os.environ.get("TIKTOK_CLIENT_KEY", ""),
                        os.environ.get("TIKTOK_CLIENT_SECRET", ""), store)


def tiktok_auth(args: argparse.Namespace) -> int:
    key, secret = os.environ.get("TIKTOK_CLIENT_KEY", ""), os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not key:
        print("Set TIKTOK_CLIENT_KEY (and TIKTOK_CLIENT_SECRET for --code).", file=sys.stderr)
        return 1
    if not args.code:
        print("Open this URL while signed in to the Matchday TikTok account, approve, and copy\n"
              "the `code` parameter from the page it redirects to:\n")
        print(tiktok_authorize_url(key, args.redirect_uri, secrets.token_urlsafe(16)))
        print("\nThen run again with --code CODE.")
        return 0
    tokens = _tiktok_tokens(urllib_transport("POST", f"{TIKTOK_API}/oauth/token/", {
        "Content-Type": "application/x-www-form-urlencoded"}, _form({
            "client_key": key, "client_secret": secret, "code": args.code,
            "grant_type": "authorization_code", "redirect_uri": args.redirect_uri}), 30))
    FileTokenStore(Path(args.token_file)).save(tokens["refresh_token"])
    print(f"Saved the refresh token to {args.token_file} (scopes: {tokens.get('scope')}).")
    print("For CI, store it once as the TIKTOK_REFRESH_TOKEN secret:\n"
          f"  gh secret set TIKTOK_REFRESH_TOKEN < {args.token_file}  (the token value only)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("platform", choices=PLATFORMS + ("tiktok-auth",))
    parser.add_argument("--graphics", help="render_social.py output folder (X images)")
    parser.add_argument("--videos", help="render_reels.py output folder (TikTok videos)")
    parser.add_argument("--publish", action="store_true", help="actually send (default: dry run)")
    parser.add_argument("--now", help="evaluate as of this UTC time (ISO 8601)")
    parser.add_argument("--ledger-dir", default=str(LEDGER_DIR))
    parser.add_argument("--token-file", default=str(ROOT / ".tiktok_token.json"))
    parser.add_argument("--resolve", metavar="KEY", help="settle an ambiguous attempt")
    parser.add_argument("--resolution", choices=("success", "failed"))
    parser.add_argument("--post-id", help="the verified post/publish id, for --resolution success")
    parser.add_argument("--redirect-uri", help="tiktok-auth: the app's registered redirect URI")
    parser.add_argument("--code", help="tiktok-auth: the code from the redirect")
    parser.add_argument("--ignore-schedule", action="store_true",
                        help="post outside the weekly slots (manual runs only)")
    parser.add_argument("--plan", action="store_true",
                        help="print only the kind of the next post (for rendering just that)")
    args = parser.parse_args(argv)

    if args.platform == "tiktok-auth":
        if not args.redirect_uri:
            parser.error("tiktok-auth needs --redirect-uri")
        return tiktok_auth(args)

    now = content_engine.parse_time(args.now) if args.now else _utc_now()
    ledger = Ledger(args.platform, Path(args.ledger_dir))

    if args.resolve:
        prior = ledger.latest().get(args.resolve)
        if not prior or prior.get("status") not in ("attempting", "ambiguous"):
            parser.error(f"{args.resolve} has no unresolved attempt")
        if not args.resolution or (args.resolution == "success" and not args.post_id):
            parser.error("--resolve needs --resolution, and success needs --post-id")
        ledger.record(args.resolve, prior.get("kind", ""), args.resolution, now,
                      post_id=args.post_id, detail="manually reconciled against the account")
        print(f"Recorded {args.resolve} as {args.resolution}.")
        return 0

    queue = content_engine.build_queue(now, ROOT)
    posts = candidates(args.platform, queue, Path(args.graphics) if args.graphics else None,
                       Path(args.videos) if args.videos else None, assume_videos=args.plan)
    slot = None
    if not args.ignore_schedule:
        posts, slot = social_schedule.order(posts, now)
    chosen, reasons = select(posts, ledger, now)
    if args.plan:
        print(chosen[0].kind if chosen else "")
        return 0
    if slot is None and not args.ignore_schedule:
        print(f"[{args.platform}] outside every posting slot; nothing to send.")
        return 0
    if slot is not None:
        print(f"slot: {slot.name}")
    for reason in reasons:
        print(f"held: {reason}")
    if not chosen:
        print(f"[{args.platform}] nothing to send.")
        return 0
    for post in chosen:
        media = f" + {post.media.name}" if post.media else ""
        print(f"[{args.platform}] {post.key}{media}\n    {post.text}")
        for reply in post.thread:
            print("    \u21b3 " + reply.replace("\n", " / "))
    if not args.publish:
        print("Dry run: nothing was sent and the ledger was not changed.")
        return 0
    return publish(args.platform, chosen, ledger, _client(args.platform, Path(args.token_file)), now)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
