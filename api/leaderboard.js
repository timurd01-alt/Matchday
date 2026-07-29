// Matchday verified leaderboard (Vercel + PostgreSQL).
//
// The browser may request a pick lock, but it never supplies authoritative
// totals. Picks are accepted only while the published fixture is UPCOMING and
// before kickoff; results are later read from Matchday's public generated data
// and totals are derived from those server-held rows.

import crypto from "node:crypto";
import { Client } from "pg";

// Generated competition files are published by the GitHub Pages site, not by
// this Vercel function project. Keep the browser origin separate so an
// optional data mirror does not accidentally remove the production site from
// the CORS allowlist.
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
const HANDLE_POOL = [
  "Patrick Mahomes", "Josh Allen", "Nikola Jokic", "A'ja Wilson",
  "Shohei Ohtani", "Aaron Judge", "Connor McDavid", "Alex Morgan",
  "Marta", "Lionel Messi", "Kylian Mbappe", "Jude Bellingham",
];
const DEVICE_RE = /^mdx-[a-z0-9]{12,60}$/;
const MATCH_RE = /^[A-Za-z0-9:_-]{1,100}$/;
let schemaPromise;

function setHeaders(req, res) {
  const origin = String(req.headers.origin || "");
  if (SAFE_ORIGINS.has(origin) || /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Referrer-Policy", "no-referrer");
}

function requestIp(req) {
  return String(req.headers["x-forwarded-for"] || req.socket?.remoteAddress || "unknown")
    .split(",")[0].trim().slice(0, 64);
}

function opaqueKey(value) {
  const secret = process.env.RATE_LIMIT_SECRET || process.env.DATABASE_URL || "matchday";
  return crypto.createHmac("sha256", secret).update(value).digest("hex");
}

function serverHandle(deviceId) {
  const digest = crypto.createHash("sha256").update(`handle:${deviceId}`).digest();
  const name = HANDLE_POOL[digest[0] % HANDLE_POOL.length];
  const tag = 1000 + (digest.readUInt16BE(1) % 9000);
  return `${name} #${tag}`;
}

async function ensureSchema(db) {
  if (!schemaPromise) {
    schemaPromise = (async () => {
      await db.query(`CREATE TABLE IF NOT EXISTS verified_picks(
        device_id VARCHAR(64) NOT NULL,
        comp VARCHAR(16) NOT NULL,
        match_id VARCHAR(100) NOT NULL,
        handle VARCHAR(64) NOT NULL,
        pick CHAR(1) NOT NULL,
        kickoff BIGINT NOT NULL,
        result CHAR(1),
        created_at BIGINT NOT NULL,
        graded_at BIGINT,
        PRIMARY KEY(device_id, comp, match_id)
      )`);
      await db.query(`CREATE TABLE IF NOT EXISTS rate_limits(
        bucket_key VARCHAR(80) PRIMARY KEY,
        bucket_start BIGINT NOT NULL,
        request_count INT NOT NULL
      )`);
      await db.query("CREATE INDEX IF NOT EXISTS verified_picks_graded_idx ON verified_picks(graded_at)");
    })().catch(error => { schemaPromise = null; throw error; });
  }
  return schemaPromise;
}

async function consumeLimit(db, key, windowMs, limit) {
  const start = Math.floor(Date.now() / windowMs) * windowMs;
  const row = await db.query(
    `INSERT INTO rate_limits(bucket_key,bucket_start,request_count) VALUES($1,$2,1)
     ON CONFLICT(bucket_key) DO UPDATE SET
       bucket_start=EXCLUDED.bucket_start,
       request_count=CASE WHEN rate_limits.bucket_start=EXCLUDED.bucket_start
                          THEN rate_limits.request_count+1 ELSE 1 END
     RETURNING request_count`,
    [key, start]
  );
  return Number(row.rows[0]?.request_count || 0) <= limit;
}

async function loadCompetition(comp) {
  if (!ALLOWED_COMPS.has(comp)) return null;
  const response = await fetch(`${PUBLIC_DATA_ORIGIN}/data_${comp}.json`, {
    headers: { Accept: "application/json" }, redirect: "error",
  });
  if (!response.ok) return null;
  return response.json();
}

function findMatch(data, matchId) {
  return (data?.matches || []).find(match => String(match.id) === matchId) || null;
}

async function lockPick(db, body) {
  const deviceId = String(body?.deviceId || "");
  const comp = String(body?.comp || "").toLowerCase();
  const matchId = String(body?.matchId || "");
  const pick = String(body?.pick || "").toLowerCase();
  if (!DEVICE_RE.test(deviceId) || !ALLOWED_COMPS.has(comp) || !MATCH_RE.test(matchId) || !["h", "d", "a"].includes(pick)) {
    return { status: 400, payload: { ok: false, error: "invalid pick" } };
  }
  const data = await loadCompetition(comp);
  const match = findMatch(data, matchId);
  const kickoff = Date.parse(match?.kickoff || "");
  if (!match || match.status !== "UPCOMING" || !Number.isFinite(kickoff) || kickoff <= Date.now() + 30000) {
    return { status: 409, payload: { ok: false, error: "pick window closed" } };
  }
  const handle = serverHandle(deviceId);
  await db.query(
    `INSERT INTO verified_picks(device_id,comp,match_id,handle,pick,kickoff,created_at)
     VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(device_id,comp,match_id) DO NOTHING`,
    [deviceId, comp, matchId, handle, pick, kickoff, Date.now()]
  );
  return { status: 200, payload: { ok: true, handle } };
}

async function syncDevice(db, deviceId) {
  if (!DEVICE_RE.test(deviceId)) return { status: 400, payload: { ok: false, error: "invalid device" } };
  const pending = await db.query(
    "SELECT comp,match_id FROM verified_picks WHERE device_id=$1 AND result IS NULL LIMIT 500",
    [deviceId]
  );
  const datasets = new Map();
  for (const comp of new Set(pending.rows.map(row => row.comp))) datasets.set(comp, await loadCompetition(comp));
  for (const row of pending.rows) {
    const match = findMatch(datasets.get(row.comp), row.match_id);
    const result = match?.status === "FINISHED" ? String(match.score?.winner || "") : "";
    if (["h", "d", "a"].includes(result)) {
      await db.query(
        "UPDATE verified_picks SET result=$1,graded_at=$2 WHERE device_id=$3 AND comp=$4 AND match_id=$5 AND result IS NULL",
        [result, Date.now(), deviceId, row.comp, row.match_id]
      );
    }
  }
  const stats = await db.query(
    `SELECT COUNT(*) FILTER (WHERE result IS NOT NULL)::int AS graded,
            COUNT(*) FILTER (WHERE result=pick)::int AS hits
     FROM verified_picks WHERE device_id=$1`,
    [deviceId]
  );
  return { status: 200, payload: { ok: true, handle: serverHandle(deviceId), ...stats.rows[0] } };
}

async function leaderboard(db, period) {
  const allowedPeriod = ["all", "week", "month"].includes(period) ? period : "all";
  const since = allowedPeriod === "week" ? Date.now() - 7 * 86400000
    : allowedPeriod === "month" ? Date.now() - 30 * 86400000 : 0;
  const minimum = allowedPeriod === "all" ? 10 : 3;
  const rows = await db.query(
    `SELECT MAX(handle) AS handle,
            COUNT(*)::int AS graded,
            COUNT(*) FILTER (WHERE result=pick)::int AS hits
     FROM verified_picks
     WHERE result IS NOT NULL AND graded_at >= $1
     GROUP BY device_id
     HAVING COUNT(*) >= $2
     ORDER BY (COUNT(*) FILTER (WHERE result=pick))::float / COUNT(*) DESC, COUNT(*) DESC
     LIMIT 100`,
    [since, minimum]
  );
  return { ok: true, board: rows.rows.map(row => ({ ...row, streak: 0 })), period: allowedPeriod };
}

export default async function handler(req, res) {
  setHeaders(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (!["GET", "POST"].includes(req.method)) return res.status(405).json({ ok: false, error: "method not allowed" });
  if (Number(req.headers["content-length"] || 0) > 4096) return res.status(413).json({ ok: false, error: "request too large" });
  if (req.method === "POST" && !String(req.headers["content-type"] || "").toLowerCase().startsWith("application/json")) {
    return res.status(415).json({ ok: false, error: "JSON required" });
  }

  const db = new Client({ connectionString: process.env.DATABASE_URL });
  try {
    await db.connect();
    await ensureSchema(db);
    const ipKey = `ip:${opaqueKey(requestIp(req))}`;
    if (!await consumeLimit(db, ipKey, 60000, req.method === "GET" ? 120 : 30)) {
      return res.status(429).json({ ok: false, error: "slow down" });
    }
    if (!await consumeLimit(db, `${ipKey}:day`, 86400000, req.method === "GET" ? 5000 : 500)) {
      return res.status(429).json({ ok: false, error: "daily limit reached" });
    }
    const action = String(req.query.action || "");
    if (action === "leaderboard" && req.method === "GET") {
      return res.status(200).json(await leaderboard(db, String(req.query.period || "all")));
    }
    const body = typeof req.body === "string" ? JSON.parse(req.body) : (req.body || {});
    const deviceId = String(body.deviceId || "");
    if (DEVICE_RE.test(deviceId) && !await consumeLimit(db, `device:${opaqueKey(deviceId)}`, 60000, 10)) {
      return res.status(429).json({ ok: false, error: "slow down" });
    }
    if (DEVICE_RE.test(deviceId) && !await consumeLimit(db, `device:${opaqueKey(deviceId)}:day`, 86400000, 100)) {
      return res.status(429).json({ ok: false, error: "daily limit reached" });
    }
    const result = action === "pick" && req.method === "POST" ? await lockPick(db, body)
      : action === "sync" && req.method === "POST" ? await syncDevice(db, deviceId)
      : { status: 404, payload: { ok: false, error: "unknown action" } };
    return res.status(result.status).json(result.payload);
  } catch (error) {
    console.error("leaderboard request failed", error);
    return res.status(500).json({ ok: false, error: "service unavailable" });
  } finally {
    try { await db.end(); } catch (_) {}
  }
}
