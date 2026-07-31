// Matchday ROI/edge calculator — personal-only, token-gated.
//
// Compares the model's locked pick confidence against the bookmaker no-vig
// market consensus already published in data_<comp>.json (same "markets"
// object every other view on the site reads — no new data source, no new
// compliance surface). Requires a bearer token matching ROI_ACCESS_TOKEN so
// the computed edge never reaches an unauthenticated request; if the token
// env var isn't set, the endpoint refuses everything rather than opening up.
//
// Prediction-market comparison (Polymarket, Kalshi) is intentionally NOT
// wired up here yet — each row carries an explicit predictionMarket.status
// of "not_connected" rather than a fabricated number. Connecting a real feed
// needs its own provider adapter and a provider_quota.py PROVIDER_SPECS
// entry read off a live response, per CLAUDE.md's provider rules; that's a
// separate follow-up.

import crypto from "node:crypto";

const PUBLIC_SITE_ORIGIN = process.env.PUBLIC_SITE_ORIGIN || "https://matchdayterminal.com";
const PUBLIC_DATA_ORIGIN = process.env.PUBLIC_DATA_ORIGIN || PUBLIC_SITE_ORIGIN;
const ALLOWED_COMPS = new Set([
  "wc", "ucl", "epl", "laliga", "seriea", "bundesliga", "ligue1",
  "nfl", "ncaaf", "ncaam", "nba", "mlb", "nhl",
]);
const SAFE_ORIGINS = new Set([
  PUBLIC_SITE_ORIGIN,
  PUBLIC_DATA_ORIGIN,
  ...(process.env.ALLOWED_ORIGINS || "").split(",").map(v => v.trim()).filter(Boolean),
]);
const PICK_FIELD = { h: "home_pct", d: "draw_pct", a: "away_pct" };

function setHeaders(req, res) {
  const origin = String(req.headers.origin || "");
  if (SAFE_ORIGINS.has(origin) || /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Authorization");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Referrer-Policy", "no-referrer");
}

function digest(value) {
  return crypto.createHash("sha256").update(String(value)).digest();
}

function authorized(req) {
  const configured = process.env.ROI_ACCESS_TOKEN || "";
  if (!configured) return false;
  const match = String(req.headers.authorization || "").match(/^Bearer\s+(.+)$/);
  if (!match) return false;
  const supplied = digest(match[1]);
  const expected = digest(configured);
  return supplied.length === expected.length && crypto.timingSafeEqual(supplied, expected);
}

async function loadCompetition(comp) {
  if (!ALLOWED_COMPS.has(comp)) return null;
  const response = await fetch(`${PUBLIC_DATA_ORIGIN}/data_${comp}.json`, {
    headers: { Accept: "application/json" }, redirect: "error",
  });
  if (!response.ok) return null;
  return response.json();
}

function edgeRow(match) {
  const pr = match.prediction;
  const mk = (match.markets || {})["1x2"];
  if (!pr || !pr.pick || pr.confidence == null || !mk) return null;
  const marketField = PICK_FIELD[pr.pick];
  const marketPct = marketField ? mk[marketField] : null;
  if (marketPct == null || !(marketPct > 0)) return null;
  const modelPct = Number(pr.confidence);
  if (!Number.isFinite(modelPct)) return null;
  const edgePoints = Math.round((modelPct - marketPct) * 10) / 10;
  const roiPct = Math.round(((modelPct / marketPct) - 1) * 1000) / 10;
  return {
    id: match.id,
    kickoff: match.kickoff,
    home: match.home?.name || null,
    away: match.away?.name || null,
    pick: pr.pick,
    pickName: pr.pick_name || null,
    modelPct,
    marketPct,
    edgePoints,
    roiPct,
    predictionMarket: { source: "polymarket", status: "not_connected" },
  };
}

export default async function handler(req, res) {
  setHeaders(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "GET") return res.status(405).json({ ok: false, error: "method not allowed" });
  if (!authorized(req)) return res.status(401).json({ ok: false, error: "unauthorized" });

  const comp = String(req.query.comp || "").toLowerCase();
  if (!ALLOWED_COMPS.has(comp)) return res.status(400).json({ ok: false, error: "unknown competition" });

  const data = await loadCompetition(comp);
  if (!data) return res.status(502).json({ ok: false, error: "competition data unavailable" });

  const rows = (data.matches || [])
    .filter(m => m.status === "UPCOMING")
    .map(edgeRow)
    .filter(Boolean)
    .sort((a, b) => Math.abs(b.edgePoints) - Math.abs(a.edgePoints));

  return res.status(200).json({
    ok: true,
    comp,
    rows,
    note: "marketPct is the bookmaker no-vig consensus already used elsewhere on the site; " +
      "prediction-market (Polymarket/Kalshi) comparison is not connected yet.",
  });
}
