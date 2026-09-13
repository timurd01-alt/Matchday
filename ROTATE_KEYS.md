# Rotating your API keys (do before anything goes public)

Every key in config_keys.py that has appeared in an AI chat should be treated as
exposed. Rotation = generate new key, paste into config_keys.py, done. Nothing
else in the app changes -- the code reads keys only from that file.

`backfill_history.py` (a manually-run, one-time historical Elo seed script)
reads the same CFBD_KEY/CBBD_KEY from config_keys.py. If you rotate a key while
a backfill run is in progress, that run will start failing mid-way; stop it and
re-run the same command after pasting the new key -- already-applied seasons
are skipped automatically.

Matchday covers college football and men's college basketball only. The
football-data.org, API-Football, BALLDONTLIE, Sportmonks and Big Balls keys are
no longer read by anything; revoke them at the provider rather than rotating.

## 1. The Odds API  (odds)
- Log in at https://the-odds-api.com/ (account/dashboard page)
- Use "regenerate API key" on the dashboard.
- Paste into config_keys.py as ODDS_API_KEY.

## 2. CollegeFootballData / CollegeBasketballData  (NCAAF / NCAAM)
- These two share one key from the same account (that's why CFBD_KEY and
  CBBD_KEY are identical in config_keys.py today) -- one new key covers both.
- Request/regenerate at https://collegefootballdata.com/key.
- Paste the same new key into config_keys.py as both CFBD_KEY and CBBD_KEY.

## 3. SportsGameOdds  (fallback market context)
- Regenerate in the SportsGameOdds dashboard.
- Paste into config_keys.py as SPORTSGAMEODDS_KEY.

## 4. SportsDataIO  (dormant college injury overlay)
- Log in at https://dashboard.sportsdata.io/
- Account/API keys -> regenerate; contact support if your plan requires them
  to reissue it manually.
- Paste into config_keys.py as SPORTSDATAIO_KEY.

## Then
- Run one fetch (fetch_once_show_errors.bat) and confirm the diagnostics show
  fixtures and odds loading. That's the whole verification.
- From now on: keys never get pasted into chats or uploaded. config_keys.py
  stays home, and .gitignore protects it.
