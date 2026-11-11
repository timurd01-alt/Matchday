# Do the early basketball rating jumps make sense? (2026-11-11)

**Decision:** yes; no change. Updating more slowly is significantly worse.
**Scripts:** engine `docs/research/2026-11-11-hoops-rating-jumps.py` and `2026-11-11-hoops-prior-spread*.py`.

## Question
After two or three games some power ratings moved a long way from the preseason number
(Missouri +9.6 points per game, LSU +9.0, Marquette +7.5, TCU +7.4, Illinois +7.1;
Fairleigh Dickinson -8.0, Canisius -7.6). Is that sound, or an overreaction?

## What moved them
357 teams had played by 11-10. Change from the preseason set: SD 2.7 points; 90 teams
moved more than 3, 28 more than 5. Teams rated +12 or better in the preseason rose 2.05
on average (67 teams); below-average teams fell 1.33 (77 teams). Every large riser has the
same story: home wins by 35 to 75 points over weak opponents in the first week (Illinois
120-45 over Fairleigh Dickinson, Missouri 111-50 over Cleveland State, Marquette 93-32 over
Detroit Mercy). The losers are the teams on the other end of those games.

## Is the size of the update right?
Walk-forward, 2024-25 and 2025-26, the first twelve weeks: each Monday the season's box
scores are solved against the preseason prior and project the next 7 days. Production
treats the prior as worth 5 games.

| Variant, median team 0-12 games played (4,510 games) | Brier vs production (95% CI) | Margin MAE |
|---|---|---|
| Slower: prior worth 8 games | +0.0017 (+0.0008 to +0.0026) | +0.22 (+0.17 to +0.28) |
| Faster: prior worth 3 games | -0.0004 (-0.0014 to +0.0007) | -0.18 (-0.25 to -0.11) |
| Prior spread widened 30% | +0.0008 (+0.0001 to +0.0014) | -0.13 (-0.18 to -0.08) |

- A slower update is worse in both seasons. A faster one is level overall: slightly worse in
  the first three games (+0.0018, not significant), better at 7-12 games (-0.0015,
  -0.0024 to -0.0006).
- Where a fast and a slow update disagree, results land beyond the fast one (share of the
  extra movement that shows up in results: 1.5 to 2.1). The rating under-reacts if anything.
- The preseason is not too compressed at the rating level: Selection Sunday rating
  regressed on preseason rating has slope 0.56-0.63, and widening the prior hurts Brier.

## Reading
The preseason number is uncertain by 4 to 5 points (see `2026-11-11-bracketology-review.md`),
so a few decisive results are worth a lot against it, and the tests agree. Two cautions:
- A single 75-point home win over a very weak team is the noisiest kind of evidence the
  solver sees, and November home games run about 4 points better for the home team than
  later ones (`2026-11-10-hoops-early-season.md`). Individual early risers can be 1-2 points
  hot. The registered early-season experiment covers the game-level side of this.
- Moving the prior from 5 games to 3 is not supported: no overall gain.
