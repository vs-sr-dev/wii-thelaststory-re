r"""The Last Story collision (.hocb / .hcb) -- BINARY.

Two twin formats sharing a header family: `.hocb` (351 files, magic `COH@`) and
`.hcb` (388 files, magic `BCH@`). The magic is the tag `@HOC`/`@HCB` stored
byte-swapped. A `.map` names its own with a COLLI_TREE row; gimmicks use the
`.hcb` files (COLLISION_BEFORE/AFTER, see parse_gmk.py).

This is NOT a `chnkdata` container -- the generic parser is no help.

--- THE KEY: OFFSETS ARE SELF-RELATIVE -------------------------------------
Every offset is relative to the position of the field holding it, not to the
start of the file:

    target = address_of_field + value

That is why words like `ffffff70` show up: they are NEGATIVE s32, pointers
running backwards. Read as absolute offsets they are nonsense, and that is the
format's main trap.

--- header -----------------------------------------------------------------
    +0x00  char[4]  'COH@' / 'BCH@'
    +0x04  u32      0x00010000  version
    +0x08  u32      total file size  (exact on all 739)
    +0x20  u32      nSections  \  table DESCRIPTOR, not a section
    +0x24  u32      4 + n*16    >  the relation is exact on 739/739
    +0x28  u32      formatID   /   0x204 in .hocb, 0x209 in .hcb
    +0x30  ...      table: nSections rows of 16 bytes
                    (relativeOffset, size, type, flags)

.hocb always has 3 sections, .hcb between 5 and 88. In .hocb:
    type 0x203 -> collision MATERIAL table (32-byte entries)
    type 0x200 -> the TRIANGLE ARRAY
    type 0x003 -> tail

WARNING: the declared sections do NOT cover the file. Between the end of the
triangles and the tail sits the bulk of the content -- 285,612 bytes in
dg001_01, 64% -- and it is the OCTREE the .map's COLLI_TREE key is named after.
See node_at(), tree() and --check-tree: it is decoded.

--- THE OCTREE -------------------------------------------------------------
An 80-byte record, identical for internal nodes and leaves (see node_at). The
ROOT is the last record in the file, at (tailStart - 80), and is named "0".

The 8 child slots sit at fixed positions and the position IS the octant:
bit0 = X, bit1 = Y, bit2 = Z. A node's name is its PATH from the root
("0" -> "00" -> "003" -> "0033" -> "00332"), and the last digit always equals
the index of the slot its parent keeps it in.

Validated at 100% over all 351 files (--check-tree), 253,447 nodes:
  - 253,096 edges, and with 351 roots the arithmetic is exact
    (nodes - roots = edges): no cycles, no orphans;
  - 253,096/253,096 children are the EXACT octant of the parent, split at the
    midpoint on every axis;
  - 253,096/253,096 have name = parent's name + one digit, and that digit is
    the slot index;
  - 1,314,561/1,314,561 triangle references intersect their own cell.
A triangle appears in ~3.2 cells on average: it is assigned to every cell it
INTERSECTS, not just the one containing it.

Three checks of the self-relative convention (--check-offsets), each 351/351:
  - the tail: target + size lands EXACTLY on the file size;
  - the materials end exactly where the triangles begin;
  - the triangle array is an exact multiple of 72 bytes.
None of these works if the offsets are read as absolute.

Collision material: 32 bytes of which only three words carry anything --
bitfields at +0x00 and +0x04, an ARGB colour at +0x08; +0x0c..+0x1c are zero in
every one of the 1781 entries. Entry #0 of every file is the default (flags
0/0, colour 0xff000000) in 351 of 351 files. The flags are NOT decoded, but
three readings have been ruled out -- see check_materials().

--- the TRIANGLE record: 72 bytes ------------------------------------------
    +0x00  s32      self-relative pointer to a collision material
    +0x04  u32      0
    +0x08  f32[3]   v0        \
    +0x14  f32[3]   v1         > the three vertices, WORLD coordinates (f32)
    +0x20  f32[3]   v2        /
    +0x2c  f32[3]   face normal
    +0x38  f32[3]   bounding-sphere centre
    +0x44  f32      bounding-sphere radius

The vertices are neither quantised nor indexed: every triangle carries its own
three, in full. No vertex buffer, no indices -- collision is a triangle soup
with precomputed broad-phase data. That costs 3x the space of an indexed mesh,
and is exactly the trade you make when every query must read a whole triangle
with no indirection.

The pointer at +0x00 is self-relative like all the others: within a file most
triangles point at the same entry (in dg001_01: 2226 of 2242 at material #0,
12 at #2, 4 at #1).

--- how we know we are reading it right (--check, --check-map) -------------
Over 739 files and 413,385 non-degenerate triangles:

1. NORMAL = normalize(cross(v1-v0, v2-v0)): matches on 413,379, i.e. 99.9985%.
   All 6 misses are near-collinear SLIVERS (area down to 1.8e-5; in one the
   edges are 14.979 + 15.161 = 30.141 exactly). There the normal is
   numerically unstable and in one case the engine itself wrote (0,0,0). Not a
   reading problem.

2. THE SPHERE CONTAINS ITS THREE VERTICES: 413,385 of 413,385 -- 100%. This is
   the invariant that settles the (centre, radius) reading; a misread field
   does not produce spheres that always enclose their own triangle.

3. WHICH sphere: 99.91% match a closed form EXACTLY -- the midpoint of the
   longest edge with half its length (82.97%) or the centroid with the maximum
   vertex distance (16.94%); only 0.09% match neither. But what SELECTS between
   the two is not pinned down: it is not "whichever is tighter" (the stored
   sphere is sometimes wider than the available candidate), and redoing the
   arithmetic in float32 makes agreement worse, not better. It is a derived
   acceleration field; knowing it is a bounding sphere is enough to use or
   regenerate it.

4. BBOX vs MAP (--check-map): a cross-check between a binary format and an
   independent text one. Of 362 maps with a COLLI_TREE and readable terrain, 3
   match at 0.0% (identical XZ bbox) and 155 fall within 10% of the map extent.
   The others are not errors: collision extends past the visible terrain
   (invisible walls, out-of-bounds barriers -- dg012_05 has a containment box
   at +-5371.8), and some maps share one collision file.

Usage:
    python parse_hocb.py FILE            # summary
    python parse_hocb.py --check         # normals + spheres over every file
    python parse_hocb.py --check-offsets # the self-relative convention
    python parse_hocb.py --check-map     # collision bbox vs map terrain bbox
    python parse_hocb.py --materials     # what the material flags are NOT
    python parse_hocb.py --check-tree    # the octree invariants
    python parse_hocb.py --check-ground  # collision floor vs rendering floor
    python parse_hocb.py FILE --obj OUT  # export the soup as .obj
"""
import sys, os, glob, struct, math, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS = os.path.join(ROOT, "assets", "pack", "filesystem")
COL_DIR = os.path.join(FS, "data", "collision")
MAP_DIR = os.path.join(FS, "data", "map")

