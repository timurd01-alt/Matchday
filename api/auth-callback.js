// Sign-in callback: the provider redirects here with ?code&state.
//
// This path is registered with Google/GitHub, so it must stay query-free in
// its registered form -- hence its own file rather than an `?action=` on
// /api/leaderboard.
//
// It hands the browser a single-use sign-in code in the URL *fragment*, which
// browsers never send to a server. The client trades that code for a session
// token, so the durable credential never appears in a URL, a Referer header
// or a proxy log.

import {
  newClient, ensureSchema, setHeaders, requestIp, opaqueKey, consumeLimit,
  consumeOauthState, exchangeCodeForSubject, findOrCreateAccount, issueSigninCode,
} from "./_accounts.js";

function bounce(res, origin, fragment) {
  res.setHeader("Location", `${origin}/#${fragment}`);
  return res.status(302).end();
}

export default async function handler(req, res) {
  setHeaders(req, res);
  if (req.method !== "GET") return res.status(405).json({ ok: false, error: "method not allowed" });

  const db = newClient();
  try {
    await db.connect();
    await ensureSchema(db);
    if (!await consumeLimit(db, `authcb:${opaqueKey(requestIp(req))}`, 60000, 20)) {
      return res.status(429).json({ ok: false, error: "slow down" });
    }
    // The state row is deleted on read, so a replayed callback URL is inert.
    const state = await consumeOauthState(db, String(req.query.state || ""));
    if (!state) return res.status(400).json({ ok: false, error: "sign-in expired, please try again" });
    if (req.query.error) return bounce(res, state.return_origin, "mdsignin=cancelled");

    const subject = await exchangeCodeForSubject(state.provider, String(req.query.code || ""));
    if (!subject) return bounce(res, state.return_origin, "mdsignin=failed");

    const account = await findOrCreateAccount(db, state.provider, subject);
    if (!account) return bounce(res, state.return_origin, "mdsignin=failed");

    const code = await issueSigninCode(db, account.owner_key, state.device_id);
    return bounce(res, state.return_origin, `mdsignin=${encodeURIComponent(code)}`);
  } catch (error) {
    console.error("auth callback failed", error);
    return res.status(500).json({ ok: false, error: "service unavailable" });
  } finally {
    try { await db.end(); } catch (_) {}
  }
}
