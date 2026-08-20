"""Skinning for The Last Story `.model` files (`wii modl` / NW4R).

Everything below was reverse-engineered from the files themselves; the
"how we know" notes are kept because they are the point of this repository.

--- chunk `mtrx` = THE SKINNING MATRIX PALETTE ------------------------------
Not two arrays: ONE palette, split into three fixed-record tables, one per
number of influencing bones.

    +0x10  u32  total  total matrices in the palette (matIdx 0 .. total-1)
    +0x14  u32  nA
    +0x18  u32  ptrA -> table A: nA x  8 B  (matIdx, bone)             1 bone
    +0x1c  u32  nB
    +0x20  u32  ptrB -> table B: nB x 20 B  (matIdx, b0,w0, b1,w1)     2 bones
    +0x24  u32  nC
    +0x28  u32  ptrC -> table C: nC x 28 B  (matIdx, b0,w0 .. b2,w2)   3 bones

Record size is 4 + n*8, except for 1 bone where the weight is implicitly 1.0
and is not stored (so 8, not 12). Padding to 16 bytes lives at the END of each
table, not inside the records -- reading table C with a 32-byte stride silently
corrupts entries.

nA+nB+nC == total, matIdx values run sequentially across the tables, and the
weights sum to exactly 1.0 (a good integrity check).

    an008:  90 = 19 + 71 + 0
    pc001: 346 = 56 + 285 + 5   e.g. matIdx 341 = mouth_L x0.5
                                     + mouth_down x0.3 + chin x0.2

Note the 0: table C is EMPTY on an008. Looking at that model alone, table C is
invisible and the matIdx values it would hold simply look like holes in the
palette -- which is exactly how it was missed the first time round.

--- chunk `subm` = A GX PACKET ----------------------------------------------
    +0x10 .. +0x34   matrixList[10] (u32, 0xffffffff = empty slot)
    +0x38            ptr -> dlst chunk
size == 60. The 10 slots are the 10 position matrices of GX matrix memory.

--- the full chain ----------------------------------------------------------
    vertex byte0 (PNMTXIDX) / 3   ->  slot 0..9
    subm.matrixList[slot]         ->  matIdx
    palette[matIdx]               ->  1, 2 or 3 bones with weights

UNSKINNED meshes have no PNMTXIDX byte at all (zero matrix-index bytes in the
vertex layout) and their matrixList is all -1.

--- SPACES: the hybrid NW4R convention (this was the hard part) --------------
The tables are not different encodings of the same thing. They describe
DIFFERENT SPACES:

  * table A (1 bone, rigid): the vertex is in BONE SPACE.
        pos_model = world[bone] @ (raw / K)
  * tables B/C (blended):    the vertex is ALREADY in bind MODEL SPACE.
        pos_model = raw / K

The reason is that at runtime the matrix loaded for a blended vertex is
sum(w * W_bone @ W_bind^-1), which at bind pose is the IDENTITY -- so the
stored data must already be in model space.

Applying the blend transform to ALL vertices (or to none) tears the mesh apart
at bone boundaries: those are the "spikes". Measured on an008, with
median(longest edge of cross-bone triangles) / median(same-bone):

    everything treated as model space   4.37
    everything treated as bone-local    7.35
    hybrid, as above                    1.28

--- K, the POS quantisation -------------------------------------------------
POS is s16 and K is its scale: a power of two that varies PER MESH (an008 body
2048, an008 collar 8192, pc001 meshes from 1024 to 65536). This is the same
unknown that used to make accessories float away.

K does not have to be guessed. Changing K changes the ratio between R@raw/K and
the bone translation T, so triangles that CROSS a bone change blow up for every
wrong K. Pick the power of two minimising

    median(longest edge, cross-bone triangles) / median(same-bone)

Same-bone triangles are the ruler: their edge lengths are unaffected by K
(rigid transform). The minimum is sharp -- an008: 1.28 at K=2048 against 3.71
at 1024 and 6.32 at 4096.

Meshes with no cross-bone triangles carry no such signal; for them the AABB
stored in their own node (node +0x58, see node_aabb) is the ground truth, and
fit_to_node_aabb recovers both K and the bone the mesh hangs off.
"""
import math
import statistics
import struct

import parse_model as pm
import skeleton as sk

