// Offscreen document: the only place in this extension that talks to the
// network. Holds one Polymarket CLOB WebSocket per watched market, polls
// Kalshi and The Odds API for the same fixture, and reports a combined
// snapshot back to the background service worker for relaying to the
// content script.
//
// NOTE ON VERIFICATION: this session's sandbox has outbound network policy
// that blocks gamma-api.polymarket.com, clob.polymarket.com,
// trading-api.kalshi.com, and api.the-odds-api.com alike (confirmed via the
// proxy status endpoint, not just a site-side block), so most of this could
// not be checked against a live response before shipping. The one exception
// is The Odds API's sport_key values and query shape, which are copied
// directly from fetch_data.py's already-working ODDS_URL/COMP["odds"]
// mapping -- that part is real, not guessed. Everything else marked VERIFY
// is from documented public-API knowledge only. Load a real page with
// DevTools open and compare before trusting any number this produces.

const DEFAULT_DATA_ORIGIN = "https://matchdayterminal.com";
const DEFAULT_COMPS = ["epl", "ucl", "laliga", "seriea", "bundesliga", "ligue1", "wc",
  "nfl", "ncaaf", "nba", "ncaam", "mlb", "nhl"];
const GAMMA_BASE = "https://gamma-api.polymarket.com"; // VERIFY: base host
const CLOB_REST_BASE = "https://clob.polymarket.com";  // VERIFY: base host
const CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"; // VERIFY: path
const KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"; // VERIFY: base host + whether market listing needs auth
const ODDS_API_BASE = "https://api.the-odds-api.com/v4";

// Copied from fetch_data.py's COMP[...]["odds"] -- this mapping is already
// live and working in Matchday's own pipeline, not guessed.
const ODDS_API_SPORT_KEYS = {
  epl: "soccer_epl", ucl: "soccer_uefa_champs_league", laliga: "soccer_spain_la_liga",
  seriea: "soccer_italy_serie_a", bundesliga: "soccer_germany_bundesliga",
  ligue1: "soccer_france_ligue_one", wc: "soccer_fifa_world_cup",
  nfl: "americanfootball_nfl", ncaaf: "americanfootball_ncaaf",
  nba: "basketball_nba", ncaam: "basketball_ncaab",
  mlb: "baseball_mlb", nhl: "icehockey_nhl",
};

// slug -> { ws, pollTimers: {}, tokenId, side, comp, match, question, wsGotPrice, values: {...} }
const active = new Map();

async function getConfig() {
  const stored = await chrome.storage.local.get([
    "dataOrigin", "comps", "oddsApiKey", "oddsApiRegion", "kalshiApiKey",
  ]);
  return {
    dataOrigin: stored.dataOrigin || DEFAULT_DATA_ORIGIN,
    comps: stored.comps && stored.comps.length ? stored.comps : DEFAULT_COMPS,
    oddsApiKey: stored.oddsApiKey || "",
    oddsApiRegion: stored.oddsApiRegion || "eu",
    kalshiApiKey: stored.kalshiApiKey || "",
  };
}

function report(slug, message) {
  chrome.runtime.sendMessage({ target: "content", slug, ...message }).catch(() => {});
}

// --- Gamma API: resolve a market page slug to token ids + question text ---
async function fetchGammaMarket(slug) {
  // VERIFY: assumes a single binary market per event slug. Multi-outcome
  // events (e.g. "who wins the league") need /events?slug= and picking the
  // right sub-market out of events[0].markets[] -- not handled here.
  const res = await fetch(`${GAMMA_BASE}/markets?slug=${encodeURIComponent(slug)}`);
  if (!res.ok) throw new Error(`gamma markets lookup failed: HTTP ${res.status}`);
  const rows = await res.json();
  const market = Array.isArray(rows) ? rows[0] : (rows && rows.markets && rows.markets[0]);
  if (!market) throw new Error("no market found for this slug");
  const outcomes = typeof market.outcomes === "string" ? JSON.parse(market.outcomes) : market.outcomes;
  const tokenIds = typeof market.clobTokenIds === "string" ? JSON.parse(market.clobTokenIds) : market.clobTokenIds;
  if (!Array.isArray(tokenIds) || !tokenIds.length) throw new Error("market has no CLOB token ids");
  return { question: market.question || "", outcomes: outcomes || [], tokenIds };
}

