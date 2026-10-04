#!/usr/bin/env python3
"""
batch_generate.py — Orchestrate variant generation for all pending Nano Banana posts.

Reads /tmp/nbn_batch.json (from list_pending.py --json), generates 3 variants per post,
saves to /tmp/nanobanana_variants/[POSTID]/v[1-3].png.

Handles Gemini's probabilistic safety filter (IMAGE_OTHER finish reason) by retrying up to
8 times per variant — the filter is sampling-based and same prompt often passes on retry.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BATCH_FILE = "/tmp/nbn_batch.json"
DEFAULT_TEMP_DIR   = "/tmp/nanobanana_variants"
DEFAULT_RETRIES    = 8       # safety filter retry budget per variant

GEN_SCRIPT = Path(__file__).parent / "generate_image.py"

BRAND_STYLE = (
    "Bhookle brand style: warm ochre and terracotta colour palette, real home kitchen "
    "textures (steel vessels, clay pots, handwritten masala labels), natural window "
    "light from the left, editorial food photography feel — not commercial stock photo. "
    "Gritty, authentic. No artificial brightness, no plastic food styling, no sterile "
    "white studio backgrounds."
)


def aspect_for(fmt):
    f = (fmt or "").lower()
    if "story" in f or "reel" in f: return "9:16"
    if "document" in f:              return "4:3"
    if "long-form" in f or "single image" in f: return "4:5"
    return "1:1"


def extract_lead_shot(prompt, fmt):
    """For multi-slide / multi-scene prompts, isolate the Slide 1 or Scene 1 brief."""
    f = (fmt or "").lower()
    text = prompt.strip()
    if "carousel" in f or "document" in f or "long-form" in f:
        m = re.search(r"slide\s*1[^:]*:\s*(.+?)(?=slide\s*2|$)", text, re.IGNORECASE | re.DOTALL)
        if m: return m.group(1).strip()
    if "reel" in f:
        m = re.search(r"scene\s*1[^:]*:\s*(.+?)(?=scene\s*2|$)", text, re.IGNORECASE | re.DOTALL)
        if m: return m.group(1).strip()
    return text


def build_prompt(post):
    lead = extract_lead_shot(post["post_gen_prompt"], post["post_format"])
    return f"{lead}\n\n{BRAND_STYLE}"


def gen_with_retry(prompt, output, aspect, max_retries):
    """Generate one image. Retry on safety blocks (IMAGE_OTHER / IMAGE_SAFETY)."""
    env = os.environ.copy()
    for attempt in range(1, max_retries + 1):
        r = subprocess.run(
            ["python3", str(GEN_SCRIPT), prompt, "-o", str(output), "--aspect-ratio", aspect],
            env=env, capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0:
            return True, attempt, ""
        err = r.stderr
        # Retry only on safety blocks — quota/auth errors should fail fast
        if "ERROR_NO_IMAGE" in err or "IMAGE_OTHER" in err or "IMAGE_SAFETY" in err:
            time.sleep(2)
            continue
        return False, attempt, err
    return False, max_retries, "all retries exhausted (persistent safety block)"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--batch-file", default=DEFAULT_BATCH_FILE,
                   help="JSON from list_pending.py --json")
    p.add_argument("--temp-dir",   default=DEFAULT_TEMP_DIR)
    p.add_argument("--retries",    type=int, default=DEFAULT_RETRIES,
                   help="Safety-block retry budget per variant (default 8)")
    p.add_argument("--only-missing", action="store_true",
                   help="Skip variants already on disk — only generate missing ones")
    args = p.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY not set. Run: export GEMINI_API_KEY=<key>")

    data = json.load(open(args.batch_file))
    posts = data["instagram"] + data["linkedin"]
    temp_dir = Path(args.temp_dir)

    targets = []
    for post in posts:
        pdir = temp_dir / post["post_id"]
        pdir.mkdir(parents=True, exist_ok=True)
        for v in (1, 2, 3):
            out = pdir / f"v{v}.png"
            if args.only_missing and out.exists():
                continue
            targets.append((post, v, out))

    if not targets:
        print("Nothing to generate.")
        return

    print(f"Generating {len(targets)} variants ({args.retries}-retry safety budget)\n")
    t0 = time.time()
    ok = fail = 0
    fails = []
    for i, (post, v, out) in enumerate(targets, 1):
        aspect = aspect_for(post["post_format"])
        prompt = build_prompt(post)
        print(f"[{i:3}/{len(targets)}] {post['post_id']}/v{v} ({aspect}) ", end="", flush=True)
        success, attempts, err = gen_with_retry(prompt, out, aspect, args.retries)
        if success:
            print(f"✓ (attempt {attempts})")
            ok += 1
        else:
            print(f"✗ {err[:160].strip()}")
            fail += 1
            fails.append((post["post_id"], v, err[:300]))

    print(f"\n--- Done in {int(time.time()-t0)}s — OK: {ok}  FAIL: {fail} ---")
    if fails:
        print("Persistent failures (consider rewording prompt or skip):")
        for pid, v, e in fails:
            print(f"  {pid}/v{v}: {e}")


if __name__ == "__main__":
    main()
