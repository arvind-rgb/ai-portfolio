#!/usr/bin/env python3
"""
linkedin_auth.py — CLI helper to get a LinkedIn OAuth2 access token.

Run once to authorize:
  python3 linkedin_auth.py

You'll need:
  - LINKEDIN_CLIENT_ID (from your LinkedIn App)
  - LINKEDIN_CLIENT_SECRET (from your LinkedIn App)

The script prints your access token — copy it to .env as LI_ACCESS_TOKEN.
"""

import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8765/callback"
# Modern LinkedIn scopes
# w_member_social        = post to personal feed (auto-approved)
# openid + profile + email = Sign In with LinkedIn (auto-approved)
# w_organization_social  = post AS the Bhookle company page (Community Mgmt API — requires
#                          enabling "Community Management API" product on the LinkedIn app)
# r_organization_social  = read company-page posts (for verification)
# rw_organization_admin  = list org ACLs (confirms which orgs you admin)
SCOPES = "openid profile email w_member_social w_organization_social r_organization_social rw_organization_admin"

AUTH_CODE = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Authorized! You can close this tab.</h1>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>Error: no code returned</h1>")

    def log_message(self, *args):
        pass  # suppress server logs


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in your environment first.")
        print("  export LINKEDIN_CLIENT_ID=your_app_client_id")
        print("  export LINKEDIN_CLIENT_SECRET=your_app_client_secret")
        sys.exit(1)

    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(SCOPES)}"
    )

    print(f"\nOpening LinkedIn authorization URL...")
    print(f"If browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Start local server to catch callback
    server = HTTPServer(("localhost", 8765), CallbackHandler)
    server.handle_request()

    if not AUTH_CODE:
        print("❌ Authorization failed — no code received")
        sys.exit(1)

    # Exchange code for token
    r = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": AUTH_CODE,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    data = r.json()

    if "access_token" in data:
        token = data["access_token"]
        expires_in = data.get("expires_in", 5184000)

        # Get user URN via OpenID Connect userinfo endpoint
        userinfo_r = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        userinfo = userinfo_r.json()
        person_id = userinfo.get("sub", "")
        name = userinfo.get("name", "unknown")

        print(f"\n{'='*55}")
        print(f"✅ LinkedIn connected as: {name}")
        print(f"   Token valid for {expires_in // 86400} days")
        print(f"\nAdd these to your .env file:\n")
        print(f"  LI_ACCESS_TOKEN={token}")
        print(f"  LI_AUTHOR_URN=urn:li:person:{person_id}")
        print(f"  LI_COMPANY_URN=urn:li:organization:<COMPANY_ID>  # Bhookle page\n")
        print(f"{'='*55}\n")

        # Verify org scopes worked — list orgs the user admins
        acl_r = requests.get(
            "https://api.linkedin.com/v2/organizationAcls"
            "?q=roleAssignee&role=ADMINISTRATOR"
            "&projection=(elements*(organization~(localizedName,id)))",
            headers={"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0"},
            timeout=10,
        )
        if acl_r.status_code == 200:
            elems = acl_r.json().get("elements", [])
            print(f"You administer {len(elems)} LinkedIn organization(s):")
            for e in elems:
                org = e.get("organization~", {})
                print(f"  • {org.get('localizedName', '?')} (id: {org.get('id', '?')})")
            print()
        else:
            print(f"⚠ Org admin check failed (HTTP {acl_r.status_code}). The token may not")
            print(f"  have w_organization_social scope — verify your LinkedIn app has the")
            print(f"  'Community Management API' product enabled.\n")
    else:
        print(f"❌ Token exchange failed: {data}")
        sys.exit(1)


if __name__ == "__main__":
    main()
