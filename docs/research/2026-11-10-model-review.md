# Model review: CFB and NCAAM (2026-11-10)

Question: is the model sound, and where is it weakest? This follows the 2026-11-06 health check. It reads the engine's own lock table, so the raw model number is the stored one, not one backed out of the blend.

## Data
| Source | What it gave |
|---|---|
| `trdlab_picks.json` scorecard on origin/main @ `7e6beb0` | 585 graded CFB picks (08-29 to 11-08) and 513 graded NCAAM picks (11-01 to 11-10) |
| Engine database, read-only: `scorecard_locks` joined to `scorecard_results` | One row per game, home side. 667 CFB games on the adjusted-margin model and 555 NCAAM games. The stored model-only probability and the market at forecast time exist for 294 CFB games, all from 09-27 on |
| Engine `docs/research/2026-11-09-ncaaf-margin-calibration.rows.json` | 6,567 walk-forward CFB projections, 2022-25 |

Scripts: engine `docs/research/2026-11-10-model-review-*.py`. Intervals are 95%, bootstrapped over whole game dates (season-weeks for the CFB walk-forward). The game de-duplication here is simpler than the scorecard's, so counts differ slightly from the public page.

## Findings

### 1. CFB: the model's own view has not added anything to the market this season
| 294 games since 09-27 | Brier | Log loss |
|---|---|---|
| Model only | 0.2162 | 0.6218 |
| Published 60/40 blend | 0.2121 | 0.6125 |
| Market at forecast time | 0.2101 | 0.6081 |

- Model minus market: Brier +0.0061 [-0.0014, +0.0153]. That is not significant on its own, but every cut points the same way.
- Model and market on opposite sides: the model went 12-20.
- Log loss by model weight: 0.6081 at 0, 0.6083 at 0.2, 0.6097 at 0.4, 0.6124 at 0.6, 0.6218 at 1.0. The best in-sample weight is about 5% model.
- By gap size: within 10 points of the market the two score the same (227 games). All of the loss is in the 67 games where they differ by 10 or more (model 0.248, market 0.223).
- Published record, full season, lock-time market, 539 priced picks: blend minus market Brier +0.0095 [+0.0028, +0.0172]. That one is significant. September is most of it (0.148 vs 0.128). October was 0.207 vs 0.205.
- Line movement: on 105 games forecast 6+ hours before the lock with a 3+ point gap, the price moved toward the model by -0.03 points [-0.35, +0.31]. 48 moved toward it and 50 away. The model is not early on anything.

### 2. The frozen CFB baseline is void for the third time
`ncaaf-2026-11-09-2` was frozen at 19:17Z on 11-09 as `e44176db8ff8`. `hoops/cli.py` and `poll.py` were edited at 20:50 local the same day (the sigma-17 change). `evaluation_baseline identity` now reports `2100b4fd05f7` with `baseline_matches: false`. No lock carries the frozen hash. The registered cohort across three freezes is two games. The QB-injury and tier-offset experiments key on the baseline, so they are collecting nothing countable either.

### 3. Locks are honest but often late and stale
- The lock row was written after kickoff for 254 of 667 CFB games and 265 of 555 NCAAM games (median 4-5 hours late). The lock still uses only forecasts and quotes stamped before the deadline, so no result can leak in.
- Forecast age at the deadline: CFB median 14 hours, 299 of 667 older than a day, 250 older than three days. NCAAM median 28 hours.
- A day-old card is then graded against the one-hour price. On the 135 CFB cards older than a day the blend and market tie (0.2248 vs 0.2250). On the 147 fresher than three hours the market leads, 0.2020 vs 0.2052.

### 4. A silent fallback gave one full CFB slate the basketball home edge
40 forecasts made on 11-07 carry `home_edge_points` 3.5, which is twice `DEFAULT_HOME_EDGE` 1.75, the basketball prior. Forecasts before and after carry the fitted 2.42 and 2.51. The stored rating rows had a NULL `home_edge` that day and `hoops/scorecard.py` fell back without complaint. The cost was about 0.9 points toward every home team for that Saturday.

