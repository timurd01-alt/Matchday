// Matchday verified leaderboard (Vercel + PostgreSQL).
//
// The browser may request a pick lock, but it never supplies authoritative
// totals. Picks are accepted only while the published fixture is UPCOMING and
// before kickoff; results are later read from Matchday's public generated data
// and totals are derived from those server-held rows.
//
// Rows are owned by either an anonymous device id or, once someone signs in,
// their account's stable owner key -- see `_accounts.js` for why the two share
// a column and how anonymous history gets claimed.

import {
  PUBLIC_DATA_ORIGIN, HANDLE_POOL, collegeHandle, DEVICE_RE, SESSION_TTL_MS,
  PROVIDERS, providerConfigured, newClient, ensureSchema, setHeaders, requestIp,
  opaqueKey, consumeLimit, accountForToken, createSession, destroySession,
  redeemSigninCode, claimDevicePicks, reshuffleAccountHandle,
  deleteAccount, purgeDormantAccounts,
} from "./_accounts.js";
import crypto from "node:crypto";

const ALLOWED_COMPS = new Set(["ncaaf", "ncaam"]);
const MATCH_RE = /^[A-Za-z0-9:_-]{1,100}$/;

// Anonymous visitors still get a stable name derived from their device id.
// Signed-in accounts carry a real handle row instead, so this is only the
// pre-account fallback.
function serverHandle(deviceId) {
  const digest = crypto.createHash("sha256").update(`handle:${deviceId}`).digest();
  const name = HANDLE_POOL[digest[0] % HANDLE_POOL.length];
  const tag = 1000 + (digest.readUInt16BE(1) % 9000);
  return `${name} #${tag}`;
}

// Who owns the rows this request touches: the session if there is a valid one,
// otherwise the anonymous device id the browser presented.
async function resolveOwner(db, body) {
  const account = await accountForToken(db, body?.token);
  if (account) {
    return { ownerId: account.owner_key, handle: collegeHandle(account.handle), account };
  }
  const deviceId = String(body?.deviceId || "");
  if (!DEVICE_RE.test(deviceId)) return null;
  return { ownerId: deviceId, handle: serverHandle(deviceId), account: null };
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
  const owner = await resolveOwner(db, body);
  const comp = String(body?.comp || "").toLowerCase();
  const matchId = String(body?.matchId || "");
  const pick = String(body?.pick || "").toLowerCase();
  if (!owner || !ALLOWED_COMPS.has(comp) || !MATCH_RE.test(matchId) || !["h", "d", "a"].includes(pick)) {
    return { status: 400, payload: { ok: false, error: "invalid pick" } };
  }
  const data = await loadCompetition(comp);
  const match = findMatch(data, matchId);
  const kickoff = Date.parse(match?.kickoff || "");
  if (!match || match.status !== "UPCOMING" || !Number.isFinite(kickoff) || kickoff <= Date.now() + 30000) {
    return { status: 409, payload: { ok: false, error: "pick window closed" } };
  }
  // A pick may be changed until kickoff; the window check above and the
  // kickoff guard on the update both refuse a change once the game is on.
  await db.query(
    `INSERT INTO verified_picks(device_id,comp,match_id,handle,pick,kickoff,created_at)
     VALUES($1,$2,$3,$4,$5,$6,$7)
     ON CONFLICT(device_id,comp,match_id) DO UPDATE
       SET pick=EXCLUDED.pick, handle=EXCLUDED.handle, created_at=EXCLUDED.created_at
       WHERE verified_picks.result IS NULL AND verified_picks.kickoff > EXCLUDED.created_at + 30000`,
    [owner.ownerId, comp, matchId, owner.handle, pick, kickoff, Date.now()]
  );
  return { status: 200, payload: { ok: true, handle: owner.handle, signedIn: !!owner.account } };
}

