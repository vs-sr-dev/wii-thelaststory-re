"""Export The Last Story `.model` files (`wii modl` / NW4R) to OBJ + MTL.

Walks the file graph DETERMINISTICALLY -- no heuristics:
  mesh -> attribute->stream table (+0x1c: POS,NRM,CLR0,CLR1,TEX0..TEX7)
       -> subm list (+0x4c count, +0x50 ptr)
  subm -> pointer to its dlst chunk (the GX display list)
  dlst -> GX bytes: opcode 0x98(strip)/0xa0(fan)/0x90(quad) + count + N*stride

VERTEX LAYOUT. Each vertex is a run of index bytes: first the matrix indices
(PNMTXIDX then TEXnMTXIDX), then one index per present attribute in GX order,
each u8 or u16 depending on how many elements its stream holds. Both the stride
and the index widths vary per mesh, so solve_layout() derives them from the
constraint that every index must fall inside its own stream.

POSITIONS. Assembled into model space by skinning.py, which also resolves the
per-mesh POS quantisation. Vertices are written in the model's real units, the
same ones the header AABB is expressed in.

UV. TEX0 stream, s16 with frac 10 (/1024) -> [0,1]; written flipped, since OBJ
counts V from the bottom.

MATERIALS. Primary source is the node->mesh table (skinning.node_mesh_table),
which yields a material index into the model's embedded name table; the name is
then looked up in the twin `.material` file and its TexColor1 resolved to a PNG
under textures_png/. A secondary path uses the POS stream's name when it has
the form 'group__MATNAME'. The node table is what makes models with unnamed
streams (e.g. pc001) resolvable without any runtime material registry.

Usage:
    python export_obj.py FILE.model OUT.obj [--scale S] [--raw]

--raw skips skinning and writes the quantised positions untouched, which is
useful only to see what the assembly step actually fixes.
"""
import sys, struct, os
import parse_model as pm
import skeleton as sk

PRIM = {0x98, 0xa0, 0x90, 0x80}


def _u16(d, o): return struct.unpack_from(">H", d, o)[0]
def _s32(d, o): return struct.unpack_from(">i", d, o)[0]


# The mesh's attribute->stream table (+0x1c) has 12 slots in GX order.
# Read them ALL: pc001 mouth/teeth also use TEX1 (pointing at the same stream
# as TEX0), and skipping it shifts every following offset in the vertex.
ATTR_SLOTS = ("POS", "NRM", "CLR0", "CLR1",
              "TEX0", "TEX1", "TEX2", "TEX3", "TEX4", "TEX5", "TEX6", "TEX7")


def mesh_fields(d, mesh):
    o = mesh["offset"]
    f = {
        "matIdx": _s32(d, o+0x14),
        "nSubm": _s32(d, o+0x4c),
        "submPtr": _s32(d, o+0x50) & 0xffffffff,
        "attrStrm": [_s32(d, o+0x1c+i*4) for i in range(12)],
    }
    f["posStrm"] = f["attrStrm"][0]
    f["tex0Strm"] = f["attrStrm"][4]
    return f


def mesh_dlsts(d, mf):
    """List of (dlDataOff, dlEnd) for a mesh, following its subm chunks."""
    res = []
    for i in range(mf["nSubm"]):
        subm_off = _s32(d, mf["submPtr"] + i*4) & 0xffffffff
        if d[subm_off:subm_off+4] != b"subm":
            continue
        size = pm._u32(d, subm_off+0x0c)
        # the dlst ptr is the only u32 in the subm body pointing at a 'dlst' chunk
        dl = None
        for p in range(subm_off+0x10, subm_off+size, 4):
            v = pm._u32(d, p)
            if v+4 <= len(d) and d[v:v+4] == b"dlst" and pm._u32(d, v+8) == v:
                dl = v
                break
        if dl is None:
            continue
        dlen = pm._u32(d, dl+0x10)
        dataoff = pm._u32(d, dl+0x14)
        res.append((dataoff, min(dataoff+dlen, len(d))))
    return res


def linear_parse(d, start, end, stride):
    ops = []
    o = start
    while o < end:
        op = d[o]
        if op == 0x00:
            o += 1; continue
        if op not in PRIM or o+3 > end:
            return ops, False
        cnt = _u16(d, o+1)
        nxt = o + 3 + cnt*stride
        if cnt < 1 or nxt > end:
            return ops, False
        ops.append((o, op, cnt))
        o = nxt
    return ops, True


