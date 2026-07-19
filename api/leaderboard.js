// Matchday Leaderboard — serverless function (Vercel + hosted Postgres)
// Deployed as /api/leaderboard via Vercel's zero-config /api convention.
// Two routes on one function via ?action=  (score | leaderboard)
//
// ENV you set in the Vercel dashboard:
//   DATABASE_URL   — your hosted Postgres connection string (use the
//                    POOLED one — serverless functions open many short-lived
//                    connections and a free-tier Postgres has a low direct
//                    connection cap)
//
// Table (run once in your DB console):
//   CREATE TABLE scores(
//     device_id TEXT PRIMARY KEY,
//     handle    TEXT NOT NULL,
//     hits      INT  NOT NULL,
//     graded    INT  NOT NULL,
//     streak    INT  NOT NULL,
//     updated   BIGINT NOT NULL
//   );

import { Client } from "pg";

const RATE = new Map(); // in-memory rate limiter (per warm instance)

function badWord(s){ return /[<>{}$]/.test(s || ""); } // crude injection/junk guard

export default async function handler(req, res){
  // CORS so the app (any origin) can call it
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  const db = new Client({ connectionString: process.env.DATABASE_URL });
  await db.connect();
  try {
    const action = (req.query.action || "").toString();

    if (action === "leaderboard") {
      // GUARDRAIL 3: minimum sample to appear
      const r = await db.query(
        "SELECT handle, hits, graded, streak FROM scores WHERE graded >= 10 " +
        "ORDER BY (hits::float / NULLIF(graded,0)) DESC, graded DESC LIMIT 100"
      );
      return res.status(200).json({ ok: true, board: r.rows });
    }

    if (action === "score" && req.method === "POST") {
      const b = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
      const { deviceId, handle, hits, graded, streak } = b || {};

      // basic validation
      if (!deviceId || !handle) return res.status(400).json({ ok:false, error:"missing id/handle" });
      if (badWord(handle) || handle.length > 24) return res.status(400).json({ ok:false, error:"bad handle" });
      const H = parseInt(hits,10), G = parseInt(graded,10), S = parseInt(streak,10);

      // GUARDRAIL 1: server-side sanity — reject the physically impossible
      if ([H,G,S].some(n => Number.isNaN(n) || n < 0)) return res.status(400).json({ ok:false, error:"bad numbers" });
      if (H > G) return res.status(400).json({ ok:false, error:"hits>graded" });
      if (S > G) return res.status(400).json({ ok:false, error:"streak>graded" });
      if (G > 5000) return res.status(400).json({ ok:false, error:"implausible volume" });

      // GUARDRAIL 2: rate limit per device (one post / 60s per warm instance)
      const now = Date.now(), last = RATE.get(deviceId) || 0;
      if (now - last < 60000) return res.status(429).json({ ok:false, error:"slow down" });
      RATE.set(deviceId, now);

      // reject graded jumping by an implausible amount vs stored value
      const prev = await db.query("SELECT graded FROM scores WHERE device_id=$1", [deviceId]);
      if (prev.rows[0] && G - prev.rows[0].graded > 50)
        return res.status(400).json({ ok:false, error:"graded jump too large" });

      await db.query(
        "INSERT INTO scores(device_id,handle,hits,graded,streak,updated) VALUES($1,$2,$3,$4,$5,$6) " +
        "ON CONFLICT(device_id) DO UPDATE SET handle=$2,hits=$3,graded=$4,streak=$5,updated=$6",
        [deviceId, handle.slice(0,24), H, G, S, now]
      );
      return res.status(200).json({ ok: true });
    }

    return res.status(404).json({ ok:false, error:"unknown action" });
  } catch (e) {
    return res.status(500).json({ ok:false, error:String(e).slice(0,120) });
  } finally {
    await db.end();
  }
}
