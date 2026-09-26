# Bracketology display handoff

Bet Better owns every rating, résumé statistic, probability, selection, seed, result and elimination. Matchday renders those values. The release lives inside the existing Bracket navigation: projected bracket, Bubble, and a shared résumé card, with supporting read-only Seed list, Conferences, Tournament odds and Eliminated views. All supporting views use supplied fields; the simulator is deferred.

## Delivery and preview

Publish `bracketology_ncaam.json` at the site root, atomically alongside other deployed assets. The UI must never substitute legacy local projection math for a missing, invalid or stale handoff. A missing or malformed file produces an unavailable state; a stale file is plainly labeled and cannot be represented as current. The producer supplies the validity window rather than the browser guessing a freshness budget.

`docs/fixtures/bracketology_ncaam.mock.json` is a dedicated, explicitly selected preview fixture, never a production fallback. Every statistic, date, status, seed and probability is invented for layout testing. Real school names exercise existing local logo assets; these are not forecasts or factual game results. The fixture deliberately uses “Illustrative conference” and an incomplete all-team catalogue. Real delivery must cover every D1 team. The distant mock `valid_until` is solely for repeatable local preview and must not be copied into a real feed. Rebuild with `python docs/fixtures/build_bracketology_mock.py`. Open the local site with `?sport=ncaam&view=bracket&bracketology_preview=1` to select this fixture; the preview flag is accepted only on localhost, never on the public domain. The deployment excludes `docs/fixtures/`.

## Envelope: draft v0 plus display contract

Required: `version: "0.1"`, `display_contract: "matchday-1"`, `competition`, `season`, `build_id`, ISO UTC `as_of` and `valid_until`, `phase`, boolean `calibrated`, integer `simulations`, integer `field_size`, positive integer `max_seed`, ordered `regions` strings, ordered `rounds` objects `{key,label}`, and ordered `odds_rounds` objects `{key,label}`. `mock: true` requires a persistent demo notice. `calibrated: false` requires a persistent Beta tag independently of the demo notice.

Game columns use `rounds`; résumé and tournament odds use the separate `odds_rounds`. NCAAM supplies `max_seed: 16` and odds metadata in this order: `R64` / Round of 64, `R32` / Round of 32, `S16` / Sweet 16, `E8` / Elite Eight, `F4` / Final Four, `F` / Final, `champion` / Champion. First Four (`FF`) is a game round, not a separate odds column. Reaching the Final and becoming Champion are distinct supplied outcomes. The seed chart displays 1 through the supplied `max_seed`, plus out.

Phases are `early`, `in_season`, `championship_week`, `official`. Early gets an early-projection badge; the supplied seed distribution conveys uncertainty without invented intervals. `odds_basis` describes whether published odds are unconditional seasonal odds or conditional on a specified field. Production must define that basis consistently. `comparison_build_id` and `comparison_as_of` identify the movement baseline.

The UI consumes field size, regions and round labels as metadata rather than assuming 68 teams. A later NCAAF document can supply 12 teams, an empty regions array, its own rounds and no First Four; no football data/model change is part of this release.

## Canonical teams and field

`teams` is an object keyed by immutable `team_key`. Every D1 team, including out and eliminated teams, supplies `{team_key,team_name,conference,logo_key,power_rating,power_rank,resume_rank,record,conference_record,quadrants,sos_rank,sor_rank,best_wins,bad_losses,odds,movement,upset_alert,status,eliminated_on,eliminated_reason}`. `logo_key` is the name/alias accepted by the local logo resolver; a readable text fallback remains mandatory. Identity is never derived from a short display name.

`quadrants` maps Q1–Q4 to `[wins,losses]`. Both `best_wins` and `bad_losses` are arrays of `{opponent,opponent_key,site,date}`; `opponent_key` may be null when there is no linked team. `site` is `home`, `road` or `neutral`; dates are ISO calendar dates. Call the metrics “Power rating” and “Résumé rank”; do not call the latter NET or invent a proprietary name. Power rank may be supplied but is not a replacement label for power rating.

`odds` contains `make_field`, `auto_bid`, `seed` and `rounds`. Probability values are numbers 0–1; formatting to percent is display work. `seed` maps string seeds plus `out` to their producer probabilities. `rounds` maps the keys in envelope `odds_rounds` to probabilities. Omission/null means unavailable, never zero. No UI normalization, probability inference or forecast computation is permitted.

`movement: {seed,make_field}` is supplied for every team: negative seed movement means an improved/lower seed; positive means a worse/higher seed. Make-field movement is a probability difference (0.02 displays +2 percentage points). Zero means unchanged; null or an absent baseline means no comparison. These signs are contractual and not inferred from a team's current place.

`field` retains the draft array shape `{team_key,team_name,conference,seed,region,overall_seed,bid,first_four,odds,movement}`. Its identity and duplicated odds/movement must agree with canonical `teams`. Bid values are `at_large`, `auto`, `auto_clinched`; only the last is shown as clinched. A 68-team field has 68 team entries, including both participants in each play-in slot. Shared seed/region coordinates in First Four do not establish advancement by themselves.

