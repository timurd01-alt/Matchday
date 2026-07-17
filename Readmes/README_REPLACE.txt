Matchday Terminal patch — groups, bracket, third-place tracker, news sources

REPLACE these files in your Matchday folder:
- index.html
- fetch_data.py
- manifest.json
- favicon.ico
- icon-180.png
- icon-512.png
- matchday.ico

ADD this file once:
- config_keys.py

IMPORTANT ABOUT YOUR API KEY
I cannot recover a private key that was overwritten locally or was not in the files you sent.
To avoid this happening again, this build reads your football-data.org key from config_keys.py.
Open config_keys.py and paste your key there:

FOOTBALL_DATA_KEY = "your_key_here"

After that, future fetch_data.py replacements can be copied without deleting your key.
If you already have a config_keys.py with your real key, DO NOT replace it.

WHAT THIS PATCH FIXES
- Groups tab always builds tables, even from older data.json match cards.
- Bracket tab shows official knockout fixtures when available; otherwise it shows a projected qualifier board from the live group tables.
- New Thirds tab tracks best third-placed teams and marks the current top 8.
- News cards now show source badges clearly.
- News fetcher uses ESPN plus BBC, Guardian, Sky, CBS, ESPN FC, and Google News RSS searches.
- X/Twitter is included as quick links only; it is not scraped.

RUN
1. Paste your key into config_keys.py.
2. Run: python fetch_data.py
3. Start your app normally.
4. In the app, open Status to check groups/news counts.
