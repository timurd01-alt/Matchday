"""Publish one measured, auditable Matchday Terminal promotion to X.

The bot only describes a prediction when a durable ``picks_log*.json`` record
passes the same official-receipt validator as postgame grading. Everything else
is an article or evergreen product promotion. Live publishing is opt-in; use
``--dry-run`` to inspect the next post without credentials or external side effects.
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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pick_integrity import is_official_pick_record, parse_utc


BASE_URL = "https://matchdayterminal.com/"
X_POST_URL = "https://api.x.com/2/tweets"
DEFAULT_STATE_FILE = ".x_bot_state.json"
MAX_POST_LENGTH = 280
LOCKED_PICK_WINDOW = dt.timedelta(hours=48)


@dataclasses.dataclass(frozen=True)
class Candidate:
    key: str
    text: str
    kind: str


EVERGREEN_POSTS = (
    (
        "See every forecast before the game and every grade after it. "
        "Matchday Terminal keeps the full record visible—wins, misses, and all. "
        f"{BASE_URL}"
    ),
    (
        "What goes into a sports forecast? Matchday Terminal explains its Elo, "
        "opponent-adjusted ratings, confidence, and grading process in plain language. "
        f"{BASE_URL}qa.html"
    ),
    (
        "Pregame probabilities are more useful when the receipts stay public. "
        "Explore Matchday Terminal's analysis and verified postgame grading. "
        f"{BASE_URL}content.html"
    ),
    (
        "From soccer and football to basketball and baseball, Matchday Terminal "
        "turns model signals into readable matchup analysis. "
        f"{BASE_URL}"
    ),
    (
        "Pressing, rest, form, and schedule strength all shape a soccer matchup. "
        "See how Matchday Terminal reads them. "
        f"{BASE_URL}tactics-soccer.html"
    ),
    (
        "Pace, spacing, and back-to-backs can change a basketball forecast. "
        "Explore Matchday Terminal's basketball tactics guide. "
        f"{BASE_URL}tactics-basketball.html"
    ),
    (
        "Matchday Terminal locks official picks before kickoff and grades them after "
        "the final result—no rewriting the prediction after the fact. "
        f"{BASE_URL}qa.html"
    ),
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _fit(text: str, limit: int = MAX_POST_LENGTH) -> str:
    """Keep a post below X's hard limit without ever truncating its URL."""
    text = _clean(text)
    if len(text) <= limit:
        return text
    head, separator, tail = text.rpartition(" ")
    if separator and tail.startswith(("https://", "http://")):
        allowance = limit - len(tail) - 2
        return head[:allowance].rstrip(" ,.;:-") + "… " + tail
    return text[: limit - 1].rstrip(" ,.;:-") + "…"


def _json_from_url(url: str, timeout: float = 15.0) -> object:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "MatchdayTerminalBot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _safe_json_from_url(url: str) -> object:
    try:
        return _json_from_url(url)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"warning: could not load {url}: {exc}", file=sys.stderr)
        return []


