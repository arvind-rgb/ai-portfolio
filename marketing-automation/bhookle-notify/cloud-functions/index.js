"use strict";
// Bhookle on-the-dot push notifications.
// Cloud Scheduler (auto-provisioned by onSchedule) fires these in Asia/Kolkata time;
// each reads today's slot from Firestore and sends to FCM topic "all". Idempotent.
//
// Codebase: bhookle-notify (isolated — does NOT touch other <firebase-project-id> functions).
const { onSchedule } = require("firebase-functions/v2/scheduler");
const { initializeApp } = require("firebase-admin/app");
const { sendSlot, TZ } = require("./notify");
const { sendFollowup } = require("./followup");

initializeApp();

// Runtime: default compute SA (has roles/editor → FCM send + Firestore access).
const base = { region: "asia-south1", timeZone: TZ, retryCount: 1, memory: "256MiB" };

// Primary fires exactly on the dot; the +12 min retry is an idempotent safety net.
exports.notifyLunch = onSchedule(
  { ...base, schedule: "45 11 * * *" },
  async () => { console.log(JSON.stringify(await sendSlot("lunch"))); }
);
exports.notifyLunchRetry = onSchedule(
  { ...base, schedule: "57 11 * * *" },
  async () => { console.log(JSON.stringify(await sendSlot("lunch"))); }
);
exports.notifyDinner = onSchedule(
  { ...base, schedule: "45 18 * * *" },
  async () => { console.log(JSON.stringify(await sendSlot("dinner"))); }
);
exports.notifyDinnerRetry = onSchedule(
  { ...base, schedule: "57 18 * * *" },
  async () => { console.log(JSON.stringify(await sendSlot("dinner"))); }
);

// FIRST100 day-after follow-up to yesterday's registered-but-not-ordered users.
// Idempotent via the reactivation_log collection — the 12:12 retry cannot double-send.
// ⚠️ Deploy AFTER implementing getEligibleUsers() in followup.js (see its TODO).
exports.followupRegNotOrdered = onSchedule(
  { ...base, schedule: "0 11 * * *" },
  async () => { console.log(JSON.stringify(await sendFollowup())); }
);

