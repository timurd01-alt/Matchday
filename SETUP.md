# Matchday Terminal — setup (v2)

Files: `index.html` (dashboard), `fetch_data.py` (pulls data),
`data.json` (what the page reads), `SETUP.md` (this). Keep all in one folder.

## See it now (no keys)
In VS Code, open the folder, then in the terminal:

    python -m http.server 8000

Open http://localhost:8000 — three sample matches. Tap a match to open the
Markets / Stats / Lineups tabs.

## Required keys (2 min each)
1. football-data.org → https://www.football-data.org/client/register
2. The Odds API       → https://the-odds-api.com/
3. BALLDONTLIE        → https://www.balldontlie.io/account/
4. College data       → https://collegefootballdata.com/key
5. Sportmonks         → https://www.sportmonks.com/football-api/ (optional soccer detail)

Open `config_keys.py`, paste them between the quotes, and save (Ctrl+S):

    FOOTBALL_DATA_KEY = "your_key"
    ODDS_API_KEY      = "your_key"
    BALLDONTLIE_KEY   = "your_key"
    CFBD_KEY          = "your_college_key"
    CBBD_KEY          = "your_college_key"  # use the same key here
    SPORTMONKS_KEY    = "your_token"

## Licensed detail feeds
NBA and NFL schedules/scores use BALLDONTLIE's real free game feeds.
The free tier does not include standings, leaders, injuries or player statistics,
so Matchday leaves those sections unavailable instead of inventing data.
NCAAF and NCAAM are live through CollegeFootballData and CollegeBasketballData.
They share one key and use an eight-hour local provider cache so the background
refresh loop stays within the free monthly allowance. NCAAM is restricted to the
365 current Division I teams and retrieves the full season in documented date
windows instead of silently stopping at the API's 3,000-game cap. MLB and NHL are
intentionally out of the public launch scope for now.
Soccer lineups, formations, injuries and match statistics come from Sportmonks.
That optional detail requires provider credentials and the corresponding product access. One real-world note:
official starting XIs are only published about 75 minutes before kickoff, so a
match still hours away will show "drops ~75 min before kickoff" — that's normal.

## Pull live data
    python fetch_data.py            (once)
    python fetch_data.py --loop     (auto: ~45s while a match is live, else hourly)

Refresh the browser (F5). Sample banner disappears.

## Running setup
- Terminal 1: python -m http.server 8000   (serves the page)
- Terminal 2: python fetch_data.py --loop   (refreshes data)
- Browser:    http://localhost:8000

## What's in the app
Four tabs at the top:
- Matches: live + upcoming (finished hidden behind a toggle). Tap for Markets,
  Stats (group, points, W-D-L, GD, form, H2H, absences) and Lineups (live subs).
- Title: every team ranked by odds to win the tournament.
- Bracket: the best-third-placed race (top 8 advance) plus the knockout rounds,
  which fill in as the group stage finishes.
- News: linked headlines from multiple public RSS sources.

Title odds, bracket and news need no extra key (Odds API key + public feeds).
Twitter/X is not included — it has no free, reliable feed; the RSS sources above
are the legitimate way to get diverse, well-known outlets.