async function gradeAndCount(db, owner) {
  const pending = await db.query(
    "SELECT comp,match_id FROM verified_picks WHERE device_id=$1 AND result IS NULL LIMIT 500",
    [owner.ownerId]
  );
  const datasets = new Map();
  for (const comp of new Set(pending.rows.map(row => row.comp))) datasets.set(comp, await loadCompetition(comp));
  for (const row of pending.rows) {
    const match = findMatch(datasets.get(row.comp), row.match_id);
    const result = match?.status === "FINISHED" ? String(match.score?.winner || "") : "";
    if (["h", "d", "a"].includes(result)) {
      await db.query(
        "UPDATE verified_picks SET result=$1,graded_at=$2 WHERE device_id=$3 AND comp=$4 AND match_id=$5 AND result IS NULL",
        [result, Date.now(), owner.ownerId, row.comp, row.match_id]
      );
    }
  }
  const stats = await db.query(
    `SELECT COUNT(*) FILTER (WHERE result IS NOT NULL)::int AS graded,
            COUNT(*) FILTER (WHERE result=pick)::int AS hits
     FROM verified_picks WHERE device_id=$1`,
    [owner.ownerId]
  );
  return stats.rows[0];
}

async function syncOwner(db, body) {
  const owner = await resolveOwner(db, body);
  if (!owner) return { status: 400, payload: { ok: false, error: "invalid device" } };
  const stats = await gradeAndCount(db, owner);
  return {
    status: 200,
    payload: {
      ok: true,
      handle: owner.handle,
      signedIn: !!owner.account,
      canReshuffle: owner.account ? !owner.account.reshuffled : false,
      ...stats,
    },
  };
}

// Trades the single-use code from the sign-in redirect for a session token,
// and folds the browser's anonymous history into the account it just proved.
async function exchangeSignin(db, body) {
  const redeemed = await redeemSigninCode(db, body?.code);
  if (!redeemed) return { status: 400, payload: { ok: false, error: "sign-in expired, please try again" } };
  const account = await db.query("SELECT * FROM accounts WHERE owner_key=$1", [redeemed.owner_key]);
  if (!account.rows[0]) return { status: 400, payload: { ok: false, error: "sign-in expired, please try again" } };
  const row = account.rows[0];
  // The device id recorded when sign-in started is authoritative; a device id
  // supplied now is accepted only as a fallback for the same browser.
  const deviceId = redeemed.device_id || String(body?.deviceId || "");
  const claimed = await claimDevicePicks(db, row.owner_key, deviceId, row.handle);
  const token = await createSession(db, row.owner_key);
  const stats = await gradeAndCount(db, { ownerId: row.owner_key });
  return {
    status: 200,
    payload: {
      ok: true, token, handle: collegeHandle(row.handle), signedIn: true,
      canReshuffle: !row.reshuffled, claimed,
      expiresAt: Date.now() + SESSION_TTL_MS, ...stats,
    },
  };
}

async function sessionState(db, body) {
  const account = await accountForToken(db, body?.token);
  if (!account) return { status: 200, payload: { ok: true, signedIn: false } };
  const stats = await gradeAndCount(db, { ownerId: account.owner_key });
  return {
    status: 200,
    payload: {
      ok: true, signedIn: true, handle: collegeHandle(account.handle),
      canReshuffle: !account.reshuffled, ...stats,
    },
  };
}

async function reshuffle(db, body) {
  const account = await accountForToken(db, body?.token);
  if (!account) return { status: 401, payload: { ok: false, error: "sign in first" } };
  const handle = await reshuffleAccountHandle(db, account.owner_key);
  if (!handle) return { status: 409, payload: { ok: false, error: "reshuffle already used" } };
  return { status: 200, payload: { ok: true, handle, canReshuffle: false } };
}

// Deleting requires the session, not just the account id: the person doing it
// must be the person signed in. The response carries no `token`, so the client
// drops its own copy and there is nothing left to present.
async function removeAccount(db, body) {
  const account = await accountForToken(db, body?.token);
  if (!account) return { status: 401, payload: { ok: false, error: "sign in first" } };
  const removed = await deleteAccount(db, account.owner_key);
  if (!removed) return { status: 409, payload: { ok: false, error: "account already gone" } };
  return { status: 200, payload: { ok: true, deleted: true, signedIn: false } };
}

