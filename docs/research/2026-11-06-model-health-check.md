# Model health check: CFB and NCAAM vs the market

Date: 2026-11-06 · Question: how good is the model, judged the way it is meant to be judged (against the market, not by hit rate)?

## Data
| Source | What it gave |
|---|---|
| `trdlab_picks.json` → `scorecard.sports.<sport>.recent` (origin/main @ `1312f98`) | 520 graded CFB events (2026-08-29 → 11-01), 221 graded NCAAM events (season opened 2026-11-02). Published pick probability plus the no-vig market price at the 60-minute lock. |
| `market_snapshot_ledger.jsonl` (origin/main) | NCAAF/NCAAM moneyline snapshots, used for closing-line movement. NCAAF snapshots run only from about 2026-10-20 → 10-31, so the CLV sample is small. |

There was no `clv_report.json`, `market_benchmark_report.json` or `promotion_readiness.json` on main, so every number below was recomputed here from the two files above.

## Method
- One row per event: the side the model picked, its published probability, and the lock-time no-vig market probability for that side.
- Brier score and log loss for the model and the market on the same rows. A 4,000-draw bootstrap gives the interval on the Brier difference.
- The published probability is a 60/40 model/market blend. The raw model was backed out as `(p − 0.4·m) / 0.6`. That reproduces the published Brier (0.1805 vs 0.1809), so the linear assumption holds closely.
- CLV: the ledger's last snapshot at or before the lock, compared with its last snapshot before kickoff, matched on kickoff time and home-team name prefix.

## Findings

### Headline record (straight-up)
| | Picks | Hit | Expected | Brier |
|---|---|---|---|---|
| CFB | 520 | 73.5% (382–138) | 73.4% | 0.174 |
| NCAAM | 221 | 85.5% (189–32) | 87.9% | 0.095 |

Calibration is good. In CFB, every confidence band lands within 4 points of its stated probability. Hit rate mostly mirrors the favourites, though, so it says little about skill.

### Against the market (priced events)
| | n | Model Brier | Market Brier | Diff (95% CI) |
|---|---|---|---|---|
| CFB | 475 | 0.1809 | 0.1716 | **+0.0093 [+0.0020, +0.0171]**, so the market is better, and that is significant |
| NCAAM | 69 | 0.1258 | 0.1275 | −0.0017 [−0.022, +0.018], which is a wash with tiny n |

CFB by month: September model 0.145 vs market 0.125, October 0.207 vs 0.205. The gap is mostly a September problem and was nearly closed in October.

### Where CFB loses: big disagreements
| Model vs market gap | n | Model Brier | Market Brier |
|---|---|---|---|
| 0–3 pts | 193 | 0.157 | 0.155 |
| 3–6 pts | 106 | **0.181** | 0.185 |
| 6–10 pts | 91 | 0.180 | 0.175 |
| 10+ pts | 85 | **0.237** | 0.188 |

- Outright disagreements: 14 of 40 won. The model expected 23.9 wins and the market expected 16.5.
- When the model rates a side >2 pts above the market (n=172), that side wins 68.0%. The model said 75.1% and the market said 65.4%. The direction is slightly right, but the model is badly overconfident.
- When the model rates a side >2 pts below the market (n=166), that side wins 74.7%. The model said 68.0% and the market said 74.9%, so the market was right.
- Raw model (no market blend), CFB: Brier 0.1955 vs the market's 0.1716. On this season, any weight on the raw model makes CFB Brier worse. NCAAM's best mix is about 40% raw model, but with only 69 games.

### Closing-line value
| | n | Median lock lead | Mean move toward pick |
|---|---|---|---|
| CFB | 125 | 215 min | −0.01 pts [−0.21, +0.20] |
| NCAAM | 23 | 329 min | −0.22 pts [−1.78, +1.39] |

There is no CLV signal either way. Lines barely move between the lock and kickoff in this ledger, and the CFB snapshots stop at 2026-10-31.

## Conclusion
- The model is well calibrated and honest about its confidence.
- In CFB it does **not** yet beat the market. Its independent view is overconfident, and its 10+ point disagreements are where the Brier gap comes from.
- NCAAM is too early to judge.
- Per the owner's rule, the fix is not more market weight. It is finding why the raw model diverges by 10+ points: September priors, QB and availability changes, FCS/G5 talent gaps. Start by listing those 85 games.

## Caveats
- The CFB rows are one season, and the games are correlated within a week, so the bootstrap is per game rather than per week. The interval is probably a bit narrow.
- The raw-model back-out assumes a linear 60/40 blend.
- The CLV ledger covers only about 1.5 weeks of CFB.