def load_pick_records(root: str | os.PathLike[str] = ".") -> list[dict]:
    records: list[dict] = []
    for path in sorted(Path(root).glob("picks_log*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        values = payload.values() if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        records.extend(record for record in values if isinstance(record, dict))
    return records


def locked_pick_candidates(records: object, now: dt.datetime) -> list[Candidate]:
    if not isinstance(records, list):
        return []
    candidates: list[tuple[dt.datetime, Candidate]] = []
    seen: set[str] = set()
    for record in records:
        if not is_official_pick_record(record) or record.get("result") not in (None, ""):
            continue
        kickoff = parse_utc(record.get("kickoff"))
        if kickoff is None or kickoff < now or kickoff - now > LOCKED_PICK_WINDOW:
            continue
        competition = _clean(record.get("competition"))
        comp_key = competition.lower()
        home = _clean(record.get("home"))
        away = _clean(record.get("away"))
        pick = _clean(record.get("pick_name"))
        fixture_id = _clean(record.get("fixture_id"))
        locked_at = _clean(record.get("locked_at"))
        confidence = record.get("confidence")
        if not all((competition, home, away, pick, fixture_id, locked_at)):
            continue
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 100:
            continue
        candidate_key = f"locked:{comp_key}:{fixture_id}:{locked_at}"
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        if record.get("outcome_basis") == "ultimate_winner":
            pick_phrase = f"locked model pick to advance: {pick}"
        elif str(record.get("pick") or "").lower() == "d":
            pick_phrase = "locked regulation pick: draw"
        else:
            pick_phrase = f"locked model pick: {pick}"
        query = urllib.parse.urlencode(
            {"sport": comp_key, "view": "matches", "match": fixture_id,
             "utm_source": "x", "utm_medium": "organic_social", "utm_campaign": "locked_pick"}
        )
        link = f"{BASE_URL}?{query}"
        text = _fit(
            f"{competition}: {home} vs {away}. Matchday Terminal {pick_phrase}. "
            f"Model probability: {round(confidence)}%. View the pregame receipt. {link}"
        )
        candidates.append((kickoff, Candidate(candidate_key, text, "locked_pick")))
    return [candidate for _, candidate in sorted(candidates, key=lambda item: item[0])]


def article_candidates(posts: object, kind: str) -> list[Candidate]:
    if not isinstance(posts, list):
        return []
    candidates: list[tuple[str, Candidate]] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        slug = _clean(post.get("slug") or post.get("id"))
        title = _clean(post.get("title"))
        date = _clean(post.get("date"))
        if not slug or not title:
            continue
        url = f"{BASE_URL}posts/{urllib.parse.quote(slug)}.html"
        text = _fit(
            f"New from Matchday Terminal: {title}. Transparent sports analysis with "
            f"the methodology and receipts left open for inspection. {url}"
        )
        candidates.append((date, Candidate(f"{kind}:{slug}", text, kind)))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in candidates]


def evergreen_candidate(now: dt.datetime) -> Candidate:
    index = now.date().toordinal() % len(EVERGREEN_POSTS)
    iso_year, iso_week, _ = now.isocalendar()
    return Candidate(
        f"evergreen:{iso_year}-W{iso_week:02d}:{index}",
        _fit(EVERGREEN_POSTS[index]),
        "evergreen",
    )


def load_state(path: str | os.PathLike[str]) -> dict:
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {"sent": []}
    except (OSError, ValueError):
        return {"sent": []}


def choose_candidate(candidates: list[Candidate], state: dict, now: dt.datetime | None = None) -> Candidate | None:
    events = [item for item in state.get("events", []) if isinstance(item, dict)]
    latest_status = {item.get("key"): item.get("status") for item in events if item.get("key")}
    # An unknown POST outcome is global: publishing a different campaign does
    # not make it safe to ignore the account reconciliation that is still due.
    if any(status in {"attempting", "ambiguous"} for status in latest_status.values()):
        return None
    blocked_keys = {key for key, status in latest_status.items() if status == "success"}
    current = now or _utc_now()
    if any(item.get("status") == "success" and str(item.get("at", "")).startswith(current.date().isoformat()) for item in events):
        return None
    return next((candidate for candidate in candidates if candidate.key not in blocked_keys), None)


def append_event(path: str | os.PathLike[str], state: dict, candidate: Candidate, status: str,
                 now: dt.datetime, post_id: str | None = None, detail: str | None = None) -> None:
    events = [item for item in state.get("events", []) if isinstance(item, dict)]
    event = {
        "key": candidate.key,
        "kind": candidate.kind,
        "status": status,
        "at": now.isoformat().replace("+00:00", "Z"),
        "text_sha256": hashlib.sha256(candidate.text.encode("utf-8")).hexdigest(),
    }
    if post_id:
        event["post_id"] = post_id
    if detail:
        event["detail"] = detail[:300]
    events.append(event)
    state["events"] = events[-1000:]
    _write_state(path, state)


def _write_state(path: str | os.PathLike[str], state: dict) -> None:
    destination = Path(path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def resolve_ambiguous(path: str | os.PathLike[str], state: dict, key: str, resolution: str,
                      now: dt.datetime, post_id: str | None = None) -> None:
    events = [item for item in state.get("events", []) if isinstance(item, dict)]
    prior = next((item for item in reversed(events) if item.get("key") == key), None)
    if prior is None or prior.get("status") not in {"attempting", "ambiguous"}:
        raise ValueError("campaign key does not have an unresolved publication attempt")
    if resolution not in {"success", "failed"}:
        raise ValueError("resolution must be success or failed")
    if resolution == "success" and not post_id:
        raise ValueError("a reconciled success requires the verified X post id")
    event = {
        "key": key,
        "kind": prior.get("kind"),
        "status": resolution,
        "at": now.isoformat().replace("+00:00", "Z"),
        "text_sha256": prior.get("text_sha256"),
        "detail": "manually reconciled against the Matchday Terminal X account",
    }
    if post_id:
        event["post_id"] = post_id
    events.append(event)
    state["events"] = events[-1000:]
    _write_state(path, state)


def _percent(value: object) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def oauth1_header(
    method: str,
    url: str,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
    *,
    nonce: str | None = None,
    timestamp: int | None = None,
) -> str:
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
    normalized = "&".join(
        f"{_percent(key)}={_percent(value)}"
        for key, value in sorted(parameters, key=lambda item: (_percent(item[0]), _percent(item[1])))
    )
    base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    signature_base = "&".join((_percent(method.upper()), _percent(base_url), _percent(normalized)))
    signing_key = f"{_percent(api_secret)}&{_percent(access_token_secret)}"
    digest = hmac.new(signing_key.encode(), signature_base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode("ascii")
    return "OAuth " + ", ".join(
        f'{_percent(key)}="{_percent(value)}"' for key, value in sorted(oauth.items())
    )


class DefinitivePublishError(RuntimeError):
    pass


class AmbiguousPublishError(RuntimeError):
    pass


def publish_post(text: str, credentials: dict[str, str], timeout: float = 20.0) -> str:
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        raise ValueError("missing X credentials: " + ", ".join(missing))
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    authorization = oauth1_header(
        "POST",
        X_POST_URL,
        credentials["X_API_KEY"],
        credentials["X_API_SECRET"],
        credentials["X_ACCESS_TOKEN"],
        credentials["X_ACCESS_TOKEN_SECRET"],
    )
    request = urllib.request.Request(
        X_POST_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json",
            "User-Agent": "MatchdayTerminalBot/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise DefinitivePublishError(f"X API returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AmbiguousPublishError(
            "X API request ended without a definitive response; manual reconciliation is required"
        ) from exc
    post_id = ((payload.get("data") or {}).get("id") if isinstance(payload, dict) else None)
    if not post_id:
        raise AmbiguousPublishError("X API response did not contain a post id")
    return str(post_id)


def build_candidates(now: dt.datetime, base_url: str) -> list[Candidate]:
    base_url = base_url.rstrip("/") + "/"
    recaps = _safe_json_from_url(urllib.parse.urljoin(base_url, "posts.json"))
    research = _safe_json_from_url(urllib.parse.urljoin(base_url, "research_posts.json"))
    return (
        locked_pick_candidates(load_pick_records(), now)
        + article_candidates(recaps, "recap")
        + article_candidates(research, "research")
        + [evergreen_candidate(now)]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print one post; do not publish or write state (default)")
    mode.add_argument("--publish", action="store_true", help="explicitly publish one post through the X API")
    parser.add_argument("--base-url", default=BASE_URL, help="public Matchday Terminal site root")
    parser.add_argument("--state", default=DEFAULT_STATE_FILE, help="deduplication ledger path")
    parser.add_argument("--resolve-key", help="manually resolve an ambiguous campaign key")
    parser.add_argument("--resolution", choices=("success", "failed"))
    parser.add_argument("--post-id", help="verified X post id for a successful reconciliation")
    args = parser.parse_args(argv)

    now = _utc_now()
    state = load_state(args.state)
    if args.resolve_key:
        if not args.resolution:
            parser.error("--resolve-key requires --resolution")
        try:
            resolve_ambiguous(args.state, state, args.resolve_key, args.resolution, now, args.post_id)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Reconciled {args.resolve_key} as {args.resolution}.")
        return 0
    candidate = choose_candidate(build_candidates(now, args.base_url), state, now)
    if candidate is None:
        print("No unsent promotional candidate is available.")
        return 0
    print(f"[{candidate.kind}] {candidate.text}")
    if not args.publish:
        print("Dry run: nothing was published and the state ledger was not changed.")
        return 0

    credentials = {
        name: os.environ.get(name, "")
        for name in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
    }
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        print("Cannot publish: missing X credentials: " + ", ".join(missing), file=sys.stderr)
        return 1
    append_event(args.state, state, candidate, "attempting", now)
    try:
        post_id = publish_post(candidate.text, credentials)
    except AmbiguousPublishError as exc:
        append_event(args.state, state, candidate, "ambiguous", _utc_now(), detail=str(exc))
        print(str(exc), file=sys.stderr)
        return 2
    except DefinitivePublishError as exc:
        append_event(args.state, state, candidate, "failed", _utc_now(), detail=str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    append_event(args.state, state, candidate, "success", _utc_now(), post_id=post_id)
    print(f"Published X post {post_id}; recorded campaign key {candidate.key}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
