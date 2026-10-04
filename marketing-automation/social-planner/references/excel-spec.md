# Social Planner — JSON Content Schema

The build script at `scripts/build_calendar.py` reads `/tmp/social_planner_content.json`.

## Top-level structure

```json
{
  "month": "June 2026",
  "generated_date": "2026-06-01",
  "eval_source": "social/bhookle-social-eval-2026-05.json",
  "trend_scout_summary": "Short paragraph summarising top trends found this month",
  "instagram_facebook": [ ...30 post objects... ],
  "linkedin": [ ...12 post objects... ]
}
```

## Instagram/Facebook post object

```json
{
  "post_id": "IG-001",
  "post_date": "2026-06-02",
  "post_name": "Chef Lakshmi — Biryani Story",
  "post_format": "Reel",
  "content_category": "Chef Video",
  "post_hook": "She cooked biryani for 20 years. Now 8,000 people eat it.",
  "post_description": "Full caption text here...\n\nOrder on @bhookleeats 🍛\n\n#HomeCookedFood",
  "post_hashtag": "#HomeCookedFood, #ChefLife, #BhookleeEats, ...",
  "existing_asset_link": "https://drive.google.com/file/d/...",
  "asset_action": "Reformat",
  "post_gen_prompt": "Full Higgsfield/Nano-banana prompt here...",
  "post_output": "",
  "post_status": "",
  "eval_target": "Reach: 5K | ER: 5% | Saves: 50 | Shares: 30",
  "eval_hypothesis": "Chef story + trending audio drives high share velocity in food communities",
  "post_performance": ""
}
```

## LinkedIn post object

```json
{
  "post_id": "LI-001",
  "post_date": "2026-06-03",
  "post_name": "Home Food at Office — Chef Economy Angle",
  "post_theme": "HomeFood at Office",
  "post_format": "Long-form Text",
  "post_hook": "Your office lunch is making your team less productive. Here's the data.",
  "post_description": "Full 150-300 word LinkedIn post body here...",
  "post_hashtag": "#FoodAtWork, #EmployeeWellbeing, #Bhookle, #HomeFood, #StartupLife",
  "post_gen_prompt": "Document carousel brief: Slide 1 — '3 reasons your office lunch matters'. Slide 2...",
  "post_output": "",
  "post_status": "",
  "eval_target": "Reach: 800 | ER: 3% | Shares: 20",
  "eval_hypothesis": "Stat-led hook with wellbeing theme performs well with HR/founders on Tuesdays",
  "post_performance": ""
}
```

## Summary tab data object (optional, appended at top level)

```json
{
  "summary": {
    "total_posts": 42,
    "ig_fb_posts": 30,
    "linkedin_posts": 12,
    "chef_video_count": 15,
    "food_content_count": 12,
    "brand_count": 3,
    "reel_count": 12,
    "carousel_count": 8,
    "static_count": 6,
    "story_count": 4,
    "reused_assets": 15,
    "net_new_posts": 15
  }
}
```
