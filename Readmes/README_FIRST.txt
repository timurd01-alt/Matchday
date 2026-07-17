MATCHDAY TERMINAL - SAFE BUILD

Use start_app.bat first.

This build does NOT use pywebview by default. It opens the dashboard in an
Edge/Chrome app window instead, which avoids the frozen embedded WebView problem.

If start_app.bat still gets stuck:
1. Close the frozen window.
2. Run start_browser_no_fetch.bat.
3. Keep the black terminal window open.
4. Tell ChatGPT what the terminal prints.

Only use start_webview_old_mode.bat if you specifically want to test pywebview.