K_CANDIDATES = [2.0 ** e for e in range(6, 17)]
K_FALLBACK = 2048.0


# --------------------------------------------------------------------------
# palette (mtrx chunk)
# --------------------------------------------------------------------------
def palette(d, model):
    """Return (pal, rigid): pal[matIdx] = [(boneIdx, weight), ...] or None,
    rigid[matIdx] = True when the entry comes from table A (bone space)."""
    mtrx = model["chunks"]["mtrx"]
    if not mtrx:
        return [], []
    o = mtrx[0]["offset"]
    total = pm._u32(d, o + 0x10)
    if not (0 < total < 65536):
        return [], []
    pal = [None] * total
    rigid = [False] * total
    for nbone, (cnt_off, ptr_off) in enumerate(
            ((0x14, 0x18), (0x1c, 0x20), (0x24, 0x28)), start=1):
        cnt = pm._u32(d, o + cnt_off)
        ptr = pm._u32(d, o + ptr_off)
        # record = 4 (matIdx) + n*8 (bone,weight); with 1 bone the weight is
        # implicitly 1.0 and is not stored -> 8 / 20 / 28 bytes. Padding to 16
        # sits at the END of the table, not inside the records.
        rec = 8 if nbone == 1 else 4 + nbone * 8
        for i in range(cnt):
            p = ptr + i * rec
            if p + rec > len(d):
                break
            mi = pm._u32(d, p)
            if mi >= total:
                continue
            if nbone == 1:
                pal[mi] = [(pm._u32(d, p + 4), 1.0)]
                rigid[mi] = True                      # the only bone-space case
            else:
                pal[mi] = [(pm._u32(d, p + 4 + j * 8), pm._f32(d, p + 8 + j * 8))
                           for j in range(nbone)]
    return pal, rigid


def subm_matrixlist(d, subm_off):
    """The 10 matrix-memory slots of a subm (-1 = empty)."""
    return [pm._s32(d, subm_off + 0x10 + i * 4) for i in range(10)]


def subm_dlst(d, subm_off):
    """Pointer to a subm's dlst chunk, or None."""
    p = pm._u32(d, subm_off + 0x38)
    return p if d[p:p + 4] == b"dlst" else None


# --------------------------------------------------------------------------
# node -> mesh table (node chunk)
# --------------------------------------------------------------------------
def node_mesh_table(d, model):
    """Bind every mesh to the NODE that draws it and to its MATERIAL.

        node +0x70  u32  how many meshes this node draws (0 = none)
        node +0x74  ptr  array of 12-byte records:
                             +0x00 matIdx  (into the embedded name table)
                             +0x04 meshIdx
                             +0x08 (always 0 so far)

    Returns {meshIdx: (nodeIdx, matIdx)}. Verified bijective on an008
    (cat->mesh0, op_01_collar->mesh1+2) and pc001 (31 meshes, 31 records, with
    coherent material names: armer->pc001_armor, hair->pc001_hair, ...).

    This is worth two things:
      * it names the node an UNSKINNED mesh belongs to, which is the starting
        point for placing it (bags, buckles, scabbard, hilt otherwise pile up
        around the origin);
      * it gives a material to models whose streams are unnamed (pc001),
        with no need for any runtime-built global material registry.
    """
    nodes = model["chunks"]["node"]
    nmesh = len(model["chunks"]["mesh"])
    table = {}
    for ni, nd in enumerate(nodes):
        if nd["size"] < 0x78:
            continue
        cnt = pm._s32(d, nd["offset"] + 0x70)
        ptr = pm._u32(d, nd["offset"] + 0x74)
        if cnt <= 0 or not (0 < ptr < len(d)):
            continue
        for j in range(cnt):
            p = ptr + j * 12
            if p + 12 > len(d):
                break
            mat_idx = pm._s32(d, p)
            mesh_idx = pm._s32(d, p + 4)
            if 0 <= mesh_idx < nmesh:
                table.setdefault(mesh_idx, (ni, mat_idx))
    return table


# --------------------------------------------------------------------------
# transform
# --------------------------------------------------------------------------
def _apply(m, x, y, z):
    return (m[0][0]*x + m[0][1]*y + m[0][2]*z + m[0][3],
            m[1][0]*x + m[1][1]*y + m[1][2]*z + m[1][3],
            m[2][0]*x + m[2][1]*y + m[2][2]*z + m[2][3])