// --- Matchday: fetch public competition files and find the matching game ---
async function fetchMatchdayCompetitions(dataOrigin, comps) {
  const settled = await Promise.allSettled(
    comps.map(async comp => {
      const res = await fetch(`${dataOrigin}/data_${comp}.json`);
      if (!res.ok) throw new Error(String(res.status));
      return { comp, data: await res.json() };
    })
  );
  return settled.filter(r => r.status === "fulfilled").map(r => r.value);
}

function modelProbabilityForSide(match, side) {
  const pr = match.prediction || {};
  const dist = pr.blend || pr.adjusted;
  if (dist && dist[side] != null) return Number(dist[side]);
  if (pr.pick === side && pr.confidence != null) return Number(pr.confidence);
  return null; // can't determine without guessing -- report as unknown rather than wrong
}

// --- CLOB: live price for the "yes" token of our side ---
function openClobSocket(slug, tokenId) {
  const state = active.get(slug);
  let ws;
  try {
    ws = new WebSocket(CLOB_WS_URL);
  } catch (err) {
    report(slug, { type: "MARKET_ERROR", message: `Polymarket WebSocket failed to open: ${err.message}` });
    return;
  }
  ws.addEventListener("open", () => {
    // VERIFY: subscribe message shape/field names for the public market channel.
    ws.send(JSON.stringify({ type: "market", assets_ids: [tokenId] }));
  });
  ws.addEventListener("message", (event) => {
    let payload;
    try { payload = JSON.parse(event.data); } catch { return; }
    const events = Array.isArray(payload) ? payload : [payload];
    for (const evt of events) {
      const price = extractClobPrice(evt, tokenId);
      if (price != null) {
        state.wsGotPrice = true;
        setValue(slug, "polymarketPct", Math.round(price * 1000) / 10);
      }
    }
  });
  ws.addEventListener("error", () => {
    report(slug, { type: "MARKET_ERROR", message: "Polymarket WebSocket error (falling back to polling)." });
  });
  ws.addEventListener("close", () => {
    if (active.has(slug) && active.get(slug).ws === ws) active.get(slug).ws = null;
  });
  state.ws = ws;
}

// VERIFY: field names for both "book" (full snapshot) and "price_change"
// (incremental) messages. Tries a few plausible shapes defensively.
function extractClobPrice(evt, tokenId) {
  if (!evt || (evt.asset_id && evt.asset_id !== tokenId)) return null;
  if (evt.price != null) return Number(evt.price);
  if (Array.isArray(evt.bids) && Array.isArray(evt.asks) && evt.bids.length && evt.asks.length) {
    const bestBid = Number(evt.bids[0].price ?? evt.bids[0][0]);
    const bestAsk = Number(evt.asks[0].price ?? evt.asks[0][0]);
    if (Number.isFinite(bestBid) && Number.isFinite(bestAsk)) return (bestBid + bestAsk) / 2;
  }
  return null;
}

async function pollClobRest(slug, tokenId) {
  const state = active.get(slug);
  if (!state || state.wsGotPrice) return; // WS is working, stop polling
  try {
    // VERIFY: REST midpoint endpoint path/response shape.
    const res = await fetch(`${CLOB_REST_BASE}/midpoint?token_id=${encodeURIComponent(tokenId)}`);
    if (res.ok) {
      const body = await res.json();
      const price = Number(body.mid ?? body.midpoint ?? body.price);
      if (Number.isFinite(price)) setValue(slug, "polymarketPct", Math.round(price * 1000) / 10);
    }
  } catch { /* transient -- next poll will retry */ }
  if (active.has(slug)) {
    state.pollTimers.polymarket = setTimeout(() => pollClobRest(slug, tokenId), 5000);
  }
}

