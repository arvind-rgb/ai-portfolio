// Password hashing for operator credentials — scrypt (Node builtin, no deps).
// Stored form: "<saltHex>:<hashHex>". Never store plaintext.
const crypto = require("crypto");

function hash(password) {
  const salt = crypto.randomBytes(16);
  const dk = crypto.scryptSync(String(password), salt, 32);
  return salt.toString("hex") + ":" + dk.toString("hex");
}

function verify(password, stored) {
  if (!stored || typeof stored !== "string" || !stored.includes(":")) return false;
  const [saltHex, hashHex] = stored.split(":");
  let a, b;
  try { a = crypto.scryptSync(String(password), Buffer.from(saltHex, "hex"), 32); b = Buffer.from(hashHex, "hex"); }
  catch { return false; }
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// Human-typable password (no ambiguous chars).
function randomPassword(len = 14) {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  let out = "";
  const bytes = crypto.randomBytes(len);
  for (let i = 0; i < len; i++) out += alphabet[bytes[i] % alphabet.length];
  return out;
}

module.exports = { hash, verify, randomPassword };
