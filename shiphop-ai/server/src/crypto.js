// Envelope encryption for courier credentials at rest. Rules: encrypt at rest,
// never log the blob, never return it to the browser.
//
// AES-256-GCM with a key from BOOKER_CRED_KEY (32 bytes, base64 or hex). In real
// deployment prefer a KMS-wrapped data key; this is the minimum bar and keeps the
// interface (encrypt/decrypt) identical if you later swap in KMS.

const crypto = require("crypto");

function loadKey() {
  const raw = process.env.BOOKER_CRED_KEY || "";
  if (!raw) return null; // dev mode — see encrypt()
  let buf;
  if (/^[0-9a-f]{64}$/i.test(raw)) buf = Buffer.from(raw, "hex");
  else buf = Buffer.from(raw, "base64");
  if (buf.length !== 32) {
    throw new Error("BOOKER_CRED_KEY must decode to exactly 32 bytes (got " + buf.length + ")");
  }
  return buf;
}

const KEY = loadKey();

// Returns a JSON string safe to store in a JSONB/text column: {v,iv,tag,ct}.
// If no key is configured (local dev), stores base64 plaintext tagged v:0 so the
// app runs, but logs a loud warning — never ship without a key.
function encrypt(obj) {
  const plain = Buffer.from(JSON.stringify(obj), "utf8");
  if (!KEY) {
    if (!encrypt._warned) {
      console.warn("[crypto] BOOKER_CRED_KEY not set — credentials stored UNENCRYPTED (dev only).");
      encrypt._warned = true;
    }
    return JSON.stringify({ v: 0, ct: plain.toString("base64") });
  }
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", KEY, iv);
  const ct = Buffer.concat([cipher.update(plain), cipher.final()]);
  const tag = cipher.getAuthTag();
  return JSON.stringify({ v: 1, iv: iv.toString("base64"), tag: tag.toString("base64"), ct: ct.toString("base64") });
}

function decrypt(stored) {
  if (!stored) return null;
  const env = typeof stored === "string" ? JSON.parse(stored) : stored;
  if (env.v === 0) return JSON.parse(Buffer.from(env.ct, "base64").toString("utf8"));
  if (!KEY) throw new Error("BOOKER_CRED_KEY required to decrypt v1 credentials");
  const iv = Buffer.from(env.iv, "base64");
  const decipher = crypto.createDecipheriv("aes-256-gcm", KEY, iv);
  decipher.setAuthTag(Buffer.from(env.tag, "base64"));
  const plain = Buffer.concat([decipher.update(Buffer.from(env.ct, "base64")), decipher.final()]);
  return JSON.parse(plain.toString("utf8"));
}

module.exports = { encrypt, decrypt, hasKey: Boolean(KEY) };
