"""PoC: a The Last Story character WALKING on a real map.

Lines up everything reversed so far:

    .map/.locator/.building  ->  the scene         (build_scene)
    .chr/.mchr               ->  which motion for which state  (parse_chr)
    .model + .motion         ->  skinned animated character    (render_anim)

The three decisions the PoC has to make, and where each comes from:

1. THE PoC DRIVES TRANSLATION. Locomotion clips animate IN PLACE: in
   na000_wkn00_00 the bones `nw4r_root` and `reference` sit at exactly (0,0,0)
   for all 54 frames. No advance is stored in the data.

2. AT WHAT SPEED. Not picked by eye, or the feet skate. It is measured: while a
   foot is planted it is stationary on the ground, so in an in-place clip it
   slides backwards at exactly the travel speed. The plateau is clean and both
   feet agree (see gait.py):
       walk na000_wkn00_00   -0.1808 u/frame  ->   5.42 u/s at 30 fps
       run  na000_rnn00_00   -0.7505 u/frame  ->  22.51 u/s at 30 fps
   The slide is along -Z, so the character advances towards local +Z.

3. HOW LONG THE CYCLE IS. The period is NOT always frameCount: two authoring
   conventions exist (see loop_closure.py), one repeating the first frame at the
   end and one not. Here the period is measured per file rather than assumed,
   otherwise the loop stutters.

The terrain holds the character up via a downward raycast against the mesh,
which is all "walking on a map" needs: the .hocb collision tree is a separate
problem and stays out.

The check that it works is numeric: over a full walk cycle the character's
lowest vertex stays between 4.839 and 5.051 against a floor at Y = 5.000 --
within 1.6 cm at 1 u ~ 10 cm, with no offset applied.

See docs/11-maps-and-scenes.md.

Usage:
    python walk_poc.py                          # default: dg001_01, walk
    python walk_poc.py --map dg002_01.map --state run --frames 48
    python walk_poc.py --props                  # full scene, slower
    python walk_poc.py --x -258.5 --z -60 --dir 270   # explicit start
"""
import math
import os
import sys

import numpy as np
from PIL import Image

import build_scene as bs
import export_obj as eo
import motion as mo
import parse_chr as pc
import parse_model as pm
import render_anim as ra
import render_obj as ro
import skinning as skn

DATA = bs.DATA
MOTDIR = os.path.join(DATA, "motion")
MODELDIR = bs.MODELDIR
CHARDIR = pc.CHARDIR

FPS = 30.0                     # measured, not assumed: see the module docstring


