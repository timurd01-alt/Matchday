"""social_schedule.py -- when each kind of post goes out.

The week has a rhythm, in US Eastern time because that is how a college
audience reads a clock:

    Sun evening   the new Top 25s and the ballot, after the Sunday ship
    Mon midday    ballot / ratings / bracketology (whatever Sunday left)
    Tue midday    the receipts: scorecards and last week's upset calls
    Wed midday    research, basketball ratings, bracketology
    Thu midday    the weekend slate, early upset calls
    Fri midday    Game of the Week, Upset Watch
    Sat morning   Upset Watch before the first kickoff

A run outside every slot posts nothing. Inside a slot, the slot's own kinds
go first, in its order. One exception keeps time-sensitive posts from being
lost: an item that will expire before the next slot that lists its kind is
**urgent**, and any slot may post it after its own kinds. A Thursday-night
upset pick is not held for Saturday morning.

The workflow's cron times sit inside these windows in both EST and EDT, so
the clock change in March and November needs no edit.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Iterable, TypeVar

T = TypeVar("T")


@dataclasses.dataclass(frozen=True)
class Slot:
    weekday: int          # Monday = 0, as datetime.weekday()
    start_hour: int       # Eastern, inclusive
    end_hour: int         # Eastern, exclusive
    kinds: tuple[str, ...]
    name: str


SLOTS: tuple[Slot, ...] = (
    Slot(6, 18, 24, ("power_top25", "ballot_top25"), "Sunday evening: new rankings"),
    Slot(0, 11, 17, ("ballot_top25", "power_top25", "bracketology"), "Monday: rankings"),
    Slot(1, 11, 17, ("scorecard", "upset_results"), "Tuesday: receipts"),
    Slot(2, 11, 17, ("article", "power_top25", "bracketology", "scorecard"), "Wednesday: research"),
    Slot(3, 11, 17, ("slate_preview", "upset_watch"), "Thursday: the slate"),
    Slot(4, 11, 17, ("game_of_the_week", "upset_watch", "slate_preview"), "Friday: game day eve"),
    Slot(5, 8, 13, ("upset_watch", "game_of_the_week", "slate_preview"), "Saturday: before kickoff"),
)
HORIZON = dt.timedelta(days=8)


def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def eastern(moment: dt.datetime) -> dt.datetime:
    """UTC -> US Eastern, by the federal rule (no tz database needed).

    DST runs from 2:00 local on the second Sunday of March to 2:00 local on
    the first Sunday of November: 07:00 UTC and 06:00 UTC respectively.
    """
    utc = moment.astimezone(dt.timezone.utc)
    year = utc.year
    start = dt.datetime.combine(_nth_sunday(year, 3, 2), dt.time(7), dt.timezone.utc)
    end = dt.datetime.combine(_nth_sunday(year, 11, 1), dt.time(6), dt.timezone.utc)
    offset = -4 if start <= utc < end else -5
    return utc.astimezone(dt.timezone(dt.timedelta(hours=offset)))


def slot_at(moment: dt.datetime) -> Slot | None:
    local = eastern(moment)
    for slot in SLOTS:
        if local.weekday() == slot.weekday and slot.start_hour <= local.hour < slot.end_hour:
            return slot
    return None


def next_slot_start(kind: str, after: dt.datetime) -> dt.datetime | None:
    """The next moment strictly after `after` when a slot listing `kind` opens."""
    step = dt.timedelta(minutes=30)
    probe = after.astimezone(dt.timezone.utc).replace(second=0, microsecond=0)
    probe += step - dt.timedelta(minutes=probe.minute % 30)
    current = slot_at(after)
    while probe - after <= HORIZON:
        slot = slot_at(probe)
        if slot and kind in slot.kinds and slot != current:
            return probe
        if slot != current:
            current = slot
        probe += step
    return None


def order(posts: Iterable[T], now: dt.datetime, kind_of=lambda p: p.kind,
          expires_of=lambda p: p.expires_at, parse=None) -> tuple[list[T], Slot | None]:
    """Posts allowed in the current slot: the slot's kinds first, then urgent ones."""
    import content_engine

    parse = parse or content_engine.parse_time
    slot = slot_at(now)
    if slot is None:
        return [], None
    posts = list(posts)
    rank = {kind: i for i, kind in enumerate(slot.kinds)}
    own = sorted((p for p in posts if kind_of(p) in rank), key=lambda p: rank[kind_of(p)])
    urgent = []
    for post in posts:
        if kind_of(post) in rank:
            continue
        expires = parse(expires_of(post))
        upcoming = next_slot_start(kind_of(post), now)
        if expires is not None and (upcoming is None or expires <= upcoming):
            urgent.append(post)
    urgent.sort(key=lambda p: expires_of(p))
    return own + urgent, slot
