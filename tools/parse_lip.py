"""Parser for The Last Story `.lip` (lip-sync) files -- LastWorld engine.

Format: PLAINTEXT TSV, CRLF line endings.
    Line 0 (header): <nFrame>\t<fps>\t; TotalData\tFPS
    Lines 1..N:      <frame>\t<viseme>\t<weight>

The file is named after its audio stream, which is the BRIDGE to the audio side:
    VO_EV0101_010.lip  <->  VO_EV0101_010.brstm / .ogg
    SE_VOTWN_680.lip   <->  SE_VOTWN_680.brstm

Observed visemes: A E I O U (Japanese vowels) + SLT (silent, mouth closed).
The third field is the viseme WEIGHT/amplitude (0..1), not a timestamp: the
time of frame k is simply k / fps seconds.

CLI:
    python parse_lip.py FILE.lip            # summary
    python parse_lip.py FILE.lip --json     # JSON timeline
    python parse_lip.py FILE.lip --csv      # frame,time_s,viseme,weight
"""
import sys, json


def parse(text):
    """Return dict {fps, nframe, frames:[{frame, viseme, weight}]}."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"fps": 0.0, "nframe": 0, "frames": []}

    hdr = lines[0].split("\t")
    nframe = int(hdr[0]) if hdr and hdr[0].strip().isdigit() else 0
    try:
        fps = float(hdr[1])
    except (IndexError, ValueError):
        fps = 30.0

    frames = []
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        try:
            fr = int(parts[0])
            wt = float(parts[2])
        except ValueError:
            continue
        frames.append({"frame": fr, "viseme": parts[1], "weight": wt})

    return {"fps": fps, "nframe": nframe, "frames": frames}


def parse_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


def viseme_histogram(data):
    hist = {}
    for fr in data["frames"]:
        hist[fr["viseme"]] = hist.get(fr["viseme"], 0) + 1
    return hist


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    flags = sys.argv[2:]
    data = parse_file(path)

    if "--json" in flags:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if "--csv" in flags:
        fps = data["fps"] or 30.0
        print("frame,time_s,viseme,weight")
        for fr in data["frames"]:
            print(f"{fr['frame']},{fr['frame']/fps:.4f},{fr['viseme']},{fr['weight']:.6f}")
        return

    dur = (data["nframe"] / data["fps"]) if data["fps"] else 0.0
    print(f"{path}")
    print(f"  frames declared: {data['nframe']}   read: {len(data['frames'])}")
    print(f"  fps: {data['fps']}   duration: {dur:.2f}s")
    print(f"  visemes: {viseme_histogram(data)}")


if __name__ == "__main__":
    _cli()
