Matchday odds name/cache patch

Replace only fetch_data.py.

Fixes:
- Team-name mismatches across football-data.org and The Odds API, e.g. Cape Verde Islands vs Cape Verde.
- Preserves the last known pre-match odds when the free Odds API stops returning a fixture after kickoff, so the loop no longer wipes lines from data.json.

Does not change:
- index.html / UI
- app.py / launcher
- config_keys.py / API keys
- model formula
- data.json
