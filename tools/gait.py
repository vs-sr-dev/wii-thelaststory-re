"""Does the walk cycle advance? does it loop? how fast is it?

Works in WORLD SPACE, not on the Euler channels: the `hips` curves are in
gimbal lock (rotY = -pi/2 constant, so rotX and rotZ cancel out and swing with
no geometric meaning). Comparing the channels would give wrong answers.

    python gait.py MODEL MOTION            # trajectory + loop closure
    python gait.py MODEL MOTION --speed    # + the clip's implied step speed
"""
import math
import sys

import motion as mo
import parse_model as pm


def trajectory(md, model, ad, mot, bones, frames):
    """{bone: [(x,y,z) for each t in frames]}."""
    out = {b: [] for b in bones}
    for t in frames:
        nodes, world = mo.world_matrices_at(md, model, ad, mot, t)
        idx = {n["name"]: i for i, n in enumerate(nodes)}
        for b in bones:
            w = world[idx[b]]
            out[b].append((w[0][3], w[1][3], w[2][3]))
    return out


def _d(a, b):
    return math.dist(a, b)


def main():
    mpath, apath = sys.argv[1], sys.argv[2]
    md = open(mpath, "rb").read()
    model = pm.parse(md)
    ad = open(apath, "rb").read()
    mot = mo.parse(ad)
    N = int(round(mot["frameCount"]))
    names = {n["name"] for n in model["chunks"]["node"]}
    animated = {b["name"] for b in mot["bones"]}

    watch = [b for b in ("nw4r_root", "reference", "hips", "leftfoot",
                         "righttoes", "lefttoes", "rightfoot") if b in names]
    print(f"model={mpath.split('/')[-1]}  motion={apath.split('/')[-1]}")
    print(f"frameCount={mot['frameCount']:g} -> frame 0..{N-1}")
    print(f"animated bones {len(animated)}, of which present in the skeleton "
          f"{len(animated & names)}\n")

    frames = list(range(N))
    tr = trajectory(md, model, ad, mot, watch, frames)

    # ---- 0a: avanzamento netto della root -------------------------------
    print("--- world trajectory (frame 0 / mid / N-1) ---")
    for b in watch:
        p = tr[b]
        h = N // 2
        print(f"  {b:<12} f0=({p[0][0]:+8.3f},{p[0][1]:+8.3f},{p[0][2]:+8.3f})"
              f"  f{h}=({p[h][0]:+8.3f},{p[h][1]:+8.3f},{p[h][2]:+8.3f})"
              f"  f{N-1}=({p[-1][0]:+8.3f},{p[-1][1]:+8.3f},{p[-1][2]:+8.3f})")

    print("\n--- per-axis excursion (max-min) and net drift (f[N-1]-f[0]) ---")
    for b in watch:
        p = tr[b]
        for ax, nm in enumerate("XYZ"):
            v = [q[ax] for q in p]
            span = max(v) - min(v)
            drift = v[-1] - v[0]
            flag = ""
            if span > 1e-4 and abs(drift) > 0.6 * span:
                flag = "  <== MONOTONIC (advancing)"
            print(f"  {b:<12}{nm}  span={span:8.4f}  drift={drift:+8.4f}{flag}")
        print()

    # ---- 0b: chiusura del loop ------------------------------------------
    print("--- loop closure (world distance between frame i and frame 0) ---")
    for b in watch:
        p = tr[b]
        # mean step between consecutive frames, as a yardstick
        step = sum(_d(p[i], p[i + 1]) for i in range(N - 1)) / (N - 1)
        print(f"  {b:<12} mean step/frame={step:7.4f}   "
              f"|f{N-1}-f0|={_d(p[-1], p[0]):7.4f}   "
              f"|f{N-2}-f0|={_d(p[-2], p[0]):7.4f}")

    if "--speed" not in sys.argv:
        return

    # ---- the clip's implied step speed -----------------------------------
    # A planted foot is stationary with respect to the GROUND. If the
    # character does not translate, the foot slides backwards in the data,
    # and that slide is exactly the advance the root has to make.
    print("\n--- foot stance phase (world, relative to the root) ---")
    fps = 30.0
    for foot in ("leftfoot", "rightfoot"):
        if foot not in tr:
            continue
        p = tr[foot]
        ys = [q[1] for q in p]
        lo, hi = min(ys), max(ys)
        thr = lo + 0.25 * (hi - lo)
        planted = [i for i in range(N) if ys[i] <= thr]
        # horizontal velocity frame by frame during stance
        vel = []
        for i in planted:
            j = (i + 1) % N
            vel.append((p[j][0] - p[i][0], p[j][2] - p[i][2]))
        print(f"  {foot}: Y in [{lo:.3f},{hi:.3f}], stance over {len(planted)}"
              f"/{N} frames  (threshold Y<={thr:.3f})")
        if planted:
            vx = sum(v[0] for v in vel) / len(vel)
            vz = sum(v[1] for v in vel) / len(vel)
            sp = math.hypot(vx, vz)
            print(f"    mean stance slide = ({vx:+.4f},{vz:+.4f}) "
                  f"per frame  |v|={sp:.4f}")
            print(f"    -> root should advance {-vx:+.4f},{-vz:+.4f} /frame"
                  f"  = {sp*fps:.3f} units/s at {fps:g}fps")


if __name__ == "__main__":
    main()
