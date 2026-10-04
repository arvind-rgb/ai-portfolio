#!/usr/bin/env python3
"""
extract_thumbnails.py — Pull 3 representative frames from a generated .mp4 so
Claude can Read-display them inline as a video preview (since Read does not
support .mp4).

Outputs three JPGs (start / middle / end) into a `thumbs/` subfolder alongside
the source video, plus a combined strip image for a single-image preview.

Usage:
  python3 extract_thumbnails.py <video_path> [--out-dir <dir>]

Prints JSON with all four image paths.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path


def ffprobe_duration(video: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, timeout=30,
    )
    return float(r.stdout.strip())


def grab_frame(video: Path, t: float, out_frame: Path):
    out_frame.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-ss", f"{t:.2f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", str(out_frame)],
        capture_output=True, text=True, timeout=60, check=True,
    )


def make_strip(frames: list[Path], out_strip: Path):
    """Combine N frames vertically into one tall image for a single-Read preview."""
    out_strip.parent.mkdir(parents=True, exist_ok=True)
    # Use ffmpeg vstack
    inputs = []
    for f in frames:
        inputs += ["-i", str(f)]
    filter_arg = "".join(f"[{i}:v]" for i in range(len(frames))) + f"vstack=inputs={len(frames)}"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + ["-filter_complex", filter_arg, str(out_strip)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")

    out_dir = Path(args.out_dir) if args.out_dir else (video.parent / "thumbs")
    out_dir.mkdir(parents=True, exist_ok=True)

    dur = ffprobe_duration(video)
    if dur <= 0:
        sys.exit("could not determine video duration")

    # Three sample points: ~0.5s in, middle, and ~0.5s before end
    times = [
        min(0.5, dur * 0.1),
        dur / 2.0,
        max(0.5, dur - 0.5),
    ]

    frame_paths = []
    for i, t in enumerate(times, 1):
        out = out_dir / f"{video.stem}-t{i}.jpg"
        grab_frame(video, t, out)
        frame_paths.append(out)

    strip = out_dir / f"{video.stem}-strip.jpg"
    try:
        make_strip(frame_paths, strip)
    except subprocess.CalledProcessError:
        strip = None

    print(json.dumps({
        "duration_seconds": dur,
        "frames": [str(p.resolve()) for p in frame_paths],
        "strip":  str(strip.resolve()) if strip else None,
    }, indent=2))


if __name__ == "__main__":
    main()
