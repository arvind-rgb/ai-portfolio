# Setup & Token Refresh

Initial setup is **done**. This doc covers the periodic refresh and the future
"company-page LinkedIn" upgrade.

---

## 1. Refresh Instagram token (every ~50 days)

The Meta long-lived token expires 60 days after issue. To refresh:

```bash
source .env
curl "https://graph.facebook.com/v21.0/oauth/access_token\
?grant_type=fb_exchange_token\
&client_id=${IG_APP_ID}\
&client_secret=${IG_APP_SECRET}\
&fb_exchange_token=${IG_ACCESS_TOKEN}"
```

Copy the new `access_token` → update `IG_ACCESS_TOKEN` in `.env`.

The `--check-env` flag warns when the current token is within 7 days of expiry.

---

## 2. Refresh LinkedIn token (every ~50 days)

LinkedIn tokens are not directly refreshable — re-run the OAuth flow:

```bash
LINKEDIN_CLIENT_ID="${LINKEDIN_CLIENT_ID}" \
LINKEDIN_CLIENT_SECRET="${LINKEDIN_CLIENT_SECRET}" \
python3 _skills/social-post/scripts/linkedin_auth.py
```

Browser opens → log in → Allow → script prints new `LI_ACCESS_TOKEN`.
Update `.env`.

---

## 3. Future upgrade: post as Bhookle Company Page (not personal)

Currently posting as Arvind's personal LinkedIn. To post as `/company/bhookle`:

1. Create a NEW LinkedIn app at https://www.linkedin.com/developers/apps/new
   (Community Management API requires its own dedicated app)
2. Associate it with the Bhookle Company Page
3. On the new app's Products tab → request **Community Management API** (only this one)
4. Wait 5-10 business days for approval
5. Re-run `linkedin_auth.py` with org scopes (`w_organization_social`,
   `r_organization_social`) against the new app
6. Update `.env`:
   ```
   LI_AUTHOR_URN=urn:li:organization:<bhookle-org-id>
   ```

Until then, posts go to Arvind's profile with `@Bhookle` + company URL in every caption
to give the company page visibility.

---

## 4. GitHub Secrets for the cron workflow (one-time)

The GitHub Actions workflow needs ALL of these secrets in repo settings → Secrets → Actions:

| Secret | Value |
|---|---|
| `IG_USER_ID` | Instagram Business Account ID |
| `IG_ACCESS_TOKEN` | Meta long-lived token (60-day) |
| `LI_ACCESS_TOKEN` | LinkedIn token (60-day) |
| `LI_AUTHOR_URN` | e.g. `urn:li:person:XXXXXXXX` |
| `GMAIL_USER` | `owner@example.com` |
| `GMAIL_APP_PASSWORD` | 16-char Google App Password (NOT regular Gmail password) |

Refresh `IG_ACCESS_TOKEN` and `LI_ACCESS_TOKEN` every ~50 days (60-day expiry).

### Generating the Gmail App Password (one-time)

1. Enable **2-Step Verification** on the Google account `owner@example.com`
   at https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. "App name" → `Bhookle Social Bot` → **Create**
4. Google shows a 16-char password like `abcd efgh ijkl mnop`
5. **Strip the spaces** → `abcdefghijklmnop`
6. Paste that into the `GMAIL_APP_PASSWORD` GitHub Secret

To verify it works: in GitHub Actions UI → Run workflow → input `TEST_EMAIL` →
should receive an email at `owner@example.com` within 30 seconds (no posting happens).
