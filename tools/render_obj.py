"""Tiny software renderer (numpy + PIL) for the OBJ files export_obj.py writes.
Z-buffered rasteriser, affine texture mapping, Lambert shading.

Usage: python render_obj.py MODEL.obj OUT.png [--size 900] [--views 3]
                            [--no-cull | --cull 0.30]

--cull F drops triangles whose longest screen edge exceeds F * image size, so
that "spike" triangles do not swamp the picture. Pass --no-cull to disable it:
a correctly assembled mesh needs no hiding, so that is the honest check.
"""
import sys, os, math
import numpy as np
from PIL import Image


def load_obj(path):
    V, VT, F = [], [], []
    mtl = {}
    curmat = None
    facemat = []
    base = os.path.dirname(path)
    for ln in open(path):
        t = ln.split()
        if not t:
            continue
        if t[0] == "v":
            V.append([float(t[1]), float(t[2]), float(t[3])])
        elif t[0] == "vt":
            VT.append([float(t[1]), float(t[2])])
        elif t[0] == "f":
            idx = [int(p.split("/")[0]) - 1 for p in t[1:4]]
            uv = [int(p.split("/")[1]) - 1 if "/" in p and p.split("/")[1] else idx[k]
                  for k, p in enumerate(t[1:4])]
            F.append((idx, uv))
            facemat.append(curmat)
        elif t[0] == "usemtl":
            curmat = t[1]
        elif t[0] == "mtllib":
            mtl = load_mtl(os.path.join(base, t[1]))
    return np.array(V), np.array(VT) if VT else None, F, facemat, mtl


def load_mtl(path):
    tex = {}
    cur = None
    if not os.path.exists(path):
        return tex
    for ln in open(path):
        t = ln.split()
        if not t:
            continue
        if t[0] == "newmtl":
            cur = t[1]
        elif t[0] == "map_Kd":
            p = ln.split(None, 1)[1].strip()
            if os.path.exists(p):
                im = Image.open(p).convert("RGB")
                tex[cur] = np.asarray(im)
    return tex


def rot(ax, ay):
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    return Ry @ Rx


