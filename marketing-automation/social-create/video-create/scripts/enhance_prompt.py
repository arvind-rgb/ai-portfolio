#!/usr/bin/env python3
"""
enhance_prompt.py — Hyper-realistic prompt builder for Higgsfield video generation.

This is the "beast mode" eval. Given a raw PostGenPrompt from the social planner,
this script:
  1. Diagnoses what the prompt is missing across 9 cinematic-quality dimensions
  2. Returns a structured report (gaps + suggested additions)
  3. Builds an enhanced final prompt ready to pass to Higgsfield

Claude orchestrates this — the script outputs a critique and a candidate enhanced
prompt; Claude surfaces it to the user, applies any tweaks the user requests, then
sends the final approved prompt to `generate_video.py`.

Usage:
  python3 enhance_prompt.py --base "<raw PostGenPrompt>" \
      [--chef-name "Chef A. Sample"] [--dish "dal tadka with missi roti"] \
      [--city "Chennai"] [--cuisine "North Indian home food"] \
      [--duration 5] [--mood "warm, intimate, focused"] \
      [--has-ref-image] [--asmr]

Output: JSON with `critique` (list of gaps + suggestions) and `enhanced_prompt` (the
full text ready for Higgsfield). Use --plain to get just the enhanced prompt text.
"""
from __future__ import annotations
import argparse, json, sys

# ──────────────────────────────────────────────────────────────────────────────
# 9-dimensional cinematic quality checklist
# ──────────────────────────────────────────────────────────────────────────────
DIMENSIONS = [
    ("shot_type",
     "Shot type",
     "close-up, medium shot, wide shot, over-the-shoulder, top-down, low angle",
     ["close-up", "medium", "wide", "over-the-shoulder", "top-down", "low angle", "POV"]),
    ("camera_movement",
     "Camera movement",
     "static, slow push-in, dolly, gentle handheld sway, slow pull-out",
     ["static", "push-in", "dolly", "handheld", "pull-out", "slow pan", "rack focus", "tracking"]),
    ("subject_specificity",
     "Subject specificity (chef + action + dish)",
     "Real chef name, what they're doing, exactly which dish",
     []),  # checked separately via --chef-name / --dish presence
    ("setting_detail",
     "Setting (modern apartment kitchen)",
     "Specific kitchen surface, splashback, storage, window. NO village/clay-pot styling.",
     ["kitchen", "apartment", "modern", "tile", "splashback", "cabinet", "window"]),
    ("action_arc",
     "Action across the duration",
     "What happens at 0s, 2s, 5s — a concrete micro-narrative, not a freeze frame",
     ["stirs", "ladles", "pours", "lifts", "smiles", "looks", "garnishes", "plates",
      "tastes", "wipes", "adjusts"]),
    ("lighting",
     "Lighting",
     "Natural window light from left/right, golden hour, soft side light",
     ["natural", "window", "soft", "warm", "golden", "side light", "backlight", "morning"]),
    ("mood_pace",
     "Mood / pacing",
     "Intimate & calm, joyful & quick, contemplative, energetic, etc.",
     ["intimate", "calm", "warm", "joyful", "contemplative", "energetic", "focused", "tender"]),
    ("audio_direction",
     "Audio direction (Seedance respects this)",
     "Ambient kitchen sounds (sizzle, scrape, pour) + optional soft background music",
     ["sizzle", "ambient", "pour", "scrape", "soft", "music", "ASMR", "instrumental"]),
    ("technical_spec",
     "Technical: duration + aspect ratio + resolution",
     "Always include duration in seconds and 9:16 aspect for Reels",
     ["9:16", "duration", "seconds", "1080p", "720p"]),
]

# ──────────────────────────────────────────────────────────────────────────────
# Brand requirements that must be in every prompt
# ──────────────────────────────────────────────────────────────────────────────
BRAND_BLOCK = (
    "Bhookle brand style: warm ochre and terracotta colour palette, modern Indian "
    "apartment kitchen (not village styling — NO clay pots, NO mud handis, NO stone "
    "chulhas unless festival/heritage post). Editorial documentary feel — real person, "
    "real expression, real kitchen. Natural daylight. Photorealistic, not stylised. "
    "No artificial brightness, no plastic food styling."
)

ASMR_AUDIO_BLOCK = (
    "Audio: ASMR — capture only the natural ambient sounds (sizzle, scrape, pour, "
    "crackle). No background music. The sound design IS the content."
)

DEFAULT_AUDIO_BLOCK = (
    "Audio: warm ambient kitchen sounds (gentle pot stir, soft sizzle, quiet pour). "
    "Optional soft instrumental — tabla intro or sarod underlay — at low volume so "
    "the kitchen sounds remain present."
)


