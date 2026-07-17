# Rotating your API keys (10 minutes, do before anything goes public)

Your three keys have appeared in AI chats, which means they should be treated
as exposed. Rotation = generate new key, paste into config_keys.py, done.
Nothing else in the app changes — the code reads keys only from that file.

## 1. football-data.org  (fixtures)
- Log in at https://www.football-data.org/client/home
- My Account -> there is a "regenerate token" / contact option; if no self-serve
  button exists on your plan, email their support asking to reissue the token
  (they do this routinely).
- Paste the new token into config_keys.py as FOOTBALL_DATA_KEY.

## 2. The Odds API  (odds)
- Log in at https://the-odds-api.com/ (account/dashboard page)
- Use "regenerate API key" on the dashboard.
- Paste into config_keys.py as ODDS_API_KEY.

## 3. API-Football / api-sports  (box scores, optional)
- Log in at https://dashboard.api-football.com/
- Profile -> "Regenerate API Key".
- Paste into config_keys.py as API_FOOTBALL_KEY.

## Then
- Run one fetch (fetch_once_show_errors.bat) and confirm the diagnostics show
  fixtures, odds and box stats loading. That's the whole verification.
- From now on: keys never get pasted into chats or uploaded. When sharing the
  app folder with an AI, config_keys.py stays home (the shipped zips already
  exclude it, and .gitignore now protects any future GitHub repo).