def detect_stride(d, start, end):
    best = (None, [], -1)
    for stride in range(3, 49):
        ops, ok = linear_parse(d, start, end, stride)
        if ok and len(ops) > best[2]:
            best = (stride, ops, len(ops))
    return best[0], best[1]


def _read_idx(d, o, w):
    return d[o] if w == 1 else _u16(d, o)


def _col_in_range(d, ops, stride, off, w, count):
    """True when column (off,w) has every index inside [0,count).

    The ">=2 distinct values" constraint disambiguates columns, but it cannot
    hold for a stream of ONE element (a constant colour: the index is always
    0). pc001 earring/necklace/op_01_strap have CLR0 with count=1, and without
    this exception the whole mesh failed to decode."""
    seen = set()
    for (pos, op, cnt) in ops:
        base = pos + 3
        for k in range(cnt):
            v = _read_idx(d, base + k*stride + off, w)
            if v >= count:
                return False
            seen.add(v)
    return len(seen) >= 2 or count == 1


def solve_layout(d, ops, stride, counts):
    """Resolve the vertex layout: k matrix-index bytes (u8) followed by the
    present attributes in GX order, each u8 or u16.
    `counts` = list of (name, streamCount) for the present attributes, in order.
    Returns {name: (offset, width)} or None. Every attribute is checked."""
    natt = len(counts)
    for k in range(0, stride):     # leading matrix-index bytes
        remaining = stride - k
        for mask in range(1 << natt):
            widths = [2 if (mask >> j) & 1 else 1 for j in range(natt)]
            if sum(widths) != remaining:
                continue
            off = k
            ok = True
            layout = {}
            for j, (name, cnt) in enumerate(counts):
                w = widths[j]
                if not _col_in_range(d, ops, stride, off, w, cnt):
                    ok = False
                    break
                layout[name] = (off, w)
                off += w
            if ok and "POS" in layout:
                return layout
    return None


def read_pos(d, strm, i):
    return struct.unpack_from(">hhh", d, strm["dataOff"] + i*6)


def attr_counts(d, strm, mf):
    """Attributes present in the mesh, in GX order, with their stream count.
    Walks all 12 slots: skipping one (e.g. TEX1) shifts every later offset and
    the vertex layout stops adding up."""
    return [(ATTR_SLOTS[i], strm[si]["count"])
            for i, si in enumerate(mf["attrStrm"])
            if 0 <= si < len(strm)]


def mesh_geometry(d, model, mesh):
    """Decode one mesh, following mesh -> subm -> dlst.

    Returns (verts, tris, uvs):
      verts[i] = ((x,y,z) RAW s16, matIdx)   matIdx = -1 when unskinned
      uvs[i]   = (u,v), already in [0,1]
      tris     = triangles as indices into verts

    matIdx comes from the chain PNMTXIDX/3 -> subm.matrixList (see skinning.py).
    Unskinned meshes carry no PNMTXIDX byte at all; they are recognised by the
    layout having no matrix-index bytes (POS sits at offset 0).
    """
    import skinning as skn
    strm = model["chunks"]["strm"]
    mf = mesh_fields(d, mesh)
    psi = mf["posStrm"]
    if psi < 0 or psi >= len(strm) or strm[psi]["perElem"] != 6:
        return [], [], []
    usi = mf["tex0Strm"] if 0 <= mf["tex0Strm"] < len(strm) else None
    counts = attr_counts(d, strm, mf)

    verts, uvs, tris, vcache = [], [], [], {}
    for i in range(mf["nSubm"]):
        subm_off = _s32(d, mf["submPtr"] + i*4) & 0xffffffff
        if d[subm_off:subm_off+4] != b"subm":
            continue
        dl = skn.subm_dlst(d, subm_off)
        if dl is None:
            continue
        mlist = skn.subm_matrixlist(d, subm_off)
        dstart = pm._u32(d, dl + 0x14)
        dend = min(dstart + pm._u32(d, dl + 0x10), len(d))
        stride, ops = detect_stride(d, dstart, dend)
        if not stride:
            continue
        lay = solve_layout(d, ops, stride, counts)
        if lay is None:
            continue
        pcol, pw = lay["POS"]
        ucol, uw = lay.get("TEX0", (None, None))
        skinned = pcol > 0          # bytes before POS are the matrix indices
        for (pos, op, cnt) in ops:
            base = pos + 3
            ring = []
            for k in range(cnt):
                vo = base + k*stride
                mi = -1
                if skinned:
                    slot = d[vo] // 3          # byte0 = PNMTXIDX
                    if 0 <= slot < 10:
                        mi = mlist[slot]
                pi = _read_idx(d, vo + pcol, pw)
                ui = _read_idx(d, vo + ucol, uw) if ucol is not None else None
                key = (pi, ui, mi)
                if key not in vcache:
                    vcache[key] = len(verts)
                    verts.append((read_pos(d, strm[psi], pi), mi))
                    uvs.append(read_uv(d, strm[usi], ui)
                               if (ui is not None and usi is not None) else (0.0, 0.0))
                ring.append(vcache[key])
            for (a, b, c) in strips_to_tris(op, list(range(cnt))):
                tris.append((ring[a], ring[b], ring[c]))
    return verts, tris, uvs