async function leaderboard(db, period) {
  const allowedPeriod = ["all", "week", "month"].includes(period) ? period : "all";
  const since = allowedPeriod === "week" ? Date.now() - 7 * 86400000
    : allowedPeriod === "month" ? Date.now() - 30 * 86400000 : 0;
  const minimum = allowedPeriod === "all" ? 10 : 3;
  // An account's live handle wins over the one stamped on the row, so a
  // reshuffle renames the player everywhere at once.
  const rows = await db.query(
    `SELECT COALESCE(MAX(a.handle), MAX(v.handle)) AS handle,
            BOOL_OR(a.owner_key IS NOT NULL) AS verified,
            COUNT(*)::int AS graded,
            COUNT(*) FILTER (WHERE v.result=v.pick)::int AS hits
     FROM verified_picks v
     LEFT JOIN accounts a ON a.owner_key = v.device_id
     WHERE v.result IS NOT NULL AND v.graded_at >= $1 AND v.comp IN ('ncaaf','ncaam')
     GROUP BY v.device_id
     HAVING COUNT(*) >= $2
     ORDER BY (COUNT(*) FILTER (WHERE v.result=v.pick))::float / COUNT(*) DESC, COUNT(*) DESC
     LIMIT 100`,
    [since, minimum]
  );
  return { ok: true, board: rows.rows.map(row => ({ ...row, handle: collegeHandle(row.handle), streak: 0 })), period: allowedPeriod };
}

// What the community is picking: per-match counts for one competition's games
// that have not kicked off yet (plus those in the last day, so a finished
// game's split stays readable). Counts only -- no identities.
async function consensus(db, comp) {
  if (!ALLOWED_COMPS.has(comp)) return { ok: false, error: "invalid competition" };
  const rows = await db.query(
    `SELECT match_id,
            COUNT(*) FILTER (WHERE pick='h')::int AS h,
            COUNT(*) FILTER (WHERE pick='d')::int AS d,
            COUNT(*) FILTER (WHERE pick='a')::int AS a
     FROM verified_picks
     WHERE comp=$1 AND kickoff >= $2
     GROUP BY match_id`,
    [comp, Date.now() - 86400000]
  );
  const games = {};
  for (const row of rows.rows) games[row.match_id] = { h: row.h, d: row.d, a: row.a };
  return { ok: true, comp, games };
}

// A light feed of what people did: recent locked picks, and yesterday's
// records for anyone who had at least three picks graded that day. Handles are
// the assigned, pseudonymous ones already shown on the leaderboard.
async function activity(db, comp) {
  if (!ALLOWED_COMPS.has(comp)) return { ok: false, error: "invalid competition" };
  const picks = await db.query(
    `SELECT COALESCE(a.handle, v.handle) AS handle, v.match_id, v.pick, v.created_at
     FROM verified_picks v LEFT JOIN accounts a ON a.owner_key = v.device_id
     WHERE v.comp=$1 AND v.created_at >= $2
     ORDER BY v.created_at DESC LIMIT 25`,
    [comp, Date.now() - 7 * 86400000]
  );
  const dayStart = new Date(); dayStart.setUTCHours(0, 0, 0, 0);
  const since = dayStart.getTime() - 86400000;
  const days = await db.query(
    `SELECT COALESCE(MAX(a.handle), MAX(v.handle)) AS handle,
            COUNT(*) FILTER (WHERE v.result=v.pick)::int AS wins,
            COUNT(*) FILTER (WHERE v.result<>v.pick)::int AS losses,
            MAX(v.graded_at) AS at
     FROM verified_picks v LEFT JOIN accounts a ON a.owner_key = v.device_id
     WHERE v.comp=$1 AND v.result IS NOT NULL AND v.graded_at >= $2 AND v.graded_at < $3
     GROUP BY v.device_id HAVING COUNT(*) >= 3
     ORDER BY COUNT(*) FILTER (WHERE v.result=v.pick) DESC LIMIT 5`,
    [comp, since, dayStart.getTime()]
  );
  const items = [
    ...picks.rows.map(row => ({ kind: "pick", handle: collegeHandle(row.handle), matchId: row.match_id, pick: row.pick, at: Number(row.created_at) })),
    ...days.rows.map(row => ({ kind: "day", handle: collegeHandle(row.handle), wins: row.wins, losses: row.losses, at: Number(row.at) })),
  ].sort((x, y) => y.at - x.at).slice(0, 25);
  return { ok: true, comp, items };
}