TRI_SIZE = 72
MAGICS = (b"COH@", b"BCH@")


def _u32(d, o): return struct.unpack_from(">I", d, o)[0]
def _s32(d, o): return struct.unpack_from(">i", d, o)[0]


def sections(d):
    """The table rows, with the offset already resolved (self-relative).

    The row at 0x20 is NOT a section: it is the table descriptor,
    (nSections, 4 + nSections*16, formatID, 0). The relation between its first
    two fields is exact on all 739 files, and that is how you know how many
    rows to read: .hocb has 3, .hcb has 5 to 88.
    """
    n = _u32(d, 0x20)
    out = []
    for i in range(n):
        o = 0x30 + i * 16
        if o + 16 > len(d):
            break
        rel, size, kind, flags = struct.unpack_from(">iIII", d, o)
        out.append({"row": o, "rel": rel, "target": o + rel, "size": size,
                    "kind": kind, "flags": flags})
    return out


def table_header(d):
    """(nSections, field1, formatID) from the descriptor row at 0x20."""
    n, sz, fmt, _ = struct.unpack_from(">4I", d, 0x20)
    return n, sz, fmt


def parse(d):
    """-> {'tris': [...], 'sections': [...]}."""
    assert d[:4] in MAGICS, f"unexpected magic {d[:4]!r}"
    secs = sections(d)
    tri = next((s for s in secs if s["kind"] == 0x200), None)
    if tri is None:
        return {"sections": secs, "tris": [], "size": len(d)}
    base, size = tri["target"], tri["size"]
    n = size // TRI_SIZE
    tris = []
    for i in range(n):
        o = base + i * TRI_SIZE
        f = struct.unpack_from(">15f", d, o + 8)
        tris.append({
            "offset": o,
            "material": o + _s32(d, o),   # self-relative pointer
            "v": (f[0:3], f[3:6], f[6:9]),
            "normal": f[9:12],
            "center": f[12:15],
            "radius": struct.unpack_from(">f", d, o + 0x44)[0],
        })
    return {"sections": secs, "tris": tris, "size": len(d)}


