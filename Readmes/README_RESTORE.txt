KEY RESTORE ONLY
================

This pack intentionally changes only the key/fetcher side.

Copy these into your Matchday folder:

1. fetch_data.py
2. config_keys.py

Choose Replace if Windows asks. Do not replace index.html, app.py, mini.html, icons, or start files unless you specifically want to.

This restores:
- football-data.org key
- The Odds API key
- match odds
- title/outright odds
- original standings / bracket / third-place race / news payload fields

Then run:
python fetch_data.py

or double-click your existing start_app.bat.
