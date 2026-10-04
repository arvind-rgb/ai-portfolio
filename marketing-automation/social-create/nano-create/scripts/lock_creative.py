#!/usr/bin/env python3
"""
lock_creative.py — Finalise an approved Nano Banana variant.

Steps:
  1. Copy the chosen variant from temp/ to the final output folder, renamed to <POSTID>.png
  2. Update the corresponding row in the social-planner xlsx:
        PostStatus = "Creative Locked"
        PostOutput = absolute path to the final image
  3. Clean up the temp variants folder for that post

Usage:
  python3 lock_creative.py <xlsx_path> <post_id> <variant_num> \
      --temp-dir <tmp/nanobanana_variants> \
      --output-dir <assets/social/2026-06>
"""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl not installed. Run: pip install openpyxl")


def header_index(ws):
    return {
        (ws.cell(1, c).value or "").strip(): c
        for c in range(1, ws.max_column + 1)
        if ws.cell(1, c).value
    }


def find_post_row(wb, post_id: str):
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        cols = header_index(ws)
        if "PostID" not in cols:
            continue
        for r in range(2, ws.max_row + 1):
            if (ws.cell(r, cols["PostID"]).value or "").strip().upper() == post_id.upper():
                return ws, r, cols
    return None, None, None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("xlsx")
    p.add_argument("post_id")
    p.add_argument("variant_num", type=int)
    p.add_argument("--temp-dir",   required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--slide", type=int, default=None,
                   help="Slide number for multi-slide carousels. Output becomes <POSTID>-slide<N>.png. "
                        "Variant is looked up in <temp-dir>/<POSTID>/slide<N>/v<variant>.png.")
    p.add_argument("--keep-temp-other-slides", action="store_true",
                   help="When locking one slide of a multi-slide carousel, leave the other slides' temp folders intact.")
    args = p.parse_args()

    post_id = args.post_id.strip().upper()
    slide   = args.slide

    if slide is not None:
        temp_path  = Path(args.temp_dir) / post_id / f"slide{slide}" / f"v{args.variant_num}.png"
        final_name = f"{post_id}-slide{slide}.png"
    else:
        temp_path  = Path(args.temp_dir) / post_id / f"v{args.variant_num}.png"
        final_name = f"{post_id}.png"

    if not temp_path.exists():
        sys.exit(f"variant not found: {temp_path}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = (out_dir / final_name).resolve()
    shutil.copy2(temp_path, final_path)
    print(f"✅ Locked: {final_path}")

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        sys.exit(f"xlsx not found: {xlsx_path}")
    wb = openpyxl.load_workbook(xlsx_path)
    ws, row, cols = find_post_row(wb, post_id)
    if not ws:
        sys.exit(f"post_id {post_id} not found in any sheet of {xlsx_path}")
    if "PostStatus" not in cols:
        sys.exit("xlsx missing PostStatus column")
    ws.cell(row, cols["PostStatus"]).value = "Creative Locked"
    if "PostOutput" in cols:
        # For multi-slide carousels, append to existing PostOutput if present
        existing = (ws.cell(row, cols["PostOutput"]).value or "").strip()
        paths = [p for p in existing.split(",") if p.strip() and p.strip() != str(final_path)]
        paths.append(str(final_path))
        ws.cell(row, cols["PostOutput"]).value = ", ".join(paths)
    wb.save(xlsx_path)
    print(f"✅ Status updated in {xlsx_path.name}: {post_id} → Creative Locked")

    # Cleanup: for single-image posts, remove the whole post folder.
    # For multi-slide locks, only remove the locked slide's folder (unless --keep-temp-other-slides).
    if slide is None:
        temp_post_dir = Path(args.temp_dir) / post_id
        shutil.rmtree(temp_post_dir, ignore_errors=True)
        print(f"🧹 Cleaned temp: {temp_post_dir}")
    else:
        slide_dir = Path(args.temp_dir) / post_id / f"slide{slide}"
        shutil.rmtree(slide_dir, ignore_errors=True)
        print(f"🧹 Cleaned temp slide: {slide_dir}")


if __name__ == "__main__":
    main()