def parse_file(path):
    with open(path, "rb") as f:
        return parse(f.read())


# --------------------------------------------------------------------------
# recomputable invariants
# --------------------------------------------------------------------------
def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _len(a): return math.sqrt(_dot(a, a))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def face_normal(v):
    n = _cross(_sub(v[1], v[0]), _sub(v[2], v[0]))
    L = _len(n)
    return (n[0] / L, n[1] / L, n[2] / L) if L > 1e-12 else (0.0, 0.0, 0.0)


def sphere_edge(v):
    """Candidate A: midpoint of the longest edge, radius half its length."""
    pairs = ((0, 1), (1, 2), (0, 2))
    i, j = max(pairs, key=lambda p: _len(_sub(v[p[1]], v[p[0]])))
    return (tuple((v[i][k] + v[j][k]) / 2 for k in range(3)),
            _len(_sub(v[j], v[i])) / 2)


def sphere_centroid(v):
    """Candidate B: centroid, radius = max distance to a vertex."""
    c = tuple((v[0][k] + v[1][k] + v[2][k]) / 3 for k in range(3))
    return c, max(_len(_sub(p, c)) for p in v)


def _rel(a, b, scale):
    """Error relative to the triangle scale, not absolute."""
    return abs(a - b) / max(scale, 1.0)


def check(paths=None, verbose=True):
    files = paths or sorted(glob.glob(os.path.join(COL_DIR, "*.hocb")) +
                            glob.glob(os.path.join(COL_DIR, "*.hcb")))
    tally = collections.Counter()
    worst_n = (0.0, "", 0)
    strat = collections.Counter()
    for p in files:
        try:
            m = parse_file(p)
        except Exception as e:
            tally["unreadable file"] += 1
            if verbose:
                print(f"  ERROR {os.path.basename(p)}: {e}")
            continue
        for i, t in enumerate(m["tris"]):
            v = t["v"]
            scale = max(_len(_sub(v[1], v[0])), _len(_sub(v[2], v[0])), 1.0)
            area = _len(_cross(_sub(v[1], v[0]), _sub(v[2], v[0]))) / 2
            if area < 1e-9:
                tally["degenerate triangle (zero area)"] += 1
                continue
            n = face_normal(v)
            dn = max(abs(n[k] - t["normal"][k]) for k in range(3))
            tally["normal ok" if dn < 1e-3 else "normal WRONG"] += 1
            if dn > worst_n[0]:
                worst_n = (dn, os.path.basename(p), i)

            # the invariant that MUST always hold: the sphere encloses the tri
            slack = max(_len(_sub(q, t["center"])) for q in v) - t["radius"]
            tally["sphere encloses its 3 vertices" if slack <= 1e-3 * scale
                  else "sphere does NOT enclose them"] += 1

            def m_(cr):
                c, r = cr
                return (max(_rel(c[k], t["center"][k], scale) for k in range(3)) < 1e-4
                        and _rel(r, t["radius"], scale) < 1e-4)
            ma, mb = m_(sphere_edge(v)), m_(sphere_centroid(v))
            strat["longest edge" if ma and not mb else
                  ("centroid" if mb and not ma else
                   ("both" if ma else "neither"))] += 1
    tot = tally["normal ok"] + tally["normal WRONG"]
    print(f"{len(files)} files, {tot} non-degenerate triangles\n")
    for k in sorted(tally):
        print(f"  {tally[k]:>8}  {k}")
    print("\n  which closed form reproduces the sphere EXACTLY:")
    for k, n in strat.most_common():
        print(f"  {n:>8}  {k}   ({100*n/max(tot,1):.2f}%)")
    print(f"\n  max normal error : {worst_n[0]:.2e}  ({worst_n[1]} #{worst_n[2]})")


