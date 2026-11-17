# Competitive analysis and path forward (2026-11-16)

**Status:** review only, nothing on the site changed.
**Question:** where does Matchday stand against comparable college sports sites, and what would it take to become the leading site for predictions and education?

## Sources
| Source | What it gave |
|---|---|
| Live site, both sports | Every tab read in the browser on 2026-11-16 |
| `origin/main` @ `b0f3e17` | `index.html`, `sitemap.xml`, `robots.txt`, bundle sizes, earlier notes in this folder |
| kenpom.com, barttorvik.com, evanmiya.com, haslametrics.com, teamrankings.com, gameonpaper.com, espn.com FPI | Read in the browser or fetched on 2026-11-16 |
| btb-analytics.com, cfbtrack.com, redshirtanalytics.com, fourthandshort.com | Home pages fetched; newer football sites |
| thepredictiontracker.com | 2026 football results through 11-15; basketball "season to date" (season not labelled) |

Not reached: cfb-graphs.com (connection refused), kfordratings.com (empty page), Massey's composite page (the URL I tried returned 404). Traffic estimates from Similarweb and Semrush disagreed by a factor of about 40 for the same site, so no traffic numbers are used here. KenPom's price ($24.95 a year) comes from a third-party article, not from its own subscribe page; the $95 API price is from KenPom's own page.

## Where Matchday stands

### What it has
- Ten tabs for two sports: Home, Games, Rankings, Standings, Results, Research, Learn, Scorecard, Bracket, Pick 'Em.
- Ratings for 134 FBS teams and 363 basketball teams, a win probability and margin on every game, a projected playoff field, and a full basketball bracketology with seed odds and every conference tournament.
- A public record: football 468-185 (71.7%, 72.3% expected), basketball 675-148 (82.0%, 83.9% expected), with calibration bands and a split by agreement with the market.
- Learn: 8 topics and about 35 glossary terms.
- Free, no account, no ads.

### How the forecasts compare
| 2026 football, straight-up winners | Games | Correct |
|---|---|---|
| Best public system on the Prediction Tracker | 629 | 74.1% |
| Closing line | 629 | 73.8% |
| Opening line | 629 | 72.8% |
| **Matchday locked picks** | 653 | 71.7% |
| Median of 55 tracked rows (Sagarin) | 629 | 71.2% |
| Worst tracked system | 629 | 60.2% |

- The game sets are not identical (653 vs 629), so this places Matchday roughly, not exactly: about the middle of the public field, two points behind the closing line.
- Only one tracked system is ahead of the closing line on winners, by 0.3 points. Beating the line is not something the established systems do either.
- Matchday's own scorecard says the same thing from the inside: when it disagreed with the market it went 19-33 in football; in basketball 22-15, below the 67% its own probabilities implied. Its priced selections beat the price 44.3% and 42.1% of the time against a 50% coin flip.
- Football calibration is good in every band. Basketball's 70-80% band has hit 60%, the early-season effect already registered as `ncaam-early-season-calibration-v1`.
- Basketball's 82.0% is not comparable to the tracker's 78.5% line: Matchday's set includes games against non-Division I opponents.

### What it lacks
1. **It cannot be found.** The whole site is one URL. Every view is `/?view=...`, the canonical tag points at `/`, the sitemap lists 5 URLs, and the HTML a crawler receives is the welcome copy followed by "Loading...". A web search for the domain returned nothing. There is no address for a team, a game or a glossary term.
2. **No depth behind the ratings.** No player data, no past seasons, no basketball box detail (`archive/box/` is empty). KenPom goes back to 2002, Game on Paper to 2004, Torvik to 2008.
3. **No method on show.** The ratings come from a private engine. KenPom and Torvik earned trust by publishing how the number is made.
4. **No distribution.** No social account, by choice. Nothing replaces it yet.
5. **Pick 'Em looks empty.** One player on the leaderboard; most rows read "no picks yet".
6. **Weight.** The football snapshot script is 2.4 MB, `trdlab_picks.json` 2.8 MB, `styles.css` 387 KB.

## The field

### Basketball
| Site | Model | What it is best at | Shows its own record |
|---|---|---|---|
| KenPom | Free ratings table; paid game predictions, player and four-factor pages | The reference. 26 seasons, quoted on broadcasts | Not seen |
| Bart Torvik | Free | Customisable everything: date ranges, bracket projection, tournament odds, shot charts, women's ratings | Not seen |
| EvanMiya | Paid | Player and lineup ratings, transfer portal | Not seen |
| Haslametrics | Free, donations | Shot-type detail back to 2014-15 | Not seen |
| TeamRankings | Free plus paid picks, multi-sport | Betting and pool picks | A "Prediction Accuracy" page in its menu, not opened |