def strips_to_tris(op, ring):
    tris = []
    n = len(ring)
    if op == 0x98:
        for k in range(2, n):
            tris.append((ring[k-2], ring[k-1], ring[k]) if k % 2 == 0
                        else (ring[k-2], ring[k], ring[k-1]))
    elif op == 0xa0:
        for k in range(2, n):
            tris.append((ring[0], ring[k-1], ring[k]))
    elif op in (0x90, 0x80):
        for k in range(0, n-3, 4):
            q = ring[k:k+4]
            tris.append((q[0], q[1], q[2])); tris.append((q[0], q[2], q[3]))
    return tris


UV_FRAC = 1024.0   # UV = s16 / 1024 -> [0,1] (frac 10, verified)


def read_uv(d, strm, i):
    u, v = struct.unpack_from(">hh", d, strm["dataOff"] + i*4)
    return u / UV_FRAC, v / UV_FRAC


def _embedded_matnames(d):
    """Material-name table embedded in the .model: count at header +0x40, array
    of name pointers from +0x60. Returns the names in matIdx order (which is
    alphabetical)."""
    count = pm._u32(d, 0x40)
    if not (0 < count < 4096):
        return []
    names = []
    for i in range(count):
        p = pm._u32(d, 0x60 + i*4)
        names.append(pm._cstr(d, p) if 0 < p < len(d) else "")
    return names


def _find_png(stem):
    for base in ("textures_png", os.path.join("..", "textures_png")):
        if not os.path.isdir(base):
            continue
        for dp, _dn, files in os.walk(base):
            if stem + ".texture.png" in files:
                return os.path.join(dp, stem + ".texture.png")
    return None


import re


def load_material_db(model_path):
    """Load the twin .material -> {matName: pngPath|None} + embedded table."""
    try:
        import parse_material as pmat
    except Exception:
        return None, []
    mat_path = model_path.replace(os.sep+"model"+os.sep, os.sep+"material"+os.sep)
    mat_path = mat_path.replace("/model/", "/material/")
    mat_path = os.path.splitext(mat_path)[0] + ".material"
    if not os.path.exists(mat_path):
        return None, []
    db = {}
    for m in pmat.parse_file(mat_path):
        tga = m["textures"].get("TexColor1", {}).get("name", "")
        db[m["name"]] = _find_png(pmat.tga_to_asset(tga)) if tga else None
    return db, _embedded_matnames(open(model_path, "rb").read())


def resolve_mesh_material(strm_name, mat_idx, db, embedded):
    """Material name for a mesh: first from the stream name ('grp__MATNAME'),
    otherwise matIdx into the embedded table. Returns (matName, png|None)."""
    if db is None:
        return (f"mat{mat_idx}", None)
    # 1) via the stream name: the part after '__', optionally minus a '_N' tail
    if strm_name and "__" in strm_name:
        cand = strm_name.split("__")[-1]
        for nm in (cand, re.sub(r"_\d+$", "", cand)):
            if nm in db:
                return (nm, db[nm])
    # 2) via matIdx into the embedded table
    if 0 <= mat_idx < len(embedded):
        nm = embedded[mat_idx]
        if nm in db:
            return (nm, db[nm])
    return (f"mat{mat_idx}", None)


