"""Reads the pick handoff written by the Bet Better engine.

Bet Better writes one JSON document (`betbetter_picks.json`) holding its live
model read on upcoming games. This module loads that document, checks it, and
attaches each pick to the matching fixture. It is the only place Matchday
trusts anything from that engine, so every guard lives here.

Where the pick is attached, and why it is not `prediction`
----------------------------------------------------------
A Bet Better pick lands on `match["betbetter_pick"]`, beside the production
forecast rather than inside it. That follows the shape already used for
`mlb_challenger_shadow`: research output rides alongside published output and
is never mistaken for it. Three things fall out of that choice for free:

  * `_set_prediction_publication_state` clears `match["prediction"]` while the
    site-wide pause is on. A pick written into that key would be wiped; a pick
    written beside it survives, still marked unpublishable.
  * `_lock_decision` refuses new receipts for the immutable official ledger
    while paused. Nothing here ever reaches that ledger, so a displayed pick
    cannot later be graded as though it had been an official call.
  * Removing the engine is deleting one key.

What is refused
---------------
These picks are *live* forecasts: they keep moving until kickoff. They carry no
pregame lock receipt and cannot satisfy `pick_integrity.is_official_pick_record`.
So this module refuses, rather than merely labels:

  * a document whose `handoff_version` this code does not know,
  * any pick claiming `official_pick` — the handoff has no authority to mint
    one, and a document that tries is treated as broken rather than trimmed,
  * any pick for a fixture that is not `UPCOMING`, so a live number can never
    be attached to a game whose result is already known.

Publication remains `forecast_pause`'s decision. This module never consults it
to *grant* display; it stamps `official_publication_eligible: False` on every
pick it attaches, so the answer is no regardless of how the pause is set.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any

# Handoff major versions this reader understands. A document outside this set
# is refused whole: a partly-understood pick is worse than no pick.
# 2 added `rankings` (the published Top 25 per sport). A v1 document is
# still readable -- it simply carries no rankings -- so both are accepted.
SUPPORTED_VERSIONS = frozenset({1, 2})

DEFAULT_HANDOFF_PATH = "betbetter_picks.json"

# The one basis this reader accepts. If Bet Better ever sends frozen cards they
# will arrive under a different basis, and that path has to be written
# deliberately rather than inherited by a string that happens to match.
LIVE_BASIS = "live_shadow_forecast"

# Only a fixture that has not started can carry a live pick.
ATTACHABLE_STATUS = "UPCOMING"


# Shorter than this, a prefix match means nothing. Three is deliberate: TCU,
# USC, LSU and UCF are whole school names on the Matchday side, so a floor of
# four would silently drop them, while a floor of two lets a stub like "NC"
# prefix half the slate. Within a single kickoff day the uniqueness check in
# `find` is what actually prevents a wrong match; this only rules out stubs
# too short to mean anything.
MIN_PREFIX_LENGTH = 3


def _team_name(value: object) -> str:
    """The team's name, whichever shape the feed uses.

    Matchday carries a team as an object (`{"name": "TCU", "code": "T", ...}`);
    Bet Better carries a plain string. Reading `str()` of the object would
    normalize a whole dict into the key and match nothing, which is exactly
    what happened before this existed.
    """
    if isinstance(value, dict):
        return str(value.get("name") or value.get("shortName") or "")
    return str(value or "")


def _normalize(name: object) -> str:
    """A team name reduced to what two feeds actually agree on.

    The two projects source names from different providers, so
    "San José State" and "San Jose State Spartans" have to reduce to
    comparable text. Accents, punctuation, case and spacing are all noise.
    """
    text = unicodedata.normalize("NFKD", _team_name(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _kickoff_day(value: object) -> str:
    """The UTC date portion, which is all the two feeds reliably share.

    Kickoff times differ by minutes between providers (a scheduled 19:45 shows
    as 19:30 on the other side), so matching on the exact instant loses real
    fixtures. The day plus both team names is specific enough: a pair of teams
    does not play twice in one day.
    """
    return str(value or "")[:10]


def _compatible(one: str, other: str) -> bool:
    """Whether two normalized names plausibly denote the same team.

    Matchday names a team the short way and Bet Better appends the mascot —
    "tcu" against "tcuhornedfrogs", "ncstate" against "ncstatewolfpack" — so
    equality never fires and one name being a prefix of the other is the real
    relationship. The length floor stops a stub like "nc" from matching
    everything, and `attach` still requires the resulting candidate to be
    unique, so a prefix shared by two schools resolves to no pick rather than
    to the wrong one.
    """
    if not one or not other:
        return False
    if one == other:
        return True
    shorter, longer = sorted((one, other), key=len)
    return len(shorter) >= MIN_PREFIX_LENGTH and longer.startswith(shorter)


class HandoffError(ValueError):
    """The document exists but cannot be trusted."""


def load(path: str = DEFAULT_HANDOFF_PATH) -> dict[str, Any] | None:
    """The validated handoff, or None when there is simply no file.

    A missing file is normal — Bet Better may not have run — and returns None.
    A file that exists but is malformed raises, because silently continuing
    with no picks would look identical to the engine having nothing to say.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise HandoffError(f"{path} could not be read: {error}") from error

    if not isinstance(document, dict):
        raise HandoffError(f"{path} is not a JSON object")
    version = document.get("handoff_version")
    if version not in SUPPORTED_VERSIONS:
        raise HandoffError(
            f"{path} declares handoff_version {version!r}; this reader "
            f"understands {sorted(SUPPORTED_VERSIONS)}")
    if document.get("source") != "betbetter":
        raise HandoffError(f"{path} is not a Bet Better handoff")
    picks = document.get("picks")
    if not isinstance(picks, list):
        raise HandoffError(f"{path} has no picks list")
    for pick in picks:
        if not isinstance(pick, dict):
            raise HandoffError(f"{path} contains a non-object pick")
        if pick.get("official_pick"):
            # The handoff cannot mint an official receipt. A document that
            # claims one is not trimmed, it is rejected: something upstream
            # is wrong about what it is allowed to say.
            raise HandoffError(
                f"{path} contains a pick claiming official_pick; the handoff "
                "carries live forecasts and has no authority to mint receipts")
        if pick.get("basis") != LIVE_BASIS:
            raise HandoffError(
                f"{path} contains a pick with basis {pick.get('basis')!r}; "
                f"this reader accepts only {LIVE_BASIS!r}")
    return document


