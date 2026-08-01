# Matchday Edge Overlay (personal build)

Standalone Chrome extension, decoupled from the Matchday site/deploy pipeline —
not in `_site/`, `deploy.yml`, or `index.html`'s nav, and no shared keys with
Matchday's Vercel deployment. It reads: Matchday's already-public
`data_<comp>.json` files (one signal, not the source of truth), your own
Odds API key (bookmaker consensus across books), Polymarket's public API,
and Kalshi's public API. A browser extension's code is fully readable by
anyone who installs it, so no secret token belongs inside one — the access
boundary is just "only I loaded this."

## What it shows

The panel is now **always visible on every polymarket.com page** as a small
status chip (`idle` / `loading…` / `no match` / `watching`) — earlier
versions only injected on `/event/*` and showed nothing at all elsewhere,
which made a real failure indistinguishable from "not built yet." If you
see `idle`, the extension is running; if you see nothing, it isn't loaded
at all (check `chrome://extensions`).

On a market page it shows four numbers side by side for whichever team the
market is about:

- **Model** — Matchday's own probability (`prediction.blend`)
- **Odds API (books)** — no-vig consensus across bookmakers, same math as
  `market_snapshots.py`'s `no_vig_probabilities()`
- **Polymarket** — live price from the market you're viewing
- **Kalshi** — best-effort match on the same fixture, if Kalshi lists it

Plus:
- A **spread** (max − min across the three market prices) as a quick "how
  much do these disagree with each other" signal — the point of using
  several sources isn't picking one as ground truth, it's seeing where they
  diverge.
- A tiny **sparkline** of that spread (or, before every source has loaded,
  the model-vs-Polymarket gap) over the last ~20 changes.
- A **drag handle** on the header — move the panel anywhere, position is
  remembered per browser profile.
- An **alert threshold** (set in the popup, 0 = off): when the spread/gap
  crosses it, the panel border pulses and a native Chrome notification
  fires once (not on every tick past the line).

### The popup is now a dashboard, not just settings

Click the toolbar icon and you land on **Dashboard**, a table of every
market you've viewed this browser profile (up to the last 30), sorted by
spread — the most-disagreeing markets float to the top. Each row shows
Model/Books/Poly/Kalshi side by side plus a tiny trend sparkline. It keeps
updating live while the popup is open (via `chrome.storage.onChanged`), and
persists across browser restarts since it's just `chrome.storage.local` --
`offscreen.js` writes to it, the popup only ever reads. **Settings** (the
old single view) moved to its own tab. **Clear history** wipes the table.

### How market pages are detected now

Earlier this only matched `polymarket.com/event/*`, which may not be
Polymarket's actual URL shape for sports markets specifically — that
couldn't be verified from the sandbox that built it, and a wrong guess
here would make the extension silently do nothing. It now runs on every
polymarket.com page, takes the last path segment as a candidate slug
(skipping known non-market routes like `/portfolio`, `/leaderboard`,
`/search`, the homepage, etc.), and lets the Gamma API lookup itself decide
whether that's a real market. If it isn't, you'll see `no match` with a
reason instead of silence.

## Setup

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** →
   select this `chrome-extension/polymarket-overlay/` folder.
2. Click the extension's icon (may be hidden under the puzzle-piece menu —
   pin it for easy access) to open the popup, and fill in:
   - **Matchday data origin** — defaults to `https://matchdayterminal.com`.
     If you point it elsewhere, also add that host to `host_permissions` in
     `manifest.json` and reload the extension, or Chrome silently blocks
     the fetch.
   - **Odds API key** — your own account at the-odds-api.com (separate from
     whatever key Matchday's own `config_keys.py`/Vercel env uses). Without
     this, the "Odds API (books)" row just stays blank; nothing else breaks.
   - **Odds API region** — defaults to `eu`, matching what Matchday's own
     `fetch_data.py` already uses. Change to `us`/`uk`/`au` if you want a
     different bookmaker mix.
   - **Kalshi API key** — optional. Left blank, market listing is attempted
     unauthenticated first.
   - **Alert threshold** — points of spread/gap before the panel pulses and
     a notification fires. 0 disables alerts.
3. Visit any polymarket.com page — the panel now always appears bottom-right
   showing a status chip. On a match one of Matchday's covered competitions
   has, it switches to `watching` and fills in; on other pages it stays on
   `idle` or `no match` rather than disappearing, so you can always tell the
   extension is alive. Drag the header to reposition it.

No Chrome Web Store review needed for personal use — "Load unpacked" is the
whole install.

## Before you rely on this: verify the API calls

This was built in a sandbox whose outbound network policy blocks all four
external hosts it needs (`gamma-api.polymarket.com`, `clob.polymarket.com`,
`trading-api.kalshi.com`, `api.the-odds-api.com`) — confirmed via the proxy
status endpoint, not just a site-side block. The one part that's a real,
checked integration rather than a guess is **The Odds API's sport_key
values and query shape** in `offscreen.js` (`ODDS_API_SPORT_KEYS`,
`fetchOddsApiConsensus`) — those are copied directly from `fetch_data.py`'s
already-working `ODDS_URL`/`COMP["odds"]` mapping, not reconstructed from
memory. Everything else — the Gamma API response shape, the CLOB WebSocket
subscribe message, and all of the Kalshi integration (including whether its
market-listing endpoint even allows unauthenticated GETs) — is from
documented public-API knowledge only and marked `VERIFY` at each spot in
`offscreen.js`. Matchday's own `CLAUDE.md` is explicit that provider
integrations should be checked against a live response first, never
assumed; that step could not be done here, so do it before trusting any
number this overlay shows:

1. Open a real Polymarket market page with DevTools' Network tab open.
2. Compare the real requests/responses against `fetchGammaMarket()` and
   `extractClobPrice()`.
3. Do the same for Kalshi against `pollKalshi()` — in particular, confirm
   whether `GET /markets` needs auth at all, and whether `yes_bid`/`yes_ask`
   are really 0–100 already or need scaling.
4. Fix field names/paths as needed — each is isolated to one function plus
   the `*_BASE`/`*_URL` constants at the top of `offscreen.js`.

## Known limitations (v1, not fixed here)

- **Matching is heuristic**, both for Matchday (`matcher.js` token-overlap
  on the market question) and Kalshi (token-overlap on market title).
  Ambiguous cases are reported as "not found" rather than guessed.
- **Assumes one binary market per Polymarket event slug** and that
  `tokenIds[0]` is the "Yes" token. Multi-outcome events aren't handled.
- **Kalshi has no live feed here.** Their WebSocket needs signed-request
  auth (RSA-PSS timestamps) this build doesn't implement, so it's a 5s REST
  poll instead — noticeably less "live" than Polymarket's ticks.
- **ESPN was deliberately left out.** Matchday's own `PROVIDER_COMPLIANCE.md`
  fully excludes ESPN, not just as a link-out — almost certainly a ToS
  restriction on scraping/redistributing their data. Reintroducing it here
  would hit the same problem Matchday's compliance review already avoided.
- Not betting advice.
