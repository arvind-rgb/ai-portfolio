/**
 * Sets a CORS rule on <your-project>.appspot.com so the dashboard can PUT
 * directly to signed Storage URLs.
 *
 * Production-safe approach:
 *   1. GET current CORS config (logged for rollback reference).
 *   2. PRESERVE every existing rule (don't replace blindly — prod might rely
 *      on something).
 *   3. APPEND a new rule for the dashboard origin if it isn't already covered.
 *   4. SET the merged config.
 *
 * Usage:  node scripts/set-storage-cors.js
 */

require("dotenv").config();
const admin = require("firebase-admin");

const ORIGINS_TO_ALLOW = [
  "https://bhookle-qa.web.app",
  "http://localhost:7778",
];

// Initialise admin SDK using the default credentials. Locally this needs
// GOOGLE_APPLICATION_CREDENTIALS or `gcloud auth application-default login`.
// On Functions deploy this would auto-resolve. Here we're running on the
// dev machine — use the service account JSON pointed to by env, OR fall
// back to the default `firebase login` ADC.
if (!admin.apps.length) {
  admin.initializeApp({
    projectId: "<your-firebase-project>",
    storageBucket: "<your-project>.appspot.com",
  });
}

(async function main() {
  const bucket = admin.storage().bucket();

  const [meta] = await bucket.getMetadata();
  const current = meta.cors || [];
  console.log("[set-cors] CURRENT CORS rules:", JSON.stringify(current, null, 2));

  // Append our rule only if not already there.
  const alreadyCovers = current.some((rule) =>
    Array.isArray(rule.origin) &&
    ORIGINS_TO_ALLOW.every((o) => rule.origin.includes(o)) &&
    (rule.method || []).includes("PUT")
  );
  if (alreadyCovers) {
    console.log("[set-cors] ✓ All dashboard origins already covered — nothing to do.");
    return;
  }

  const newRule = {
    origin: ORIGINS_TO_ALLOW,
    method: ["GET", "HEAD", "PUT", "POST", "OPTIONS"],
    responseHeader: [
      "Content-Type", "Content-Disposition", "Content-Length",
      "Authorization", "x-goog-resumable", "x-goog-meta-*",
    ],
    maxAgeSeconds: 3600,
  };

  const merged = current.concat([newRule]);
  console.log("[set-cors] WRITING:", JSON.stringify(merged, null, 2));

  await bucket.setCorsConfiguration(merged);
  console.log("[set-cors] ✓ Applied. New rule active in ~1 min.");
})().catch((e) => {
  console.error("[set-cors] FAILED:", e.message);
  process.exit(1);
});
