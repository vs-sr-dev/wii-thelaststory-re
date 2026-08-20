"""Render a `.model` animated by a `.motion`, as a GIF or a strip of frames.

Pulls everything else together: export_obj (geometry), skinning (palette and
quantisation), skeleton (bind pose), motion (curves) and render_obj (rasteriser).

Animated skinning uses the two rules of the hybrid NW4R convention:
    RIGID vertex (1 bone, bone space)   ->  W_anim[bone] @ (raw/K)
    BLEND vertex (already model space)  ->  sum(w * W_anim[b] @ W_bind[b]^-1)
    unskinned mesh (rigid prop)         ->  W_anim[attach] @ (raw/K)
At bind pose the second reduces to the identity, so frame 0 of a still clip
equals the static export -- a useful self-check.

See docs/09-skinning.md and docs/10-animation.md.

Usage:
    python render_anim.py FILE.model FILE.motion OUT.gif [--size 360]
                          [--frames 20] [--fps 30] [--angle 25] [--strip]
"""
import math
import os
import sys

import numpy as np
from PIL import Image

import parse_model as pm
import export_obj as eo
import skeleton as sk
import skinning as skn
import motion as mo
import render_obj as ro


def build_geometry(model_path, md, model):
    """Geometry plus per-mesh skinning info, resolved ONCE.

    Returns (verts, tris, uvs, mats) where verts[i] = (raw, matIdx, k, attach)."""
    strm = model["chunks"]["strm"]
    pal, rigid = skn.palette(md, model)
    nodes, bind = sk.world_matrices(md, model)
    nmt = skn.node_mesh_table(md, model)
    mat_db, embedded = eo.load_material_db(model_path)

    verts, tris, uvs, mats = [], [], [], []
    for mno, mesh in enumerate(model["chunks"]["mesh"]):
        mverts, mtris, muvs = eo.mesh_geometry(md, model, mesh)
        if not mverts:
            continue
        attach, node_mat = nmt.get(mno, (None, -1))
        matname, png = eo.resolve_mesh_material(
            strm[eo.mesh_fields(md, mesh)["posStrm"]]["name"],
            node_mat, mat_db, embedded)
        k, ratio, how = skn.solve_k(mverts, mtris, pal, rigid, bind,
                                    model["aabb"], attach)
        if how != "cross-bone" and attach is not None:
            nab = skn.node_aabb(md, nodes[attach])
            if nab:
                fit = skn.fit_to_node_aabb(mverts, pal, rigid, bind, nab)
                if fit:
                    k, attach, _err = fit
        base = len(verts)
        for (raw, mi) in mverts:
            verts.append((raw, mi, k, attach))
        uvs.extend(muvs)
        for (a, b, c) in mtris:
            tris.append((base + a, base + b, base + c))
            mats.append((matname, png))
    return verts, tris, uvs, mats, pal, rigid, bind, nodes


def pose_positions(verts, pal, rigid, anim_world, blend_mats):
    """Every vertex position for a given pose."""
    out = np.zeros((len(verts), 3), np.float64)
    for i, (raw, mi, k, attach) in enumerate(verts):
        x, y, z = raw[0]/k, raw[1]/k, raw[2]/k
        if mi < 0:
            m = anim_world[attach] if (attach is not None and
                                       attach < len(anim_world)) else None
            out[i] = (x, y, z) if m is None else skn._apply(m, x, y, z)
            continue
        entry = pal[mi] if mi < len(pal) else None
        if entry is None:
            continue
        if rigid[mi]:
            b = entry[0][0]
            if b < len(anim_world):
                out[i] = skn._apply(anim_world[b], x, y, z)
            continue
        ax = ay = az = 0.0
        for (b, w) in entry:
            if b >= len(blend_mats):
                continue
            bx, by, bz = skn._apply(blend_mats[b], x, y, z)
            ax += w*bx; ay += w*by; az += w*bz
        out[i] = (ax, ay, az)
    return out


def main():
    a = sys.argv
    if len(a) < 4:
        print(__doc__); return
    model_path, motion_path, out = a[1], a[2], a[3]
    size = int(a[a.index("--size")+1]) if "--size" in a else 360
    nfrm = int(a[a.index("--frames")+1]) if "--frames" in a else 20
    fps = float(a[a.index("--fps")+1]) if "--fps" in a else 30.0
    ang = float(a[a.index("--angle")+1]) if "--angle" in a else 25.0
    strip = "--strip" in a

    md = open(model_path, "rb").read()
    ad = open(motion_path, "rb").read()
    model = pm.parse(md)
    anim = mo.parse(ad)

    verts, tris, uvs, mats, pal, rigid, bind, nodes = build_geometry(
        model_path, md, model)
    print(f"{os.path.basename(model_path)}: {len(verts)} verts, {len(tris)} tris")
    print(f"{os.path.basename(motion_path)}: {anim['frameCount']:g} frames, "
          f"{len(anim['bones'])} animated bones")

    # rasteriser structures, built once
    VT = np.array(uvs) if uvs else None
    F = [([t[0], t[1], t[2]], [t[0], t[1], t[2]]) for t in tris]
    facemat = [m for (m, _p) in mats]
    mtl = {}
    for (m, p) in mats:
        if p and m not in mtl and os.path.exists(p):
            mtl[m] = np.asarray(Image.open(p).convert("RGB"))

    total = anim["frameCount"] or 1
    times = [total * i / nfrm for i in range(nfrm)]

    # FIXED camera: bounds over all poses, so the subject moves, not the framing
    print("computing poses...")
    poses = []
    for t in times:
        _n, aw = mo.world_matrices_at(md, model, ad, anim, t)
        bm = mo.skin_matrices(bind, aw)
        poses.append(pose_positions(verts, pal, rigid, aw, bm))
    allp = np.concatenate(poses, 0)
    R = ro.rot(0.35, math.radians(ang))
    P = allp @ R.T
    mn, mx = P.min(0), P.max(0)
    bounds = ((mn + mx) / 2, (mx - mn)[:2].max() * 1.25)

    imgs = []
    for i, V in enumerate(poses):
        im = ro.render_view(V, VT, F, facemat, mtl, size, math.radians(ang),
                            cull=0.0, bounds=bounds)
        imgs.append(Image.fromarray(im))
        print(f"  frame {i+1}/{nfrm}", end="\r")
    print()

    if strip:
        n = min(len(imgs), 8)
        sel = [imgs[round(k*(len(imgs)-1)/(n-1))] for k in range(n)]
        canvas = Image.new("RGB", (size*n, size), (235, 235, 235))
        for k, im in enumerate(sel):
            canvas.paste(im, (k*size, 0))
        canvas.save(out)
        print(f"wrote {out} ({size*n}x{size}, {n} frames)")
    else:
        imgs[0].save(out, save_all=True, append_images=imgs[1:],
                     duration=int(1000*total/nfrm/fps), loop=0, optimize=True)
        print(f"wrote {out} ({size}x{size}, {len(imgs)} frames @ {fps:g}fps)")


if __name__ == "__main__":
    main()
