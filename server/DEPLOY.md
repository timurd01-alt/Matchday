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
2. No manual schema migration is required. The verified-pick and durable
   rate-limit tables are created idempotently by `api/leaderboard.js`.
3. Import this GitHub repo as a new Vercel project. `vercel.json` supplies
   production security headers, while Vercel auto-detects files under `/api`
   as serverless functions; the rest of the (Python/static-site) repo is
   just deployed alongside as static files, harmlessly. Confirm the env
   var name Vercel
   set for the connection string matches `DATABASE_URL` — rename in the
   Vercel dashboard, or the code, if they differ.
4. Deploy. Your function URL looks like
   `https://yourapp.vercel.app/api/leaderboard` (the base URL before
   `?action=` is what gets pasted into the app).

## PATH B — Legacy read-only app — do not deploy for new installations
File: `server_app.py`

Kept only for reading an old SQLite leaderboard. Its score-write endpoint is
disabled because browser-supplied totals cannot be verified. Use Path A for any
new deployment.

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

---

## ACCOUNTS — sign in with Google / GitHub (optional, but it is what makes a
## handle survive a cleared browser)

Without this step the Community tab still works exactly as before: everyone
plays as a guest, identified by the device id in their browser storage. The
sign-in buttons only appear once at least one provider below is configured —
`/api/leaderboard?action=providers` reports which ones are, and the app hides
buttons for the rest.

### 1. Register the OAuth apps
Both need the same callback URL, which must be the **clean path** (Google
rejects a registered redirect URI carrying a query string):

    https://yourapp.vercel.app/api/auth-callback

- **Google** — console.cloud.google.com → APIs & Services → Credentials →
  Create OAuth client ID → *Web application*. Add the callback above as an
  Authorized redirect URI. Scopes needed: `openid email` (the default consent
  screen covers these). Keep the client ID and secret.
- **GitHub** — github.com/settings/developers → New OAuth App. *Authorization
  callback URL* is the same URL. Generate a client secret.

### 2. Set the Vercel environment variables
| Variable | Value |
| --- | --- |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from the Google credential |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | from the GitHub OAuth app |
| `API_ORIGIN` | `https://yourapp.vercel.app` (used to build the callback URL) |
| `PUBLIC_SITE_ORIGIN` | the site people actually visit, e.g. `https://matchdayterminal.com` |

Either provider may be omitted; whichever pair is present is offered. No
schema migration is needed — the account tables are created idempotently on
the next request.

### 3. What a user sees
Community tab → "Continue with Google/GitHub" → back on the site signed in.
The picks they had already locked as a guest are moved onto the account on
that first sign-in ("N earlier picks moved across"), one time only. From then
on the same sign-in on any browser or device returns the same handle and the
same record.

### What is stored
The provider's opaque subject id, nothing else — no email, no name, no
avatar. Sessions are bearer tokens held in the browser (the site and the API
are different origins, so a session cookie would be a blocked third-party
cookie). Losing the token is harmless: signing in again finds the same
account, which is the entire point of the feature.

## What I could not do for you
Create the hosting/database accounts or run the deploy — those need you
logged into real services. Everything else (all server + client code) is
written and ready.
