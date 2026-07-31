# Matchday Edge Overlay (personal build)

Standalone Chrome extension, decoupled from the Matchday site/deploy pipeline —
it isn't in `_site/`, `deploy.yml`, `index.html`'s nav, or anything Vercel
serves. It only reads two things at runtime: Polymarket's public API, and
Matchday's already-public `data_<comp>.json` files. Nothing about it needs
the site's private `ROI_ACCESS_TOKEN` from the earlier `api/roi.js` work —
a Chrome extension's code is fully readable by anyone who inspects it, so a
secret doesn't belong inside one. The access boundary here is just "only you
installed it."

## What it does

On a Polymarket event page (`polymarket.com/event/<slug>`), a content script:
1. Reads the market slug from the URL.
2. Looks up the market on Polymarket's public Gamma API (question text,
   CLOB token ids).
3. Fetches your site's public competition JSON files and matches the
   question text to a fixture using a simplified port of `fetch_data.py`'s
   team-name normalizer (`matcher.js`).
4. Reads your model's probability for whichever side the market is asking
   about (`prediction.blend`/`adjusted`, not just the model's own top pick).
5. Opens a WebSocket to Polymarket's CLOB API for that market's live price
   and shows model% vs. market% vs. edge in a small corner overlay,
   updating on every tick.

## Before you rely on this: verify the Polymarket API calls

This was built in a sandboxed environment whose outbound network policy
blocks `gamma-api.polymarket.com` and `clob.polymarket.com` — confirmed via
the proxy status endpoint, not just a site-side block. That means the Gamma
API response shape, the CLOB WebSocket subscribe message, and the REST
fallback endpoint in `offscreen.js` are from documented public-API
knowledge, **not a checked live response**. Every spot that matters is
marked `VERIFY` in `offscreen.js`. Matchday's own `CLAUDE.md` is explicit
that provider integrations should never assume a header/response shape and
should be checked against a live call first — normally that's a `curl`
before writing code; here that step couldn't be done, so it's on you (or a
follow-up session with network access) to do it before trusting any number
this overlay shows:

1. Open a Polymarket market page with DevTools Network tab open.
2. Compare the real request/response for the markets lookup and the
   WebSocket messages against `fetchGammaMarket()` and `extractPrice()` in
   `offscreen.js`.
3. Fix field names/paths as needed — they're isolated to those two
   functions plus the `CLOB_WS_URL`/`GAMMA_BASE`/`CLOB_REST_BASE` constants
   at the top of the file.

## Install (unpacked, personal use — no Chrome Web Store review needed)

1. `chrome://extensions` → enable **Developer mode** (top right).
2. **Load unpacked** → select this `chrome-extension/polymarket-overlay/`
   folder.
3. Click the extension icon → popup lets you set the Matchday data origin
   (defaults to `https://matchdayterminal.com`). If you point it somewhere
   else (e.g. a Vercel preview URL), also add that host to
   `host_permissions` in `manifest.json` and reload the extension, or the
   fetch will be silently blocked by Chrome's permission model.
4. Visit a Polymarket event page for a match your site covers. The overlay
   appears bottom-right once a fixture match is found.

## Known limitations (v1, not fixed here)

- **Matching is heuristic.** `matcher.js` matches by team-name token overlap
  in the market question. Ambiguous questions (both teams named, or
  neither) are reported as "no matching fixture" rather than guessed.
- **Assumes one binary market per event slug.** Multi-outcome events
  (e.g. "who wins the tournament") aren't handled — `fetchGammaMarket()`
  only reads `/markets?slug=`, not the `/events?slug=` shape with several
  sub-markets.
- **`tokenIds[0]` is assumed to be the "Yes" token.** If Gamma ever orders
  outcomes differently, the price reported would be for "No" instead.
- Not betting advice; see the earlier conversation about promotion/vs.
  commentary framing if you ever want to show this to anyone but yourself.
