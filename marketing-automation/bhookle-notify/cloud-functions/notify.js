"use strict";
// Shared send logic — used by the scheduled functions (index.js) and local test harness.
const { getFirestore } = require("firebase-admin/firestore");
const { getMessaging } = require("firebase-admin/messaging");

const COLLECTION = "app_notifications";
const TOPIC = "all";
const TZ = "Asia/Kolkata";

// YYYY-MM-DD in IST (en-CA locale yields ISO-style date)
function istDate(d = new Date()) {
  return d.toLocaleDateString("en-CA", { timeZone: TZ });
}

// Send the given slot ("lunch"|"dinner") for today (IST). Idempotent via Firestore status.
async function sendSlot(slot, { dryRun = false, dateOverride = null } = {}) {
  const db = getFirestore();
  const date = dateOverride || istDate();
  const id = `${date}_${slot}`;
  const ref = db.collection(COLLECTION).doc(id);
  const snap = await ref.get();

  if (!snap.exists) return { skipped: "no-doc", id };
  const e = snap.data();
  if (e.status === "posted") return { skipped: "already-posted", id };
  if (e.status !== "scheduled") return { skipped: `status-${e.status}`, id };

  const message = {
    topic: TOPIC,
    notification: { title: e.title, body: e.body || " " },
    android: { priority: "high", notification: { sound: "default" } },
    apns: { payload: { aps: { sound: "default" } } },
  };

  if (dryRun) {
    // validate the message without delivering
    await getMessaging().send(message, true);
    return { dry: true, id, title: e.title };
  }

  const fcmId = await getMessaging().send(message);
  await ref.update({ status: "posted", postedAt: new Date().toISOString(), fcmId });
  return { sent: true, id, title: e.title, fcmId };
}

module.exports = { sendSlot, istDate, COLLECTION, TOPIC, TZ };
