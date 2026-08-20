r"""The Last Story `.hcb` collision - BINARY. Twin of `.hocb`, but not the same.

388 files in `assets/pack/filesystem/data/collision/`, magic `BCH@` (the tag
`@HCB` stored byte-swapped). These are the GIMMICK collisions: `.gmk` files name
them with `COLLISION_BEFORE` / `COLLISION_AFTER`, one per visual state of the
object (see parse_gmk.py).

The header, the self-relative offsets and the section table are identical to
`.hocb` and are already handled by `parse_hocb.sections()` / `table_header()`.
Everything below them differs.

--- THE TWO TRAPS ----------------------------------------------------------

1. **THE TRIANGLE RECORD IS 68 BYTES, NOT 72.** It holds the same data as
   `.hocb`, packed differently: `.hocb` puts the material pointer first and pads
   (4 + 4 + 64 = 72), `.hcb` puts it LAST with no padding (64 + 4 = 68). Testing
   sections for divisibility by 72 finds nothing and leads to the wrong
   conclusion that there are no triangles here at all.

2. **THE TABLE'S "TYPE" FIELD IS NOT A TYPE.** It takes values 0x205..0x208, but
   the same class of data appears under different values in different files:
   0x205 is the material table in 280 rows and a NODE in 273; 0x207 is a mesh in
   553, a node in 683 and the material table in 108. This is not a misread: the
   (offset, size) pair of every row is verified against the relocation table on
   388/388 files. The real discriminator is SIZE, plus position. Only two
   mappings are exact:
       0x206 -> triangle array   553/553, and no other row is one
       0x208 -> root node        388/388, exactly one per file
   File order is what carries meaning: the material table is the first row in
   388/388 files, while sorting rows by type makes that false (in 67 files it
   lands third). See check_kinds() / --kinds.

--- THE RELOCATION TABLE (the proof) ---------------------------------------
Right after the section table, at `0x30 + 16*nSections`, there is a list of
self-relative s32 values pointing at EVERY POINTER FIELD in the file. Its count
and byte length live in the LAST table row, which is not a section but the
file's tail:

    tail: (rel -> last 16 bytes, size 16, nRelocations, 4*(nRelocations+1))

The relation between those last two fields holds on 388/388. This is the
strongest check available on this format: if the record layout is right, the set
of pointer fields it implies must EXACTLY equal the set the file declares.
**It does, on 388/388 files** (check()). One field in the wrong place breaks it
immediately - which is how the node's second pointer at +0x38 was found, as the
early layout came out short by exactly nNodes + 2 entries.

--- logical structure ------------------------------------------------------
No octree: `.hcb` objects are small. Instead there is a SCENE GRAPH, which
`.hocb` does not have.

    material table    1 per file, 32-byte entries (identical to .hocb)
    triangle array    1 per mesh, 68-byte records
    mesh descriptor   1 per array, 28 bytes
    nodes             scene graph, 104- or 116-byte records
    root              1 per file, a node zeroed except for its child pointer

--- TRIANGLE record: 68 bytes ----------------------------------------------
    +0x00  f32[3]  v0        \
    +0x0c  f32[3]  v1         > model-space floats, not quantised, not indexed
    +0x18  f32[3]  v2        /
    +0x24  f32[3]  face normal
    +0x30  f32[3]  bounding-sphere centre
    +0x3c  f32     bounding-sphere radius
    +0x40  s32     self-relative pointer to the material   <- at the END

Both of `.hocb`'s recomputable invariants hold, and more cleanly:
  - normal == normalize(cross(v1-v0, v2-v0)): **13,562/13,562** of the
    non-degenerate records, i.e. 100.0000% (4 degenerate out of 13,566);
  - the sphere contains its own three vertices: **13,566/13,566 = 100%**.

--- MESH descriptor: 28 bytes ----------------------------------------------
    +0x00  u32     1  (never anything else: 553/553)
    +0x04  u32     triangle count
    +0x08  s32     self-relative pointer to the array
    +0x0c  f32[3]  bounding-sphere centre
    +0x18  f32     radius
Array size == count*68 on 553/553; each mesh's sphere contains every vertex of
its own triangles on 553/553 (worst overshoot 1.2e-5, float noise).

--- NODE record: 104 or 116 bytes ------------------------------------------
    +0x00   u32     authoring index (0 = root; NOT a 0..n-1 numbering)
    +0x04   u32     always 0
    +0x08   u32     0 or 1
    +0x0c   s32     -> mesh descriptor, or 0 (791 of 1344 nodes carry no
                       geometry: they are transform / grouping nodes)
    +0x10   f32[3]  translation
    +0x1c   f32[4]  rotation, Euler angles in RADIANS (4th value always 0)
    +0x2c   f32[3]  scale
    +0x38   s32     -> first child, 0 if leaf
    +0x3c   s32     -> next sibling, 0 if last
    +0x40   char[]  NUL-terminated name (max 15 characters observed)
    end-12  f32[3]  an authored point, see below

The record size is constant WITHIN a file (317 files at 116, 71 at 104); only
the name field length changes. That is why the trailing three floats must be
read from end-12 and not from a fixed offset.

That it really is a tree is checked: walking from the root reaches every node on
388/388 files, with edges == nodes-1 on 388/388 (no cycles, no orphans). The
root is the node at the highest address and has index 0 on 388/388.

The index at +0x00 is not a per-file numbering (it is 0..n-1 in only 102 of 388
files) and reaches 111 in a file with 8 nodes: it is the object's index in the
AUTHOR's scene. The names confirm it - they are DCC names left in the shipped
data: `Sphere01`, `pCube2`, `hasira01` (hasira = pillar), `hako` (box), `ita01`
(board), plus working names like `c8`, `g20`. Many files export the artist's
whole hierarchy and hang the collision off a single node, the one suffixed
`_hcb` or `_c`.

The trailing three floats are zero in 1174 of 1344 nodes. Where they are not,
155 belong to a node with a mesh and 85 of those equal the mesh's bounding-sphere
centre (51 exactly). They are NOT derived from the geometry, though: in the other
70 cases they match nothing recomputable, and two different files carry identical
values. An authored point, most likely an interaction pivot. See --pivot.

--- materials --------------------------------------------------------------
Same 32-byte entries as `.hocb`, same layout (bitfields at +0x00 and +0x04, ARGB
at +0x08, +0x0c..+0x1c zero in all 757 entries). As in `.hocb`, entry #0 of every
file is the default (flags 0/0, 0xff000000) on 388/388. One to three per file.
**The flags are NOT decoded and this is no longer a data-analysis problem**:
three readings were already ruled out on `.hocb` (parse_hocb.check_materials);
going further needs the DOL or an in-game observation.

--- cross-format check against .model (--check-model) ----------------------
A test against a completely independent binary format. For every gimmick that
declares both `MODEL_*` and `COLLISION_*`, compare the `.hcb` triangle bbox with
the AABB in the `.model` header:
  - **141/141 pairs overlap**;
  - 48/141 agree within 2%, several float-for-float identical (gm001_011a: both
    min(-5,0,-5) max(5,60,5); gm001_074a: both min(-35,0,-4.5) max(35,140,4.5));
  - the 52 beyond 30% are not misreads: either the `.model` AABB is inflated by a
    distant vertex (gm001_095b reaches y=-1905, gm001_054b z=-699), or the
    BEFORE/AFTER states genuinely differ - gm001_037b's collision is a flattened
    slab (y from 0 to 0.65) while its model stands 80 tall: the object after it
    falls over.

--- NEGATIVE result, do not redo -------------------------------------------
The leading float in `COLLISION_BEFORE 5.0 <file>.hcb` **is not the collision
radius**, which was the assumption this format was opened on. It is 0.0 in 108 of
141 cases, and where it is not, its ratio to the file's real bounding radius runs
from 0.08 to 2.62 (median 0.73): no relation. There are no primitives
(spheres/capsules/boxes) in this format either - all 553 meshes are triangles,
including the node named `Sphere01`.

Usage:
    python parse_hcb.py FILE              # summary + scene graph
    python parse_hcb.py --check           # structure: relocations, tree, meshes
    python parse_hcb.py --check-tris      # triangle normals and spheres
    python parse_hcb.py --check-model     # .hcb bbox vs the gimmick's .model
    python parse_hcb.py --kinds           # the type field is not a type
    python parse_hcb.py --pivot           # the three trailing floats
    python parse_hcb.py FILE --obj OUT    # export the triangles as .obj
"""
import sys, os, glob, struct, math, collections

