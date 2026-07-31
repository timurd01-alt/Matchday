// Offscreen document: the only place in this extension that talks to the
// network. Holds one Polymarket CLOB WebSocket per watched market and one
// set of fetched Matchday competition files, and reports snapshots back to
// the background service worker for relaying to the content script.
//
// NOTE ON VERIFICATION: this session's sandbox has outbound network policy
// that blocks gamma-api.polymarket.com and clob.polymarket.com, so none of
// the endpoint paths / message shapes below could be confirmed against a
// live response before shipping (Matchday's own CLAUDE.md is explicit that
// provider integrations should never assume header/response shapes --
// normally that means "curl it first"; here that step could not be done).
// Everything marked VERIFY is from documented public-API knowledge, not a
// checked live response. Load a Polymarket market page with DevTools open,
// compare the real Network tab requests/responses against these, and adjust
// before trusting any number this produces.

const DEFAULT_DATA_ORIGIN = "https://matchdayterminal.com";
const DEFAULT_COMPS = ["epl", "ucl", "laliga", "seriea", "bundesliga", "ligue1", "wc",
  "nfl", "ncaaf", "nba", "ncaam", "mlb", "nhl"];
const GAMMA_BASE = "https://gamma-api.polymarket.com"; // VERIFY: base host
const CLOB_REST_BASE = "https://clob.polymarket.com";  // VERIFY: base host
const CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"; // VERIFY: path

// slug -> { ws, pollTimer, tokenId, side, comp, match, question, wsGotPrice }
const active = new Map();

async function getConfig() {
  const stored = await chrome.storage.local.get(["dataOrigin", "comps"]);
  return {
    dataOrigin: stored.dataOrigin || DEFAULT_DATA_ORIGIN,
    comps: stored.comps && stored.comps.length ? stored.comps : DEFAULT_COMPS,
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
    report(slug, { type: "MARKET_ERROR", message: `WebSocket failed to open: ${err.message}` });
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
      const price = extractPrice(evt, tokenId);
      if (price != null) {
        state.wsGotPrice = true;
        emitSnapshot(slug, price);
      }
    }
  });
  ws.addEventListener("error", () => {
    report(slug, { type: "MARKET_ERROR", message: "WebSocket error (falling back to polling)." });
  });
  ws.addEventListener("close", () => {
    if (active.has(slug) && active.get(slug).ws === ws) active.get(slug).ws = null;
  });
  state.ws = ws;
}

// VERIFY: field names for both "book" (full snapshot) and "price_change"
// (incremental) messages. Tries a few plausible shapes defensively.
function extractPrice(evt, tokenId) {
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
      if (Number.isFinite(price)) emitSnapshot(slug, price);
    }
  } catch { /* transient -- next poll will retry */ }
  if (active.has(slug)) {
    state.pollTimer = setTimeout(() => pollClobRest(slug, tokenId), 5000);
  }
}

function emitSnapshot(slug, yesPrice) {
  const state = active.get(slug);
  if (!state) return;
  const marketPct = Math.round(yesPrice * 1000) / 10; // price is a 0-1 probability
  const modelPct = state.modelPct;
  const edgePoints = modelPct != null ? Math.round((modelPct - marketPct) * 10) / 10 : null;
  report(slug, {
    type: "MARKET_SNAPSHOT",
    snapshot: {
      question: state.question,
      comp: state.comp,
      home: state.match.home?.name,
      away: state.match.away?.name,
      side: state.side,
      modelPct,
      marketPct,
      edgePoints,
      at: Date.now(),
    },
  });
}

async function watchMarket(slug) {
  if (active.has(slug)) return; // already watching
  active.set(slug, { ws: null, pollTimer: null, tokenId: null, wsGotPrice: false });
  try {
    const { question, tokenIds } = await fetchGammaMarket(slug);
    const { dataOrigin, comps } = await getConfig();
    const competitions = await fetchMatchdayCompetitions(dataOrigin, comps);
    const found = self.MatchdayMatcher.findMatch(question, competitions);
    if (!found) {
      report(slug, { type: "MARKET_ERROR", message: "No matching Matchday fixture found for this market." });
      active.delete(slug);
      return;
    }
    const { comp, match, side } = found;
    const modelPct = modelProbabilityForSide(match, side);
    const tokenId = tokenIds[0]; // VERIFY: assumes tokenIds[0] is the "Yes" outcome token
    const state = active.get(slug);
    Object.assign(state, { question, comp, match, side, modelPct, tokenId });

    openClobSocket(slug, tokenId);
    state.pollTimer = setTimeout(() => pollClobRest(slug, tokenId), 8000);
  } catch (err) {
    report(slug, { type: "MARKET_ERROR", message: err.message || String(err) });
    active.delete(slug);
  }
}

function unwatchMarket(slug) {
  const state = active.get(slug);
  if (!state) return;
  if (state.ws) { try { state.ws.close(); } catch {} }
  if (state.pollTimer) clearTimeout(state.pollTimer);
  active.delete(slug);
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.target !== "offscreen") return;
  if (message.type === "WATCH_MARKET") watchMarket(message.slug);
  if (message.type === "UNWATCH_MARKET") unwatchMarket(message.slug);
});
