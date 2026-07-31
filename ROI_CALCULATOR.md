# ROI/edge calculator — personal-only

Compares the model's locked pick confidence against the bookmaker no-vig
market consensus already published in `data_<comp>.json` (the same
`markets["1x2"]` object every other view on the site reads — no new data
source, no new provider-compliance surface). Gated behind a bearer token so
it's usable only by you, not the public site.

Files: `api/roi.js` (Vercel serverless function), `roi.html` (static page,
not linked from the nav, `noindex`).

## Turn it on

1. In the Vercel project's dashboard, set an environment variable
   `ROI_ACCESS_TOKEN` to a long random string. Unset (or empty) means the
   endpoint refuses every request — it fails closed, not open.
2. Deploy. `roi.html` and `api/roi.js` ship with the Vercel deployment
   automatically (the same "rest of the repo deploys alongside as static
   files" behavior described in `server/DEPLOY.md`). They are **not**
   copied into `_site/` by `deploy.yml`, so they never reach the public
   GitHub Pages domain (`matchdayterminal.com`) — only the Vercel URL.
3. Visit `https://<your-vercel-app>.vercel.app/roi.html?key=<the token>`
   once. The page stores the token in `localStorage` and strips it from the
   URL. Every visit after that just works; anyone without the token gets a
   generic "Not available." page and the API returns 401.

## What this does not do yet

`predictionMarket.status` on every row is hardcoded to `"not_connected"` —
there is no live Polymarket or Kalshi feed wired in. Adding one needs its
own provider adapter and a `provider_quota.py` `PROVIDER_SPECS` entry read
off a real response (per `CLAUDE.md`'s provider rules — never assume rate-
limit numbers), plus a compliance pass in `PROVIDER_COMPLIANCE.md` before
any prediction-market data gets displayed, even privately. The bookmaker
side is safe to ship now only because it reuses data the app already fetches
and displays elsewhere under existing compliance terms.

## To turn it back off

Unset `ROI_ACCESS_TOKEN` in Vercel. The endpoint fails closed immediately.