### 5. CFB leans to the home side more than the market does (2026 only)
- Raw model 5+ points above the market on the home team: 120 games. Below it: 41.
- 2026 home-margin bias: +1.1 points over 667 games (SE about 0.6). Last 100 same-tier games: projected +5.6, actual +0.1. The market also overshot there (57.5% home, 53.0% won).
- I suspected the fitted intercept (+1.8, added to the listed home team, including at neutral sites) was double-counting home field. **It is not.** Walk-forward 2022-25 on FBS home games, the bias with the intercept is +0.16, +0.19, -0.13, +0.12. Without it the bias is -0.67 to -2.07. Dropping it costs MAE +0.12 [+0.03, +0.20] on the holdout. At neutral sites (143 holdout games) the intercept leaves a +1.35 bias and removing it gives -0.61, with no significant Brier difference [-0.006, +0.007].
- So the lean is a 2026 pattern or noise, not a structural fault. Watch it; do not change it.

### 6. NCAAM: too low on home teams, too sure in the middle
- The published number is the raw model. There is no market blend, and no model/market receipt is stored with the forecast.
- 155 priced games: model Brier 0.1392 vs market 0.1269 [-0.0047, +0.0278]. Log loss 0.4565 vs 0.3946 [+0.002, +0.099].
- Home margin: projected 17.8, actual 20.7 over 555 games (about 4 SE). When the model is 5+ points lower than the market on the home team (43 games), the home team won 69.8%. The model said 54.2% and the market said 68.3%.
- 60-70% picks hit 53.8% (52 picks) and 70-80% picks hit 63.6% (55 picks). The residual SD around the projection is 16.2 (14.1 in games projected within 10) against a stored sigma of 11.5.
- All ten days are November. 508 of the 555 were forecast before the 11-09 stretch removal. The 47 since show the same home shortfall (14.7 vs 18.4).

## Conclusion
The engineering is careful. No leakage was found, locks are append-only, CFB is well calibrated band by band, and changes are tested walk-forward before they ship. The forecasting claim is not there yet. In CFB the model's disagreements with the market lose, its large ones lose badly, and prices do not move toward it. The largest obstacle to learning more is procedural: the baseline keeps being voided by same-day edits, so two and a half months of forecasts are unregistered.

