# CFB 2026: patterns behind game outcomes

Date: 2026-10-21 · Question: what patterns from this season influence outcomes, beyond what TRDLab already rates?

## Data: where it actually lives (corrected)
The first pass of this note wrongly said the season record was thin. It had looked in places retired or never persisted:

| Source | State | Why |
|---|---|---|
| `picks_log_ncaaf.json` | Dead since 2026-09-25 (20 graded) | Commit `814d5cf` retired the in-house model and its pick lock/grading. TRDLab is the only pick source now. |
| `archive/games/ncaaf/` | Never written to git | `fetch_data` still calls `game_archive.record_build()` hourly, but `deploy.yml`'s commit-back step never `git add`s `archive/`, so each run's archive is discarded. |
| `data/trdlab.sqlite3` (both copies) | Empty | Not the DB TRDLab runs from, or reset. |
| Live `data_ncaaf.json` | Display window only (~40 finals) | Holds *current* team stats, so testing finished games against it leaks. |
| **`trdlab_picks.json` → `results`** | **510 CFB finals, 2026-08-29 → 10-17, with EPA/play and success rate** | The real record. Committed by Sunday ship. |

**Correction:** past picks *are* locked and graded. `trdlab_picks.json` → `scorecard.sports.ncaaf.recent` holds 410 graded CFB picks (307–101, 75.2% vs 74.5% expected) — the live Scorecard page. An earlier draft of this note missed it and wrongly called picks ungraded.

Real gap found and fixed (Build 1021D): `deploy.yml` never committed `archive/games/`, so the hourly game archive was discarded each run.

## Method
Walk-forward: each game is judged using only the two teams' *earlier* games (both teams with ≥2 prior games, so n=289). There is no leakage. Home-field tests use all 503 non-neutral games.

## Findings
| Pattern | Result |
|---|---|
| Prior point diff/game favourite wins | 185/288 (64.2%) |
| Prior win% favourite wins | 136/207 (65.7%) |
| Prior EPA/play favourite wins | 174/285 (61.1%) |
| Prior success-rate favourite wins | 178/285 (62.5%) |
| When point diff and EPA disagree | **Point-diff side wins 25/40 (62.5%)** |
| When record and EPA disagree | Record side wins 17/27 (63%) |
| Prior pd gap <7 / 7–14 / 14+ | 54.5% / 65.6% / 69.9% |
| Home win rate, all | 353/503 (70.2%) |
| Home win rate, **conference** games | **112/216 (51.9%)** |
| Home win rate, **non-conference** | **241/287 (84.0%)**, mostly buy games |
| Home edge vs prior pd, conf / non-conf | +4.4 / +5.4 pts |
| In-game EPA winner = scoreboard winner | 457/495 (92%) |

### Readings
1. **Season-to-date EPA is not beating plain point diff this year.** When the two disagree, point diff wins about 5 times in 8. Do not add EPA as a new input on this evidence.
2. **Conference home win rate (52%) is a matchup effect, not a weak home field.** After strength is controlled for, the home edge is still about +4.4 points. The 84% non-conference rate is scheduling (buy games), not home field.
3. **Games with a gap under 7 points are close to coin flips (54.5%).** No current signal separates them, so that is where new inputs should be tested.
4. **Close-game records to watch for regression:** UTSA 4-0, USC 3-0, Kentucky 3-0 in one-score games; TCU 0-3, Penn State 0-3, Kennesaw St 0-3, Coastal Carolina 1-4, Navy 1-4.

## Graded-record check (scorecard, n=410)
- Agreed with market: 255–75 (77.3% vs 75.0% expected). Disagreed: 14–21 (40.0% vs 61.7% expected, −21.7).
- So TRDLab's edge is calibration, not disagreement: when it leaves the market it loses. Consistent with finding 1 — its disagreements don't carry an extra signal the market lacks.

## Next
- Test rest/travel/weather inside the sub-7-point band, where the misses live.
- Re-run once `archive/games/ncaaf/2026.csv` accumulates.
