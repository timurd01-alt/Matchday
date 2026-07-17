RESTORE ODDS + MODEL PICKS ONLY
===============================

Copy these files into your existing Matchday folder and choose Replace:

  app.py
  fetch_data.py
  config_keys.py
  index.html

Then run this once so data.json gets rebuilt with odds + model picks:

  python fetch_data.py

Then start the app normally with start_app.bat.

What this restores:
- football-data.org key loading
- The Odds API key loading
- 1X2 odds per match
- over/under odds per match
- tournament winner / title odds board
- model pick visible on every match card
- Model tab showing all picks and market edge
- groups, bracket, third-place tracker, news, status, customization remain in the UI

Important:
- ESPN/public feeds are NOT used for odds or model picks.
- ESPN/public feeds are only optional for lineups, injuries, public box-score style stats, and news.
- If odds still do not show, run python fetch_data.py in a terminal and read the diagnostics lines that start with odds: or title odds:.
