"use strict";
// FIRST100 follow-up: push to users who REGISTERED YESTERDAY and have NOT ordered.
//
// Runs daily at 11:00 IST (see index.js). Flow:
//   1. getEligibleUsers() — ⚠️ DEVELOPER: implement the data query (TODOs below)
//   2. Skip anyone already in the `reactivation_log` Firestore collection
//      (once-ever guarantee — safe against re-runs, retries, overlapping sources)
//   3. Send the FIRST100 push per token (batches of 500)
//   4. Log every touched user to `reactivation_log`; mark dead tokens
//
// Why "yesterday": tokens are ~95% alive on day 1 and decay ~60% within a month
// (measured on the Jul 2026 blast). Day-after is the activation window.
//
// NOTE for cutover: the interim CSV-upload pipeline (bhookle-marketing repo,
// notify-daily-followup.yml) does the same job manually. When this function goes
// live, disable that workflow — running both can double-ping users registered
// on the cutover day.

const { getFirestore, Timestamp } = require("firebase-admin/firestore");
const { getMessaging } = require("firebase-admin/messaging");

const TZ = "Asia/Kolkata";
const LOG_COLLECTION = "reactivation_log";

// Message copy — approved 2026-07-13. Keep offer-first and short (lock-screen truncation).
const PUSH_TITLE = "₹100 off your first meal 🍱";
const PUSH_BODY = "Use code FIRST100 · home-cooked by real ammas near you.";

// "Yesterday" as [start, end) in IST, returned as JS Dates (UTC instants).
// Timezone-independent: correct on UTC Cloud Functions AND on local dev machines.
function yesterdayWindowIST(now = new Date()) {
  const istDate = (d) => d.toLocaleDateString("en-CA", { timeZone: TZ }); // YYYY-MM-DD
  const todayIST = istDate(now);
  const yesterdayIST = istDate(new Date(now.getTime() - 24 * 3600 * 1000));
  return {
    start: new Date(`${yesterdayIST}T00:00:00+05:30`),
    end: new Date(`${todayIST}T00:00:00+05:30`),
  };
}

/**
 * ⚠️ DEVELOPER TODO — the only part that needs your schema knowledge.
 * Return: Array<{ uid: string, token: string }>
 * Criteria: registered during [start, end) AND zero orders AND has an FCM token.
 *
 * Firestore sketch (adjust collection/field names to the real schema):
 *
 *   const db = getFirestore();
 *   const snap = await db.collection("users")
 *     .where("createdAt", ">=", Timestamp.fromDate(start))
 *     .where("createdAt", "<", Timestamp.fromDate(end))
 *     .get();
 *   const users = [];
 *   for (const doc of snap.docs) {
 *     const u = doc.data();
 *     if (!u.fcmToken) continue;
 *     if ((u.orderCount || 0) > 0) continue;      // or query the orders collection:
 *     // const ordered = !(await db.collection("orders")
 *     //   .where("userId", "==", doc.id).limit(1).get()).empty;
 *     // if (ordered) continue;
 *     users.push({ uid: doc.id, token: u.fcmToken });
 *   }
 *   return users;
 *
 * If users/orders live in SQL instead, the equivalent query:
 *   SELECT u.user_id AS uid, u.fcm_token AS token
 *   FROM users u
 *   LEFT JOIN orders o ON o.user_id = u.user_id
 *   WHERE u.created_at >= :start AND u.created_at < :end
 *     AND o.id IS NULL AND u.fcm_token IS NOT NULL;
 * — run it via your existing DB client and map rows to {uid, token}.
 */
async function getEligibleUsers(start, end) {
  throw new Error("getEligibleUsers() not implemented — see TODO in followup.js");
}

// Send FIRST100 to all eligible-and-never-touched users. Idempotent via reactivation_log.
async function sendFollowup({ dryRun = false } = {}) {
  const db = getFirestore();
  const { start, end } = yesterdayWindowIST();

  const eligible = await getEligibleUsers(start, end);

  // Once-ever filter
  const fresh = [];
  for (const u of eligible) {
    const logged = await db.collection(LOG_COLLECTION).doc(u.uid).get();
    if (!logged.exists) fresh.push(u);
  }

  const summary = {
    window: { startUTC: start.toISOString(), endUTC: end.toISOString() },
    eligible: eligible.length,
    alreadyTouched: eligible.length - fresh.length,
    sent: 0, invalidToken: 0, errors: 0, dryRun,
  };
  if (!fresh.length || dryRun) return summary;

  const messaging = getMessaging();
  const now = new Date().toISOString();

  for (let i = 0; i < fresh.length; i += 500) {
    const chunk = fresh.slice(i, i + 500);
    const res = await messaging.sendEachForMulticast({
      tokens: chunk.map((u) => u.token),
      notification: { title: PUSH_TITLE, body: PUSH_BODY },
      android: { priority: "high", notification: { sound: "default" } },
      apns: { payload: { aps: { sound: "default" } } },
    });

    const batch = db.batch();
    res.responses.forEach((r, j) => {
      const u = chunk[j];
      const ref = db.collection(LOG_COLLECTION).doc(u.uid);
      if (r.success) {
        summary.sent += 1;
        batch.set(ref, { status: "sent", at: now, campaign: "first100_day1" });
      } else if (r.error && String(r.error.code).includes("registration-token")) {
        summary.invalidToken += 1;
        batch.set(ref, { status: "invalid_token", at: now, campaign: "first100_day1" });
        // Optional: also clear users/{uid}.fcmToken so the backend knows it's stale.
      } else {
        summary.errors += 1; // transient — NOT logged, retried tomorrow if still eligible
      }
    });
    await batch.commit();
  }
  return summary;
}

module.exports = { sendFollowup, yesterdayWindowIST, PUSH_TITLE, PUSH_BODY };
