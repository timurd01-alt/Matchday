# Rankings and Projections

Matchday distinguishes real polls and standings from model projections. Projected lists are labeled so they are not mistaken for official rankings.

## College Top 25

Matchday displays two separate lists:

- **Matchday Top 25** is the site's model ranking. It uses the same public power-rating signal as Matchday's forecasts: preseason roster/class strength, self-training Elo, and current-season results with sample-size-aware weighting.
- **AP Top 25**, **CFP Rankings**, or **Coaches Poll** is the provider-authored national poll, labeled by its actual name. It does not replace or get relabeled as Matchday's calculation.

Before games begin, the Matchday ranking is necessarily driven mostly by its preseason and historical inputs. Current-season results gain weight as the sample grows.

The earlier offseason-only projection blended two normalized signals:

- **55% prior-season performance:** the previous season's final poll
- **45% upcoming roster strength:** multi-year Team Talent Composite for college football, or recruiting ratings for men's college basketball

The old final poll is used only as an input; it is not relabeled and presented as the new season's poll. This blend allows a team with proven recent results to remain visible even when recruiting rankings underrate its transfers, development, or coaching, while still accounting for offseason roster turnover.

If one input was unavailable, the projection could use the remaining signal. That formula remains part of the implementation history, but a real new-season poll no longer replaces the independent Matchday list.

## CFP projections

College Football Playoff seeding is generated only from a real poll with enough ranked teams. A way-too-early projected Top 25 does not masquerade as an official CFP seed list.

## Other derived rankings

Power rankings, title estimates, upset indicators, and tournament projections are Matchday model outputs. Their labels and source notes should always be read alongside the values.
