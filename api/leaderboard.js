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
//
// One-time migration for periodic (weekly/monthly) leaderboards — safe to
// run even with existing rows, all new columns default to 0:
//   ALTER TABLE scores
//     ADD COLUMN week_start BIGINT NOT NULL DEFAULT 0,
//     ADD COLUMN week_base_hits INT NOT NULL DEFAULT 0,
//     ADD COLUMN week_base_graded INT NOT NULL DEFAULT 0,
//     ADD COLUMN month_start BIGINT NOT NULL DEFAULT 0,
//     ADD COLUMN month_base_hits INT NOT NULL DEFAULT 0,
//     ADD COLUMN month_base_graded INT NOT NULL DEFAULT 0;

import { Client } from "pg";

const RATE = new Map(); // in-memory rate limiter (per warm instance)

function badWord(s){ return /[<>{}$]/.test(s || ""); } // crude injection/junk guard

// Synchronized period boundaries (same instant for every user, so "this
// week" resets together instead of on a per-user rolling clock). Week =
// 7-day chunks since epoch; month = 30-day chunks (approximate, not
// calendar months, but simple and good enough for a casual leaderboard).
function periodStart(days){
  const ms = days * 86400000;
  return Math.floor(Date.now() / ms) * ms;
}

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
      const period = (req.query.period || "all").toString();
      if (period === "week" || period === "month") {
        const start = periodStart(period === "week" ? 7 : 30);
        const baseHits = period === "week" ? "week_base_hits" : "month_base_hits";
        const baseGraded = period === "week" ? "week_base_graded" : "month_base_graded";
        const startCol = period === "week" ? "week_start" : "month_start";
        // GUARDRAIL 3 (period-scoped): a smaller in-period minimum than the
        // all-time gate, since a single week has far fewer graded picks
        // to draw from than a full history.
        const r = await db.query(
          `SELECT handle, (hits - ${baseHits}) AS hits, (graded - ${baseGraded}) AS graded, streak ` +
          `FROM scores WHERE ${startCol} = $1 AND (graded - ${baseGraded}) >= 3 ` +
          `ORDER BY ((hits - ${baseHits})::float / NULLIF(graded - ${baseGraded}, 0)) DESC, (graded - ${baseGraded}) DESC LIMIT 100`,
          [start]
        );
        return res.status(200).json({ ok: true, board: r.rows, period });
      }
      // GUARDRAIL 3 (all-time): minimum sample to appear
      const r = await db.query(
        "SELECT handle, hits, graded, streak FROM scores WHERE graded >= 10 " +
        "ORDER BY (hits::float / NULLIF(graded,0)) DESC, graded DESC LIMIT 100"
      );
      return res.status(200).json({ ok: true, board: r.rows, period: "all" });
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

      const prev = await db.query(
        "SELECT graded, week_start, week_base_hits, week_base_graded, " +
        "month_start, month_base_hits, month_base_graded FROM scores WHERE device_id=$1",
        [deviceId]
      );
      const row = prev.rows[0];

      // reject graded jumping by an implausible amount vs stored value
      if (row && G - row.graded > 50)
        return res.status(400).json({ ok:false, error:"graded jump too large" });

      // Roll the period baseline forward whenever the synchronized boundary
      // has moved on since this device's last write -- snapshot the
      // CURRENT cumulative hits/graded as the new "zero point", so
      // (hits - base) reads 0 right at the reset and grows through the
      // period from there. A brand-new device gets a fresh baseline too.
      // NOTE: pg returns BIGINT columns as strings, not numbers -- must
      // convert before comparing, or this "===" never matches and the
      // baseline resets on every single write.
      const curWeek = periodStart(7), curMonth = periodStart(30);
      const rowWeekStart = row ? Number(row.week_start) : null;
      const rowMonthStart = row ? Number(row.month_start) : null;
      const weekStart = rowWeekStart === curWeek ? rowWeekStart : curWeek;
      const weekBaseHits = rowWeekStart === curWeek ? row.week_base_hits : H;
      const weekBaseGraded = rowWeekStart === curWeek ? row.week_base_graded : G;
      const monthStart = rowMonthStart === curMonth ? rowMonthStart : curMonth;
      const monthBaseHits = rowMonthStart === curMonth ? row.month_base_hits : H;
      const monthBaseGraded = rowMonthStart === curMonth ? row.month_base_graded : G;

      await db.query(
        "INSERT INTO scores(device_id,handle,hits,graded,streak,updated," +
        "week_start,week_base_hits,week_base_graded,month_start,month_base_hits,month_base_graded) " +
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) " +
        "ON CONFLICT(device_id) DO UPDATE SET handle=$2,hits=$3,graded=$4,streak=$5,updated=$6," +
        "week_start=$7,week_base_hits=$8,week_base_graded=$9,month_start=$10,month_base_hits=$11,month_base_graded=$12",
        [deviceId, handle.slice(0,24), H, G, S, now,
         weekStart, weekBaseHits, weekBaseGraded, monthStart, monthBaseHits, monthBaseGraded]
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
