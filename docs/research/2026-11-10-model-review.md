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