### Football
| Site | Model | What it is best at | Shows its own record |
|---|---|---|---|
| ESPN FPI and SP+ | Free and ESPN subscription | Reach; season simulations | Not seen |
| Game on Paper | Free | Per-game advanced box scores, 2004-2026, FCS included | Makes no predictions |
| CollegeFootballData | Free API, paid tiers | The data source most hobby sites, this one included, are built on | Not a forecaster |
| TeamRankings | Free plus paid | Projected records, pick grids | Same accuracy page |
| BTB Analytics, Redshirt Analytics, CFBTrack, Fourth and Short | Mixed; some paid, some affiliate | New 2026 sites: ratings, futures, glossaries, bracket builders | A "historical results" page at BTB, unread |

### What the comparison shows
- **Ratings are a commodity.** Matchday and TeamRankings have the same football top three in the same order. At least four new football sites publish ratings this season. A rating table alone will not set Matchday apart.
- **The leaders are tables without explanation.** KenPom's home page is one dense table and a "help" link. Torvik tells phone users to rotate the screen. None of them tells a newcomer what the number means or how far to trust it.
- **Almost nobody grades themselves in public.** Of the sites read, only TeamRankings linked an accuracy page. None showed a calibration chart or a model-versus-market split. Matchday shows both, including the part where its own disagreements underperform.
- **Nobody covers both sports for the plain fan.** KenPom, Torvik, EvanMiya and Haslametrics are basketball only. Game on Paper is football only. ESPN and TeamRankings cover both but serve bettors and subscribers.
- **The leaders' positions come from time.** KenPom is the reference because coaches, committees and broadcasters have quoted it for two decades, and that cannot be built in a season.

## Conclusion
Matchday is a well-made, honest site with average public-model accuracy and no audience path. It will not displace KenPom as the reference rating or ESPN on reach in the near term, and "the model that beats the market" is not available as a claim: the evidence says it does not, and neither do the 50 systems on the Prediction Tracker.

The position that is open is the one the leaders ignore: **the site where a fan learns what the numbers mean and can check whether a model is any good**, for both sports, free. Three things Matchday already has point there and no competitor combines them: the explained glossary, the locked and graded record, and one interface for football and basketball. The work is to make those findable and deep, in that order.

## Path forward

### 1. Make the site addressable (before conference play)
- Real URLs with prerendered HTML: one page per team (about 500), per game, and per Learn term. `build_cfb_snapshot.py` already has the data at build time.
- Each page gets its own title, description, canonical and structured data, and goes in the sitemap.
- Split the 2.4 MB snapshot so a team page loads only its own team.
- This is the dependency for everything below. `robots.txt` already invites search and AI crawlers; today there is nothing for them to read.

### 2. Own the education (before Selection Sunday, mid-March 2027)
- Grow Learn from a glossary into a reference: one page per term, each with a live example from this week's data.
- Plain-language guides to the numbers fans meet elsewhere: NET and quadrants, efficiency margin, SP+ and FPI, strength of record. Explaining a public metric is allowed; reproducing a provider's numbers is not (`PROVIDER_COMPLIANCE.md`).
- A bracket guide for March and a playoff guide for December, the two weeks a year when casual fans search for this.
- Game pages that say why: which efficiency edge drives the probability, in a sentence. The leaders show the number and stop.

### 3. Let third parties vouch for it
- Ask the Prediction Tracker and the Massey composite to track Matchday's ratings. It fits "check the work", needs no social account, and puts Matchday beside 50 known systems. The submission process still has to be confirmed; neither page stated it.
- Publish ratings and the graded record as a dated CSV with a citation line, so the welcome page's "bring it to the argument" is something a blogger can actually do.
- Put the tracker context on the Scorecard: the closing line's own hit rate next to Matchday's.

### 4. Earn the forecasting claim honestly
- Lead with calibration, which is true, and keep "beats the market" off the page until the pre-registered tests say so.
- Keep the baseline frozen through the season and batch model changes.
- The two known gaps stay as registered research: basketball's early-season home edge, and football's September gap, which the 2026-11-11 notes traced to news the model does not have.

### 5. Add depth where it is cheap
- Past seasons from `archive/games/`: team history pages, and a second large set of findable pages.
- Basketball box detail remains the open sourcing task; without it Matchday cannot show four factors the way the free basketball sites do.
- Hide Pick 'Em's leaderboard until there are enough players for it to read as alive.

### Not recommended
- More sports, including women's basketball for now. It is under-served, but the two-sport scope was a deliberate decision.
- A picks or betting funnel, paid tiers, or ads.
- Raising market weight to gain accuracy.

## Caveats
- Competitor features were read from home pages and navigation, not from full use of each site. "Not seen" means not found on the pages read.
- The Prediction Tracker comparison is approximate: different game sets, and the tracker's basketball page did not state its season.
- Matchday's own traffic was not measured; I did not look for an analytics or Search Console source.
- Similarweb and Semrush figures were discarded as unreliable.