Statuses are `locked`, `in`, `bubble`, `out`, `auto_bid_only`, `eliminated`, `tournament_eliminated`. Alive longshots remain visually distinct from certain elimination. Eliminations supply reason and date. A tournament-eliminated team additionally supplies `eliminated_round`; round odds and outcomes come from the producer, never a UI rule.

## Explicit bracket graph

`bracket` is `{kind:"projected"|"official",games:[...]}`. Each game supplies:

```json
{"id":"east-r64-1","label":"East · Round of 64 · Game 1","round":"R64","region":"East","slots":[{"team_key":"duke"},{"source_game":"ff-1","label":"First Four winner"}],"next_game":"east-r32-1","next_slot":0,"status":"projected","winner_key":null,"score":null}
```

Game IDs are unique. Every game requires a readable `label` for matchup headings and advancement destinations; internal IDs are not user-facing copy. `round` references round metadata; `region` references region metadata (or null for an unregionalized competition). Each of two slots contains either `team_key` or `source_game` plus a producer display label. Explicit feeder references and zero-based `next_slot` must agree in both directions. The championship alone has null advancement. A full 68-team single-elimination graph has 67 games, including four First Four games; ordering is supplied, never inferred from geographic region names or seeds.

`status` is `projected`, `scheduled`, `live`, `finished`, `postponed` or `cancelled`. `score`, when present, is a two-element array in slot order, each a number or null. `winner_key` is a canonical team key, supplied only when resolved. Official downstream participants should be populated by the producer, while predecessor games retain the explicit advancement destination. Matchday does not decide a winner from scores. Games in national rounds use the supplied `National` region; play-ins may use `First Four`.

`first_four` retains draft entries `{game_id,region,seed,kind,teams,win_prob}` for compatibility. Its game reference must match the graph and each team's field entry. The graph is authoritative for display connections. Projected placeholders remain recognizable as feeder paths and never silently become predicted winners.

## Bubble and remaining report shapes

`bubble` has `last_four_byes`, `last_four_in`, `first_four_out`, `next_four_out`, each an ordered array of team keys resolving in `teams`. Empty arrays mean no entries supplied. Membership and movement come from the feed. `bid_thieves` entries are `{team_key,conference,auto_bid_odds,at_large_spots_at_risk}`; do not compute the total cost of overlapping scenarios.

`eliminated` is an ordered array of `{team_key,eliminated_on,eliminated_reason}`, newest first, agreeing with team status. `conferences` entries are `{conference,projected_bids,auto_bid_odds:{team_key:probability}}`. The read-only Eliminated and Conferences views render those reports. Seed list displays `field` ordered by supplied `overall_seed`, together with canonical team résumé measures and make-field odds. Tournament odds displays supplied `odds_rounds` for the field and the producer's `upset_alert`, without identifying disagreements in the browser.

Preview checks include Bradley in Next four out (`out`, 0.005 make-field odds: alive below 1%), George Mason under Bid thieves and Conferences (`auto_bid_only`, 0.08), Cleveland State in Eliminated (`eliminated`, zero odds with reason/date), and bubble teams outside the field such as Indiana. All are invented examples. Each example opens a résumé from its listed view; absence from the projected field must not prevent canonical team lookup.

After Selection Sunday, `bracket.kind` becomes `official`. Optional `final_projection` embeds a complete document in this same contract with projected bracket, original build/time and team data, but without another nested `final_projection`. Its archival as-of is shown as such; it is not mislabeled as the current feed. The primary feed's validity still governs current data availability.

## Simulator decision

The draft `matchup_model: {type:"logistic_on_rating_diff",scale,neutral_site}` contradicts “Matchday displays; it never calculates.” The first release does not evaluate it or offer a simulator. To enable a later simulator, Bet Better must deliver a complete supported-pair probability lookup or a documented endpoint returning `{team_a,team_b,team_a_win,team_b_win,build_id,site}`. It must specify coverage, stale/missing behavior and the baseline/model identity. Unsupported pairings show unavailable rather than browser-derived probabilities. This is a producer dependency, not permission to implement a formula.

## Acceptance

The page shows a persistent Beta state until calibrated, clearly marks projected versus official data, and exposes feed time and stale/unavailable status. The bracket scrolls only inside its own frame on phones. Every real team slot has school name, logo fallback, seed, bid type and supplied odds for that seed; click or keyboard activation opens its résumé. Bubble cards resolve even when their team is absent from the field. Résumé cards place power rating and résumé rank side by side, show supplied quadrant records, SOS/SOR, wins/losses, seed odds including out, round odds and status. Explanations are accessible through tap and keyboard as well as hover. Missing data never appears as 0%, a verdict, or a calculated fallback.
