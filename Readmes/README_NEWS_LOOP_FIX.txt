Matchday News Loop Fix
======================

Replace only this file in your Matchday folder:

  fetch_data.py

What this fixes:
- The auto loop will no longer overwrite a diverse news feed with ESPN-only data.
- If RSS/Google News feeds temporarily fail, the fetcher preserves the previous diverse news list from data.json.
- ESPN remains included, but it cannot take over the whole feed.
- Your UI, data structure, odds tracker, model picks, API keys, and launcher are otherwise left alone.

After replacing:

  python fetch_data.py

or restart your normal loop/app.
