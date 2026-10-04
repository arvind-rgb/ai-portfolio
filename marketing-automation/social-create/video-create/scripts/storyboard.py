#!/usr/bin/env python3
"""Storyboard key frames with nano-banana (Gemini Flash image). Clean, NO text.

Usage:
  storyboard.py --post IG-010 --prompt "<scene>" --frames 2 --out /tmp/vc/IG-010 [--max-seconds 180]
"""
import argparse, base64, io, os, sys, time
import requests
from PIL import Image

API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3.1-flash-image-preview"  # nano-banana


def gen_one(prompt, deadline):
    if time.time() > deadline:
        raise TimeoutError("storyboard deadline exceeded")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    r = requests.post(url, json=payload, timeout=90).json()
    for part in r.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            return Image.open(io.BytesIO(base64.b64decode(part["inlineData"]["data"]))).convert("RGB")
    raise RuntimeError(str(r)[:200])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--frames", type=int, default=2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seconds", type=float, default=180)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    deadline = time.time() + a.max_seconds
    base = a.prompt.strip().rstrip(".") + ". NO text, NO overlays, NO watermarks. Vertical 9:16."

    paths = []
    for i in range(1, a.frames + 1):
        p = base if i == 1 else base + f" Alternate angle / moment {i}."
        img = gen_one(p, deadline)
        img = img.resize((1080, int(img.height * 1080 / img.width)), Image.LANCZOS)
        out = os.path.join(a.out, f"frame{i}.png")
        img.save(out, "PNG")
        paths.append(out)
        print(f"frame{i}: {out}")

    print("STORYBOARD_OK " + " ".join(paths))


if __name__ == "__main__":
    main()