// --- Kalshi: search + poll (no WS -- their live feed needs signed-request
// auth this extension doesn't implement; REST polling avoids that entirely) ---
async function pollKalshi(slug, homeTeam, awayTeam, apiKey) {
  const state = active.get(slug);
  if (!state) return;
  try {
    const headers = apiKey ? { Authorization: `Bearer ${apiKey}` } : {}; // VERIFY: header name/scheme
    // VERIFY: whether market listing needs auth at all, and the real query
    // params for finding sports markets (status filter, pagination).
    const res = await fetch(`${KALSHI_BASE}/markets?status=open&limit=200`, { headers });
    if (res.ok) {
      const body = await res.json();
      const markets = body.markets || [];
      const found = markets.find(m => {
        const title = `${m.title || ""} ${m.subtitle || ""}`;
        return self.MatchdayMatcher.teamAppearsIn(homeTeam, title)
          && self.MatchdayMatcher.teamAppearsIn(awayTeam, title);
      });
      if (found) {
        // VERIFY: Kalshi prices are documented as cents (0-100 = probability %).
        const bid = Number(found.yes_bid), ask = Number(found.yes_ask);
        const pct = Number.isFinite(bid) && Number.isFinite(ask) ? (bid + ask) / 2
          : Number.isFinite(found.last_price) ? Number(found.last_price) : null;
        if (pct != null) setValue(slug, "kalshiPct", Math.round(pct * 10) / 10);
      }
    }
  } catch { /* transient -- next poll will retry */ }
  if (active.has(slug)) {
    state.pollTimers.kalshi = setTimeout(() => pollKalshi(slug, homeTeam, awayTeam, apiKey), 5000);
  }
}

// --- The Odds API: bookmaker no-vig consensus (same math as market_snapshots.py) ---
async function fetchOddsApiConsensus(slug, comp, homeTeam, awayTeam, apiKey, region) {
  const sportKey = ODDS_API_SPORT_KEYS[comp];
  if (!sportKey || !apiKey) return;
  try {
    const url = `${ODDS_API_BASE}/sports/${sportKey}/odds/`
      + `?apiKey=${encodeURIComponent(apiKey)}&regions=${encodeURIComponent(region)}`
      + `&markets=h2h&oddsFormat=decimal`;
    const res = await fetch(url);
    if (!res.ok) {
      report(slug, { type: "MARKET_ERROR", message: `The Odds API returned HTTP ${res.status}.` });
      return;
    }
    const events = await res.json();
    const event = findOddsApiEvent(events, homeTeam, awayTeam);
    if (!event) return;
    const pct = noVigTeamProbability(event, homeTeam === event.home_team ? homeTeam : awayTeam);
    if (pct != null) setValue(slug, "oddsApiPct", Math.round(pct * 10) / 10);
  } catch (err) {
    report(slug, { type: "MARKET_ERROR", message: `The Odds API request failed: ${err.message}` });
  }
  const state = active.get(slug);
  if (state) {
    state.pollTimers.oddsApi = setTimeout(
      () => fetchOddsApiConsensus(slug, comp, homeTeam, awayTeam, apiKey, region), 30000
    ); // bookmaker lines move much slower than a live order book -- 30s is plenty and easy on quota
  }
}

function findOddsApiEvent(events, homeTeam, awayTeam) {
  const targetHome = self.MatchdayMatcher.norm(homeTeam);
  const targetAway = self.MatchdayMatcher.norm(awayTeam);
  return (events || []).find(e => {
    const h = self.MatchdayMatcher.norm(e.home_team || "");
    const a = self.MatchdayMatcher.norm(e.away_team || "");
    return (h === targetHome && a === targetAway) || (h === targetAway && a === targetHome);
  }) || null;
}