import parse_hocb as P

ROOT = P.ROOT
COL_DIR = P.COL_DIR
GMK_DIR = os.path.join(P.FS, "data", "gimmick")

TRI_SIZE = 68
MAGIC = b"BCH@"


def _u32(d, o): return struct.unpack_from(">I", d, o)[0]
def _s32(d, o): return struct.unpack_from(">i", d, o)[0]
def _f3(d, o): return struct.unpack_from(">3f", d, o)


def classify(size):
    """Size discriminates the section's class; the "type" field does not."""
    if size == 28:
        return "mesh"
    if size == 16:
        return "tail"
    if size in (104, 116):
        return "node"
    if size % TRI_SIZE == 0:
        return "tri"
    if size % 32 == 0:
        return "mat"
    return "?"


def sections(d):
    secs = P.sections(d)
    for s in secs:
        s["cls"] = classify(s["size"])
    return secs


def relocations(d, secs):
    """Offsets of EVERY pointer field, as the file itself declares them."""
    n = _u32(d, 0x20)
    start = 0x30 + 16 * n
    count = secs[-1]["kind"]          # in the tail row this field is a count
    return {start + i * 4 + _s32(d, start + i * 4) for i in range(count)}


def mesh_at(d, o):
    return {"offset": o, "n": _u32(d, o + 4), "tris": o + 8 + _s32(d, o + 8),
            "center": _f3(d, o + 0x0c),
            "radius": struct.unpack_from(">f", d, o + 0x18)[0]}


