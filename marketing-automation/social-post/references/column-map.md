# Content Planner — Column Mapping

## Instagram_Facebook sheet

| Column | Description | Used by social-post |
|---|---|---|
| PostID | Unique ID, e.g. IG-001 | Key for logging and status update |
| PostDate | YYYY-MM-DD | Combined with PostTime for `publish_at` |
| PostTime (IST) | HH:MM AM/PM in IST (UTC+5:30) | Converted to UTC Unix timestamp |
| PostName | Human title of the post | Logging only |
| PostFormat | Reel / Carousel / Static Image / Story | Determines IG media_type |
| AssetType | Reel (Video) / Static Image / Carousel | Used to choose upload path |
| ContentCategory | Chef Video / Food Visual / etc. | Logging only |
| Generator | Veo + Imagen Ultra / etc. | Logging only |
| PostHook | First line / hook text | Not posted separately; part of caption |
| PostDescription | Main caption body | Posted as caption |
| PostHashtag | Hashtag string | Appended to caption |
| ExistingAssetLink | Google Drive URL of source asset | Fallback if PostOutput is missing |
| AssetAction | Reformat / Generate / etc. | Validation check |
| PostGenPrompt | Generation brief | Not used in posting |
| PostOutput | Local file path to finalized asset | Primary asset for upload |
| PostStatus | Current status | Filter: `Creative Locked` → post → update |
| EvalTarget | Performance goal | Logged to post_log |
| EvalHypothesis | Content hypothesis | Logged to post_log |
| PostPerformance | Filled after posting | Not touched by this skill |

## LinkedIn sheet

| Column | Description | Used by social-post |
|---|---|---|
| PostID | Unique ID, e.g. LI-001 | Key for logging and status update |
| PostDate | YYYY-MM-DD | Used for GitHub Actions cron schedule |
| PostTime (IST) | HH:MM AM/PM in IST (UTC+5:30) | Converted to UTC for cron |
| PostName | Human title | Logging only |
| PostTheme | Theme of the post | Logging only |
| PostFormat | Long-form Text / Document / Video / etc. | Determines LI post type |
| AssetType | Static Image / Document / Video | Used to choose upload path |
| Generator | Imagen Ultra / etc. | Logging only |
| PostHook | Hook text | Part of main text body |
| PostDescription | Main body text | Posted as commentary text |
| PostHashtag | Hashtag string | Appended to text |
| PostGenPrompt | Generation brief | Not used |
| PostOutput | Local file path to finalized asset | Uploaded to LinkedIn |
| PostStatus | Current status | Filter and update target |
| EvalTarget | Performance goal | Logged |
| EvalHypothesis | Content hypothesis | Logged |
| PostPerformance | Filled after posting | Not touched |

## PostStatus Values (workflow states)

| Status | Meaning |
|---|---|
| `Draft` | Content being written |
| `Creative Locked` | Asset approved, ready to post → **this skill picks these up** |
| `Scheduled (IG)` | Instagram container created with `publish_at` — Meta will publish automatically |
| `GH Actions Generated` | LinkedIn workflow YAML generated — push to GitHub to activate |
| `Posted` | Successfully published |
| `Failed` | Post attempt failed — check `post_log_YYYY-MM.json` for error |

## IST to UTC Conversion

All `PostTime (IST)` values in the planner are in Indian Standard Time (UTC+5:30).

```
IST 7:00 AM  → UTC 01:30
IST 11:00 AM → UTC 05:30
IST 1:00 PM  → UTC 07:30
IST 6:00 PM  → UTC 12:30
IST 7:00 PM  → UTC 13:30
IST 8:00 PM  → UTC 14:30
```

The runner uses `pytz` to handle this conversion correctly:
```python
from datetime import datetime
import pytz
ist = pytz.timezone('Asia/Kolkata')
utc = pytz.utc
dt_ist = ist.localize(datetime(2026, 6, 1, 19, 0))  # 7:00 PM IST
dt_utc = dt_ist.astimezone(utc)
unix_ts = int(dt_utc.timestamp())
```
