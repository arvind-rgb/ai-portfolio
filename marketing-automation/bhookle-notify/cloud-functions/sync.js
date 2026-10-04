"use strict";
// Sync the GitHub calendar (source of truth) -> Firestore (the function's read store).
// Upserts title/body/send_ist for every armed (scheduled) entry. Never downgrades a
// doc that Firestore already marked "posted" (prevents re-sends).
//
// Auth: GOOGLE_APPLICATION_CREDENTIALS (local) or the runtime SA (CI via the SA key).
// Run: node sync.js   (from notifications/functions/)
const path = require("path");
const fs = require("fs");
const { initializeApp, applicationDefault } = require("firebase-admin/app");
const { getFirestore } = require("firebase-admin/firestore");

const CALENDAR = path.join(__dirname, "..", "notification-calendar.json");
const COLLECTION = "app_notifications";

initializeApp({ credential: applicationDefault() });
const db = getFirestore();

async function main() {
  const cal = JSON.parse(fs.readFileSync(CALENDAR, "utf8"));
  const armed = cal.entries.filter((e) => e.status === "scheduled");
  let upserts = 0;

  for (const e of armed) {
    const id = `${e.date}_${e.slot}`;
    const ref = db.collection(COLLECTION).doc(id);
    const snap = await ref.get();
    const existing = snap.exists ? snap.data() : null;

    const doc = {
      date: e.date, slot: e.slot, send_ist: e.send_ist,
      title: e.title, body: e.body || " ", kind: e.kind || null,
    };
    // keep posted state; otherwise (re)arm
    doc.status = existing && existing.status === "posted" ? "posted" : "scheduled";

    await ref.set(doc, { merge: true });
    upserts++;
  }
  console.log(`synced ${upserts} armed entries -> Firestore/${COLLECTION}`);
}

main().then(() => process.exit(0)).catch((e) => { console.error(e); process.exit(1); });
