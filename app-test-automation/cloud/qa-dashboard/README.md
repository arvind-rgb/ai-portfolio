# BhookleQaDashboard

Hosted FE for the Bhookle QA test-catalog dashboard. Single static page deployed to Firebase Hosting. Backed by `BhookleQaBackend`.

## Files

```
public/
  index.html      the dashboard
  config.js       Firebase web config + API_BASE (edit before deploy)
firebase.json     Hosting config (SPA rewrite, no-cache headers)
.firebaserc.example  copy → .firebaserc and set Firebase project id
```

## Deploy

See `BhookleQaBackend/README.md` § 6 for the full sequence. Short form:

```bash
cp .firebaserc.example .firebaserc        # set project id
# Edit public/config.js:
#   API_BASE  = https://asia-south1-<project>.cloudfunctions.net/bhookleQaBackend
#   FIREBASE  = web app config from Firebase console
firebase deploy --only hosting
```

## Add-TC flow

Header has **+ New Test Case** button → modal → POST `/api/tcs` → BE auto-assigns `tc_id` based on the screen's existing prefix (e.g. picking `CartScreen` yields `TC-CART-027` if `TC-CART-026` was the highest). The new TC is inserted into the rendered list and filter is narrowed to it so the user can verify immediately.
