#!/usr/bin/env python3
"""
Format the next-batch summary JSON into a Bhookle-branded HTML email.

Reads:  /tmp/lemlist-next-batch-summary.json   (written by create_next_batch.py)
Writes: /tmp/next-batch-email.html              (consumed by GH Actions email step)
"""
import json
import sys
from pathlib import Path

IN = Path("/tmp/lemlist-next-batch-summary.json")
OUT = Path("/tmp/next-batch-email.html")


def main():
    if not IN.exists():
        OUT.write_text("<p>Next-batch script ran but no summary file was produced.</p>")
        print(f"⚠️  {IN} not found — wrote fallback to {OUT}")
        return 0

    s = json.loads(IN.read_text())
    html = f"""<html><body style='font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#FFF8EC;padding:24px;margin:0;'>
  <div style='max-width:560px;margin:0 auto;background:#FFFFFF;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);'>
    <div style='background:#FFA70B;padding:18px 24px;color:#2D1B3D;font-weight:700;font-size:20px;'>Bhookle &middot; Next Batch Ready for Review</div>
    <div style='padding:24px;color:#1A1A1A;'>
      <h2 style='color:#2D1B3D;margin:0 0 12px;'>{s.get('new_campaign_name','?')}</h2>
      <p style='color:#6E4F7A;margin:0 0 16px;'>The previous batch completed, so a fresh {s.get('fresh_leads_added',0)}-lead batch is queued as a DRAFT campaign &mdash; same filters, no duplicates from prior batches.</p>
      <div style='padding:14px 16px;background:#FFE9C2;border-left:4px solid #FFA70B;border-radius:6px;margin:18px 0;color:#2D1B3D;'>
        <strong>&#x1F449; Next step:</strong> Review the leads in Lemlist, then launch when ready.<br>
        <a href='{s.get('ui_url','#')}' style='color:#FFA70B;'>Open in Lemlist &rarr;</a>
      </div>
      <pre style='background:#F5F5F5;padding:12px;border-radius:6px;font-size:12px;color:#2D1B3D;overflow:auto;'>{json.dumps(s, indent=2)}</pre>
    </div>
  </div>
</body></html>"""
    OUT.write_text(html)
    print(f"✅ Wrote {OUT} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