def diagnose(base_prompt: str, args) -> list[dict]:
    """Return a list of gaps with severity and a suggested fix per missing dimension."""
    text = base_prompt.lower()
    gaps = []

    for key, label, hint, keywords in DIMENSIONS:
        present = False

        # Special check: subject specificity needs chef name + dish from args
        if key == "subject_specificity":
            if args.chef_name and args.dish:
                present = True
            else:
                gaps.append({
                    "dimension": label,
                    "severity":  "high",
                    "issue":     "Missing chef name and/or dish — without specifics, the video reads as a generic stock cooking shot.",
                    "fix":       f"Provide --chef-name and --dish (e.g. 'Chef A. Sample plating his slow-cooked dal tadka').",
                })
                continue

        # Keyword presence check
        if keywords:
            present = any(kw in text for kw in keywords)

        if not present:
            gaps.append({
                "dimension": label,
                "severity":  "medium" if key in ("audio_direction", "mood_pace", "technical_spec") else "high",
                "issue":     f"No explicit {label.lower()} specified.",
                "fix":       f"Add: {hint}",
            })

    return gaps


def build_enhanced(base_prompt: str, args, gaps: list[dict]) -> str:
    """Stitch a final hyper-realistic prompt from base + missing-dimension fills."""
    parts = []

    # 1. Hero scene line — always rebuild this from args if chef/dish provided
    if args.chef_name and args.dish:
        scene = f"{args.shot_type} cinematic video of {args.chef_name}"
        if args.city:
            scene += f" in {args.city}"
        scene += f", in their modern home kitchen, {args.action or 'preparing'} {args.dish}"
        if args.cuisine:
            scene += f" — a {args.cuisine} dish"
        parts.append(scene + ".")

    # 2. Original PostGenPrompt content — keep its specificity but trim Higgsfield-style noise
    parts.append("Source brief: " + base_prompt.strip())

    # 3. Camera movement
    parts.append(f"Camera: {args.camera_movement}.")

    # 4. Action arc — concrete micro-narrative for the duration
    if args.action_arc:
        parts.append(f"Action across {args.duration}s: {args.action_arc}.")
    else:
        # Build a default arc
        parts.append(
            f"Action across {args.duration}s: hands work the dish in the first half; "
            f"chef looks at camera with a small confident smile in the second half; "
            f"steam visible throughout."
        )

    # 5. Lighting
    parts.append(f"Lighting: {args.lighting}.")

    # 6. Mood
    parts.append(f"Mood: {args.mood}.")

    # 7. Setting reinforcement (modern apartment kitchen ban-list)
    parts.append(
        "Setting: modern Indian apartment kitchen. Specific details: " + (args.kitchen_detail or
        "white subway tile splashback, modular cabinets, gas cooktop, hand-labeled glass spice jars on an open wooden shelf, window with daylight from the left, no clay pots, no mud handis, no village styling.")
    )

    # 8. Audio
    parts.append(ASMR_AUDIO_BLOCK if args.asmr else DEFAULT_AUDIO_BLOCK)

    # 9. Brand block
    parts.append(BRAND_BLOCK)

    # 10. Technical
    parts.append(f"Technical: {args.duration} seconds, 9:16 vertical, 1080p, photorealistic.")

    # 11. Reference image hint
    if args.has_ref_image:
        parts.append(
            "Identity: the first frame should match the supplied reference image. "
            "Preserve the chef's face, complexion, hair, and body proportions exactly."
        )

    return "\n\n".join(parts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base",           required=True, help="Raw PostGenPrompt text")
    p.add_argument("--chef-name",      default=None)
    p.add_argument("--dish",           default=None)
    p.add_argument("--city",           default=None)
    p.add_argument("--cuisine",        default=None)
    p.add_argument("--action",         default=None,
                   help="One-line summary of the action: 'plating', 'ladling', 'stirring'")
    p.add_argument("--action-arc",     default=None,
                   help="Specific micro-narrative across duration (override default)")
    p.add_argument("--duration",       type=int, default=5)
    p.add_argument("--shot-type",      default="Close-up to medium")
    p.add_argument("--camera-movement", default="static with very subtle handheld breathing, no fast moves")
    p.add_argument("--lighting",       default="natural window light from the left, warm and soft, no artificial brightness")
    p.add_argument("--mood",           default="warm, intimate, focused — the rhythm of a kitchen at work")
    p.add_argument("--kitchen-detail", default=None,
                   help="Specific kitchen details — see SKILL.md kitchen-variety table")
    p.add_argument("--asmr",           action="store_true",
                   help="ASMR Reel — strips music, keeps only natural sound")
    p.add_argument("--has-ref-image",  action="store_true",
                   help="A chef-ref or catalogue frame will be passed to higgsfield as --image")
    p.add_argument("--plain",          action="store_true",
                   help="Output only the enhanced prompt text (no JSON)")
    args = p.parse_args()

    gaps = diagnose(args.base, args)
    enhanced = build_enhanced(args.base, args, gaps)

    if args.plain:
        print(enhanced)
        return

    print(json.dumps({
        "critique":        gaps,
        "enhanced_prompt": enhanced,
        "score": {
            "dimensions_total":  len(DIMENSIONS),
            "dimensions_filled": len(DIMENSIONS) - len(gaps),
            "ready_to_generate": all(g["severity"] != "high" for g in gaps),
        },
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
