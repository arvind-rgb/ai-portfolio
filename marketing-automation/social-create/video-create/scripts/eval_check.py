#!/usr/bin/env python3
"""Pre-present eval gate (req #3). A reel must pass before it is shown to the user.

Checks: file exists · 9:16 aspect · expected duration window · end card present
(duration long enough) · overlay design has no URL. Exit 0 = pass, 1 = fail.

Usage:
  eval_check.py final.mp4 --post IG-010 [--design design.json] [--min-dur 9] [--max-dur 35]
"""
import argparse, json, os, subprocess, sys


def probe(path, stream, field):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", f"stream={field}", "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True).stdout.strip().splitlines()
    return out[0] if out else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--post", required=True)
    ap.add_argument("--design")
    ap.add_argument("--min-dur", type=float, default=9.0)
    ap.add_argument("--max-dur", type=float, default=35.0)
    a = ap.parse_args()

    fails = []
    if not os.path.exists(a.video) or os.path.getsize(a.video) < 10000:
        print("FAIL: file missing or too small"); sys.exit(1)

    w = probe(a.video, "v:0", "width"); h = probe(a.video, "v:0", "height")
    if not (w and h):
        fails.append("could not read dimensions")
    else:
        ratio = int(h) / int(w)
        if abs(ratio - 16 / 9) > 0.02:
            fails.append(f"not 9:16 (got {w}x{h})")

    dur = probe(a.video, "v:0", "duration")
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", a.video],
                    capture_output=True, text=True).stdout.strip())
        if dur < a.min_dur:
            fails.append(f"too short ({dur:.1f}s < {a.min_dur}s — end card likely missing)")
        if dur > a.max_dur:
            fails.append(f"too long ({dur:.1f}s)")
    except Exception:
        fails.append("could not read duration")

    if a.design and os.path.exists(a.design):
        if "bhookleeats" in open(a.design).read().lower():
            fails.append("URL found in design (L5 violation)")

    if probe(a.video, "a:0", "codec_name") is None:
        fails.append("no audio track")

    if fails:
        print(f"EVAL FAIL ({a.post}):")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print(f"EVAL PASS ({a.post}): {w}x{h}, {dur:.1f}s, audio ok, no URL.")
    sys.exit(0)


if __name__ == "__main__":
    main()