def check_offsets():
    """Does the self-relative convention hold across the whole disc?

    The decisive test: the type-3 row is the file tail, so target + size must
    land EXACTLY on the file size.
    """
    files = sorted(glob.glob(os.path.join(COL_DIR, "*.hocb")) +
                   glob.glob(os.path.join(COL_DIR, "*.hcb")))
    tally = collections.Counter()
    for p in files:
        d = open(p, "rb").read()
        if d[:4] not in MAGICS:
            tally["unexpected magic"] += 1
            continue
        tally["header size == real size" if _u32(d, 8) == len(d)
              else "header size wrong"] += 1
        n, sz, fmt = table_header(d)
        tally["descriptor: field1 == 4 + n*16" if sz == 4 + n * 16
              else "descriptor INCONSISTENT"] += 1
        secs = sections(d)
        tally[f"{len(secs)} sections ({os.path.splitext(p)[1]})"] += 1
        tail = next((s for s in secs if s["kind"] == 3), None)
        if tail:
            end = tail["target"] + tail["size"]
            tally["tail ends at end of file" if end == len(d)
                  else f"tail off by {end - len(d)}"] += 1
        tri = next((s for s in secs if s["kind"] == 0x200), None)
        if tri:
            tally["triangle array is a multiple of 72" if tri["size"] % TRI_SIZE == 0
                  else "triangle array NOT a multiple of 72"] += 1
            mat = next((s for s in secs if s["kind"] == 0x203), None)
            if mat:
                tally["materials end where triangles begin"
                      if mat["target"] + mat["size"] == tri["target"]
                      else "materials NOT adjacent to triangles"] += 1
    for k in sorted(tally):
        print(f"  {tally[k]:>5}  {k}")


def bbox(tris):
    lo = [1e30] * 3
    hi = [-1e30] * 3
    for t in tris:
        for v in t["v"]:
            for k in range(3):
                lo[k] = min(lo[k], v[k])
                hi[k] = max(hi[k], v[k])
    return lo, hi


