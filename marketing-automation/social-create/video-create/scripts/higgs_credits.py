#!/usr/bin/env python3
"""Higgsfield CREDIT GUARD (req #6). Run BEFORE any Higgsfield spend.

Prints credits available, estimated cost for the requested reel, and remaining-after.
Exit code 0 = sufficient (safe to proceed); 1 = insufficient or unknown (BLOCK).

Usage:
  higgs_credits.py --duration 8 --model seedance_2_0
"""
import argparse, re, shutil, subprocess, sys

# Approx credit cost per second by model (tune as Higgsfield pricing changes).
COST_PER_SEC = {
    "seedance_2_0": 4.5,
    "kling3_0": 7.0,
    "marketing_studio_video": 6.0,
}


def get_credits():
    """Parse `higgsfield account status` for a credit balance. Returns int or None."""
    if not shutil.which("higgsfield"):
        return None, "higgsfield CLI not installed"
    try:
        out = subprocess.run(["higgsfield", "account", "status"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception as e:
        return None, f"could not query account: {e}"
    m = re.search(r"([\d,]+)\s*credits", out, re.I)
    if not m:
        return None, "could not parse credit balance"
    return int(m.group(1).replace(",", "")), out.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=8)
    ap.add_argument("--model", default="seedance_2_0")
    a = ap.parse_args()

    per = COST_PER_SEC.get(a.model, 5.0)
    est = round(per * a.duration)

    avail, info = get_credits()
    print(f"Model: {a.model}  |  Duration: {a.duration}s  |  Est cost: ~{est} credits")
    if avail is None:
        print(f"BLOCK: {info}")
        print("Cannot verify Higgsfield credits — do NOT spend. Fall back to Google/Ultra.")
        sys.exit(1)

    remaining = avail - est
    print(f"Credits available: {avail}")
    print(f"Remaining after this reel: {remaining}")
    if remaining < 0:
        print("BLOCK: insufficient credits for this reel. Use Google/Ultra or top up.")
        sys.exit(1)
    if remaining < est:  # less than one more reel's worth
        print("WARN: this would leave less than one more reel's worth of credits.")
    print("OK: sufficient credits. Confirm 'go' before spending.")
    sys.exit(0)


if __name__ == "__main__":
    main()
