#!/usr/bin/env python3
"""Generate a raw video clip. Engine = veo (default) or higgsfield (opt-in).
Hard time cap via --max-seconds so a hung job can never crash the machine.

Usage:
  generate_video.py --engine veo --image frame.png --prompt "<motion>" \
      --duration 8 --aspect 9:16 --out raw.mp4 --max-seconds 480
  generate_video.py --engine higgsfield --model seedance_2_0 --prompt "..." \
      --duration 8 --out raw.mp4 --max-seconds 480
"""
import argparse, base64, os, sys, time, subprocess, shutil
import requests

API_KEY = os.environ.get("GEMINI_API_KEY", "")
VEO = "veo-3.1-fast-generate-preview"


def veo(a):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{VEO}:predictLongRunning?key={API_KEY}"
    inst = {"prompt": a.prompt}
    if a.image:
        with open(a.image, "rb") as f:
            inst["image"] = {"bytesBase64Encoded": base64.b64encode(f.read()).decode(),
                             "mimeType": "image/png"}
    payload = {"instances": [inst],
               "parameters": {"aspectRatio": a.aspect, "durationSeconds": a.duration}}
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    op = r.json()["name"]

    deadline = time.time() + a.max_seconds
    while time.time() < deadline:
        st = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{op}?key={API_KEY}",
                          timeout=30).json()
        if st.get("done"):
            if st.get("error"):
                raise RuntimeError(f"Veo failed: {st['error']}")
            resp = st["response"]
            samples = resp.get("generateVideoResponse", {}).get("generatedSamples", [])
            uri = samples[0]["video"]["uri"] if samples else None
            if not uri:
                preds = resp.get("predictions", [])
                if preds and "bytesBase64Encoded" in preds[0]:
                    open(a.out, "wb").write(base64.b64decode(preds[0]["bytesBase64Encoded"]))
                    return
                uri = preds[0].get("video", {}).get("uri") if preds else None
            dl = uri if "key=" in uri else f"{uri}{'&' if '?' in uri else '?'}key={API_KEY}"
            open(a.out, "wb").write(requests.get(dl, timeout=120).content)
            return
        time.sleep(15)
    raise TimeoutError(f"Veo exceeded {a.max_seconds}s — aborting (no machine hang).")


def higgsfield(a):
    if not shutil.which("higgsfield"):
        raise RuntimeError("higgsfield CLI not installed; cannot use Higgsfield engine.")
    cmd = ["higgsfield", "generate", "create", "--prompt", a.prompt,
           "--model", a.model, "--duration", str(a.duration),
           "--aspect", a.aspect, "--output", a.out, "--wait"]
    if a.image:
        cmd += ["--image", a.image]
    # subprocess timeout is the hard cap.
    subprocess.run(cmd, timeout=a.max_seconds, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["veo", "higgsfield"], default="veo")
    ap.add_argument("--image")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--model", default="seedance_2_0")
    ap.add_argument("--duration", type=int, default=8)
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seconds", type=float, default=480)
    a = ap.parse_args()

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    (veo if a.engine == "veo" else higgsfield)(a)
    if not os.path.exists(a.out) or os.path.getsize(a.out) < 10000:
        print("ERROR: output missing or too small", file=sys.stderr)
        sys.exit(1)
    print(f"GEN_OK {a.engine} -> {a.out} ({os.path.getsize(a.out)//1024}KB)")


if __name__ == "__main__":
    main()
