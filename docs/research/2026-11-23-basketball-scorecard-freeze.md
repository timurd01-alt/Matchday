# Basketball scorecard froze on 2026-11-16 (fixed 2026-11-23)

**Symptom.** The Home "Last week" strip showed basketball at 4-0 for the week of
Nov 16-22. The published `scorecard.sports.ncaam` on main stopped at Monday
Nov 16.

**What the engine actually held.** 241-90 with 22 pending before the repair,
259-93 with 1 pending after (Eastern dates Nov 16-22).

## Cause, two parts

1. **Export guard was all-or-nothing.** `refresh_engine_scorecard.py` refused
   to publish if *any* card from the last 7 days was still pending 6h after
   tip. The daily NCAAM scorecard task failed every run from Nov 15 to Nov 23,
   each time on a different game (Morgan State at Loyola MD, Paine at
   Bethune-Cookman, West Virginia at Auburn, Cal State Fullerton at UCLA, ...).
   Some never settle: exhibition opponents the odds feed names differently
   (`Wilson WILSON` vs ESPN `Wilson Phoenix`), or a changed opponent (Paine
   listed, Stillman played).
2. **Engine repair pass used the UTC date.** The poller stopped at
   2026-11-19 03:21Z with 20 late games from Nov 18 mid-play (`status='in'`).
   `Engine._frozen_days` re-fetched `substr(starts_at,1,10)`, i.e. the Nov 19
   board. ESPN files a 7pm Pacific tip under the US date (Nov 18), so the
   repair never found them.

## Fix

- Matchday `refresh_engine_scorecard.py`: overdue cards are published as
  pending and named in the ship log; publication is refused only when overdue
  cards exceed `max(10, 10% of the week's graded cards)`. A dead poller is
  still caught separately by the 24h event-feed freshness check.
- Engine (`TRDLab`, `trdlab/engine.py`): `board_days()` returns the US
  date(s) a tip can be filed under (tip -4h and -10h, Eastern summer to
  Hawaii); `_frozen_days` uses it.
- One-off: re-pulled the free ESPN NCAAM boards for Nov 12-22 with the poller
  paused, which settled the stuck cards. Rows touched were backed up to
  `C:\TRDLabData\backup-2026-11-23-scorecard-rows.json`.
