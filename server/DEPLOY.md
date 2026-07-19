# Matchday Leaderboard — Deploy Guide

Path A (serverless + hosted Postgres) is the one in use. Both anti-abuse
guardrails (sanity checks, rate limiting, 10-pick minimum to appear) are
already built into the function.

Nothing goes live in the app until the LAST step, where the deployed server
URL is pasted into `app-1-core.js`. Until then the leaderboard shows
"Coming soon" and the app behaves exactly as it does now.

---

## PATH A — Serverless on Vercel (near-$0)
File: `../api/leaderboard.js` (repo root's `api/` folder — Vercel's
zero-config convention for serverless functions)

1. Sign in to Vercel → **Storage** tab → provision a Postgres database
   (Vercel's marketplace, backed by Neon, does this in a few clicks and
   wires up a connection-string env var automatically). Use the **pooled**
   connection string, not a direct one — serverless functions open many
   short-lived connections and a free-tier Postgres has a low direct
   connection cap.
2. In that database's SQL console, run the `CREATE TABLE` block from the
   top of `api/leaderboard.js`.
3. Import this GitHub repo as a new Vercel project. No `vercel.json` is
   needed — Vercel auto-detects any file under `/api` as a serverless
   function with zero config; the rest of the (Python/static-site) repo is
   just deployed alongside as static files, harmlessly. Confirm the env
   var name Vercel
   set for the connection string matches `DATABASE_URL` — rename in the
   Vercel dashboard, or the code, if they differ.
4. Deploy. Your function URL looks like
   `https://yourapp.vercel.app/api/leaderboard` (the base URL before
   `?action=` is what gets pasted into the app).

## PATH B — Always-on app (simpler, a few $/mo) — not in use
File: `server_app.py`

Kept as an alternative in case Path A ever needs replacing. Not deployed —
some free always-on hosts reset their disk on redeploy, which would wipe
the SQLite file this path relies on.

1. Create a small app host (Render, Railway, Fly, a cheap VPS).
2. Point it at `server_app.py`. Start command: `gunicorn server_app:APP`
   (or just `python server_app.py` for a quick test).
3. It creates its own SQLite file automatically — no separate database to
   set up, but confirm the host's disk actually persists across redeploys.
4. Your URL looks like `https://matchday-board.onrender.com`

---

## FINAL STEP — turn it on in the app
1. Open `app-1-core.js`, find:  `const LEADERBOARD_URL = "";`
2. Paste the deployed base server URL between the quotes, e.g.
   `const LEADERBOARD_URL = "https://yourapp.vercel.app/api/leaderboard";`
3. Commit, push. The Community tab now shows a handle prompt, then the live
   board. Picks post automatically as they grade.

## To turn it back off
Set `LEADERBOARD_URL` back to `""`. The app returns to local-only instantly.

## What I could not do for you
Create the hosting/database accounts or run the deploy — those need you
logged into real services. Everything else (all server + client code) is
written and ready.