def rankings(document: dict[str, Any] | None, sport: str) -> dict[str, Any]:
    """The published Top 25 for one sport, or why there is none.

    The ranking is computed by the Bet Better engine and only rendered here.
    It is an *edition* with a date on it, so it is read as published rather
    than recomputed -- a table that changed between two page loads would not
    be a poll.
    """
    if not document:
        return {"available": False, "sport": sport, "reason": "no handoff loaded"}
    entry = (document.get("rankings") or {}).get(sport)
    if not entry:
        return {"available": False, "sport": sport,
                "reason": f"handoff carries no ranking for {sport}"}
    return entry


def index(document: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Picks bucketed by kickoff day.

    The day is the only part of a fixture the two feeds agree on exactly, so it
    is the index; team names are then compared within the day, where the
    candidate set is small enough that a near-match can be checked for
    uniqueness rather than accepted on faith.
    """
    if not document:
        return {}
    buckets: dict[str, list[dict[str, Any]]] = {}
    for pick in document.get("picks") or []:
        buckets.setdefault(_kickoff_day(pick.get("kickoff")), []).append(pick)
    return buckets


def find(buckets: dict[str, list[dict[str, Any]]], home: object, away: object,
         kickoff: object) -> dict[str, Any] | None:
    """The one pick for this fixture, or None when that is not unambiguous.

    Both sides must be compatible and exactly one candidate may survive. Two
    schools sharing a prefix on the same day therefore yield no pick, which is
    the right answer: showing the wrong team's number is worse than showing
    none.
    """
    wanted_home, wanted_away = _normalize(home), _normalize(away)
    if not wanted_home or not wanted_away:
        return None
    candidates = [pick for pick in buckets.get(_kickoff_day(kickoff), [])
                  if _compatible(_normalize(pick.get("home")), wanted_home)
                  and _compatible(_normalize(pick.get("away")), wanted_away)]
    return candidates[0] if len(candidates) == 1 else None


def _display_block(pick: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """Exactly what a match card may show, and nothing that implies more."""
    return {
        "pick_name": pick.get("pick_name"),
        "pick": pick.get("pick"),
        "model_pct": pick.get("model_pct"),
        "market_pct": pick.get("market_pct"),
        "edge_points": pick.get("edge_points"),
        "best_price": pick.get("best_price"),
        "best_american": pick.get("best_american"),
        "book_count": pick.get("book_count"),
        "sides": pick.get("sides") or [],

        "model_name": pick.get("model_name"),
        "model_version": pick.get("model_version"),
        "generated_at": pick.get("generated_at"),
        "handoff_generated_at": document.get("generated_at"),

        # Repeated on every block rather than kept once at the top of the file,
        # because a match card is rendered on its own and whatever travels with
        # it is all the renderer can check.
        "engine": "betbetter",
        "basis": LIVE_BASIS,
        "official_pick": False,
        "official_publication_eligible": False,
        "moves_until_kickoff": bool(pick.get("moves_until_kickoff", True)),
        "integrity_note": pick.get("integrity_note"),
        "edge_warning": document.get("edge_warning"),
    }


def attach(matches: list[dict[str, Any]] | None,
           document: dict[str, Any] | None) -> int:
    """Attach each pick to its fixture. Returns how many landed.

    Only `UPCOMING` fixtures are eligible: a live forecast attached to a played
    game would read as a call that was made in advance.
    """
    buckets = index(document)
    if not buckets:
        return 0
    attached = 0
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        if str(match.get("status") or "").upper() != ATTACHABLE_STATUS:
            continue
        pick = find(buckets, match.get("home"), match.get("away"),
                    match.get("kickoff"))
        if pick is None:
            continue
        match["betbetter_pick"] = _display_block(pick, document)
        attached += 1
    return attached


def attach_from_file(matches: list[dict[str, Any]] | None,
                     path: str = DEFAULT_HANDOFF_PATH) -> dict[str, Any]:
    """Load and attach in one call, reporting what happened.

    A broken handoff is reported, not raised, so one bad export cannot stop a
    fetch that has a whole slate of other work to finish.
    """
    try:
        document = load(path)
    except HandoffError as error:
        return {"attached": 0, "available": False, "reason": str(error)}
    if document is None:
        return {"attached": 0, "available": False,
                "reason": f"no handoff at {path}"}
    attached = attach(matches, document)
    return {
        "attached": attached,
        "available": True,
        "picks_in_handoff": len(document.get("picks") or []),
        "generated_at": document.get("generated_at"),
        "reason": None,
    }