def skin_vertex(raw, mat_idx, pal, rigid, world, k, attach=None):
    """Take a raw vertex (s16 x3) to model space, in real (AABB) units.

    skinned mesh, rigid matIdx (table A)  -> world[bone] @ (raw/k)
    skinned mesh, blended matIdx (B / C)  -> raw/k  (already model space)
    UNSKINNED mesh                        -> world[attach] @ (raw/k)
    Returns None when the matIdx cannot be resolved."""
    x, y, z = raw[0] / k, raw[1] / k, raw[2] / k
    if mat_idx < 0:                      # unskinned mesh: node/bone space
        if attach is None or attach >= len(world):
            return (x, y, z)
        return _apply(world[attach], x, y, z)
    if mat_idx >= len(pal) or pal[mat_idx] is None:
        return None
    if not rigid[mat_idx]:               # blended: already model space
        return (x, y, z)
    ax = ay = az = 0.0
    for (b, w) in pal[mat_idx]:
        if b >= len(world):
            return None
        bx, by, bz = _apply(world[b], x, y, z)
        ax += w * bx
        ay += w * by
        az += w * bz
    return (ax, ay, az)


def _edge_stats(verts, tris, pal, rigid, world, k, attach=None):
    """(same-bone longest-edge list, cross-bone list) at quantisation k."""
    cache = {}

    def pt(i):
        if i not in cache:
            raw, mi = verts[i]
            cache[i] = skin_vertex(raw, mi, pal, rigid, world, k, attach)
        return cache[i]

    same, cross = [], []
    for (a, b, c) in tris:
        pa, pb, pc = pt(a), pt(b), pt(c)
        if pa is None or pb is None or pc is None:
            continue
        e = max(math.dist(pa, pb), math.dist(pb, pc), math.dist(pc, pa))
        mats = {verts[a][1], verts[b][1], verts[c][1]}
        (same if len(mats) == 1 else cross).append(e)
    return same, cross


def node_aabb(d, node):
    """MODEL-SPACE AABB of the part a node draws, or None.

        node +0x58  6 floats: min.xyz, max.xyz

    Only present on nodes that draw meshes (the larger ones, size >= 0x70);
    bone nodes have zeros there. This is the reference against which a mesh's
    placement can be VERIFIED: for rigid parts it matches to three decimals,
    while for deformable ones (cape, hair) it is the envelope over the
    animation and so is wider than the bind-pose bbox.
    """
    if node["size"] < 0x70:
        return None
    v = [pm._f32(d, node["offset"] + 0x58 + i * 4) for i in range(6)]
    lo, hi = v[0:3], v[3:6]
    if all(a == 0.0 for a in v) or any(hi[i] < lo[i] for i in range(3)):
        return None
    return lo, hi


def _bbox(verts, pal, rigid, world, k, attach):
    lo = [1e30] * 3
    hi = [-1e30] * 3
    for (raw, mi) in verts:
        p = skin_vertex(raw, mi, pal, rigid, world, k, attach)
        if p is None:
            continue
        for i in range(3):
            lo[i] = min(lo[i], p[i])
            hi[i] = max(hi[i], p[i])
    return (None if lo[0] > 1e29 else (lo, hi))


def fit_to_node_aabb(verts, pal, rigid, world, nd_aabb, bones=None):
    """Find the (K, bone) that lands the mesh on the AABB its node declares.

    Needed by UNSKINNED meshes (bags, buckles, scabbard, teeth): they are in
    bone space, but the node chunk does not say WHICH bone, and the part node
    that draws them sits at the origin. The node's AABB, however, is ground
    truth in model space, so the (bone, K) pair that overlaps it is determined
    by the data rather than guessed. On pc001 the recovered bones are
    anatomically right: bag1/bag2/belt/buckle1 -> waist, buckle2 -> spine,
    earring/eye_kage -> head, hand_l_obj -> leftforearm, necklace -> spine1.

    Returns (k, attach, err) for the best match, or None."""
    lo_t, hi_t = nd_aabb
    span = max(hi_t[i] - lo_t[i] for i in range(3)) or 1.0
    cand_bones = range(len(world)) if bones is None else bones
    best = None
    for k in K_CANDIDATES:
        for b in cand_bones:
            bb = _bbox(verts, pal, rigid, world, k, b)
            if bb is None:
                continue
            lo, hi = bb
            err = max(max(abs(lo[i] - lo_t[i]), abs(hi[i] - hi_t[i]))
                      for i in range(3))
            if best is None or err < best[2]:
                best = (k, b, err)
        # no bone at all: the mesh is already in model space
        bb = _bbox(verts, pal, rigid, world, k, None)
        if bb is not None:
            lo, hi = bb
            err = max(max(abs(lo[i] - lo_t[i]), abs(hi[i] - hi_t[i]))
                      for i in range(3))
            if best is None or err < best[2]:
                best = (k, None, err)
    if best is None or best[2] > 0.10 * span:
        return None
    return best