def export(path, out, scale=None, raw=False, verbose=True):
    """Export a .model to OBJ + MTL, assembled in model space.

    Every mesh is skinned per the hybrid NW4R convention (rigid vertices in
    bone space, blended ones already in model space -- see skinning.py), with
    the POS quantisation K resolved per mesh. With raw=True the skinning step
    is skipped and the quantised positions are written as-is, for comparison.
    """
    import skinning as skn
    d = open(path, "rb").read()
    model = pm.parse(d)
    strm = model["chunks"]["strm"]
    mat_db, embedded = load_material_db(path)
    pal, rigid = skn.palette(d, model)
    nodes, world = sk.world_matrices(d, model)
    nmt = skn.node_mesh_table(d, model)

    verts = []                 # (x,y,z) model-space
    uvs = []                   # (u,v)
    faces = []                 # (a,b,c, matName)
    mat_png = {}               # matName -> png|None
    ndrop = 0
    ks = []

    for mno, mesh in enumerate(model["chunks"]["mesh"]):
        mverts, mtris, muvs = mesh_geometry(d, model, mesh)
        if not mverts:
            continue
        mf = mesh_fields(d, mesh)
        attach, node_mat = nmt.get(mno, (None, -1))
        # matIdx from the node table (deterministic) before the stream name
        matname, png = resolve_mesh_material(strm[mf["posStrm"]]["name"],
                                             node_mat, mat_db, embedded)
        mat_png[matname] = png

        if raw:
            k, ratio, how = 1.0, float("nan"), "raw"
            pts = [tuple(map(float, v[0])) for v in mverts]
        else:
            k, ratio, how = skn.solve_k(mverts, mtris, pal, rigid, world,
                                        model["aabb"], attach)
            # With no cross-bone triangles K is unconstrained, so fall back on
            # the AABB the node declares -- which also pins down the bone that
            # rigid parts (bags, buckles, teeth...) hang off.
            if how != "cross-bone" and attach is not None:
                nab = skn.node_aabb(d, nodes[attach])
                if nab:
                    fit = skn.fit_to_node_aabb(mverts, pal, rigid, world, nab)
                    if fit:
                        k, attach, err = fit
                        how = f"node-aabb({err:.3f})"
            pts = [skn.skin_vertex(rw, mi, pal, rigid, world, k, attach)
                   for (rw, mi) in mverts]
        label = nodes[attach]["name"] if attach is not None else mesh["name"]
        ks.append((label, k, ratio, how))

        base = len(verts)
        remap = {}
        for i, p in enumerate(pts):
            if p is None:
                continue
            remap[i] = len(verts) + 1          # OBJ is 1-based
            verts.append(p)
            uvs.append(muvs[i])
        for (a, b, c) in mtris:
            if a in remap and b in remap and c in remap:
                faces.append((remap[a], remap[b], remap[c], matname))
            else:
                ndrop += 1

    if not verts:
        print("no vertices decoded"); return
    if scale is None:
        span = max(max(v[i] for v in verts) - min(v[i] for v in verts)
                   for i in range(3)) or 1
        scale = 2.0/span

    mtl_path = os.path.splitext(out)[0] + ".mtl"
    with open(out, "w") as f:
        f.write(f"# TLS {path}\n# {len(verts)} verts {len(faces)} tris scale={scale}\n")
        f.write(f"mtllib {os.path.basename(mtl_path)}\n")
        for (x, y, z) in verts:
            f.write(f"v {x*scale:.5f} {y*scale:.5f} {z*scale:.5f}\n")
        for (u, v) in uvs:
            f.write(f"vt {u:.5f} {1.0-v:.5f}\n")   # OBJ counts V from the bottom
        last = None
        for (a, b, c, mat) in faces:
            if mat != last:
                f.write(f"usemtl {mat}\n"); last = mat
            f.write(f"f {a}/{a} {b}/{b} {c}/{c}\n")

    if verbose and not raw:
        print("  K per mesh (POS quantisation):")
        for (nm, k, ratio, how) in ks:
            rs = f"{ratio:.3f}" if ratio == ratio else "n/d"
            print(f"    {nm:<12} K={k:<7g} ratio={rs:<7} ({how})")
        if ndrop:
            print(f"  {ndrop} triangles dropped (unresolved matIdx)")

    # MTL: material name -> PNG texture
    used_mats = sorted({fc[3] for fc in faces})
    ntex = 0
    with open(mtl_path, "w") as f:
        for mat in used_mats:
            f.write(f"newmtl {mat}\nKd 0.8 0.8 0.8\n")
            png = mat_png.get(mat)
            if png:
                f.write(f"map_Kd {os.path.abspath(png)}\n"); ntex += 1
            f.write("\n")
    print(f"{out}: {len(verts)} verts, {len(faces)} tris, "
          f"{ntex}/{len(used_mats)} materials textured")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit()
    a = sys.argv
    sc = float(a[a.index("--scale")+1]) if "--scale" in a else None
    export(a[1], a[2], sc, raw="--raw" in a)
