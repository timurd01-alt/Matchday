Matchday auto-refresh fix
=========================

Replace only these launcher files in your Matchday folder:

- app.py
- start_app.bat
- start_browser.bat
- start_webview_old_mode.bat
- start_with_mini.bat
- fetch_once_show_errors.bat

Optional helper:
- fetch_loop_visible.bat

What this fixes:

1. The launcher now always changes into the Matchday folder before running.
2. The fetcher is forced to write to the exact data.json that the app serves.
3. The batch files now also cd into the app folder, so shortcuts/VS Code do not make data.json update in the wrong place.

No UI, model formula, odds logic, data.json, config_keys.py, or API keys are changed.

How to test:

1. Run start_app.bat.
2. The terminal should say: Data fetcher started in the background.
3. It should later print: Auto-refresh wrote ...\data.json
4. In the app, check Status/Updated time after the refresh interval.

If you want to watch only the fetcher, run fetch_loop_visible.bat.