## Recommended order
1. Stop editing the forecast import closure, refreeze, and hold it through the end of the regular season. Batch model changes into one dated release.
2. Make the pre-lock refresh run for every game so cards are frozen from a forecast under three hours old. Alert when a lock is written after kickoff.
3. Fail loudly on a NULL stored `home_edge` instead of falling back to the basketball constant.
4. Research, not apply (owner's rule): the NCAAM home edge, and an early-season sigma that includes rating uncertainty. Also the 67 CFB games with a 10+ point gap, split by cause (QB change, cross-tier, early-season prior).
5. Store the model-only and market-at-forecast numbers on NCAAM forecasts the way CFB does.

## Caveats
- One CFB season. 29 game dates carry the paired sample.
- NCAAM is ten days of November, dominated by mismatches.
- Raw-model numbers exist only from 09-27, so September's damage is visible only in the published blend.
- The home-edge fallback is inferred from the stored payload values and the code path, not from a log line.

## Follow-up (same day): corrections, and what was done about it

Detailed notes and scripts are in the engine: `docs/research/2026-11-10-ncaaf-replay-vs-market.md` and `docs/research/2026-11-10-hoops-early-season.md`.

### Corrections to the findings above
- **Finding 3 described the past.** Late and stale locks were fixed in the engine on 11-06 and 11-08. On 11-10 and 11-11, 1 of 100 basketball locks was written late and the median forecast was 8-15 minutes old at the deadline. The season-long totals are right; the "make the pre-lock refresh run" recommendation was already done.
- **Finding 4 was wrong about scope.** It was not one Saturday. No stored football rating set before 11-08 carried a home edge, so cards used the basketball default (3.5 points) all season. The payload label read 2.42 only because it was computed with a basketball tempo. Fixed on 11-08 and covered by a test. This also explains most of finding 5's home lean in the published record.
- **Finding 2, detail.** The baseline was voided by an edit to `hoops/ratings.py` at 16:20 local and then `poll.py` at 20:50, not by `hoops/cli.py`.

### Football: today's procedure replayed over 2026
Method: each Monday the production ratings are solved from earlier results and project the next 7 days, with the production tier and quarterback adjustments, sigma 17. 564 FBS-vs-FBS games, 454 with a lock-time market price. Not out of sample: the prior settings were tuned partly on 2026.

| | n | Replay Brier | Market Brier | Difference (95% CI) |
|---|---|---|---|---|
| All priced | 454 | 0.1873 | 0.1784 | +0.0089 (+0.0024 to +0.0150) |
| Weeks 1-5 | 146 | 0.1390 | 0.1237 | +0.0153 (+0.0095 to +0.0230) |
| Weeks 6-9 | 197 | 0.2124 | 0.2123 | +0.0001 (-0.0075 to +0.0055) |
| Weeks 10+ | 111 | 0.2062 | 0.1903 | +0.0159 (-0.0147 to +0.0247) |
| Weeks 6+ together | 308 | | 0.2044 | +0.0058 (-0.0028 to +0.0138) |

- Opposite sides of the market: 2-14 in weeks 1-5, 15-17 after.
- From October the model is statistically level with the market. The point estimate is still behind.
- Expressed as margins, the model's disagreement with the market averages 3.5 points, and from week 6 on none of it shows up in results (share -0.01; 0 means the market was right on average).
- Two calibration changes were tested and rejected. Dropping the fitted intercept makes 2022-25 home games 0.7-2.1 points too low. A fixed FBS-only calibration won on the 2024-25 holdout (Brier -0.0018, -0.0033 to -0.0004) but not on the 2026 replay (+0.0004, -0.0013 to +0.0025; margin MAE +0.24).

### Basketball: a real early-season effect, registered as an experiment
- Walk-forward, 2024-25 and 2025-26: before mid-January home teams beat the projection by 4.3 points (4,365 games) and projected gaps are too small (slope 1.23-1.28). After mid-January both vanish (5,245 home games, shortfall 0.0), and neutral sites show neither.
- A calibration fitted on one season and scored on the other: Brier -0.0018 (-0.0031 to -0.0006) backward, -0.0009 (-0.0023 to +0.0005) forward. The forward interval includes zero, so under the significant-or-research rule it is not applied.
- Registered as `ncaam-early-season-calibration-v1` (slope 1.264, +2.83 home points, sigma 14.25, games before 2027-01-15). It is scored straight from scorecard locks; decision at 600 games.
- Exploratory, not in the cohort: on the 36 priced games forecast since 11-09, candidate Brier 0.1268, market 0.1297, production 0.1361.

### Changed in the engine
- Basketball forecasts now store the model probability, the market at forecast time and the neutral flag, as football does. Published numbers are unchanged.
- Football baseline refrozen as `ncaaf-2026-11-10` (`fd58b812e420`) after the full suite passed.
- Not changed: the forecast modules were not split by sport. The edits that voided the last baseline were in rating code both sports share, so a split would not have prevented it.

## Follow-up 2 (2026-11-11): the September football gap
Engine notes: `docs/research/2026-11-11-ncaaf-september-gap.md`. No change and no experiment.

- Data: 1,317 FBS-vs-FBS games from weeks 1-6 of 2022-2026, each projected by today's procedure from earlier results, with every team's preseason facts attached. 187 of the 2026 games have a lock-time market price.
- Against results, no pregame fact improves the September margin with a season held out: preseason rating, in-season update, talent, recruiting, returning share, quarterback, home field, programme history. Reacting faster or slower to the first games is significantly worse (Brier +0.0013, +0.0005 to +0.0021).
- The market's 2026 disagreement lines up with programme history (R2 0.31 in weeks 1-3) and talent (0.17). Used as diagnosis only.
- Programme history put inside the preseason rating and re-solved (1,042 games, 2023-26): projections move 0.41 points on average, Brier -0.0001 (-0.0006 to +0.0004), and the 2026 gap to the market is unchanged (+0.0119 to +0.0116). Rejected as immaterial.
- First-year head coaches finish 1.16 points below the preseason rating (-2.35 to +0.05; 102 cases) against +0.62 for continuing coaches. The coach table only holds coaches still in the job, so this is a lead, not a test.
- Reading: the model is about 4 points per game from the market in September, and nothing in the database explains more than a few tenths of it. What is missing is news: camp and depth-chart reports, injuries, staff changes.
