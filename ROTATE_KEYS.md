# Rotating your API keys (do before anything goes public)

All seven keys in config_keys.py have appeared in AI chats at one point or
another, which means every one of them should be treated as exposed — not
just the three this doc originally covered. Rotation = generate new key,
paste into config_keys.py, done. Nothing else in the app changes — the code
reads keys only from that file.

## 1. football-data.org  (soccer fixtures)
- Log in at https://www.football-data.org/client/home
- My Account -> there is a "regenerate token" / contact option; if no self-serve
  button exists on your plan, email their support asking to reissue the token
  (they do this routinely).
- Paste the new token into config_keys.py as FOOTBALL_DATA_KEY.

## 2. The Odds API  (odds)
- Log in at https://the-odds-api.com/ (account/dashboard page)
- Use "regenerate API key" on the dashboard.
- Paste into config_keys.py as ODDS_API_KEY.

## 3. API-Football / api-sports  (soccer box scores, lineups, injuries)
- Log in at https://dashboard.api-football.com/
- Profile -> "Regenerate API Key".
- Paste into config_keys.py as API_FOOTBALL_KEY.

## 4. BALLDONTLIE  (NFL / NBA / MLB fixtures)
- Log in at https://app.balldontlie.io/
- Account/API settings -> regenerate key; if there's no self-serve button,
  contact their support to reissue it.
- Paste into config_keys.py as BALLDONTLIE_KEY.

## 5. CollegeFootballData / CollegeBasketballData  (NCAAF / NCAAM)
- These two share one key from the same account (that's why CFBD_KEY and
  CBBD_KEY are identical in config_keys.py today) — one new key covers both.
- Request/regenerate at https://collegefootballdata.com/key (their key signup
  is request-based rather than a dashboard toggle on the free tier; check
  their site for the current process if that's changed).
- Paste the same new key into config_keys.py as both CFBD_KEY and CBBD_KEY.

## 6. SportsDataIO  (NHL, currently not reachable from the live site)
- Log in at https://dashboard.sportsdata.io/
- Account/API keys -> regenerate; contact support if your plan requires them
  to reissue it manually.
- Paste into config_keys.py as SPORTSDATAIO_KEY.
- Worth doing anyway even though nothing on the live site currently reads
  this key (NHL is hidden from the sport picker) — it's still a live,
  working credential on your account and exposure risk doesn't depend on
  whether the app happens to be using it right now.

## Then
- Run one fetch (fetch_once_show_errors.bat) and confirm the diagnostics show
  fixtures, odds and box stats loading. That's the whole verification.
- From now on: keys never get pasted into chats or uploaded. When sharing the
  app folder with an AI, config_keys.py stays home (the shipped zips already
  exclude it, and .gitignore now protects any future GitHub repo).