def check_map():
    """Does the collision bbox match the map geometry's?

    A cross-check between a binary format and a text one: if the .hocb were
    read wrong, the two volumes would have no reason to coincide.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import parse_model
    rows = []
    for mp in sorted(glob.glob(os.path.join(MAP_DIR, "*.map"))):
        colli, models = None, []
        for line in open(mp, "r", encoding="utf-8", errors="replace"):
            f = line.rstrip("\r\n").split("\t")
            if f[0] == "COLLI_TREE" and len(f) > 1:
                colli = os.path.basename(f[1])
            elif f[0] == "MODEL" and len(f) > 1:
                models.append(os.path.basename(f[1]))
        cp = os.path.join(COL_DIR, colli) if colli else None
        if not cp or not os.path.exists(cp):
            continue
        lo = [1e30] * 3
        hi = [-1e30] * 3
        got = False
        for m in models:
            # terrain only: no sky, backdrops or occluders
            if "_base" not in m or "hide" in m:
                continue
            q = os.path.join(FS, "data", "model", m)
            if not os.path.exists(q):
                continue
            a = parse_model.parse_file(q)["aabb"]
            if any(math.isnan(x) for x in a["min"] + a["max"]):
                continue
            got = True
            for k in range(3):
                lo[k] = min(lo[k], a["min"][k])
                hi[k] = max(hi[k], a["max"][k])
        if not got:
            continue
        clo, chi = bbox(parse_file(cp)["tris"])
        # horizontal error, normalised over the map extent
        span = max(hi[0] - lo[0], hi[2] - lo[2], 1.0)
        err = max(abs(clo[0] - lo[0]), abs(chi[0] - hi[0]),
                  abs(clo[2] - lo[2]), abs(chi[2] - hi[2])) / span
        rows.append((err, os.path.basename(mp), colli, lo, hi, clo, chi))
    rows.sort()
    good = sum(1 for r in rows if r[0] < 0.10)
    print(f"{len(rows)} maps with a COLLI_TREE and readable terrain")
    print(f"  {good} with an XZ bbox within 10% of the map extent\n")

    def show(rs):
        for e, mp, c, lo, hi, clo, chi in rs:
            print(f"   {e*100:5.1f}%  {mp:<18} terrain   X[{lo[0]:8.1f},{hi[0]:8.1f}]"
                  f" Z[{lo[2]:8.1f},{hi[2]:8.1f}]")
            print(f"           {'':<18} collision X[{clo[0]:8.1f},{chi[0]:8.1f}]"
                  f" Z[{clo[2]:8.1f},{chi[2]:8.1f}]")
    print("  best:")
    show(rows[:4])
    print("  worst:")
    show(rows[-3:])


def materials(d):
    """The entries of the 0x203 section. 32 bytes, of which 3 useful words."""
    ss = [s for s in sections(d) if s["kind"] == 0x203]
    if not ss:
        return []
    s = ss[0]
    out = []
    for i in range(s["size"] // 32):
        o = s["target"] + i * 32
        f0, f4, argb = struct.unpack_from(">3I", d, o)
        out.append({"index": i, "offset": o, "flags0": f0, "flags4": f4,
                    "argb": argb})
    return out


def colli_for_map(map_file):
    """The .hocb a map declares with COLLI_TREE, or None."""
    mp = map_file if os.path.exists(map_file) else os.path.join(MAP_DIR, map_file)
    if not os.path.exists(mp):
        return None
    for line in open(mp, "r", encoding="utf-8", errors="replace"):
        f = line.rstrip("\r\n").split("\t")
        if f[0] == "COLLI_TREE" and len(f) > 1:
            p = os.path.join(COL_DIR, os.path.basename(f[1]))
            return p if os.path.exists(p) else None
    return None


def soup(d):
    """The collision as (verts, faces), ready for a renderer or for Ground."""
    tris = parse(d)["tris"]
    verts, faces = [], []
    for i, t in enumerate(tris):
        verts.extend(t["v"])
        faces.append((i * 3, i * 3 + 1, i * 3 + 2))
    return verts, faces


class Collision:
    """Vertical queries against the collision, using the file's OCTREE.

    This is what the octree is for: instead of sweeping every triangle (or
    building a separate grid, as Ground does in walk_poc.py over the rendering
    geometry), you descend the tree and look only at the cells above the query
    point. On dg001_01 that is ~10 triangles instead of 2242.
    """

    def __init__(self, data):
        self.d = data
        self.tree = tree(data)
        self.root = self.tree["root"] if self.tree else None

    def _leaves_over(self, x, z, o, out):
        nd = self.tree["nodes"].get(o)
        if nd is None:
            return
        lo, hi = nd["aabb"][:3], nd["aabb"][3:]
        # the ray is vertical: the cell only has to cover (x, z)
        if not (lo[0] - 1e-3 <= x <= hi[0] + 1e-3 and
                lo[2] - 1e-3 <= z <= hi[2] + 1e-3):
            return
        if nd["tris"] and nd["tris"] != ["MALFORMATO"]:
            out.extend(nd["tris"])
        for _, c in nd["children"]:
            self._leaves_over(x, z, c, out)

    def hits(self, x, z):
        """Heights of every surface above/below (x,z), highest first."""
        if self.root is None:
            return []
        refs, out = [], []
        self._leaves_over(x, z, self.root, refs)
        for a in set(refs):
            v = struct.unpack_from(">9f", self.d, a + 8)
            p0, p1, p2 = v[0:3], v[3:6], v[6:9]
            den = ((p1[2] - p2[2]) * (p0[0] - p2[0]) +
                   (p2[0] - p1[0]) * (p0[2] - p2[2]))
            if abs(den) < 1e-12:
                continue
            w0 = ((p1[2] - p2[2]) * (x - p2[0]) +
                  (p2[0] - p1[0]) * (z - p2[2])) / den
            w1 = ((p2[2] - p0[2]) * (x - p2[0]) +
                  (p0[0] - p2[0]) * (z - p2[2])) / den
            w2 = 1.0 - w0 - w1
            if w0 < -1e-6 or w1 < -1e-6 or w2 < -1e-6:
                continue
            out.append(w0 * p0[1] + w1 * p1[1] + w2 * p2[1])
        out.sort(reverse=True)
        return out

    def height(self, x, z, ref=None, tol=40.0):
        """Standing height at (x,z): same semantics as Ground.height."""
        hs = self.hits(x, z)
        if not hs:
            return None
        if ref is None:
            return hs[0]
        below = [h for h in hs if h <= ref + tol]
        return below[0] if below else None


def check_ground(map_file="dg001_01.map"):
    """Does the COLLISION floor agree with the RENDERING floor?

    The session-6 PoC walks the character over the visible mesh. If the
    collision is read correctly, querying the two surfaces at the same point
    must give the same height -- and where it does not there should be a
    reason (collision has invisible walls and floors the graphics never draw).
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_scene, walk_poc
    import random
    mp = os.path.join(MAP_DIR, map_file)
    colli = None
    for line in open(mp, "r", encoding="utf-8", errors="replace"):
        f = line.rstrip("\r\n").split("\t")
        if f[0] == "COLLI_TREE" and len(f) > 1:
            colli = os.path.basename(f[1])
    scratch = os.path.join(ROOT, "obj_out", "_colli_cmp_scene.obj")
    sc = build_scene.build(map_file, scratch, terrain_only=True, gimmick=False)
    ground = walk_poc.Ground(sc.verts, sc.faces)
    col = Collision(open(os.path.join(COL_DIR, colli), "rb").read())

    rnd = random.Random(12345)
    x0, x1 = ground.x0, ground.x0 + ground.nx * ground.cell
    z0, z1 = ground.z0, ground.z0 + ground.nz * ground.cell
    both, only_r, only_c, none = [], 0, 0, 0
    for _ in range(4000):
        x = rnd.uniform(x0, x1)
        z = rnd.uniform(z0, z1)
        # Both geometries are LAYERED (stacked floors, bridges, roofs) and
        # collision additionally has walls and invisible barriers. Comparing
        # "highest surface" against "highest surface" is therefore the wrong
        # test. The right question is: does every rendering surface have a
        # collision surface matching it?
        hrs = ground.hits(x, z)
        hcs = col.hits(x, z)
        if hrs and hcs:
            both.extend(min(abs(hr - hc) for hc in hcs) for hr in hrs)
        elif hrs:
            only_r += 1
        elif hcs:
            only_c += 1
        else:
            none += 1
    both.sort()
    print(f"{map_file}  <->  {colli}")
    print(f"  points with both surfaces   : {len(both)}")
    print(f"  rendering only              : {only_r}")
    print(f"  collision only              : {only_c}")
    print(f"  neither                     : {none}")
    if both:
        n = len(both)
        print("\n  height difference between the two surfaces:")
        print(f"    median {both[n//2]:.3f}   90th {both[int(n*.9)]:.3f}"
              f"   max {both[-1]:.3f}")
        for t in (0.01, 0.1, 1.0, 5.0):
            k = sum(1 for v in both if v <= t)
            print(f"    within {t:>5} units: {k:>5} ({100*k/n:.1f}%)")


