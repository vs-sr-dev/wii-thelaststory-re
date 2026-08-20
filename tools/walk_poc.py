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

With collision=True the character walks on the real COLLISION (.hocb) instead
of the visible mesh -- the surface the game actually stands them on. Pass
filter_slivers=False with it: that filter exists for artefacts of the rendering
strip decode, and on collision it would throw away the large floors. The path
finder gains a lot from it: on dg001_01 it finds 200 units of clear run instead
of 40.

The terrain holds the character up via a downward raycast, with a 2D grid over
XZ so a query does not sweep the whole map. For a hierarchical query that
really uses the .hocb octree, the way the game does, see parse_hocb.Collision.

The check that it works is numeric: over a full walk cycle the character's
lowest vertex stays between 4.839 and 5.051 against a floor at Y = 5.000 --
within 1.6 cm at 1 u ~ 10 cm, with no offset applied.

See docs/11-maps-and-scenes.md.

Usage:
    python walk_poc.py                          # default: dg001_01, walk
    python walk_poc.py --map dg002_01.map --state run --frames 48
    python walk_poc.py --props                  # full scene, slower
    python walk_poc.py --plan "idle:20,walk:60,run:40"   # the state machine
    python walk_poc.py --fixed-cam              # fixed camera instead of follow
    python walk_poc.py --collision              # walk on the .hocb collision
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
    MIN_ASPECT = 0.02          # 4*area / longest_edge^2

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
def parse_plan(spec):
    """'idle:24,walk:72,run:48' -> [('idle',24), ('walk',72), ('run',48)].

    The sequence of states to play. Each state brings ITS OWN motion, ITS OWN
    period and ITS OWN speed, all taken from the data.
    """
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, n = part.partition(":")
        name = name.strip()
        if name not in pc.LOCOMOTION:
            raise SystemExit(f"unknown state {name!r}; "
                             f"available: {', '.join(pc.LOCOMOTION)}")
        out.append((name, int(n) if n else 30))
    return out


