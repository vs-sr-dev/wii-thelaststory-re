"""Measure a locomotion clip's real PERIOD, without assuming it.

Method: a walk/run cycle is symmetric -- the left leg traces the same curve as
the right one, half a period out of phase. So the period is MEASURED by finding
the shift L that minimises

    sum_t | leftfoot(t) - mirror(rightfoot(t + L)) |

where mirror flips the X axis (right/left). If the true period is P, the minimum
falls at L = P/2.

CAVEAT: sampling with a candidate P > N is biased. Past the last keyframe
eval_track clamps, so a tail of frozen pose lowers the mismatch artificially and
larger P always looks better. Use this as corroboration, not as the primary
test -- loop_closure.py is the decisive one.

Uses world positions, not the Euler channels (gimbal-locked on hips).
"""
import math
import sys

import motion as mo
import parse_model as pm

SUB = 4          # sub-samples per frame, for 0.25-frame resolution


def sample(md, model, ad, mot, bones, P, nsteps):
    """Sample `bones` at nsteps evenly spaced instants over a period P."""
    out = {b: [] for b in bones}
    for k in range(nsteps):
        t = P * k / nsteps
        nodes, w = mo.world_matrices_at(md, model, ad, mot, t)
        idx = {n["name"]: i for i, n in enumerate(nodes)}
        for b in bones:
            m = w[idx[b]]
            out[b].append((m[0][3], m[1][3], m[2][3]))
    return out


def mismatch(L, left, right, nsteps):
    """Mean error between the left foot and the mirrored right one, shifted L."""
    e = 0.0
    for k in range(nsteps):
        a = left[k]
        b = right[(k + L) % nsteps]
        e += math.dist((a[0], a[1], a[2]), (-b[0], b[1], b[2]))
    return e / nsteps


def main():
    mpath, apath = sys.argv[1], sys.argv[2]
    md = open(mpath, "rb").read()
    model = pm.parse(md)
    ad = open(apath, "rb").read()
    mot = mo.parse(ad)
    N = int(round(mot["frameCount"]))
    print(f"{apath.split('/')[-1]}   frameCount={mot['frameCount']:g}\n")

    print("hypothesis   best shift   error    implied period")
    best = None
    for P in (N - 1, N, N + 1):
        nsteps = P * SUB
        s = sample(md, model, ad, mot, ("leftfoot", "rightfoot"), P, nsteps)
        cand = [(mismatch(L, s["leftfoot"], s["rightfoot"], nsteps), L)
                for L in range(nsteps)]
        err, L = min(cand)
        half = L / SUB * (P / N) if False else L / SUB
        print(f"  P={P:<5}  L={half:6.2f} frames     {err:7.4f}   "
              f"2L = {2*half:.2f}")
        if best is None or err < best[0]:
            best = (err, P, 2 * half)
    print(f"\n=> measured period {best[2]:.2f} frames under hypothesis P={best[1]} "
          f"(error {best[0]:.4f})")
    print(f"   declared frameCount = {N}")


if __name__ == "__main__":
    main()