def check_materials():
    """What are the material flags? Largely a NEGATIVE result.

    Worth knowing what they are *not*, so nobody re-runs these:

    - They are NOT a floor/wall classification. That would be redundant: the
      normal is already in the triangle record. Correlating with orientation
      separates nothing, except two bits that never appear on an up-facing
      face (+0x04 bit 8: 0.5% up over 99 files; +0x04 bit 18: 0.0% over 58
      files). Those are the "not walkable" candidates.
    - The colour at +0x08 is NOT a function of the flags: the commonest combo
      (0,0) shows up with 65 different colours. It is a hand-picked per-material
      tint with real alpha (0x82, 0x9d) -- a translucent debug overlay, not
      derived data.
    - Triangle groups carrying a special material are NOT placed gimmicks: in
      dg001_01 the two groups (4 and 12 triangles) fall on none of the map's 18
      GIMMICK_LOC positions. They are hand-authored volumes -- the 12-triangle
      one is exactly a box.

    What is settled: 32-byte entries whose +0x0c..+0x1c are always zero; two
    bitfields at +0x00 and +0x04; an ARGB at +0x08. Entry #0 of EVERY file is
    the default (flags 0/0, colour 0xff000000): 351 of 351.
    """
    files = sorted(glob.glob(os.path.join(COL_DIR, "*.hocb")))
    combos = collections.Counter()
    colours = collections.defaultdict(set)
    zeros = collections.Counter()
    first_default = 0
    for p in files:
        d = open(p, "rb").read()
        ms = materials(d)
        if ms and ms[0]["flags0"] == 0 and ms[0]["flags4"] == 0 \
                and ms[0]["argb"] == 0xff000000:
            first_default += 1
        for m in ms:
            combos[(m["flags0"], m["flags4"])] += 1
            colours[(m["flags0"], m["flags4"])].add(m["argb"])
            for w in range(3, 8):
                zeros[w] += _u32(d, m["offset"] + w * 4) != 0
    n = sum(combos.values())
    print(f"{len(files)} .hocb files, {n} material entries")
    print(f"  entry #0 is the default (0/0, 0xff000000): {first_default}/{len(files)}")
    print(f"  non-zero words in +0x0c..+0x1c: {sum(zeros.values())}")
    det = sum(1 for k, v in colours.items() if len(v) == 1)
    print(f"  {len(combos)} flag combos; with a single colour: {det}"
          f"  -> the colour is NOT a function of the flags")
    print("\n  commonest combos:")
    for k, c in combos.most_common(10):
        print(f"    f0={k[0]:08x} f4={k[1]:08x}  {c:>4} entries,"
              f" {len(colours[k])} colours")


NODE_SIZE = 80