def run(map_file="dg001_01.map", chr_file="pc001_bs00_00.chr", state="walk",
        nframes=36, size=520, out=None, props=False, start=None, heading=None,
        step=2, margin=26.0, cam_ax=0.62, plan=None, follow=True,
        ceiling_cut=True, collision=False):
    out = out or os.path.join("..", "obj_out",
                              f"poc_{'seq' if plan else state}.gif")

    # --- scene -----------------------------------------------------------
    print(f"[1/5] scene from {map_file}")
    sc = bs.build(map_file, os.path.join("..", "obj_out", "_poc_scene.obj"),
                  terrain_only=not props, gimmick=False)
    if collision:
        # Walk on the real collision (.hocb) rather than the visible mesh.
        # The rendered scene stays as it is -- it is only there to look at.
        import parse_hocb
        cp = parse_hocb.colli_for_map(map_file)
        if not cp:
            raise SystemExit(f"no COLLI_TREE for {map_file}")
        # filter_slivers=False: that filter discards artefacts of the RENDERING
        # strip decode. Collision is authored geometry with no such artefacts,
        # and the filter would throw away 635 of 2242 triangles on dg001_01 --
        # the large floors, which are exactly what you walk on.
        ground = Ground(*parse_hocb.soup(open(cp, "rb").read()),
                        filter_slivers=False)
        print(f"      collision from {os.path.basename(cp)}: "
              f"{len(ground.tris)} triangles")
    else:
        ground = Ground(sc.verts, sc.faces)
    print(f"      terrain: {len(sc.verts)} vertices, {len(sc.faces)} triangles")

    # --- character --------------------------------------------------------
    print(f"[2/5] character from {chr_file}")
    c = pc.load(os.path.join(CHARDIR, chr_file))
    steps = parse_plan(plan) if plan else [(state, nframes)]
    model_path = os.path.join(MODELDIR, c["model"][0])
    md = open(model_path, "rb").read()
    model = pm.parse(md)
    verts, tris, uvs, mats, pal, rigid, bind, nodes = ra.build_geometry(
        model_path, md, model)
    print(f"      {len(verts)} vertices, {len(tris)} triangles")

    # Each state brings its own motion: the state machine lives in the
    # .chr/.mchr, and period and speed are measured from that clip's data (not
    # copied from another: walk and run differ in both period and stride).
    print("[3/5] states and cycles, all measured:")
    S = {}
    for name, _n in steps:
        if name in S:
            continue
        code = pc.LOCOMOTION[name]
        mot_name = c["motions"][code]
        mot_path = os.path.join(MOTDIR, mot_name)
        period, speed = measure_cycle(model_path, mot_path)
        if name == "idle":
            speed = 0.0          # standing still: no translation to drive
        ad = open(mot_path, "rb").read()
        S[name] = {"anim": mo.parse(ad), "data": ad, "period": period,
                   "speed": speed, "motion": mot_name, "code": code}
        print(f"      {code:<10} {mot_name:<26} period {period:>3} frames  "
              f"{speed:+.4f} u/f = {speed*FPS:6.2f} u/s "
              f"({speed*FPS*0.1:.2f} m/s)")

    # --- path -------------------------------------------------------------
    total = sum(n for _s, n in steps)
    need = sum(S[s]["speed"] * n * step for s, n in steps)
    if start is None or heading is None:
        start, heading, span = pick_path(ground, max(need, 40.0))
        print(f"[4/5] path chosen automatically: from "
              f"({start[0]:.1f},{start[1]:.1f}) heading {math.degrees(heading):.0f} deg, "
              f"{span:.0f} u clear ({need:.0f} needed)")
    else:
        print(f"[4/5] path given: {start} heading "
              f"{math.degrees(heading):.0f} deg, {need:.0f} u needed")

    # --- animation ----------------------------------------------------------
    print(f"[5/5] {total} frames, {len(steps)} segments")
    dirx, dirz = math.sin(heading), math.cos(heading)
    ch, sh = math.cos(heading), math.sin(heading)
    x, z = start
    y = ground.height(x, z) or 0.0
    frames_xyz, poses, labels = [], [], []

    for name, n in steps:
        st = S[name]
        for f in range(n):
            # Phase restarts at 0 on every state change. A real engine would
            # cross-fade the two clips; this does not, and it is the one place
            # in the PoC that visibly reads as "not from the game".
            t = float((f * step) % st["period"])
            _n, aw = mo.world_matrices_at(md, model, st["data"], st["anim"], t)
            blend = mo.skin_matrices(bind, aw)
            P = ra.pose_positions(verts, pal, rigid, aw, blend)
            # heading: the character advances towards local +Z, so rotate by
            # `heading` about Y
            X = P[:, 0] * ch + P[:, 2] * sh
            Z = -P[:, 0] * sh + P[:, 2] * ch
            gy = ground.height(x, z, ref=y)
            if gy is not None:
                y = gy
            poses.append(np.stack([X + x, P[:, 1] + y, Z + z], axis=1))
            frames_xyz.append((x, y, z))
            labels.append(st["code"])
            x += dirx * st["speed"] * step
            z += dirz * st["speed"] * step

    render(sc, poses, tris, uvs, mats, out, size, frames_xyz, step,
           margin, cam_ax, follow, labels, ceiling_cut)
    return frames_xyz


def pick_path(ground, need, cap=200.0):
    """Find a straight stretch to walk the character along.

    From a sample of supported points it tries a fan of directions and advances
    while the ground is there and does not step sharply, stopping at `cap` so it
    does not spend more time searching than rendering. The middle of the stretch
    becomes the start, so there is road both ahead and behind.

    The score is NOT length alone. Maximising only that lets the thin fringes at
    the map edges win: they are long and empty, and the character ends up
    walking in a bare corner (measured on dg001_01: cell density ranges 1..228,
    and an edge strip at density 14 beat the central courtyard). So it is
    weighted by the MINIMUM density met along the stretch, which favours a path
    that stays inside the real map throughout.

    Even so this is a heuristic, and it can still pick a spot the camera cannot
    see into. Pass an explicit start when the framing matters.
    """
    xs = np.linspace(ground.x0, ground.x0 + ground.nx * ground.cell, 30)
    zs = np.linspace(ground.z0, ground.z0 + ground.nz * ground.cell, 30)
    # Density gate: only start where the map is actually built.
    dens = [ground.density(float(x), float(z)) for x in xs for z in zs]
    dens = [d for d in dens if d]
    min_dens = max(6, int(np.percentile(dens, 60))) if dens else 0

    best = (0.0, 0.0, (float(xs[0]), float(zs[0])), 0.0)   # score, dist, xz, ang
    step = 4.0
    for x0 in xs:
        for z0 in zs:
            d0 = ground.density(float(x0), float(z0))
            if d0 < min_dens:
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
                dmin = d0
                while dist < cap:
                    nx_, nz_ = x + dx, z + dz
                    nh = ground.height(nx_, nz_, ref=h, tol=8.0)
                    if nh is None or abs(nh - h) > 3.0:
                        break
                    dn = ground.density(nx_, nz_)
                    if dn < min_dens:
                        break
                    if len(ground.hits(nx_, nz_)) != 1:
                        break
                    x, z, h = nx_, nz_, nh
                    dmin = min(dmin, dn)
                    dist += step
                # past `need` extra length is useless, so it saturates and the
                # richness of the area breaks the tie instead
                score = min(dist, need * 1.2) * dmin
                if score > best[0]:
                    best = (score, dist, (float(x0), float(z0)), ang)
    _score, dist, (sx, sz), ang = best
    # start a little before the middle, if the stretch is longer than needed
    if dist > need:
        back = min((dist - need) / 2, dist - need)
        sx += math.sin(ang) * back
        sz += math.cos(ang) * back
    return (sx, sz), ang, dist


