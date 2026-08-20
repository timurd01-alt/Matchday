// Sign-in start: /api/auth?provider=google|github
//
// Sends the browser to the provider with a server-held `state`. The device id
// travels with the state, not in the redirect back, so the pick history a
// visitor already built anonymously can be claimed on their first sign-in
// without the browser being trusted to say whose history it is.

import {
  PROVIDERS, SAFE_ORIGINS, PUBLIC_SITE_ORIGIN, providerConfigured, redirectUri,
  newClient, ensureSchema, setHeaders, requestIp, opaqueKey, consumeLimit, startOauth,
} from "./_accounts.js";

export default async function handler(req, res) {
  setHeaders(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "GET") return res.status(405).json({ ok: false, error: "method not allowed" });

  const providerName = String(req.query.provider || "").toLowerCase();
  if (!PROVIDERS[providerName]) return res.status(400).json({ ok: false, error: "unknown provider" });
  if (!providerConfigured(providerName)) return res.status(503).json({ ok: false, error: "provider not configured" });

  // An open redirect here would hand a sign-in code to any site that asked, so
  // the return origin must be one we published, never whatever was requested.
  const requested = String(req.query.return || "");
  const returnOrigin = SAFE_ORIGINS.has(requested) || /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(requested)
    ? requested : PUBLIC_SITE_ORIGIN;

  const db = newClient();
  try {
    await db.connect();
    await ensureSchema(db);
    if (!await consumeLimit(db, `auth:${opaqueKey(requestIp(req))}`, 60000, 20)) {
      return res.status(429).json({ ok: false, error: "slow down" });
    }
    const state = await startOauth(db, providerName, returnOrigin, String(req.query.deviceId || ""));
    const provider = PROVIDERS[providerName];
    const params = new URLSearchParams({
      client_id: process.env[provider.idEnv],
      redirect_uri: redirectUri(),
      response_type: "code",
      state,
    });
    // Omitted entirely rather than sent empty: GitHub reads `scope=` as a
    // request it must render, and an empty one is not the same as no request.
    if (provider.scope) params.set("scope", provider.scope);
    if (providerName === "google") params.set("prompt", "select_account");
    res.setHeader("Location", `${provider.authorize}?${params}`);
    return res.status(302).end();
  } catch (error) {
    console.error("auth start failed", error);
    return res.status(500).json({ ok: false, error: "service unavailable" });
  } finally {
    try { await db.end(); } catch (_) {}
  }
}