// No-vig probability for one team, averaged across bookmakers -- same idea
// as market_snapshots.py's no_vig_probabilities(): per-bookmaker implied
// probabilities normalized to remove the overround, then averaged.
function noVigTeamProbability(event, teamName) {
  const perBook = [];
  for (const bookmaker of event.bookmakers || []) {
    const market = (bookmaker.markets || []).find(m => m.key === "h2h");
    if (!market || !Array.isArray(market.outcomes)) continue;
    const implied = market.outcomes.map(o => ({ name: o.name, implied: 1 / Number(o.price) }));
    const total = implied.reduce((sum, o) => sum + (Number.isFinite(o.implied) ? o.implied : 0), 0);
    if (!(total > 0)) continue;
    const outcome = implied.find(o => self.MatchdayMatcher.teamAppearsIn(teamName, o.name));
    if (outcome) perBook.push(outcome.implied / total);
  }
  if (!perBook.length) return null;
  return (perBook.reduce((a, b) => a + b, 0) / perBook.length) * 100;
}

function setValue(slug, key, value) {
  const state = active.get(slug);
  if (!state) return;
  state.values[key] = value;
  emitSnapshot(slug);
}

function emitSnapshot(slug) {
  const state = active.get(slug);
  if (!state) return;
  const { modelPct, polymarketPct, kalshiPct, oddsApiPct } = state.values;
  const marketValues = [polymarketPct, kalshiPct, oddsApiPct].filter(v => v != null);
  const spread = marketValues.length > 1
    ? Math.round((Math.max(...marketValues) - Math.min(...marketValues)) * 10) / 10
    : null;
  report(slug, {
    type: "MARKET_SNAPSHOT",
    snapshot: {
      question: state.question,
      comp: state.comp,
      home: state.match.home?.name,
      away: state.match.away?.name,
      side: state.side,
      modelPct, polymarketPct, kalshiPct, oddsApiPct, spread,
      at: Date.now(),
    },
  });
}

async function watchMarket(slug) {
  if (active.has(slug)) return; // already watching
  active.set(slug, { ws: null, pollTimers: {}, tokenId: null, wsGotPrice: false, values: {} });
  try {
    const { question, tokenIds } = await fetchGammaMarket(slug);
    const config = await getConfig();
    const competitions = await fetchMatchdayCompetitions(config.dataOrigin, config.comps);
    const found = self.MatchdayMatcher.findMatch(question, competitions);
    if (!found) {
      report(slug, { type: "MARKET_ERROR", message: "No matching Matchday fixture found for this market." });
      active.delete(slug);
      return;
    }
    const { comp, match, side } = found;
    const homeTeam = match.home?.name || "";
    const awayTeam = match.away?.name || "";
    const modelPct = modelProbabilityForSide(match, side);
    const tokenId = tokenIds[0]; // VERIFY: assumes tokenIds[0] is the "Yes" outcome token
    const state = active.get(slug);
    Object.assign(state, { question, comp, match, side, tokenId });
    state.values.modelPct = modelPct;

    openClobSocket(slug, tokenId);
    state.pollTimers.polymarket = setTimeout(() => pollClobRest(slug, tokenId), 8000);
    pollKalshi(slug, homeTeam, awayTeam, config.kalshiApiKey);
    if (config.oddsApiKey) {
      fetchOddsApiConsensus(slug, comp, homeTeam, awayTeam, config.oddsApiKey, config.oddsApiRegion);
    } else {
      report(slug, { type: "MARKET_ERROR", message: "No Odds API key set -- bookmaker consensus skipped. Set one in the popup." });
    }
    emitSnapshot(slug);
  } catch (err) {
    report(slug, { type: "MARKET_ERROR", message: err.message || String(err) });
    active.delete(slug);
  }
}

function unwatchMarket(slug) {
  const state = active.get(slug);
  if (!state) return;
  if (state.ws) { try { state.ws.close(); } catch {} }
  for (const timer of Object.values(state.pollTimers)) clearTimeout(timer);
  active.delete(slug);
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.target !== "offscreen") return;
  if (message.type === "WATCH_MARKET") watchMarket(message.slug);
  if (message.type === "UNWATCH_MARKET") unwatchMarket(message.slug);
});