def solve_k(verts, tris, pal, rigid, world, aabb=None, attach=None):
    """Find the POS quantisation K of a mesh.

    Primary: the power of two that makes cross-bone triangles as long as
    same-bone ones. Fallback, for meshes with no cross-bone triangles: the
    smallest K that keeps every vertex inside the header AABB -- prefer
    fit_to_node_aabb when the mesh's node declares its own AABB.
    Returns (k, ratio, method)."""
    best = None
    for k in K_CANDIDATES:
        same, cross = _edge_stats(verts, tris, pal, rigid, world, k, attach)
        if len(same) < 4 or len(cross) < 4:
            continue
        ratio = statistics.median(cross) / (statistics.median(same) or 1e-9)
        score = abs(math.log(ratio)) if ratio > 0 else float("inf")
        if best is None or score < best[0]:
            best = (score, k, ratio)
    if best is not None:
        return best[1], best[2], "cross-bone"

    if aabb is not None:                        # fallback: fit the header AABB
        # Use the REAL per-axis interval, not |max|: a character AABB starts at
        # Y=0, so a symmetric test would happily accept very negative Y.
        lo, hi = aabb["min"], aabb["max"]
        pad = [0.05 * (hi[i] - lo[i]) for i in range(3)]
        # NB with attach the transform is not linear in 1/k (the bone
        # translation gets in the way), so evaluate each k in full.
        for k in K_CANDIDATES:
            if all(lo[i] - pad[i] <= p[i] <= hi[i] + pad[i]
                   for (raw, mi) in verts
                   for p in (skin_vertex(raw, mi, pal, rigid, world, k, attach),)
                   if p
                   for i in range(3)):
                return k, float("nan"), "aabb-fit"
    return K_FALLBACK, float("nan"), "default"


def model_skin_context(d, model=None):
    """(model, pal, rigid, nodes, world), ready for export."""
    if model is None:
        model = pm.parse(d)
    pal, rigid = palette(d, model)
    nodes, world = sk.world_matrices(d, model)
    return model, pal, rigid, nodes, world


# --------------------------------------------------------------------------
# CLI: palette summary + the K resolved for each mesh
# --------------------------------------------------------------------------
def _cli():
    import sys
    import export_obj as eo
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    d = open(path, "rb").read()
    model, pal, rigid, nodes, world = model_skin_context(d)
    nA = sum(1 for r in rigid if r)
    print(f"{path}")
    print(f"  palette: {len(pal)} matrices  ({nA} rigid / {len(pal)-nA} blended), "
          f"{len(nodes)} bones")
    for mi, e in enumerate(pal):
        if e is None:
            print(f"    matIdx {mi:3}  <hole>")
            continue
        kind = "rigid  " if rigid[mi] else "blended"
        s = " + ".join(f"{nodes[b]['name']}({b})x{w:g}" if b < len(nodes)
                       else f"?{b}x{w:g}" for b, w in e)
        print(f"    matIdx {mi:3}  {kind}  {s}")

    print("  --- K (POS quantisation) per mesh ---")
    for mno, mesh in enumerate(model["chunks"]["mesh"]):
        verts, tris, _uvs = eo.mesh_geometry(d, model, mesh)
        if not verts:
            continue
        k, ratio, how = solve_k(verts, tris, pal, rigid, world, model["aabb"])
        rs = f"{ratio:.3f}" if ratio == ratio else "n/d"
        print(f"    mesh{mno} {mesh['name']:<12} {len(verts):5}v {len(tris):5}t  "
              f"K={k:<7g} ratio={rs:<7} ({how})")


if __name__ == "__main__":
    _cli()
