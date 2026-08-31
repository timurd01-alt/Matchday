// Matchday accounts (shared by /api/auth, /api/auth-callback, /api/leaderboard).
//
// Why accounts exist: identity used to be `localStorage['matchday.device']`
// alone, so clearing a browser or picking up a second device produced a new
// person with a new handle and an empty record. An account is a durable row
// that a third-party sign-in maps onto, so the handle and the pick history
// survive the browser.
//
// The site (GitHub Pages) and this API (Vercel) are different origins, so a
// session cookie would be a third-party cookie and blocked by default in
// several browsers. Sessions are therefore bearer tokens the client stores
// itself. Losing the token is harmless -- signing in again returns the same
// account, which is the whole point.

import crypto from "node:crypto";
import { Client } from "pg";

export const PUBLIC_SITE_ORIGIN = process.env.PUBLIC_SITE_ORIGIN || "https://matchdayterminal.com";
export const PUBLIC_DATA_ORIGIN = process.env.PUBLIC_DATA_ORIGIN || PUBLIC_SITE_ORIGIN;
export const SAFE_ORIGINS = new Set([
  PUBLIC_SITE_ORIGIN,
  PUBLIC_DATA_ORIGIN,
  ...(process.env.ALLOWED_ORIGINS || "").split(",").map(v => v.trim()).filter(Boolean),
]);

// Handles stay assigned, never free text: a public board with user-typed names
// is an open door for offensive ones, and moderation is not a thing we staff.
// College names only, to match what the site covers. These are retired college
// greats rather than current players: a handle assigned at random to a stranger
// should not read as a living student athlete's account, and a list of current
// names would need rewriting every year as rosters turn over.
export const HANDLE_POOL = [
  "Herschel Walker", "Doug Flutie", "Charlie Ward", "Vince Young",
  "Bo Jackson", "Tim Tebow", "Pete Maravich", "Christian Laettner",
  "Danny Manning", "Grant Hill", "Tyler Hansbrough", "Bill Bradley",
];

export const DEVICE_RE = /^mdx-[a-z0-9]{12,60}$/;
export const OWNER_RE = /^acct-[0-9a-f]{24}$/;
export const TOKEN_RE = /^[A-Za-z0-9_-]{40,90}$/;
export const SESSION_TTL_MS = 180 * 86400000;
const SIGNIN_CODE_TTL_MS = 120000;
const OAUTH_STATE_TTL_MS = 600000;

// Scopes are the narrowest that still identify a returning user, because a
// scope is a promise about what we look at, not merely about what we keep.
// `openid` yields the subject id alone; adding `email` would put an address in
// the id_token that this code reads past and discards -- data we asked for,
// were trusted with, and had no use for. GitHub needs no scope at all (an
// OAuth app may read its own user's id unscoped), so it asks for none and its
// consent screen says so.
export const PROVIDERS = {
  google: {
    authorize: "https://accounts.google.com/o/oauth2/v2/auth",
    tokenUrl: "https://oauth2.googleapis.com/token",
    scope: "openid",
    idEnv: "GOOGLE_CLIENT_ID",
    secretEnv: "GOOGLE_CLIENT_SECRET",
  },
  github: {
    authorize: "https://github.com/login/oauth/authorize",
    tokenUrl: "https://github.com/login/oauth/access_token",
    scope: "",
    idEnv: "GITHUB_CLIENT_ID",
    secretEnv: "GITHUB_CLIENT_SECRET",
  },
};

export function providerConfigured(name) {
  const provider = PROVIDERS[name];
  return !!(provider && process.env[provider.idEnv] && process.env[provider.secretEnv]);
}

// Google rejects a registered redirect URI that carries a query string, so the
// callback lives at its own clean path rather than behind `?action=`.
export function redirectUri() {
  const base = process.env.API_ORIGIN || "https://matchday-lake-omega.vercel.app";
  return process.env.OAUTH_REDIRECT_URI || `${base}/api/auth-callback`;
}

export function newClient() {
  return new Client({ connectionString: process.env.DATABASE_URL });
}