def render_view(V, VT, F, facemat, mtl, size, ay, ax=0.35, cull=0.30,
                bounds=None, twosided=False):
    """bounds=(centre, span) pins the camera, which animation needs: a per-frame
    fit would wobble the framing instead of moving the subject.

    twosided=True disables backface culling. MAP geometry needs it: the floors
    of *_base.model are wound with the normal pointing DOWN (checked by hand on
    a courtyard quad of dg001_01: e1 x e2 = (0,-459.8,0)), so seen from above
    they are backfaces and every floor in the level disappears. Character
    winding is consistent, so the cull can stay on there."""
    P = V @ rot(ax, ay).T
    # ortho fit
    mn, mx = P.min(0), P.max(0)
    c = (mn + mx) / 2
    span = (mx - mn)[:2].max() * 1.15
    s = size / span
    sx = (P[:, 0] - c[0]) * s + size / 2
    sy = -(P[:, 1] - c[1]) * s + size / 2
    z = P[:, 2]

    img = np.full((size, size, 3), 235, np.uint8)
    # The viewer sits at +z: the backface cull below says so, keeping faces with
    # n[2] > 0. The depth test must use the SAME convention, i.e. larger z wins.
    # With rot() the world's +Y maps to a positive view z, so with the test the
    # other way round the terrain covered whatever stood on it.
    #
    # This stayed latent for three sessions because everything rendered until
    # now was a single closed object: with backface culling each pixel has
    # exactly one front-facing triangle, so the depth test never decides
    # anything. It only shows up with separate objects at different depths --
    # a character standing on terrain.
    zbuf = np.full((size, size), -1e9)
    light = np.array([0.3, 0.5, 0.8]); light = light / np.linalg.norm(light)

    cull_edge = size * cull if cull else 1e9   # 0 = no culling (honest check)
    for (idx, uv), mat in zip(F, facemat):
        x0, y0 = sx[idx], sy[idx]
        za = z[idx]
        e01 = math.hypot(x0[0]-x0[1], y0[0]-y0[1])
        e12 = math.hypot(x0[1]-x0[2], y0[1]-y0[2])
        e20 = math.hypot(x0[2]-x0[0], y0[2]-y0[0])
        if max(e01, e12, e20) > cull_edge:
            continue
        minx, maxx = int(max(0, x0.min())), int(min(size - 1, x0.max()))
        miny, maxy = int(max(0, y0.min())), int(min(size - 1, y0.max()))
        if minx > maxx or miny > maxy:
            continue
        # view-space normal, for shading + backface culling (-Z faces away)
        e1 = P[idx[1]] - P[idx[0]]; e2 = P[idx[2]] - P[idx[0]]
        n = np.cross(e1, e2); nl = np.linalg.norm(n)
        if nl == 0:
            continue
        n = n / nl
        if n[2] < 0 and not twosided:    # facing away -> drop
            continue
        shade = 0.35 + 0.75 * max(0.0, abs(n @ light))
        tex = mtl.get(mat)
        xs = np.arange(minx, maxx + 1)
        ys = np.arange(miny, maxy + 1)
        gx, gy = np.meshgrid(xs, ys)
        d = ((y0[1] - y0[2]) * (x0[0] - x0[2]) + (x0[2] - x0[1]) * (y0[0] - y0[2]))
        if abs(d) < 1e-9:
            continue
        w0 = ((y0[1] - y0[2]) * (gx - x0[2]) + (x0[2] - x0[1]) * (gy - y0[2])) / d
        w1 = ((y0[2] - y0[0]) * (gx - x0[2]) + (x0[0] - x0[2]) * (gy - y0[2])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        zz = w0 * za[0] + w1 * za[1] + w2 * za[2]
        sub = zbuf[miny:maxy + 1, minx:maxx + 1]
        mask = inside & (zz > sub)
        if not mask.any():
            continue
        if tex is not None and VT is not None:
            u = w0 * VT[uv[0], 0] + w1 * VT[uv[1], 0] + w2 * VT[uv[2], 0]
            v = w0 * VT[uv[0], 1] + w1 * VT[uv[1], 1] + w2 * VT[uv[2], 1]
            th, tw = tex.shape[:2]
            tx = np.clip((u * tw).astype(int) % tw, 0, tw - 1)
            ty = np.clip(((1 - v) * th).astype(int) % th, 0, th - 1)
            col = tex[ty, tx].astype(float)
        else:
            col = np.full(gx.shape + (3,), 180.0)
        col = np.clip(col * shade, 0, 255).astype(np.uint8)
        dst = img[miny:maxy + 1, minx:maxx + 1]
        dst[mask] = col[mask]
        sub[mask] = zz[mask]
    return img


def main():
    a = sys.argv
    path, out = a[1], a[2]
    size = int(a[a.index("--size") + 1]) if "--size" in a else 900
    nv = int(a[a.index("--views") + 1]) if "--views" in a else 3
    cull = 0.0 if "--no-cull" in a else (
        float(a[a.index("--cull") + 1]) if "--cull" in a else 0.30)
    V, VT, F, fm, mtl = load_obj(path)
    print(f"loaded {len(V)} v, {len(F)} tris, tex={list(mtl.keys())}")
    angles = [math.radians(x) for x in (25, 115, 205)][:nv] if nv > 1 else [math.radians(30)]
    imgs = [render_view(V, VT, F, fm, mtl, size, ay, cull=cull) for ay in angles]
    W = size * len(imgs)
    canvas = Image.new("RGB", (W, size), (235, 235, 235))
    for i, im in enumerate(imgs):
        canvas.paste(Image.fromarray(im), (i * size, 0))
    canvas.save(out)
    print(f"wrote {out} ({W}x{size})")


if __name__ == "__main__":
    main()
