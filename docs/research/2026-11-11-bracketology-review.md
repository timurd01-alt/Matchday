# Bracketology review: how the tab's odds are made, and four faults (2026-11-11)

**Status:** review only. Nothing changed. Three fixes are proposed; one of them replaces an
owner rule, so none was applied.
**Scripts and full notes:** engine `docs/research/2026-11-11-bracketology-*`.
**Read:** `hoops/bracketology.py`, `simulate.py`, `committee.py`, `bracket.py`, `resume.py`,
`bracketology_contract.py`; Matchday `app-bracketology.js`; the published
`bracketology_ncaam.json` built 2026-11-10 (phase `early`, preseason basis, median team 2 games).

## How the odds are made
1. A power rating plays every remaining game 10,000 times (normal margin, sigma 11, home
   edge 3.2). Each simulated season gives every team one strength offset (SD 2.5 points).
2. Every conference tournament is played in each simulated season, in the format that
   conference used last year.
3. A committee model, fitted on stored past fields with the projected season held out,
   picks and seeds a field from each simulated season's résumés, with its own noise.
4. Make-field, auto-bid, at-large and seed odds are counts over those seasons.
5. The drawn bracket is one field: each conference's likeliest champion plus the at-large
   teams picked most often when not champions, ordered by average simulated seed.
6. Round and title odds come from playing that one bracket 10,000 times on a "tournament
   rating": half power rating, half the usual strength of the seed line.

The published file is internally consistent: make-field odds sum to 68.00, auto bids to
32.00, title odds to 1.000, every seed line has the right count.

## Faults
### 1. The simulation plays games on the weaker rating in every phase
Bracketology uses the preseason projection alone until the median team has 10 games, then
this season's games alone with no prior. Walk-forward on 2024-25 and 2025-26 (each Monday,
project the next 7 days; 9,279 games; sigma 11, home 3.2), against the rating the game picks
use (this season solved against the preseason prior):

| Median games played | n | Brier: preseason only | this season only | both |
|---|---|---|---|---|
| 0-3 | 1,262 | 0.1909 | 0.1925 | **0.1793** |
| 4-6 | 640 | 0.1997 | 0.1872 | **0.1741** |
| 7-9 | 1,013 | 0.1837 | 0.1681 | **0.1573** |
| 10-12 | 1,486 | 0.1908 | 0.1744 | **0.1654** |
| 13-16 | 1,333 | 0.2282 | 0.2054 | **0.2010** |
| 17-22 | 2,023 | 0.2297 | 0.1968 | 0.1956 |
| 23+ | 1,522 | 0.2343 | 0.1996 | 0.1996 |

- Before the switch the bracket uses the first column; the combined rating is better by
  0.012 to 0.026 Brier in every bucket.
- After the switch it uses the middle column. From 10 games on, season-only is worse than
  combined by +0.0034 (95% CI +0.0020 to +0.0049; margin MAE +0.22, +0.14 to +0.33). At
  10-12 games the gap is +0.0090 (+0.0056 to +0.0125). The two are level from about 17 games.
- The résumé the committee judges would still be this season only. The power rating only
  decides who wins the games not yet played.
- Caveat: the replay's prior has roster adjustments off; production's has them on.

### 2. First Four at-large teams are not the lowest at-large seeds
"Last four in" is chosen by how often a team is picked; seed order comes from average
simulated seed, which is taken only over the seasons the team made the field. A 55% team
is therefore averaged over its good seasons. In the 11-10 file Creighton and Iowa are
overall seeds 35 and 36 and play in for a 9 seed, while Clemson, Miami, Indiana and UCLA
(37-40) do not. The real committee puts the last four at-large teams at the bottom of the
at-large list. A 9-line play-in has never happened.
Fix: after ordering, move the last-four-in teams below every other at-large team.

### 3. November title odds treat today's rating as exact
The season simulation gives each team a 2.5-point strength offset; the bracket play-out
gives none. Preseason rating to Selection Sunday rating moved by 4.3 and 4.8 points RMS
(2025, 2026), and 4.9 and 6.7 for the preseason top 40. Replaying the published bracket:

| Strength offset | Duke title | Top 4 share | Top 8 share |
|---|---|---|---|
| 0 (published) | 16.5% (published 18.1%) | 45% | 74% |
| 2.5 | 14.7% | 42% | 68% |
| 4.5 | 11.8% | 36% | 60% |

The 50/50 power/seed blend was fitted at Selection Sunday, where no offset is right. A
sigma that starts near 4.5 in November and falls to 0 at Selection Sunday would keep that
calibration and stop the early page overstating favourites by about a third.

### 4. The tab never says what the round odds assume
The engine sends `odds_basis` as a sentence ("...round odds are for the projected bracket
as drawn"). `app-bracketology.js` only recognises `unconditional_season` or
`conditional_on_field`, so the footer shows neither line. Virginia Tech is 53% to make the
field and shows 46% to reach the Round of 64, which is its play-in chance in this one
bracket. A reader cannot tell.
Fix: send an enum the page knows and add the "as drawn" wording.

## Smaller points
- Early résumé numbers are shown as if they meant something: Duke is résumé rank 94 and
  schedule rank 316 at 2-0.
- The simulation's sigma 11 and home edge 3.2 are separate constants from the pick model's
  11.5 and about 2.4. Before mid-January home teams beat the pick projection by 4.3 points
  (`2026-11-10-hoops-early-season.md`), so 3.2 is the nearer of the two.
- `calibrated` is false in the file, correctly: no stored test compares these odds with
  outcomes before Selection Sunday.
