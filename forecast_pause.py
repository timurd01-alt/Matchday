"""Site-wide publication pause for model forecasts.

Matchday's published predictions are paused across every competition while the
forecasting stack is rebuilt on the Bet Better data engine. This module is the
single switch that controls that: `fetch_data.py` reads it when it builds a
payload, `generate_posts.py` reads it before it writes a post, and the browser
mirrors the same decision in `app-1-core.js`.

Why a pause rather than a swap. The Bet Better engine is the intended
replacement, but it cannot serve Matchday's slate today, for three reasons that
are measured rather than assumed (see PAUSE_EVIDENCE):

  * Coverage. It carries soccer, NCAAF, NFL and a token NCAAM sample. Matchday
    also publishes MLB, NBA and NHL, for which that engine holds no events at
    all -- there is nothing to forecast from.
  * Promotion. Every forecast it has produced is still `shadow` status. Its own
    pipeline has never promoted one to published, so adopting it wholesale would
    mean publishing output that has not cleared the gate it was built with.
  * Evidence. On the only graded sample it has (86 head-to-head games) the model
    scores a worse Brier than the closing market it is measured against. A
    sample that size cannot establish calibration in either direction.

The pause applies to every competition equally. There are no per-sport
exemptions and no carve-outs: while it is on, no upcoming game anywhere gets a
published pick, a confidence figure, an edge, or a model-derived percentage.

Restoring publication is deliberately one edit: set PAUSE_ACTIVE to False.
Publication then returns wherever the dataset's own publication payload says
`eligible`, so a sport comes back when its data is actually there rather than
because a flag was flipped.
"""

from __future__ import annotations

from typing import Any


# The one switch. Flip to False when the coverage gaps above are closed and the
# replacement model has cleared its own promotion gate.
PAUSE_ACTIVE = True

PAUSE_REASON = "rebuilding_on_betbetter_data_engine"

# Kept to one sentence: it is rendered inside match cards, not just the banner.
PAUSE_MESSAGE = (
    "Predictions are paused while the model is rebuilt on a new data engine."
)

# The longer version, for the banner and the Q&A page.
PAUSE_DETAIL = (
    "Matchday is moving its forecasting onto the Bet Better data engine. That "
    "engine does not yet cover every competition published here, so rather than "
    "ship predictions for some sports and guesses for the rest, all picks are "
    "on hold until the coverage gaps are closed."
)

# What has to become true before PAUSE_ACTIVE goes back to False. Kept in code
# so the bar cannot quietly drift while the pause is in place.
PAUSE_EVIDENCE = {
    "measured_at": "2026-08-30",
    "engine": "betbetter",
    "covered_sports": ["soccer", "ncaaf", "nfl"],
    "uncovered_published_sports": ["mlb", "nba", "nhl"],
    "thin_coverage_sports": {"ncaam": 52},
    "forecasts_in_shadow_status": 4194,
    "forecasts_promoted_to_published": 0,
    "graded_sample": 86,
    "model_brier": 0.1907,
    "market_brier": 0.1809,
}

RESTORE_CRITERIA = (
    "Every published competition has events in the replacement engine; the "
    "engine has promoted forecasts out of shadow status; and a graded sample "
    "large enough to support a calibration claim beats the closing market.",
)


def paused(competition: Any = None) -> bool:
    """True when published forecasts are withheld for this competition.

    The competition argument is accepted so callers read naturally and so a
    future partial restore (one sport at a time) has an obvious seam. While
    PAUSE_ACTIVE is set the answer is the same everywhere: no sport is exempt.
    """
    if PAUSE_ACTIVE:
        return True
    return False


def publication_decision(competition: Any = None) -> dict[str, Any]:
    """Canonical payload stamped onto every dataset the pipeline writes."""
    if not paused(competition):
        return {"state": "eligible", "official_publication_eligible": True,
                "message": None, "reason": None}
    return {
        "state": "paused",
        "official_publication_eligible": False,
        "message": PAUSE_MESSAGE,
        "detail": PAUSE_DETAIL,
        "reason": PAUSE_REASON,
        "scope": "all_competitions",
        "evidence": PAUSE_EVIDENCE,
    }


def publication_eligible(competition: Any = None) -> bool:
    return not paused(competition)
