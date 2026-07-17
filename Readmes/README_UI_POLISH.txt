Matchday UI polish patch

Copy ONLY index.html into your existing Matchday folder and choose Replace.

This patch does not change fetch_data.py, config_keys.py, data.json, app.py, your API keys, or your odds/model logic.

Changes:
- Fixture detail UI redesigned: model/odds cards, match-read panel, better stats visualization, cleaner lineups.
- Bracket tab redesigned as a horizontal bracket with connectors. Uses official knockout data when present; otherwise shows a projected bracket-shaped field without changing data.
- Third-place tracker redesigned as a top-to-bottom ranked table.
- Right-side Latest news now intentionally rotates sources instead of showing one source repeatedly.