export default async function handler(req, res) {
  setHeaders(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (!["GET", "POST"].includes(req.method)) return res.status(405).json({ ok: false, error: "method not allowed" });
  if (Number(req.headers["content-length"] || 0) > 4096) return res.status(413).json({ ok: false, error: "request too large" });
  if (req.method === "POST" && !String(req.headers["content-type"] || "").toLowerCase().startsWith("application/json")) {
    return res.status(415).json({ ok: false, error: "JSON required" });
  }

  const db = newClient();
  try {
    await db.connect();
    await ensureSchema(db);
    // Reads and writes are counted separately. They used to share one bucket
    // with a lower ceiling for writes, so the page's own background reads
    // (consensus, activity and the leaderboard, every minute) used up the
    // budget and every pick after that was refused with "daily limit reached".
    const ipKey = `ip:${opaqueKey(requestIp(req))}:${req.method === "GET" ? "read" : "write"}`;
    if (!await consumeLimit(db, ipKey, 60000, req.method === "GET" ? 120 : 30)) {
      return res.status(429).json({ ok: false, error: "slow down" });
    }
    if (!await consumeLimit(db, `${ipKey}:day`, 86400000, req.method === "GET" ? 5000 : 500)) {
      return res.status(429).json({ ok: false, error: "daily limit reached" });
    }
    // The retention sweep rides on the same durable counter the rate limiter
    // uses, so exactly one request a day performs it and the rest skip. A
    // failed sweep must never fail the request that happened to trigger it --
    // the visitor asked for a leaderboard, not for housekeeping.
    if (await consumeLimit(db, "retention:daily", 86400000, 1)) {
      try { await purgeDormantAccounts(db); }
      catch (error) { console.error("retention sweep failed", error); }
    }
    const action = String(req.query.action || "");
    if (action === "leaderboard" && req.method === "GET") {
      return res.status(200).json(await leaderboard(db, String(req.query.period || "all")));
    }
    if ((action === "consensus" || action === "activity") && req.method === "GET") {
      const comp = String(req.query.comp || "").toLowerCase();
      const payload = action === "consensus" ? await consensus(db, comp) : await activity(db, comp);
      res.setHeader("Cache-Control", "public, s-maxage=60, stale-while-revalidate=120");
      return res.status(payload.ok ? 200 : 400).json(payload);
    }
    if (action === "providers" && req.method === "GET") {
      return res.status(200).json({
        ok: true,
        providers: Object.keys(PROVIDERS).filter(providerConfigured),
      });
    }
    const body = typeof req.body === "string" ? JSON.parse(req.body) : (req.body || {});
    // Per-identity throttles, on whichever identity the caller presented.
    const deviceId = String(body.deviceId || "");
    if (DEVICE_RE.test(deviceId) && !await consumeLimit(db, `device:${opaqueKey(deviceId)}`, 60000, 10)) {
      return res.status(429).json({ ok: false, error: "slow down" });
    }
    if (DEVICE_RE.test(deviceId) && !await consumeLimit(db, `device:${opaqueKey(deviceId)}:day`, 86400000, 100)) {
      return res.status(429).json({ ok: false, error: "daily limit reached" });
    }
    const token = String(body.token || "");
    if (token && !await consumeLimit(db, `session:${opaqueKey(token)}`, 60000, 20)) {
      return res.status(429).json({ ok: false, error: "slow down" });
    }
    if (token && !await consumeLimit(db, `session:${opaqueKey(token)}:day`, 86400000, 200)) {
      return res.status(429).json({ ok: false, error: "daily limit reached" });
    }
    if (action === "signout" && req.method === "POST") {
      await destroySession(db, token);
      return res.status(200).json({ ok: true, signedIn: false });
    }
    const result = action === "pick" && req.method === "POST" ? await lockPick(db, body)
      : action === "sync" && req.method === "POST" ? await syncOwner(db, body)
      : action === "session-exchange" && req.method === "POST" ? await exchangeSignin(db, body)
      : action === "session" && req.method === "POST" ? await sessionState(db, body)
      : action === "reshuffle" && req.method === "POST" ? await reshuffle(db, body)
      : action === "delete-account" && req.method === "POST" ? await removeAccount(db, body)
      : { status: 404, payload: { ok: false, error: "unknown action" } };
    return res.status(result.status).json(result.payload);
  } catch (error) {
    console.error("leaderboard request failed", error);
    return res.status(500).json({ ok: false, error: "service unavailable" });
  } finally {
    try { await db.end(); } catch (_) {}
  }
}