def triangles(d, off, n):
    out = []
    for i in range(n):
        o = off + i * TRI_SIZE
        f = struct.unpack_from(">16f", d, o)
        out.append({"offset": o, "v": (f[0:3], f[3:6], f[6:9]),
                    "normal": f[9:12], "center": f[12:15], "radius": f[15],
                    "material": o + 0x40 + _s32(d, o + 0x40)})
    return out


def nodes(d, secs):
    out = []
    for s in secs:
        if s["cls"] != "node":
            continue
        o, sz = s["target"], s["size"]
        mp, cp, np_ = _s32(d, o + 0x0c), _s32(d, o + 0x38), _s32(d, o + 0x3c)
        out.append({
            "offset": o, "size": sz, "index": _u32(d, o), "flag": _u32(d, o + 8),
            "mesh": (o + 0x0c + mp) if mp else None,
            "t": _f3(d, o + 0x10), "r": struct.unpack_from(">4f", d, o + 0x1c),
            "s": _f3(d, o + 0x2c),
            "child": (o + 0x38 + cp) if cp else None,
            "next": (o + 0x3c + np_) if np_ else None,
            "name": d[o + 0x40:o + sz - 12].split(b"\0")[0].decode("latin1"),
            "pivot": _f3(d, o + sz - 12),
        })
    return out


