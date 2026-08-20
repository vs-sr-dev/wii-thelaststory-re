"""Does the last frame repeat the first (the N+1 convention)?

Per-track test, needing no model. For every animated track it compares the
WRAP JUMP against the typical interior step:

    wrap = |v(N-1) - v(0)|          how far you jump returning to the start
    step = median |v(i+1) - v(i)|   how far an ordinary frame moves
    r    = wrap / step

  r ~ 0  -> v(N-1) == v(0): the last frame REPEATS the first, the true period
            is N-1 and the last frame must be dropped for a clean loop.
  r ~ 1  -> the wrap is a step like any other: the period is exactly N and the
            last frame is a real frame, to be kept.

The MEDIAN of r is taken over tracks with non-negligible excursion, so flat
tracks and gimbal-locked ones do not skew the result.

BOTH conventions occur in this game and encode the SAME period, so no single
rule can be applied globally -- see docs/10-animation.md for the evidence.
"""
import glob
import os
import statistics
import sys

import motion as mo

MOTDIR = "../assets/pack/filesystem/data/motion"


def ratio(d, mot, min_span=1e-3):
    """Median of wrap/step over the significant tracks, or None."""
    N = int(round(mot["frameCount"]))
    if N < 4:
        return None, 0
    rs = []
    for b in mot["bones"]:
        for tr in b["tracks"]:
            if tr["fmt"] == mo.FMT_CONST:
                continue
            v = [mo.eval_track(d, tr, float(i)) for i in range(N)]
            span = max(v) - min(v)
            if span < min_span:
                continue
            steps = [abs(v[i + 1] - v[i]) for i in range(N - 1)]
            st = statistics.median(steps)
            if st < 1e-9:
                continue
            rs.append(abs(v[-1] - v[0]) / st)
    if not rs:
        return None, 0
    return statistics.median(rs), len(rs)


def main():
    pats = sys.argv[1:] or ["na000_wtn00_*", "na000_wkn00_*", "na000_rnn00_*",
                            "an008_*"]
    paths = []
    for p in pats:
        paths += sorted(glob.glob(os.path.join(MOTDIR, p + ".motion")))
        paths += sorted(glob.glob(os.path.join(MOTDIR, p)))
    print(f"{'file':<32}{'N':>5}{'tracks':>8}{'wrap/step':>11}   verdict")
    for p in paths:
        d = open(p, "rb").read()
        mot = mo.parse(d)
        r, n = ratio(d, mot)
        if r is None:
            print(f"{os.path.basename(p):<32}{int(mot['frameCount']):>5}"
                  f"{'-':>8}{'-':>11}   (static / too short)")
            continue
        if r < 0.25:
            verdict = "LAST FRAME = FIRST  -> drop it"
        elif r < 2.5:
            verdict = "N-frame loop, no duplicate"
        else:
            verdict = "not cyclic (start != end)"
        print(f"{os.path.basename(p):<32}{int(mot['frameCount']):>5}{n:>8}"
              f"{r:>11.2f}   {verdict}")


if __name__ == "__main__":
    main()
