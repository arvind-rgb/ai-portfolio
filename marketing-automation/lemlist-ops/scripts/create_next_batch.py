#!/usr/bin/env python3
"""
Create the next 100-lead batch using the same filters as Batch 1, while
excluding contacts already used in any prior Bhookle B2B batch.

Behavior:
  1. Auto-discover all prior "BatchN-100Leads-*" campaigns
  2. Collect all contact emails / LinkedIn URLs used so far  →  exclusion set
  3. Search Lemlist People Database with hard-coded ICP filters
  4. Filter out anyone in the exclusion set
  5. Create a new draft campaign (DOES NOT auto-launch — user reviews first)
  6. Add the top 100 fresh leads to the new campaign
  7. Print a summary so the GH Action can email it

This is intentionally STOPPED before launching the campaign — user must
approve in the UI or via API ('lemlist start <id>') before sends begin.
"""
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
import lemlist_api as lem

IST = timezone(timedelta(hours=5, minutes=30))

# ── ICP filters (from Batch 1 — Bengaluru founders/co-founders in Tech) ──────
# Source: user-confirmed Lemlist People DB search shown in screenshots 2026-05-28
ICP_FILTERS = [
    {
        "filterId": "currentCompanySubIndustry",
        "in": ["Media and Telecommunications", "Technology, Information and Internet"],
    },
    {
        "filterId": "currentCompanyHeadcount",
        "in": ["11-50"],
    },
    {
        "filterId": "currentCompanyCountry",
        "in": ["India"],
    },
    {
        "filterId": "currentCompanyLocation",
        "in": ["karnataka bengaluru"],
    },
    {
        "filterId": "currentTitle",
        "in": ["admin", "senior administrative assistant", "office manager",
               "executive assistant", "executive administrative assistant",
               "founder", "co-founder"],
    },
]

BATCH_NAME_RE = re.compile(r"^Batch\d+-\d+Leads-", re.IGNORECASE)


def collect_used_contact_ids() -> set:
    """Walk every prior 'BatchN-...' campaign and collect contactIds used."""
    used = set()
    for c in lem.list_campaigns():
        if not BATCH_NAME_RE.match(c.get("name", "")):
            continue
        leads = lem.get_campaign_leads(c["_id"], limit=500)
        for l in leads:
            cid = l.get("contactId")
            if cid:
                used.add(cid)
    return used


def next_batch_number() -> int:
    """Find the highest BatchN in existing campaign names, return N+1."""
    highest = 0
    for c in lem.list_campaigns():
        m = re.match(r"^Batch(\d+)-", c.get("name", ""))
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def search_fresh_candidates(used_contact_ids: set, target_count: int = 100):
    """
    Page through People DB results, skipping anyone in used_contact_ids,
    until we collect target_count fresh leads.
    """
    fresh = []
    seen_in_search = set()
    page = 1
    while len(fresh) < target_count and page <= 20:  # cap to avoid runaway
        resp = lem.search_people(ICP_FILTERS, page=page, size=100)
        if not isinstance(resp, dict):
            print(f"⚠️  Unexpected response on page {page}: {type(resp)}")
            break
        people = resp.get("people", resp.get("results", resp.get("data", [])))
        if not people:
            break
        for p in people:
            pid = p.get("_id") or p.get("id")
            if not pid or pid in seen_in_search:
                continue
            seen_in_search.add(pid)
            if pid in used_contact_ids:
                continue  # already in a prior batch
            fresh.append(p)
            if len(fresh) >= target_count:
                break
        page += 1
    return fresh


def create_draft_campaign(name: str, template_campaign_id: str = None) -> str:
    """Create a new draft campaign. Returns campaign_id."""
    # If a template_id is given, we'd ideally duplicate it (preserves sequence + schedule).
    # Lemlist Duplicate Campaign endpoint:
    if template_campaign_id:
        resp = lem.post(f"campaigns/{template_campaign_id}/duplicate", {"name": name})
        if resp.get("_error"):
            print(f"⚠️  Duplicate failed: {resp}")
            sys.exit(1)
        return resp.get("_id") or resp.get("campaignId") or resp.get("id")
    # Fallback: create empty campaign
    resp = lem.post("campaigns", {"name": name})
    return resp.get("_id")


def add_lead_to_campaign(campaign_id: str, person: dict) -> bool:
    """Push a person from People DB into a campaign as a new lead."""
    payload = {
        "email": person.get("email") or person.get("primaryEmail"),
        "firstName": person.get("firstName"),
        "lastName": person.get("lastName"),
        "companyName": person.get("companyName") or person.get("currentCompanyName"),
        "jobTitle": person.get("jobTitle") or person.get("currentTitle"),
        "linkedinUrl": person.get("linkedinUrl") or person.get("leadLinkedInUrl"),
    }
    # Filter None values
    payload = {k: v for k, v in payload.items() if v}
    if "email" not in payload:
        return False
    resp = lem.create_lead(campaign_id, payload)
    return not resp.get("_error")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--template-campaign", default="cam_sbsPrGji9Qa4E4cmJ",
                    help="Duplicate this campaign's sequence/schedule into the new one. "
                         "Default = Batch1-100Leads-May27.")
    ap.add_argument("--target-count", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true",
                    help="Search + dedupe but don't create the campaign or add leads.")
    args = ap.parse_args()

    print("🔍 Step 1: collecting used contact IDs from prior batches ...")
    used = collect_used_contact_ids()
    print(f"   → {len(used)} contacts already used")

    print(f"🔍 Step 2: searching People DB for fresh ICP matches ...")
    fresh = search_fresh_candidates(used, args.target_count)
    print(f"   → {len(fresh)} fresh candidates found")
    if len(fresh) < args.target_count:
        print(f"   ⚠️  Only {len(fresh)}/{args.target_count} fresh leads available — "
              f"ICP pool may be exhausted, consider widening filters")

    if args.dry_run:
        print("🛑 Dry run — not creating campaign")
        return 0

    batch_num = next_batch_number()
    today = datetime.now(IST).strftime("%b%d")
    name = f"Batch{batch_num}-{len(fresh)}Leads-{today}"
    print(f"🆕 Step 3: creating draft campaign '{name}' (duplicate of {args.template_campaign}) ...")
    new_id = create_draft_campaign(name, args.template_campaign)
    print(f"   → {new_id}")

    print(f"➕ Step 4: adding {len(fresh)} leads to new campaign ...")
    added = 0
    failed = 0
    for p in fresh:
        if add_lead_to_campaign(new_id, p):
            added += 1
        else:
            failed += 1
    print(f"   → Added: {added}, Failed: {failed}")

    # Write summary for the GH Action to email
    summary = {
        "new_campaign_id": new_id,
        "new_campaign_name": name,
        "fresh_leads_added": added,
        "failed": failed,
        "ui_url": f"https://app.lemlist.com/campaigns/{new_id}/leads",
        "next_action": "Review leads in Lemlist UI, then launch via API or UI",
    }
    Path("/tmp/lemlist-next-batch-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
