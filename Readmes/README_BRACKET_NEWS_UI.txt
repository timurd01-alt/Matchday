Matchday UI + news source patch

Replace these files in your Matchday folder:

1) index.html
   - Compact two-sided tournament bracket.
   - Smaller bracket cards so the bracket fits better.
   - Flags added where team country codes are available.
   - News UI detects and displays multiple sources more clearly.

2) fetch_data.py
   - Keeps the football-data.org + Odds API workflow.
   - Keeps model picks, match odds, over/under, title odds, groups, bracket, and thirds.
   - Only improves the news fetcher by adding more RSS/Google News backup sources and preserving source labels.

After replacing, run once:

python fetch_data.py

Then start the app normally. If News still only says ESPN, open the News tab and check Feed diagnostics at the bottom.