def node_at(d, o):
    """An octree node. FIXED 80-byte record:

        +0x00  u32      N = how many triangles it holds (0 on internal nodes)
        +0x04  f32[6]   the cell's AABB, min/max
        +0x1c  s32[8]   the 8 child SLOTS (self-relative, 0 = empty)
        +0x3c  s32      pointer to the triangle list (0 when N == 0)
        +0x40  char[16] name = the node's PATH in the tree

    There are 8 slots at fixed positions: this is an octree, and the position
    tells you WHICH octant that child is, even when the other slots are empty.

    NOTE: a parent's pointers target the N field, not the AABB. The triangle
    list is a blob placed immediately BEFORE the record (N self-relative
    pointers), so the record proper begins where the blob ends.
    """
    n = _u32(d, o)
    aabb = struct.unpack_from(">6f", d, o + 4)
    slots = [(i, o + 0x1c + i * 4 + _s32(d, o + 0x1c + i * 4))
             for i in range(8) if _u32(d, o + 0x1c + i * 4)]
    tris = []
    if _u32(d, o + 0x3c):
        blob = o + 0x3c + _s32(d, o + 0x3c)
        if 0 < n <= 4096 and blob >= 0 and blob + n * 4 == o:
            tris = [blob + i * 4 + _s32(d, blob + i * 4) for i in range(n)]
        else:
            tris = ["MALFORMATO"]
    name = d[o + 0x40:o + 0x50].split(b"\0")[0].decode("ascii", "replace")
    return {"offset": o, "count": n, "aabb": aabb, "children": slots,
            "tris": tris, "name": name}


def tree(d):
    """The whole tree. The ROOT is the last record, at (tailStart - 80)."""
    r = tree_region(d)
    if not r:
        return None
    a, b, _ = r
    root = b - NODE_SIZE
    if root < a:
        return None
    nodes, stack, seen = {}, [root], set()
    while stack:
        o = stack.pop()
        if o in seen or not (a <= o < b):
            continue
        seen.add(o)
        nd = node_at(d, o)
        nodes[o] = nd
        for _, c in nd["children"]:
            stack.append(c)
    return {"root": root, "nodes": nodes}


def check_tree():
    """Does the tree hold up? Four recomputable invariants.

    1. CONTAINMENT. A node's AABB must contain its children's and every
       triangle it lists. A spatial tree cannot pass this by accident.
    2. NAMES. A child's name must be its parent's plus ONE digit: the name IS
       the path from the root.
    3. THE DIGIT IS THE SLOT INDEX. If this is an octree, the appended digit
       must match the position of the slot holding the child.
    4. THE CHILD IS THE EXACT OCTANT. bit0=X, bit1=Y, bit2=Z: the child's AABB
       must be exactly half the parent on each axis, on the side the bit picks.
       This is the decisive one -- you do not hit a regular subdivision by
       chance across a quarter of a million nodes.
    """
    files = sorted(glob.glob(os.path.join(COL_DIR, "*.hocb")))
    t = collections.Counter()
    depth = collections.Counter()
    for p in files:
        d = open(p, "rb").read()
        tr = tree(d)
        if not tr:
            t["no tree"] += 1
            continue
        t["files with a tree"] += 1
        secs = sections(d)
        tri = next((s for s in secs if s["kind"] == 0x200), None)
        T0, T1 = tri["target"], tri["target"] + tri["size"]
        for o, nd in tr["nodes"].items():
            if nd["tris"] == ["MALFORMATO"]:
                t["MALFORMED triangle blob"] += 1
                continue
            lo, hi = nd["aabb"][:3], nd["aabb"][3:]
            t["leaf node" if nd["tris"] else "internal node"] += 1
            depth[len(nd["name"])] += 1
            for i, c in nd["children"]:
                ch = tr["nodes"].get(c)
                if ch is None:
                    t["child outside the tree"] += 1
                    continue
                clo, chi = ch["aabb"][:3], ch["aabb"][3:]
                t["child AABB contained" if all(
                    clo[k] >= lo[k] - 1e-2 and chi[k] <= hi[k] + 1e-2
                    for k in range(3)) else "child AABB OUTSIDE"] += 1
                # bit0 = X, bit1 = Y, bit2 = Z: the child must be EXACTLY
                # that octant of the parent, split down the middle
                exp = []
                for k in range(3):
                    mid = (lo[k] + hi[k]) / 2
                    exp += [(mid, hi[k]) if (i >> k) & 1 else (lo[k], mid)]
                span = max(hi[k] - lo[k] for k in range(3))
                t["child == exact octant of parent" if all(
                    abs(clo[k] - exp[k][0]) < 1e-3 * span and
                    abs(chi[k] - exp[k][1]) < 1e-3 * span
                    for k in range(3)) else "child is NOT the expected octant"] += 1
                t["child name = parent + 1 digit" if
                  ch["name"][:-1] == nd["name"] and len(ch["name"]) == len(nd["name"]) + 1
                  else "child name INCONSISTENT"] += 1
                t["digit == slot index" if
                  ch["name"][-1:] == str(i) else "digit != slot index"] += 1
            for a_ in nd["tris"]:
                if not (T0 <= a_ < T1) or (a_ - T0) % TRI_SIZE:
                    t["MISALIGNED triangle pointer"] += 1
                    continue
                # a triangle belongs to every cell it INTERSECTS, not only the
                # one containing it: a large one straddles several
                v = struct.unpack_from(">9f", d, a_ + 8)
                eps = 1e-2
                hit = all(min(v[k], v[k+3], v[k+6]) <= hi[k] + eps and
                          max(v[k], v[k+3], v[k+6]) >= lo[k] - eps
                          for k in range(3))
                t["triangle intersects its cell" if hit
                  else "triangle DISJOINT from cell"] += 1
    for k in sorted(t):
        print(f"  {t[k]:>9}  {k}")
    print(f"\n  depth (name length): {dict(sorted(depth.items()))}")


