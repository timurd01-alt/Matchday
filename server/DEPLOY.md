# Matchday Leaderboard — Deploy Guide

You have TWO server options. Pick one. Both enforce the same three anti-abuse
guardrails (sanity checks, rate limiting, 10-pick minimum to appear).

Nothing goes live in the app until the LAST step, where you paste your server
URL into index.html. Until then the leaderboard shows "Coming soon" and the
app behaves exactly as it does now.

---

## PATH A — Serverless (near-$0, a bit more setup)
File: serverless_function.js

1. Create a free hosted Postgres database (e.g. Neon, Supabase, or your host's
   built-in). Copy its connection string.
2. In its SQL console, run the CREATE TABLE block from the top of
   serverless_function.js.
3. Create a project on a serverless host (Vercel/Netlify/Cloudflare). Add the
   file as a function. Set env var DATABASE_URL to your connection string.
4. Deploy. Your function URL looks like https://yourapp.vercel.app/api/leaderboard
   (the base URL before ?action= is what you'll paste into the app).

## PATH B — Always-on app (simpler, a few $/mo)
File: server_app.py

1. Create a small app host (Render, Railway, Fly, a cheap VPS).
2. Point it at server_app.py. Start command: `gunicorn server_app:APP`
   (or just `python server_app.py` for a quick test).
3. It creates its own SQLite file automatically — no separate database to set up.
4. Your URL looks like https://matchday-board.onrender.com

---

## FINAL STEP — turn it on in the app (do this when you're ready to launch)
1. Open index.html, find:  const LEADERBOARD_URL = "";
2. Paste your base server URL between the quotes, e.g.
   const LEADERBOARD_URL = "https://matchday-board.onrender.com";
3. Save, reload the app. The Community tab now shows a handle prompt, then the
   live board. Your picks post automatically as they grade.

## To turn it back off
Set LEADERBOARD_URL back to "". The app returns to local-only instantly.

## What I could not do for you
Create the hosting/database accounts or run the deploy — those need you logged
into real services. Everything else (all server + client code) is written and ready.