# --------------------------------------------------------------------------
# terrain: height query
# --------------------------------------------------------------------------
class Ground:
    """Terrain height at (x,z), by vertical raycast against the mesh.

    Triangles go into a 2D grid over XZ so a query does not scan the whole map.
    For a point, the triangle containing it in projection is used; if more than
    one does (bridges, stacked floors) the highest surface below a reference
    height wins, which is exactly how a walking character behaves.
    """

    # A healthy terrain triangle, on a ~750 u map with a few thousand faces,
    # is about ten units across. The very long thin ones are the "slivers" left
    # where a strip decode does not close: near-zero area but spanning half the
    # map. Left in, they make the path finder follow fake flat corridors out
    # over empty space. They must come out of the support mesh.
    MAX_EDGE = 80.0
    MIN_ASPECT = 0.02          # 4*area / lato_max^2

    def __init__(self, verts, faces, cell=20.0, filter_slivers=True):
        self.V = np.asarray(verts, np.float64)
        tris = np.array([[f[0], f[1], f[2]] for f in faces], np.int32)
        if filter_slivers and len(tris):
            tris = tris[self._solid_mask(tris)]
        self.tris = tris
        self.cell = cell
        xs, zs = self.V[:, 0], self.V[:, 2]
        self.x0, self.z0 = xs.min(), zs.min()
        self.nx = max(1, int((xs.max() - self.x0) / cell) + 1)
        self.nz = max(1, int((zs.max() - self.z0) / cell) + 1)
        self.grid = {}
        for ti, (a, b, c) in enumerate(self.tris):
            p = self.V[[a, b, c]]
            i0 = int((p[:, 0].min() - self.x0) / cell)
            i1 = int((p[:, 0].max() - self.x0) / cell)
            j0 = int((p[:, 2].min() - self.z0) / cell)
            j1 = int((p[:, 2].max() - self.z0) / cell)
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    self.grid.setdefault((i, j), []).append(ti)

    def _solid_mask(self, tris):
        """True for triangles that can hold a character up."""
        p0, p1, p2 = self.V[tris[:, 0]], self.V[tris[:, 1]], self.V[tris[:, 2]]
        e0 = np.linalg.norm(p1 - p0, axis=1)
        e1 = np.linalg.norm(p2 - p1, axis=1)
        e2 = np.linalg.norm(p0 - p2, axis=1)
        emax = np.maximum(np.maximum(e0, e1), e2)
        area = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            aspect = np.where(emax > 0, 4.0 * area / (emax * emax), 0.0)
        return (emax <= self.MAX_EDGE) & (aspect >= self.MIN_ASPECT)

    def density(self, x, z):
        """How many terrain triangles sit in the cell containing (x,z).

        Keeps the character from starting in the middle of nowhere: real parts
        of the map have dozens of faces per cell, the fringes one or two.
        """
        i = int((x - self.x0) / self.cell)
        j = int((z - self.z0) / self.cell)
        return len(self.grid.get((i, j), ()))

    def hits(self, x, z):
        """Every terrain Y under (x,z), highest first."""
        i = int((x - self.x0) / self.cell)
        j = int((z - self.z0) / self.cell)
        out = []
        for ti in self.grid.get((i, j), ()):
            a, b, c = self.tris[ti]
            p0, p1, p2 = self.V[a], self.V[b], self.V[c]
            # barycentric coordinates in XZ projection
            d = ((p1[2] - p2[2]) * (p0[0] - p2[0]) +
                 (p2[0] - p1[0]) * (p0[2] - p2[2]))
            if abs(d) < 1e-12:
                continue
            w0 = ((p1[2] - p2[2]) * (x - p2[0]) +
                  (p2[0] - p1[0]) * (z - p2[2])) / d
            w1 = ((p2[2] - p0[2]) * (x - p2[0]) +
                  (p0[0] - p2[0]) * (z - p2[2])) / d
            w2 = 1.0 - w0 - w1
            if w0 < -1e-6 or w1 < -1e-6 or w2 < -1e-6:
                continue
            out.append(w0 * p0[1] + w1 * p1[1] + w2 * p2[1])
        out.sort(reverse=True)
        return out

    def height(self, x, z, ref=None, tol=40.0):
        """Support height at (x,z), or None if there is no terrain.

        `ref` is the character's current height: among several surfaces the
        highest one not too far above them wins, so they do not "snap" onto a
        ceiling while walking underneath it.
        """
        hs = self.hits(x, z)
        if not hs:
            return None
        if ref is None:
            return hs[0]
        below = [h for h in hs if h <= ref + tol]
        return below[0] if below else None


