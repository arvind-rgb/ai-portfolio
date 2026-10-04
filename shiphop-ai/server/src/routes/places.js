// Google Places proxy — keeps the Maps key server-side (never shipped to the
// browser). The portal calls /api/places/autocomplete as the operator types and
// /api/places/details on selection to resolve coordinates + pincode + city.
// Tenant-scoped (mounted behind tenantContext) so it isn't an open key proxy.
//
// With no GOOGLE_MAPS_API_KEY the routes answer from a small built-in demo
// address book (public landmarks in Bengaluru) so the portal runs with zero config.

const express = require("express");
const router = express.Router();

const KEY = process.env.GOOGLE_MAPS_API_KEY || "";
const AC_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json";
const DET_URL = "https://maps.googleapis.com/maps/api/place/details/json";

const DEMO_PLACES = [
  { id: "demo-indiranagar", name: "100 Feet Road, Indiranagar", area: "Bengaluru, Karnataka", lat: 12.9719, lng: 77.6412, pincode: "560038" },
  { id: "demo-koramangala", name: "80 Feet Road, Koramangala 4th Block", area: "Bengaluru, Karnataka", lat: 12.9338, lng: 77.6293, pincode: "560034" },
  { id: "demo-hsr", name: "27th Main Road, HSR Layout Sector 1", area: "Bengaluru, Karnataka", lat: 12.9121, lng: 77.6446, pincode: "560102" },
  { id: "demo-mgroad", name: "MG Road Metro Station", area: "Bengaluru, Karnataka", lat: 12.9755, lng: 77.6068, pincode: "560001" },
  { id: "demo-whitefield", name: "ITPL Main Road, Whitefield", area: "Bengaluru, Karnataka", lat: 12.9857, lng: 77.7311, pincode: "560066" },
  { id: "demo-jayanagar", name: "11th Main Road, Jayanagar 4th Block", area: "Bengaluru, Karnataka", lat: 12.9293, lng: 77.5826, pincode: "560011" },
  { id: "demo-malleshwaram", name: "Sampige Road, Malleshwaram", area: "Bengaluru, Karnataka", lat: 13.0035, lng: 77.5709, pincode: "560003" },
  { id: "demo-hebbal", name: "Outer Ring Road, Hebbal", area: "Bengaluru, Karnataka", lat: 13.0358, lng: 77.5970, pincode: "560024" },
];
const demoPrediction = (p) => ({ description: `${p.name}, ${p.area}`, main: p.name, secondary: p.area, place_id: p.id });

// No key → serve the demo address book instead of failing.
function needKey(res) { return false; }
// Surface Google's own status so a restricted/denied key is obvious in the UI.
function mapStatus(data) {
  const s = data && data.status;
  if (s === "OK" || s === "ZERO_RESULTS") return null;
  if (s === "REQUEST_DENIED") return "Places request denied — enable the Places API on this key and allow server (IP) use.";
  if (s === "OVER_QUERY_LIMIT") return "Places quota exceeded on this key.";
  return "Places error: " + (s || "unknown") + (data && data.error_message ? " — " + data.error_message : "");
}

// GET /api/places/autocomplete?q=<text>&session=<token>
router.get("/autocomplete", async (req, res) => {
  if (needKey(res)) return;
  const q = String(req.query.q || "").trim();
  if (q.length < 3) return res.json({ ok: true, predictions: [] });
  if (!KEY) {
    const terms = q.toLowerCase().split(/[\s,]+/).filter(Boolean);
    const hits = DEMO_PLACES.filter((p) => terms.every((t) => (p.name + " " + p.area).toLowerCase().includes(t)));
    return res.json({ ok: true, source: "demo", predictions: hits.slice(0, 5).map(demoPrediction) });
  }
  const p = new URLSearchParams({ input: q, key: KEY, components: "country:in", language: "en" });
  if (req.query.session) p.set("sessiontoken", String(req.query.session));
  try {
    const r = await fetch(`${AC_URL}?${p.toString()}`);
    const data = await r.json();
    const err = mapStatus(data);
    if (err) return res.status(502).json({ ok: false, error: err });
    const predictions = (data.predictions || []).map((x) => ({
      description: x.description,
      main: x.structured_formatting?.main_text || x.description,
      secondary: x.structured_formatting?.secondary_text || "",
      place_id: x.place_id,
    }));
    res.json({ ok: true, predictions });
  } catch (e) { res.status(502).json({ ok: false, error: e.message }); }
});

// GET /api/places/details?place_id=<id>&session=<token>
router.get("/details", async (req, res) => {
  if (needKey(res)) return;
  const placeId = String(req.query.place_id || "").trim();
  if (!placeId) return res.status(400).json({ ok: false, error: "place_id_required" });
  if (!KEY) {
    const p = DEMO_PLACES.find((x) => x.id === placeId);
    if (!p) return res.status(404).json({ ok: false, error: "unknown_place" });
    return res.json({ ok: true, place: { place_id: p.id, label: `${p.name}, ${p.area}`, name: p.name,
      lat: p.lat, lng: p.lng, pincode: p.pincode, city: "Bengaluru" } });
  }
  const p = new URLSearchParams({
    place_id: placeId, key: KEY, language: "en",
    fields: "geometry,formatted_address,name,address_component",
  });
  if (req.query.session) p.set("sessiontoken", String(req.query.session));
  try {
    const r = await fetch(`${DET_URL}?${p.toString()}`);
    const data = await r.json();
    const err = mapStatus(data);
    if (err) return res.status(502).json({ ok: false, error: err });
    const g = data.result || {};
    const comps = g.address_components || [];
    const pick = (type) => { const c = comps.find((x) => (x.types || []).includes(type)); return c ? c.long_name : null; };
    const loc = g.geometry && g.geometry.location;
    res.json({
      ok: true,
      place: {
        place_id: placeId,
        label: g.formatted_address || g.name || "",
        name: g.name || "",
        lat: loc ? loc.lat : null,
        lng: loc ? loc.lng : null,
        pincode: pick("postal_code"),
        city: pick("locality") || pick("administrative_area_level_2") || pick("administrative_area_level_1"),
      },
    });
  } catch (e) { res.status(502).json({ ok: false, error: e.message }); }
});

module.exports = router;
