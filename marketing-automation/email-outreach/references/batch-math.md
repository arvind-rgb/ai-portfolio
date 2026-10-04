# Free-Tier Batch Math

## Per-day cap
- Resend free tier: **100 emails/day**
- Safety margin: **90/day** (10 reserved for test sends + headroom)

## Batch plan formula
Given an audience of N emails:

```
days_needed = ceil(N / 90)
start_date  = user-confirmed send start date
batches     = {start_date + i: emails[i*90 : (i+1)*90] for i in range(days_needed)}
```

## Monthly quota guard
- Monthly cap: **3,000 emails**
- Before generating send-plan, sum all emails-planned across ALL active campaigns
  in `email-marketing/campaigns/*/send-plan.json` for the current month.
- Formula: `already_planned_this_month + new_audience_size <= 3000`
- If over limit: warn user, propose splitting into next month or reducing audience.

## Daily collision guard
On each dispatch day, `dispatch_batch.py` reads `sent-log.csv` across ALL campaigns
to count emails sent today. If `already_sent_today + today_batch_size > 100`: abort.

Example:
- Campaign A has 90 in today's batch → 90 sent
- Campaign B has 90 in today's batch → BLOCKED (90+90=180 > 100)
- Solution: stagger Campaign B start date by 1 day in send-plan.json

## Example scenarios

| Audience size | Days needed | Span |
|---|---|---|
| 90 | 1 | same day |
| 270 | 3 | Mon–Wed |
| 900 | 10 | 2 weeks |
| 2,700 | 30 | full month |
| 3,000 | 34 | hits monthly cap — warn |

## Multi-campaign sharing
If two campaigns are active simultaneously, their daily sends add up against the
100/day cap. `dispatch_batch.py` enforces this globally before each send.

Recommended approach for concurrent campaigns: stagger start dates so their
daily batches don't overlap. The skill prompts the user about this in Stage 2
if a collision is detected.