def _stamp(im, label, i, n):
    """Stamp the current state on the frame, so the switch is visible."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, im.width, 18], fill=(20, 20, 20))
    d.text((6, 4), f"{label}   frame {i+1}/{n}", fill=(240, 240, 240))
    return im


def render(sc, poses, ctris, cuvs, cmats, out, size, path, step_hint=2,
           margin=26.0, ax=0.62, follow=True, labels=None,
           ceiling_cut=True):
    """Static terrain + animated character, GIF.

    Two ways to frame it:
      follow=False  FIXED camera over the whole path. Honest, but if the
                    stretch is long the character comes out small.
      follow=True   FOLLOW camera with a CONSTANT span. The constant span is
                    the point: what makes framing "breathe" is recomputing the
                    span per frame, not the centre moving. Here the centre
                    tracks the character and the scale never changes, so there
                    is no wobble.
    """
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
    # Minimum height of each face, for the ceiling cut (see below).
    f0minY = np.array([min(V0[f[0]][1], V0[f[1]][1], V0[f[2]][1])
                       for f in keep])

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
    M = ro.rot(ax, ay).T
    if follow:
        # constant span derived from the margin alone: the character is 17.8 u
        # tall, so margin=26 leaves room and keeps them large on screen
        span = 2.2 * margin
        centres = [np.array([[p[0], p[1] + 8.0, p[2]]]) @ M for p in path]
        bounds_of = lambda i: (centres[i][0], span)
    else:
        box = np.array([[x, y, z]
                        for x in (px.min()-margin, px.max()+margin)
                        for y in (py.min()-6, py.max()+margin)
                        for z in (pz.min()-margin, pz.max()+margin)])
        R = box @ M
        c = (R.min(0) + R.max(0)) / 2
        span = (R.max(0) - R.min(0))[:2].max() * 1.05
        bounds_of = lambda i: (c, span)

    # CEILING CUT. The camera looks down at 30-50 degrees, not straight down,
    # so upper floors and roofs end up BETWEEN the camera and the character and
    # hide them: with a follow camera the subject vanishes behind the terrain.
    # This is the same problem the game solves with the HIDE_BIRDVIEW flag in
    # the .map, and the fix here is the same idea in minimal form: do not draw
    # faces sitting above the character's head. The threshold moves with them,
    # so climbing a floor makes the floor above vanish while the one they walk
    # on stays.
    headroom = 24.0
    imgs = []
    for i, P in enumerate(poses):
        V = np.concatenate([V0, P])
        if ceiling_cut:
            vis = f0minY <= path[i][1] + headroom
            Fi = [f for f, ok in zip(F0, vis) if ok] + F1
            fmi = [m for m, ok in zip(fm0, vis) if ok] + fm1
        else:
            Fi, fmi = F, fm
        # cull=0: render_obj's anti-spike threshold is for models whose decode
        # is in doubt, but here the camera is close and terrain triangles are
        # large on screen -- with the cull on, the ground would vanish.
        im = ro.render_view(V, VT, Fi, fmi, mtl, size, ay=ay, ax=ax,
                            cull=0, bounds=bounds_of(i), twosided=True)
        im = im if isinstance(im, Image.Image) else Image.fromarray(im)
        if labels:
            im = _stamp(im, labels[i], i, len(poses))
        imgs.append(im)
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
        plan=opt("--plan"),
        follow="--fixed-cam" not in a,
        ceiling_cut="--no-ceiling-cut" not in a,
        collision="--collision" in a,
        start=((opt("--x", 0.0, float), opt("--z", 0.0, float))
               if "--x" in a else None),
        heading=(math.radians(opt("--dir", 0.0, float))
                 if "--dir" in a else None))