export function setHeaders(req, res) {
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

export function requestIp(req) {
  return String(req.headers["x-forwarded-for"] || req.socket?.remoteAddress || "unknown")
    .split(",")[0].trim().slice(0, 64);
}

export function opaqueKey(value) {
  // Rate-limit buckets are keyed by an HMAC of an identifier -- an IP, a device
  // id, a session token -- so the table never stores the identifier itself. That
  // only holds while the key is secret. With a literal fallback ("matchday"),
  // anyone could compute the bucket key for an IP or device that is not theirs
  // and spend that victim's allowance for them, locking them out with the
  // rate limiter working exactly as designed.
  //
  // There is no safe default, so there is no default. DATABASE_URL is an
  // acceptable derivation because this module cannot function without it
  // anyway; if neither is present the request fails loudly rather than
  // silently using a key an attacker already knows.
  const secret = process.env.RATE_LIMIT_SECRET || process.env.DATABASE_URL;
  if (!secret) {
    throw new Error("RATE_LIMIT_SECRET or DATABASE_URL must be set to key rate limits");
  }
  return crypto.createHmac("sha256", secret).update(value).digest("hex");
}

export async function consumeLimit(db, key, windowMs, limit) {
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

let schemaPromise;
export async function ensureSchema(db) {
  if (!schemaPromise) {
    schemaPromise = (async () => {
      // device_id holds either an anonymous `mdx-` id or an account's stable
      // `acct-` owner key. Keeping one column means signing in migrates rows
      // in place instead of forcing a primary-key rewrite, and two devices on
      // one account collapse onto the same rows for free.
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
      await db.query(`CREATE TABLE IF NOT EXISTS accounts(
        owner_key VARCHAR(64) PRIMARY KEY,
        handle VARCHAR(64) NOT NULL UNIQUE,
        reshuffled BOOLEAN NOT NULL DEFAULT FALSE,
        created_at BIGINT NOT NULL,
        last_seen_at BIGINT NOT NULL
      )`);
      // No email, no name, no avatar: the provider's opaque subject id is all
      // that is needed to recognise a returning user, so it is all we keep.
      await db.query(`CREATE TABLE IF NOT EXISTS account_identities(
        provider VARCHAR(16) NOT NULL,
        subject VARCHAR(128) NOT NULL,
        owner_key VARCHAR(64) NOT NULL REFERENCES accounts(owner_key) ON DELETE CASCADE,
        created_at BIGINT NOT NULL,
        PRIMARY KEY(provider, subject)
      )`);
      await db.query(`CREATE TABLE IF NOT EXISTS sessions(
        token_hash CHAR(64) PRIMARY KEY,
        owner_key VARCHAR(64) NOT NULL REFERENCES accounts(owner_key) ON DELETE CASCADE,
        created_at BIGINT NOT NULL,
        expires_at BIGINT NOT NULL
      )`);
      await db.query(`CREATE TABLE IF NOT EXISTS oauth_states(
        state_hash CHAR(64) PRIMARY KEY,
        provider VARCHAR(16) NOT NULL,
        return_origin VARCHAR(200) NOT NULL,
        device_id VARCHAR(64),
        expires_at BIGINT NOT NULL
      )`);
      // The browser never receives its session token over a redirect URL --
      // it receives a single-use code it trades for one, so the durable
      // credential never lands in history, logs or a Referer header.
      await db.query(`CREATE TABLE IF NOT EXISTS signin_codes(
        code_hash CHAR(64) PRIMARY KEY,
        owner_key VARCHAR(64) NOT NULL REFERENCES accounts(owner_key) ON DELETE CASCADE,
        device_id VARCHAR(64),
        expires_at BIGINT NOT NULL
      )`);
    })().catch(error => { schemaPromise = null; throw error; });
  }
  return schemaPromise;
}

const sha256 = value => crypto.createHash("sha256").update(value).digest("hex");
const randomToken = () => crypto.randomBytes(32).toString("base64url");

function drawHandle() {
  const name = HANDLE_POOL[crypto.randomInt(HANDLE_POOL.length)];
  return `${name} #${1000 + crypto.randomInt(9000)}`;
}

export async function findOrCreateAccount(db, provider, subject) {
  const now = Date.now();
  const existing = await db.query(
    `SELECT a.* FROM accounts a JOIN account_identities i ON i.owner_key=a.owner_key
     WHERE i.provider=$1 AND i.subject=$2`,
    [provider, subject]
  );
  if (existing.rows[0]) {
    await db.query("UPDATE accounts SET last_seen_at=$1 WHERE owner_key=$2", [now, existing.rows[0].owner_key]);
    return existing.rows[0];
  }
  const ownerKey = `acct-${crypto.randomBytes(12).toString("hex")}`;
  let account = null;
  for (let attempt = 0; attempt < 12 && !account; attempt += 1) {
    const inserted = await db.query(
      `INSERT INTO accounts(owner_key,handle,created_at,last_seen_at) VALUES($1,$2,$3,$3)
       ON CONFLICT(handle) DO NOTHING RETURNING *`,
      [ownerKey, drawHandle(), now]
    );
    account = inserted.rows[0] || null;
  }
  if (!account) return null;
  // Two tabs finishing sign-in at once: whoever loses the identity race keeps
  // the account that actually owns the identity row.
  const claimed = await db.query(
    `INSERT INTO account_identities(provider,subject,owner_key,created_at) VALUES($1,$2,$3,$4)
     ON CONFLICT(provider,subject) DO NOTHING RETURNING owner_key`,
    [provider, subject, account.owner_key, now]
  );
  if (!claimed.rows[0]) {
    await db.query("DELETE FROM accounts WHERE owner_key=$1", [account.owner_key]);
    const winner = await db.query(
      `SELECT a.* FROM accounts a JOIN account_identities i ON i.owner_key=a.owner_key
       WHERE i.provider=$1 AND i.subject=$2`,
      [provider, subject]
    );
    return winner.rows[0] || null;
  }
  return account;
}

export async function issueSigninCode(db, ownerKey, deviceId) {
  const code = randomToken();
  await db.query("DELETE FROM signin_codes WHERE expires_at < $1", [Date.now()]);
  await db.query(
    "INSERT INTO signin_codes(code_hash,owner_key,device_id,expires_at) VALUES($1,$2,$3,$4)",
    [sha256(code), ownerKey, DEVICE_RE.test(String(deviceId || "")) ? deviceId : null, Date.now() + SIGNIN_CODE_TTL_MS]
  );
  return code;
}

export async function redeemSigninCode(db, code) {
  const row = await db.query(
    "DELETE FROM signin_codes WHERE code_hash=$1 AND expires_at > $2 RETURNING owner_key,device_id",
    [sha256(String(code || "")), Date.now()]
  );
  return row.rows[0] || null;
}

export async function createSession(db, ownerKey) {
  const token = randomToken();
  const now = Date.now();
  await db.query("DELETE FROM sessions WHERE expires_at < $1", [now]);
  await db.query(
    "INSERT INTO sessions(token_hash,owner_key,created_at,expires_at) VALUES($1,$2,$3,$4)",
    [sha256(token), ownerKey, now, now + SESSION_TTL_MS]
  );
  return token;
}

export async function accountForToken(db, token) {
  const value = String(token || "");
  if (!TOKEN_RE.test(value)) return null;
  const row = await db.query(
    `SELECT a.* FROM sessions s JOIN accounts a ON a.owner_key=s.owner_key
     WHERE s.token_hash=$1 AND s.expires_at > $2`,
    [sha256(value), Date.now()]
  );
  if (row.rows[0]) {
    await db.query("UPDATE accounts SET last_seen_at=$1 WHERE owner_key=$2", [Date.now(), row.rows[0].owner_key]);
  }
  return row.rows[0] || null;
}

export async function destroySession(db, token) {
  const value = String(token || "");
  if (!TOKEN_RE.test(value)) return;
  await db.query("DELETE FROM sessions WHERE token_hash=$1", [sha256(value)]);
}

// Erasure has to be actual erasure, so this removes the picks too rather than
// orphaning them under an owner key nobody can sign into. It runs in one
// transaction: a half-deleted account -- rows gone, identity left behind --
// would let the same provider login return to a hollow account and would be a
// worse outcome than either finishing or not starting.
//
// The graded picks are the account's own contribution, so they leave with it.
// The leaderboard recomputes from the surviving rows, and the person is gone
// from it by the next read.
export async function deleteAccount(db, ownerKey) {
  if (!OWNER_RE.test(String(ownerKey || ""))) return false;
  try {
    await db.query("BEGIN");
    await db.query("DELETE FROM verified_picks WHERE device_id=$1", [ownerKey]);
    await db.query("DELETE FROM sessions WHERE owner_key=$1", [ownerKey]);
    await db.query("DELETE FROM signin_codes WHERE owner_key=$1", [ownerKey]);
    await db.query("DELETE FROM account_identities WHERE owner_key=$1", [ownerKey]);
    const removed = await db.query("DELETE FROM accounts WHERE owner_key=$1 RETURNING owner_key", [ownerKey]);
    await db.query("COMMIT");
    return !!removed.rows[0];
  } catch (error) {
    try { await db.query("ROLLBACK"); } catch (_) {}
    throw error;
  }
}

// Keeping an identity forever because nobody came back is a retention policy by
// neglect. `last_seen_at` is refreshed on every authenticated request, so
// dormancy here means the account genuinely went unused for the full window,
// not merely that its owner was quiet this month.
//
// There is no scheduler in front of this function, so it is called from ordinary
// traffic and gated on a once-a-day rate-limit bucket: the first request after
// midnight pays for the sweep and every other request skips it.
export const RETENTION_MS = 540 * 86400000; // 18 months
export async function purgeDormantAccounts(db) {
  const cutoff = Date.now() - RETENTION_MS;
  const dormant = await db.query(
    // Capped so one unlucky request never pays for a huge sweep; a backlog
    // simply drains over the following days.
    "SELECT owner_key FROM accounts WHERE last_seen_at < $1 LIMIT 50",
    [cutoff]
  );
  let purged = 0;
  for (const row of dormant.rows) {
    if (await deleteAccount(db, row.owner_key)) purged += 1;
  }
  // Guest rows have no account to age out, so they are swept on the same clock.
  await db.query(
    "DELETE FROM verified_picks WHERE device_id LIKE 'mdx-%' AND created_at < $1",
    [cutoff]
  );
  return purged;
}

// One-way and one-shot: rows already owned by an account are never re-assigned,
// so a guessed device id cannot lift someone else's graded history.
export async function claimDevicePicks(db, ownerKey, deviceId, handle) {
  if (!OWNER_RE.test(String(ownerKey || "")) || !DEVICE_RE.test(String(deviceId || ""))) return 0;
  const moved = await db.query(
    `UPDATE verified_picks v SET device_id=$1, handle=$2
     WHERE v.device_id=$3 AND NOT EXISTS (
       SELECT 1 FROM verified_picks o
       WHERE o.device_id=$1 AND o.comp=v.comp AND o.match_id=v.match_id)`,
    [ownerKey, handle, deviceId]
  );
  // Anything left collided with a pick the account already made for that
  // fixture; the account's own pick wins.
  await db.query("DELETE FROM verified_picks WHERE device_id=$1", [deviceId]);
  return moved.rowCount || 0;
}

export async function reshuffleAccountHandle(db, ownerKey) {
  const current = await db.query("SELECT handle,reshuffled FROM accounts WHERE owner_key=$1", [ownerKey]);
  if (!current.rows[0] || current.rows[0].reshuffled) return null;
  const base = String(current.rows[0].handle).replace(/\s#\d+$/, "");
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const candidate = drawHandle();
    if (candidate.replace(/\s#\d+$/, "") === base) continue;
    const updated = await db.query(
      `UPDATE accounts SET handle=$1, reshuffled=TRUE WHERE owner_key=$2
       AND NOT EXISTS (SELECT 1 FROM accounts WHERE handle=$1) RETURNING handle`,
      [candidate, ownerKey]
    );
    if (updated.rows[0]) return updated.rows[0].handle;
  }
  return null;
}

export async function startOauth(db, provider, returnOrigin, deviceId) {
  const state = randomToken();
  await db.query("DELETE FROM oauth_states WHERE expires_at < $1", [Date.now()]);
  await db.query(
    "INSERT INTO oauth_states(state_hash,provider,return_origin,device_id,expires_at) VALUES($1,$2,$3,$4,$5)",
    [sha256(state), provider, returnOrigin, DEVICE_RE.test(String(deviceId || "")) ? deviceId : null, Date.now() + OAUTH_STATE_TTL_MS]
  );
  return state;
}

export async function consumeOauthState(db, state) {
  const row = await db.query(
    "DELETE FROM oauth_states WHERE state_hash=$1 AND expires_at > $2 RETURNING provider,return_origin,device_id",
    [sha256(String(state || "")), Date.now()]
  );
  return row.rows[0] || null;
}

// The id_token arrives straight from Google's token endpoint over TLS, so its
// payload is trusted without a separate signature check (it was never handled
// by the browser). GitHub has no id_token, so its subject comes from the API.
export async function exchangeCodeForSubject(providerName, code) {
  const provider = PROVIDERS[providerName];
  if (!provider) return null;
  const response = await fetch(provider.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: new URLSearchParams({
      client_id: process.env[provider.idEnv] || "",
      client_secret: process.env[provider.secretEnv] || "",
      code: String(code || ""),
      redirect_uri: redirectUri(),
      grant_type: "authorization_code",
    }),
  });
  if (!response.ok) return null;
  const payload = await response.json().catch(() => null);
  if (!payload || payload.error) return null;
  if (providerName === "google") {
    const segments = String(payload.id_token || "").split(".");
    if (segments.length !== 3) return null;
    try {
      const claims = JSON.parse(Buffer.from(segments[1], "base64url").toString("utf8"));
      return claims.sub ? String(claims.sub).slice(0, 128) : null;
    } catch (_) { return null; }
  }
  const accessToken = String(payload.access_token || "");
  if (!accessToken) return null;
  const user = await fetch("https://api.github.com/user", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "matchday-accounts",
    },
  });
  if (!user.ok) return null;
  const profile = await user.json().catch(() => null);
  return profile?.id ? String(profile.id).slice(0, 128) : null;
}
