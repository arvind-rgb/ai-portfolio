# Resend API Reference

Base URL: `https://api.resend.com`
Auth: `Authorization: Bearer <RESEND_API_KEY>` header on all requests.

## Endpoints used

### Verify domain (Stage 4 guard)
```
GET /domains
```
Returns list of domains. Check for `status == "verified"` before any send.
Refuse dispatch if no verified domain found.

### Send batch emails (Stage 4)
```
POST /emails/batch
Content-Type: application/json

[
  {
    "from": "Bhookle <team@example.com>",
    "to": ["recipient@example.com"],
    "subject": "...",
    "text": "...",
    "html": "...",
    "headers": {
      "X-Campaign": "<slug>",
      "X-Batch-Date": "YYYY-MM-DD"
    }
  },
  ...
]
```
Returns array of `{id, from, to, created_at}`. Max 100 per request.
Store each `id` in `sent-log.csv`.

### Poll email status (Stage 5)
```
GET /emails/{id}
```
Returns:
```json
{
  "id": "...",
  "from": "...",
  "to": [...],
  "subject": "...",
  "created_at": "...",
  "last_event": "delivered" | "opened" | "clicked" | "bounced" | "complained" | "sent"
}
```
Note: `last_event` is the most recent state — not cumulative. We record the
best event seen across all polls within 7 days.

## Free-tier limits
| Limit | Value |
|---|---|
| Emails/day | 100 |
| Emails/month | 3,000 |
| Verified domains | 1 |
| API rate limit | ~10 req/s |

## Event hierarchy (for reporting)
`complained` > `bounced` > `clicked` > `opened` > `delivered` > `sent`

When polling, track the "best positive event" (clicked > opened > delivered > sent)
and "negative events" (bounced, complained) separately.

## Webhook upgrade path (v2, optional)
For real-time events instead of polling:
1. Create a free Cloudflare Worker at `<subdomain>.workers.dev`
2. Worker receives POST from Resend webhook, extracts `{email_id, event, timestamp}`
3. Worker calls GitHub API to append event to `email-marketing/campaigns/<slug>/events.jsonl`
4. Update `fetch_stats.py` to read `events.jsonl` instead of polling

Resend webhook payload:
```json
{
  "type": "email.opened",
  "data": {
    "email_id": "...",
    "to": ["..."],
    "created_at": "..."
  }
}
```
Configure in Resend dashboard → Webhooks → Add endpoint.
