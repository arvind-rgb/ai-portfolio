// ─────────────────────────────────────────────────────────────────────────────
// Provider registry — the single source of truth for ShipHop.AI's courier layer.
//
// Drives BOTH the backend (validation, adapter loading) AND the Connections screen
// (rendered fields, instructions, capability chips). Served as JSON at
// GET /api/providers, so the UI can never drift from the backend.
//
// Showcase note: in this public repo every courier uses the same mobile → OTP
// connect flow and is served by the mock adapter. Courier-specific connect
// mechanics live with the private production adapters.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * authType:
 *   'otp'   — send OTP to the operator's registered mobile, then verify (self-serve).
 *   'paste' — admin fallback: an operator-supplied session is saved directly.
 *
 * capabilities feed the UI chips and let the booking layer degrade gracefully
 * (e.g. a courier that exposes only a masked rider number shows a "masked" chip).
 */

const otpLogin = (courier) => ({
  fields: [
    { name: "mobile", label: `Registered ${courier} mobile`, type: "tel", maxlen: 10,
      placeholder: "10-digit mobile", required: true,
      help: `The mobile registered with your ${courier} account. If it's already connected, no OTP is sent.` },
  ],
  verifyFields: [
    { name: "otp", label: "OTP", type: "tel", maxlen: 6, placeholder: "6-digit OTP", required: true },
  ],
});

const otpSteps = (courier) => ({
  title: `How to connect ${courier}`,
  steps: [
    `Enter the mobile number registered with your ${courier} account.`,
    `${courier} sends a 6-digit OTP by SMS.`,
    "Enter the OTP to connect. ShipHop verifies the connection with a live fare check.",
  ],
});

const PROVIDERS = [
  {
    code: "W", key: "porter_web", name: "Porter Web", color: "#2C6BED",
    authType: "otp", tagline: "OTP login · 2-wheeler on-demand",
    capabilities: { estimate: true, cancel: true, pickupOtp: false, dropOtp: false,
      riderPhone: true, riderLocation: false, status: "webhook" },
    notes: ["Self-serve OTP login.", "Status arrives by push — no polling pressure."],
    login: otpLogin("Porter"), instructions: otpSteps("Porter"),
  },
  {
    code: "H", key: "delhivery", name: "Delhivery", color: "#C0392B",
    authType: "otp", tagline: "OTP login · hyperlocal 2-wheeler",
    capabilities: { estimate: true, cancel: true, pickupOtp: false, dropOtp: false,
      riderPhone: "masked", riderLocation: false, status: "poll" },
    notes: ["Self-serve OTP login.", "Sessions are short-lived — the portal prompts a reconnect when one ends.",
      "Rider phone is a masked bridge number."],
    login: otpLogin("Delhivery"),
    instructions: { ...otpSteps("Delhivery"), caveat: "Sessions are short-lived. If quotes stop appearing, reconnect with a fresh OTP." },
  },
  {
    code: "R", key: "shiprocket", name: "Shiprocket Quick", color: "#5F3DC4",
    authType: "otp", tagline: "OTP login · hyperlocal courier broadcast",
    capabilities: { estimate: true, cancel: true, pickupOtp: false, dropOtp: false,
      riderPhone: true, riderLocation: true, status: "poll" },
    notes: ["Self-serve OTP login.", "Estimate is a pure read — no order is created."],
    login: otpLogin("Shiprocket"), instructions: otpSteps("Shiprocket"),
  },
  {
    code: "X", key: "shadowfax", name: "Shadowfax Flash", color: "#D8332A",
    authType: "otp", tagline: "OTP login · on-demand rider, pays from credits",
    capabilities: { estimate: true, cancel: true, pickupOtp: true, dropOtp: true,
      riderPhone: true, riderLocation: true, status: "poll" },
    notes: ["Self-serve OTP login.", "Gives both pickup and drop OTPs, plus a live rider map."],
    login: otpLogin("Shadowfax"), instructions: otpSteps("Shadowfax"),
  },
  {
    code: "D", key: "rapido", name: "Rapido", color: "#F6C542", textColor: "#17150F",
    authType: "otp", tagline: "OTP login · parcel rider",
    capabilities: { estimate: true, cancel: true, pickupOtp: "heuristic", dropOtp: "heuristic",
      riderPhone: true, riderLocation: false, status: "poll" },
    notes: ["Self-serve OTP login.", "One account tracks one live order at a time."],
    login: otpLogin("Rapido"), instructions: otpSteps("Rapido"),
  },
  {
    code: "U", key: "uber", name: "Uber Connect", color: "#101010",
    authType: "otp", tagline: "Connect · parcel",
    capabilities: { estimate: true, cancel: true, pickupOtp: false, dropOtp: false,
      riderPhone: "masked", riderLocation: true, status: "poll" },
    notes: ["Rider phone is masked — contact is via the courier's live trip link."],
    login: otpLogin("Uber"), instructions: otpSteps("Uber"),
  },
];

const BY_KEY = Object.fromEntries(PROVIDERS.map((p) => [p.key, p]));
const BY_CODE = Object.fromEntries(PROVIDERS.map((p) => [p.code, p]));

// Public shape for the Connections screen — everything it needs, nothing secret.
function publicRegistry() {
  return PROVIDERS.map((p) => ({
    code: p.code, key: p.key, name: p.name, color: p.color, textColor: p.textColor || "#ffffff",
    authType: p.authType, tagline: p.tagline, capabilities: p.capabilities,
    notes: p.notes, login: p.login, instructions: p.instructions,
  }));
}

module.exports = { PROVIDERS, BY_KEY, BY_CODE, publicRegistry };
