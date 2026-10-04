/**
 * HMAC callback tokens for CI → BugBhook callbacks.
 *
 * Token format:  <run_id>.<expires_unix_ms>.<base64url_hmac>
 *   hmac = HMAC-SHA256(key=CALLBACK_HMAC_KEY, message="<run_id>.<expires_unix_ms>")
 *
 * Token TTL: 90 min by default (enough for a full run + slack, short enough that
 * a leaked token can't be reused indefinitely).
 *
 * We store sha256(token) in qa.test_runs.callback_token_hash so we can verify
 * later — never the raw token.
 */

const crypto = require("crypto");

const TTL_MS_DEFAULT = 90 * 60 * 1000;

function key() {
  const k = process.env.CALLBACK_HMAC_KEY;
  if (!k || k.length < 32) {
    throw new Error("CALLBACK_HMAC_KEY missing or shorter than 32 chars");
  }
  return k;
}

function b64url(buf) {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function issue(runId, ttlMs = TTL_MS_DEFAULT) {
  const expires = Date.now() + ttlMs;
  const msg = `${runId}.${expires}`;
  const hmac = crypto.createHmac("sha256", key()).update(msg).digest();
  const token = `${msg}.${b64url(hmac)}`;
  const hash = crypto.createHash("sha256").update(token).digest("hex");
  return { token, hash, expires_at: new Date(expires).toISOString() };
}

function verify(token, expectedRunId) {
  if (!token || typeof token !== "string") return { ok: false, reason: "no token" };
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "bad format" };
  const [runIdStr, expiresStr, sig] = parts;
  const runId = parseInt(runIdStr, 10);
  const expires = parseInt(expiresStr, 10);
  if (!Number.isFinite(runId) || !Number.isFinite(expires)) {
    return { ok: false, reason: "bad ids" };
  }
  if (expectedRunId !== undefined && Number(expectedRunId) !== runId) {
    return { ok: false, reason: "run id mismatch" };
  }
  if (Date.now() > expires) return { ok: false, reason: "expired" };
  const msg = `${runId}.${expires}`;
  const expected = b64url(
    crypto.createHmac("sha256", key()).update(msg).digest()
  );
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return { ok: false, reason: "bad signature" };
  }
  return { ok: true, run_id: runId, expires_at: expires };
}

function hash(token) {
  return crypto.createHash("sha256").update(token).digest("hex");
}

module.exports = { issue, verify, hash };