def materials(d, secs):
    out = []
    for s in secs:
        if s["cls"] != "mat":
            continue
        for i in range(s["size"] // 32):
            o = s["target"] + i * 32
            w = struct.unpack_from(">8I", d, o)
            out.append({"offset": o, "flags": (w[0], w[1]), "color": w[2]})
    return out


def parse(d):
    """-> dict with sections/materials/meshes/nodes/root/tris."""
    assert d[:4] == MAGIC, f"unexpected magic {d[:4]!r} (want {MAGIC!r})"
    secs = sections(d)
    ms = [mesh_at(d, s["target"]) for s in secs if s["cls"] == "mesh"]
    nd = nodes(d, secs)
    tris = []
    for m in ms:
        tris += triangles(d, m["tris"], m["n"])
    return {"size": len(d), "sections": secs, "materials": materials(d, secs),
            "meshes": ms, "nodes": nd,
            "root": max(nd, key=lambda x: x["offset"]) if nd else None,
            "tris": tris}


def parse_file(path):
    with open(path, "rb") as f:
        return parse(f.read())


def _files(paths=None):
    return sorted(paths or glob.glob(os.path.join(COL_DIR, "*.hcb")))


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
def check(paths=None):
    """Structure: relocations, tail, meshes, node tree."""
    files = _files(paths)
    st = collections.defaultdict(collections.Counter)
    worst_sphere = 0.0
    for p in files:
        d = open(p, "rb").read()
        secs = sections(d)
        tail = secs[-1]
        st["header size == len(file)"][_u32(d, 0x08) == len(d)] += 1
        st["tail: 16 bytes at EOF"][
            tail["size"] == 16 and tail["target"] + 16 == len(d)] += 1
        st["tail: bytes == 4*(nReloc+1)"][tail["flags"] == 4 * (tail["kind"] + 1)] += 1

        # --- the pointer fields I derive == the ones the file declares
        declared = relocations(d, secs)
        mine = {s["row"] for s in secs} | {tail["target"] + 0x0c}
        for s in secs:
            if s["cls"] == "tri":
                for i in range(s["size"] // TRI_SIZE):
                    mine.add(s["target"] + i * TRI_SIZE + 0x40)
            elif s["cls"] == "mesh":
                mine.add(s["target"] + 0x08)
            elif s["cls"] == "node":
                mine.update((s["target"] + 0x0c, s["target"] + 0x38,
                             s["target"] + 0x3c))
        st["POINTERS == RELOCATIONS"][mine == declared] += 1

        # --- meshes
        tri_secs = {s["target"]: s for s in secs if s["cls"] == "tri"}
        for s in secs:
            if s["cls"] != "mesh":
                continue
            m = mesh_at(d, s["target"])
            st["mesh: +0x00 == 1"][_u32(d, s["target"]) == 1] += 1
            hit = tri_secs.get(m["tris"])
            st["mesh: size == nTri*68"][
                hit is not None and hit["size"] == m["n"] * TRI_SIZE] += 1
            if hit:
                hit["used"] = True
                over = max(
                    (math.dist(v, m["center"]) - m["radius"]
                     for t in triangles(d, m["tris"], m["n"]) for v in t["v"]),
                    default=0.0)
                worst_sphere = max(worst_sphere, over)
                st["mesh: sphere contains its triangles"][over <= 1e-2] += 1
        st["every triangle array has a mesh"][
            all(s.get("used") for s in tri_secs.values())] += 1

        # --- tree
        nd = nodes(d, secs)
        by_off = {x["offset"]: x for x in nd}
        root = max(by_off)
        seen, edges, stack = set(), 0, [root]
        while stack:
            o = stack.pop()
            if o in seen:
                continue
            seen.add(o)
            for f in ("child", "next"):
                if by_off[o][f] is not None:
                    stack.append(by_off[o][f])
                    edges += 1
        st["tree: reaches every node"][len(seen) == len(nd)] += 1
        st["tree: edges == nodes-1"][edges == len(nd) - 1] += 1
        st["tree: root has index 0"][by_off[root]["index"] == 0] += 1
        st["root == the only type-0x208 row"][
            next(s["kind"] for s in secs if s["target"] == root) == 0x208] += 1
        for x in nd:
            if x["mesh"] is not None:
                st["node: mesh pointer valid"][
                    x["mesh"] in {s["target"] for s in secs if s["cls"] == "mesh"}] += 1
        mats = materials(d, secs)
        st["material #0 == default (0,0,ff000000)"][
            bool(mats) and mats[0]["flags"] == (0, 0)
            and mats[0]["color"] == 0xff000000] += 1

    print(f"=== .hcb structure over {len(files)} files ===")
    for k, v in st.items():
        tot = sum(v.values())
        ok = v.get(True, 0)
        print(f"  {k:42s} {ok}/{tot}" + ("" if ok == tot else "   <-- WARNING"))
    print(f"  worst mesh-sphere overshoot: {worst_sphere:.3g}")


def check_tris(paths=None):
    """The two recomputable triangle invariants."""
    n = norm = sph = degen = 0
    worst = []
    for p in _files(paths):
        for t in parse_file(p)["tris"]:
            n += 1
            v = t["v"]
            e1 = [v[1][k] - v[0][k] for k in range(3)]
            e2 = [v[2][k] - v[0][k] for k in range(3)]
            cr = (e1[1] * e2[2] - e1[2] * e2[1],
                  e1[2] * e2[0] - e1[0] * e2[2],
                  e1[0] * e2[1] - e1[1] * e2[0])
            L = math.sqrt(sum(c * c for c in cr))
            if L < 1e-6:
                degen += 1
            else:
                e = max(abs(cr[k] / L - t["normal"][k]) for k in range(3))
                if e < 1e-3:
                    norm += 1
                else:
                    worst.append((e, os.path.basename(p), t["offset"]))
            if max(math.dist(x, t["center"]) for x in v) <= t["radius"] * (1 + 1e-5) + 1e-3:
                sph += 1
    ok = n - degen
    print(f"=== .hcb triangles: {n} records ({degen} degenerate) ===")
    print(f"  normal == normalize(cross): {norm}/{ok}  ({100*norm/max(ok,1):.4f}%)")
    print(f"  sphere contains its 3 vertices: {sph}/{n}  ({100*sph/max(n,1):.4f}%)")
    for w in sorted(worst, reverse=True)[:5]:
        print(f"    error {w[0]:.4g} in {w[1]} @0x{w[2]:x}")


def bbox(tris):
    lo = [1e30] * 3
    hi = [-1e30] * 3
    for t in tris:
        for v in t["v"]:
            for a in range(3):
                lo[a] = min(lo[a], v[a])
                hi[a] = max(hi[a], v[a])
    return lo, hi


def check_model():
    """.hcb triangle bbox vs the AABB declared by the gimmick's .model."""
    import parse_gmk as G
    import parse_model as M
    res = collections.Counter()
    rows = []
    ratios = []
    for gp in sorted(glob.glob(os.path.join(GMK_DIR, "*.gmk"))):
        ent = G.parse(gp)
        for suf in ("BEFORE", "AFTER"):
            col = [a for k, a in ent if k == "COLLISION_" + suf]
            mdl = [a for k, a in ent if k == "MODEL_" + suf]
            if not col or not mdl:
                continue
            hp, mp = G.resolve(col[0][-1]), G.resolve(mdl[0][-1])
            if not (hp and mp and hp.endswith(".hcb")):
                continue
            try:
                rad = float(col[0][0]) if len(col[0]) >= 2 else None
            except ValueError:
                rad = None
            tris = parse_file(hp)["tris"]
            if not tris:
                res["hcb with no triangles"] += 1
                continue
            lo, hi = bbox(tris)
            try:
                aabb = M.parse_file(mp)["aabb"]
            except Exception:
                res["model unreadable"] += 1
                continue
            mlo, mhi = list(aabb["min"]), list(aabb["max"])
            res["boxes overlap" if all(
                lo[a] <= mhi[a] + 1e-3 and hi[a] >= mlo[a] - 1e-3
                for a in range(3)) else "DISJOINT"] += 1
            ext = max(mhi[a] - mlo[a] for a in range(3)) or 1.0
            dif = max(max(abs(lo[a] - mlo[a]), abs(hi[a] - mhi[a]))
                      for a in range(3)) / ext
            res["within 2%" if dif < .02 else "within 10%" if dif < .10
                else "within 30%" if dif < .30 else "beyond 30%"] += 1
            rows.append((dif, os.path.basename(gp), os.path.basename(hp),
                         lo, hi, mlo, mhi))
            if rad:
                ratios.append(rad / max(math.dist(lo, hi) / 2, 1e-6))
    print(f"=== .hcb vs .model, {len(rows)} pairs declared by gimmicks ===")
    for k, v in res.most_common():
        print(f"  {k:22s} {v}")
    rows.sort()
    print("  best:")
    for r in rows[:4]:
        print(f"    {r[0]*100:6.2f}%  {r[1]:16s} {r[2]}")
        print(f"            hcb   {[round(v,2) for v in r[3]]} .. {[round(v,2) for v in r[4]]}")
        print(f"            model {[round(v,2) for v in r[5]]} .. {[round(v,2) for v in r[6]]}")
    print("  worst:")
    for r in rows[-3:]:
        print(f"    {r[0]*100:6.2f}%  {r[1]:16s} {r[2]}")
        print(f"            hcb   {[round(v,2) for v in r[3]]} .. {[round(v,2) for v in r[4]]}")
        print(f"            model {[round(v,2) for v in r[5]]} .. {[round(v,2) for v in r[6]]}")
    if ratios:
        ratios.sort()
        print(f"\n  the COLLISION_* float is NOT the radius: ratio to the real"
              f" radius median {ratios[len(ratios)//2]:.2f},"
              f" from {ratios[0]:.2f} to {ratios[-1]:.2f}"
              f" over {len(ratios)} non-zero values")


def check_kinds(paths=None):
    """Evidence that the table's "type" field is not a type."""
    kc = collections.defaultdict(collections.Counter)
    first = collections.Counter()
    seq_file = collections.Counter()
    seq_kind = collections.Counter()
    files = _files(paths)
    for p in files:
        secs = sections(open(p, "rb").read())[:-1]
        for s in secs:
            kc[s["kind"]][s["cls"]] += 1
        first[secs[0]["cls"]] += 1
        seq_file[tuple(s["cls"] for s in secs)] += 1
        seq_kind[tuple(s["cls"] for s in
                       sorted(secs, key=lambda x: (x["kind"], x["target"])))] += 1
    print(f"=== the \"type\" field over {len(files)} files ===")
    for k in sorted(kc):
        tot = sum(kc[k].values())
        print(f"  0x{k:03x}: {tot:5d} rows -> {dict(kc[k])}")
    print("\n  only these two are exact: 0x206 = triangle array,"
          " 0x208 = root node.")
    print(f"\n  first row of the file, by class: {dict(first)}")
    print(f"  distinct sequences in file order: {len(seq_file)}")
    print(f"  distinct sequences by type      : {len(seq_kind)}")
    print("  in file order (top 3):")
    for s, n in seq_file.most_common(3):
        print(f"    {n:4d}  {s}")
    print("  sorted by type (top 3) - the regularity breaks:")
    for s, n in seq_kind.most_common(3):
        print(f"    {n:4d}  {s}")


def check_pivot(paths=None):
    """The three trailing floats of a node: authored, not derived."""
    st = collections.defaultdict(collections.Counter)
    ex = []
    for p in _files(paths):
        d = open(p, "rb").read()
        m = parse(d)
        by_off = {x["offset"]: x for x in m["meshes"]}
        for x in m["nodes"]:
            if x["pivot"] == (0.0, 0.0, 0.0):
                st["zero"][True] += 1
                continue
            st["zero"][False] += 1
            if x["mesh"] is None:
                st["non-zero, no mesh"][True] += 1
                continue
            mesh = by_off[x["mesh"]]
            tris = triangles(d, mesh["tris"], mesh["n"])
            lo, hi = bbox(tris)
            mid = [(lo[a] + hi[a]) / 2 for a in range(3)]
            ds = max(abs(x["pivot"][a] - mesh["center"][a]) for a in range(3))
            dm = max(abs(x["pivot"][a] - mid[a]) for a in range(3))
            dt = max(abs(x["pivot"][a] - x["t"][a]) for a in range(3))
            st["vs sphere centre"]["exact" if ds == 0 else
                                   "<1e-3" if ds < 1e-3 else "no"] += 1
            st["vs bbox centre"]["exact" if dm == 0 else
                                 "<1e-3" if dm < 1e-3 else "no"] += 1
            st["vs translation"]["<1e-3" if dt < 1e-3 else "no"] += 1
            if ds >= 1e-3 and len(ex) < 5:
                ex.append((os.path.basename(p), x["name"], x["pivot"],
                           mesh["center"]))
    print("=== the three trailing floats of a node ===")
    for k, v in st.items():
        print(f"  {k:22s} {dict(v)}")
    print("  cases matching nothing recomputable:")
    for e in ex:
        print(f"    {e[0]:20s} {e[1]!r:18s} pivot={tuple(round(v,3) for v in e[2])}"
              f"  sphere centre={tuple(round(v,3) for v in e[3])}")


# --------------------------------------------------------------------------
def summary(path):
    d = open(path, "rb").read()
    m = parse(d)
    print(f"=== {os.path.basename(path)} - {m['size']} bytes ===")
    for s in m["sections"]:
        print(f"  row +{s['row']:03x}  type 0x{s['kind']:03x}  {s['cls']:5s}"
              f"  rel {s['rel']:+8d} -> 0x{s['target']:06x}  size {s['size']}")
    print(f"\n  {len(m['tris'])} triangles in {len(m['meshes'])} meshes,"
          f" {len(m['materials'])} materials, {len(m['nodes'])} nodes")
    if m["tris"]:
        lo, hi = bbox(m["tris"])
        print(f"  bbox min ({lo[0]:.2f}, {lo[1]:.2f}, {lo[2]:.2f})"
              f"  max ({hi[0]:.2f}, {hi[1]:.2f}, {hi[2]:.2f})")
    for i, mat in enumerate(m["materials"]):
        print(f"    material #{i} @0x{mat['offset']:x}"
              f"  flags 0x{mat['flags'][0]:x}/0x{mat['flags'][1]:x}"
              f"  colour {mat['color']:08x}")
    by_off = {x["offset"]: x for x in m["nodes"]}
    mesh_by = {x["offset"]: x for x in m["meshes"]}
    print("\n  scene graph:")

    def walk(o, dep):
        x = by_off[o]
        bits = []
        if x["t"] != (0.0, 0.0, 0.0):
            bits.append("T=" + str(tuple(round(v, 2) for v in x["t"])))
        if any(x["r"]):
            bits.append("R=" + str(tuple(round(v, 3) for v in x["r"][:3])))
        if x["s"] not in ((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)):
            bits.append("S=" + str(tuple(round(v, 2) for v in x["s"])))
        if x["pivot"] != (0.0, 0.0, 0.0):
            bits.append("pivot=" + str(tuple(round(v, 2) for v in x["pivot"])))
        if x["mesh"] is not None:
            g = mesh_by[x["mesh"]]
            bits.append(f"mesh {g['n']} tris, r={g['radius']:.1f}")
        print("    " + "  " * dep + f"[{x['index']:3d}] {x['name']!r:22s} "
              + "  ".join(bits))
        if x["child"] is not None:
            walk(x["child"], dep + 1)
        if x["next"] is not None:
            walk(x["next"], dep)

    if m["root"]:
        walk(m["root"]["offset"], 0)


def to_obj(path, out):
    m = parse_file(path)
    with open(out, "w") as f:
        f.write(f"# {os.path.basename(path)} - {len(m['tris'])} triangles\n")
        for t in m["tris"]:
            for v in t["v"]:
                f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        for i in range(len(m["tris"])):
            a = i * 3 + 1
            f.write(f"f {a} {a+1} {a+2}\n")
    print(f"wrote {out}: {len(m['tris'])} triangles")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "--check":
        check()
    elif a[0] == "--check-tris":
        check_tris()
    elif a[0] == "--check-model":
        check_model()
    elif a[0] == "--kinds":
        check_kinds()
    elif a[0] == "--pivot":
        check_pivot()
    else:
        p = a[0] if os.path.exists(a[0]) else os.path.join(COL_DIR, a[0])
        if "--obj" in a:
            to_obj(p, a[a.index("--obj") + 1])
        else:
            summary(p)