def tree_region(d):
    """The region AFTER the triangle array: the spatial tree.

    The 3 declared sections do NOT cover the file: between the end of the
    triangles and the tail sits most of the content (64% in dg001_01). It is a
    spatial subdivision tree; each node carries self-relative pointers to its
    children, their count, an AABB (6 f32) and an ASCII NAME which is the
    node's path in the tree ("0" = root, then "00", "003", "0033", "00332"...).

    Node records are variable-sized and the exact layout after the AABB is not
    pinned down: the tree is located and characterised, not fully decoded.

    Returns (start, end, [names]).
    """
    import re
    secs = sections(d)
    tri = next((s for s in secs if s["kind"] == 0x200), None)
    tail = next((s for s in secs if s["kind"] == 3), None)
    if not tri or not tail:
        return None
    a, b = tri["target"] + tri["size"], tail["target"]
    names = [m.group(1).decode() for m in
             re.finditer(rb"([0-9]{1,10})\x00", d[a:b])]
    return a, b, names


def summary(path):
    m = parse_file(path)
    d = open(path, "rb").read()
    print(f"=== {os.path.basename(path)} - {m['size']} bytes ===")
    for s in m["sections"]:
        print(f"  row +{s['row']:03x}  type 0x{s['kind']:03x}  rel {s['rel']:+8d}"
              f"  -> 0x{s['target']:06x}  size 0x{s['size']:x}")
    tris = m["tris"]
    print(f"\n  {len(tris)} triangles")
    if tris:
        lo, hi = bbox(tris)
        print(f"  bbox min ({lo[0]:.1f}, {lo[1]:.1f}, {lo[2]:.1f})"
              f"  max ({hi[0]:.1f}, {hi[1]:.1f}, {hi[2]:.1f})")
    mats = collections.Counter(t["material"] for t in tris)
    print(f"  {len(mats)} distinct collision materials:")
    for a, n in mats.most_common():
        print(f"     0x{a:06x}  {n} triangles")
    tr = tree_region(d)
    if tr:
        a, b, names = tr
        print(f"\n  spatial tree: 0x{a:06x}..0x{b:06x}  ({b-a} bytes,"
              f" {100*(b-a)/m['size']:.0f}% of the file)")
        tr = tree(d)
        if tr:
            nodes = tr["nodes"]
            leaves = sum(1 for x in nodes.values() if x["tris"])
            refs = sum(len(x["tris"]) for x in nodes.values())
            depth = collections.Counter(len(x["name"]) for x in nodes.values())
            print(f"    octree: {len(nodes)} nodes ({leaves} leaves),"
                  f" {refs} triangle references"
                  f" ({refs/max(len(tris),1):.1f} cells per triangle)")
            print(f"    root {nodes[tr['root']]['name']!r},"
                  f" depth {dict(sorted(depth.items()))}")


def to_obj(path, out):
    tris = parse_file(path)["tris"]
    with open(out, "w") as f:
        f.write(f"# {os.path.basename(path)} - {len(tris)} triangles\n")
        for t in tris:
            for v in t["v"]:
                f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        for i in range(len(tris)):
            a = i * 3 + 1
            f.write(f"f {a} {a+1} {a+2}\n")
    print(f"wrote {out}: {len(tris)} triangles")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "--check":
        check()
    elif a[0] == "--check-offsets":
        check_offsets()
    elif a[0] == "--check-map":
        check_map()
    elif a[0] == "--materials":
        check_materials()
    elif a[0] == "--check-tree":
        check_tree()
    elif a[0] == "--check-ground":
        check_ground(a[1] if len(a) > 1 else "dg001_01.map")
    else:
        p = a[0] if os.path.exists(a[0]) else os.path.join(COL_DIR, a[0])
        if "--obj" in a:
            to_obj(p, a[a.index("--obj") + 1])
        else:
            summary(p)
