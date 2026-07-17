Matchday UI patch — lineups, flags, and odds board

Replace only index.html.

Changes:
- Lineups now render on pitch-style fields with player cards instead of plain crossed lists.
- Subbed-off players are marked softly with a small “sub” tag, not crossed out.
- Flags added to fixtures, modal headers, groups, bracket-compatible UI, and odds board when team codes are available.
- Odds board redesigned with a favorite card, top contender cards, and a cleaner ranked market table.

This patch does not touch fetch_data.py, config_keys.py, app.py, data.json, model formula, odds keys, or the launcher.
