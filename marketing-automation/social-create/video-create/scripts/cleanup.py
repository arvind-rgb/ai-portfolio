#!/usr/bin/env python3
"""Clean up /tmp working dirs (req #7 — leave no scratch behind).

Usage:
  cleanup.py --post IG-010      # remove /tmp/vc/IG-010/
  cleanup.py --all              # remove /tmp/vc/ entirely + known stray scratch
"""
import argparse, glob, os, shutil

VC_ROOT = "/tmp/vc"
# Stray patterns produced during ad-hoc runs (safe to remove — all regenerable).
STRAY = ["/tmp/IG-*_base.png", "/tmp/IG-*_overlay.png", "/tmp/IG-*_raw.mp4",
         "/tmp/IG-*_body.mp4", "/tmp/IG-*_end.mp4", "/tmp/IG-*_concat.txt",
         "/tmp/IG-*_check_*.jpg", "/tmp/IG-*_frame*.jpg", "/tmp/IG-*_f_*.jpg",
         "/tmp/IG-*_contact.jpg", "/tmp/IG-*_source.mp4",
         "/tmp/LI-*.png", "/tmp/li_prompts.json", "/tmp/li2.json",
         "/tmp/veo_*.json", "/tmp/veo_*.py", "/tmp/build_li_carousels.py"]


def rm(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path); return True
        if os.path.exists(path):
            os.remove(path); return True
    except Exception as e:
        print(f"  could not remove {path}: {e}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    n = 0
    if a.post:
        if rm(os.path.join(VC_ROOT, a.post)):
            n += 1
    if a.all:
        if rm(VC_ROOT):
            n += 1
        for pat in STRAY:
            for f in glob.glob(pat):
                if rm(f):
                    n += 1
    print(f"CLEANUP_OK removed {n} item(s)")


if __name__ == "__main__":
    main()