# --------------------------------------------------------------------------
# cycle measurement (period and speed)
# --------------------------------------------------------------------------
def measure_cycle(model_path, motion_path):
    """(period in frames, speed in u/frame), both measured from the data."""
    import loop_closure as lc
    md = open(model_path, "rb").read()
    model = pm.parse(md)
    ad = open(motion_path, "rb").read()
    anim = mo.parse(ad)
    N = int(round(anim["frameCount"]))
    r, _ = lc.ratio(ad, anim)
    period = N - 1 if (r is not None and r < 0.25) else N

    # speed: median Z slide of the foot while it is planted
    P = {}
    for t in range(period):
        nodes, w = mo.world_matrices_at(md, model, ad, anim, float(t))
        idx = {n["name"]: i for i, n in enumerate(nodes)}
        for b in ("leftfoot", "rightfoot"):
            if b in idx:
                m = w[idx[b]]
                P.setdefault(b, []).append((m[0][3], m[1][3], m[2][3]))
    vs = []
    for b, pts in P.items():
        ys = [q[1] for q in pts]
        thr = min(ys) + 0.12 * (max(ys) - min(ys))
        for i in range(period):
            if ys[i] <= thr:
                vs.append(pts[(i + 1) % period][2] - pts[i][2])
    vs.sort()
    speed = -vs[len(vs) // 2] if vs else 0.0
    return period, speed


# --------------------------------------------------------------------------
# PoC
# --------------------------------------------------------------------------
def run(map_file="dg001_01.map", chr_file="pc001_bs00_00.chr", state="walk",
        nframes=36, size=520, out=None, props=False, start=None, heading=None,
        step=2, margin=26.0, cam_ax=0.62):
    out = out or os.path.join("..", "obj_out", f"poc_{state}.gif")

    # --- scene -----------------------------------------------------------
    print(f"[1/5] scene from {map_file}")
    sc = bs.build(map_file, os.path.join("..", "obj_out", "_poc_scene.obj"),
                  terrain_only=not props, gimmick=False)
    ground = Ground(sc.verts, sc.faces)
    print(f"      terrain: {len(sc.verts)} vertices, {len(sc.faces)} triangles")

    # --- character --------------------------------------------------------
    print(f"[2/5] character from {chr_file}")
    c = pc.load(os.path.join(CHARDIR, chr_file))
    state_code = pc.LOCOMOTION[state]
    motion_name = c["motions"][state_code]
    model_path = os.path.join(MODELDIR, c["model"][0])
    motion_path = os.path.join(MOTDIR, motion_name)
    print(f"      {state_code} -> {motion_name}")

    period, speed = measure_cycle(model_path, motion_path)
    print(f"[3/5] measured cycle: period {period} frames, "
          f"{speed:+.4f} u/frame = {speed*FPS:.2f} u/s at {FPS:g} fps "
          f"({speed*FPS*0.1:.2f} m/s)")

    md = open(model_path, "rb").read()
    model = pm.parse(md)
    ad = open(motion_path, "rb").read()
    anim = mo.parse(ad)
    verts, tris, uvs, mats, pal, rigid, bind, nodes = ra.build_geometry(
        model_path, md, model)
    print(f"      {len(verts)} vertices, {len(tris)} triangles")

    # --- path -------------------------------------------------------------
    if start is None or heading is None:
        start, heading, span = pick_path(ground, speed * nframes * step)
        print(f"[4/5] path chosen automatically: from "
              f"({start[0]:.1f},{start[1]:.1f}) heading {math.degrees(heading):.0f} deg, "
              f"{span:.0f} u clear")
    else:
        print(f"[4/5] path given: {start} heading {heading}")

    # --- animation ----------------------------------------------------------
    print(f"[5/5] {nframes} frames")
    dirx, dirz = math.sin(heading), math.cos(heading)
    x, z = start
    y = ground.height(x, z) or 0.0
    frames_xyz = []
    poses = []
    for f in range(nframes):
        t = float((f * step) % period)
        # the character's local pose
        _n, aw = mo.world_matrices_at(md, model, ad, anim, t)
        blend = mo.skin_matrices(bind, aw)
        P = ra.pose_positions(verts, pal, rigid, aw, blend)
        # heading: the character advances towards local +Z, so rotate by
        # `heading` about Y
        ch, sh = math.cos(heading), math.sin(heading)
        X = P[:, 0] * ch + P[:, 2] * sh
        Z = -P[:, 0] * sh + P[:, 2] * ch
        gy = ground.height(x, z, ref=y)
        if gy is not None:
            y = gy
        poses.append(np.stack([X + x, P[:, 1] + y, Z + z], axis=1))
        frames_xyz.append((x, y, z))
        x += dirx * speed * step
        z += dirz * speed * step

    render(sc, poses, tris, uvs, mats, out, size, frames_xyz, step,
           margin, cam_ax)
    return frames_xyz


def pick_path(ground, need, cap=160.0):
    """Find the longest straight stretch of terrain to walk along.

    From a sample of supported points it tries a fan of directions and advances
    while the ground is there and does not step sharply. It keeps the longest,
    stopping at `cap` so it does not spend more time searching than rendering.
    The middle of the stretch becomes the start, so the character has road both
    ahead and behind.
    """
    xs = np.linspace(ground.x0, ground.x0 + ground.nx * ground.cell, 30)
    zs = np.linspace(ground.z0, ground.z0 + ground.nz * ground.cell, 30)
    # Density gate: only start where the map is actually built.
    dens = [ground.density(float(x), float(z)) for x in xs for z in zs]
    dens = [d for d in dens if d]
    min_dens = max(6, int(np.percentile(dens, 60))) if dens else 0

    best = (0.0, (float(xs[0]), float(zs[0])), 0.0)
    step = 4.0
    for x0 in xs:
        for z0 in zs:
            if ground.density(float(x0), float(z0)) < min_dens:
                continue
            hs0 = ground.hits(float(x0), float(z0))
            # A single surface = no ceiling overhead. Needed both by the
            # character (so they do not end up inside a gap) and by the camera,
            # which would otherwise frame the roof instead of them.
            if len(hs0) != 1:
                continue
            h0 = hs0[0]
            for k in range(8):
                ang = k * math.pi / 4
                dx, dz = math.sin(ang) * step, math.cos(ang) * step
                x, z, h, dist = float(x0), float(z0), h0, 0.0
                while dist < cap:
                    nx_, nz_ = x + dx, z + dz
                    nh = ground.height(nx_, nz_, ref=h, tol=8.0)
                    if nh is None or abs(nh - h) > 3.0:
                        break
                    if ground.density(nx_, nz_) < min_dens:
                        break
                    if len(ground.hits(nx_, nz_)) != 1:
                        break
                    x, z, h = nx_, nz_, nh
                    dist += step
                if dist > best[0]:
                    best = (dist, (float(x0), float(z0)), ang)
    dist, (sx, sz), ang = best
    # start a little before the middle, if the stretch is longer than needed
    if dist > need:
        back = min((dist - need) / 2, dist - need)
        sx += math.sin(ang) * back
        sz += math.cos(ang) * back
    return (sx, sz), ang, dist


def render(sc, poses, ctris, cuvs, cmats, out, size, path, step_hint=2,
           margin=26.0, ax=0.62):
    """Static terrain + animated character, fixed camera, GIF."""
    nV = len(sc.verts)
    V0 = np.asarray(sc.verts, np.float64)
    VT0 = np.asarray(sc.uvs, np.float64) if sc.uvs else np.zeros((nV, 2))
    # The same slivers Ground drops from the support mesh are dropped from the
    # drawing too. This is a GEOMETRIC filter (degenerate triangles), not
    # render_obj's screen-space threshold, which with a close camera would
    # erase the ground itself.
    solid = Ground(sc.verts, sc.faces)._solid_mask(
        np.array([[f[0], f[1], f[2]] for f in sc.faces], np.int32))
    keep = [f for f, ok in zip(sc.faces, solid) if ok]
    print(f"      {len(sc.faces)-len(keep)} degenerate triangles dropped from "
          f"the drawing, of {len(sc.faces)}")
    F0 = [([f[0], f[1], f[2]], [f[0], f[1], f[2]]) for f in keep]
    fm0 = [f[3] for f in keep]

    mtl = {}
    for m, p in sc.mat_png.items():
        if p and os.path.exists(p):
            mtl[m] = np.asarray(Image.open(p).convert("RGB"))
    for (m, p) in cmats:
        if p and m not in mtl and os.path.exists(p):
            mtl[m] = np.asarray(Image.open(p).convert("RGB"))

    nc = poses[0].shape[0]
    F1 = [([nV + t[0], nV + t[1], nV + t[2]],
           [nV + t[0], nV + t[1], nV + t[2]]) for t in ctris]
    fm1 = [m for (m, _p) in cmats]
    VTc = np.asarray(cuvs, np.float64) if cuvs else np.zeros((nc, 2))
    VT = np.concatenate([VT0, VTc])
    F = F0 + F1
    fm = fm0 + fm1

    # FIXED camera framed on the path (not on the whole map, or the character
    # is one pixel). render_view wants (centre, span) already in ROTATED space,
    # so the box has to be rotated before deriving them.
    ay = 0.9
    px = np.array([p[0] for p in path])
    py = np.array([p[1] for p in path])
    pz = np.array([p[2] for p in path])
    # margin: how much room to leave around the path (the character is 17.8 u)
    box = np.array([[x, y, z]
                    for x in (px.min()-margin, px.max()+margin)
                    for y in (py.min()-6, py.max()+margin)
                    for z in (pz.min()-margin, pz.max()+margin)])
    R = box @ ro.rot(ax, ay).T
    c = (R.min(0) + R.max(0)) / 2
    span = (R.max(0) - R.min(0))[:2].max() * 1.05
    bounds = (c, span)

    imgs = []
    for i, P in enumerate(poses):
        V = np.concatenate([V0, P])
        # cull=0: render_obj's anti-spike threshold is for models whose decode
        # is in doubt, but here the camera is close and terrain triangles are
        # large on screen -- with the cull on, the ground would vanish.
        im = ro.render_view(V, VT, F, fm, mtl, size, ay=ay, ax=ax,
                            cull=0, bounds=bounds, twosided=True)
        imgs.append(im if isinstance(im, Image.Image) else Image.fromarray(im))
        print(f"      frame {i+1}/{len(poses)}", end="\r")
    print()
    imgs[0].save(out, save_all=True, append_images=imgs[1:],
                 duration=int(1000*step_hint/FPS), loop=0)
    print(f"\n{out}: {len(imgs)} frames")
    strip = Image.new("RGB", (size*min(6, len(imgs)), size), (235, 235, 235))
    for i, im in enumerate(imgs[::max(1, len(imgs)//6)][:6]):
        strip.paste(im, (i*size, 0))
    sp = os.path.splitext(out)[0] + "_strip.png"
    strip.save(sp)
    print(f"{sp}")


if __name__ == "__main__":
    a = sys.argv
    def opt(name, d=None, cast=str):
        return cast(a[a.index(name)+1]) if name in a else d
    run(map_file=opt("--map", "dg001_01.map"),
        chr_file=opt("--chr", "pc001_bs00_00.chr"),
        state=opt("--state", "walk"),
        nframes=opt("--frames", 36, int),
        size=opt("--size", 520, int),
        out=opt("--out"),
        props="--props" in a,
        step=opt("--step", 2, int),
        margin=opt("--margin", 26.0, float),
        cam_ax=opt("--cam", 0.62, float),
        start=((opt("--x", 0.0, float), opt("--z", 0.0, float))
               if "--x" in a else None),
        heading=(math.radians(opt("--dir", 0.0, float))
                 if "--dir" in a else None))
