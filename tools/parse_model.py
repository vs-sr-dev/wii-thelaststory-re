"""Structural parser for The Last Story `.model` files ('wii modl' container).

The file is a big-endian `chnkdata` container with the subtag `wii modl`.
After the global header comes a table of pointers to sub-chunks. Every chunk is
SELF-DESCRIBING:

    <4CC magic> <u32 count> <u32 selfOffset> <u32 size> ...chunk-specific...

selfOffset equals the chunk's own offset, so we VALIDATE chunks (scan for the
magic, then confirm selfOffset) rather than trusting the pointer table alone.

Known chunks:
  strm  vertex attribute stream (one per attribute per mesh). Header:
        +0x10 nameOff  +0x14 id  +0x18 count  +0x1c dataOff.
        bytes/element = (chunkEnd - dataOff) / count:
            6 -> POS  (s16 x3, quantised; the scale is per-mesh, see skinning.py)
            3 -> NRM  (s8  x3)
            4 -> UV (s16 x2)  or  CLR (rgba8)
  mesh  draw descriptor ('polygon0'...). +0x10 nameOff  +0x14 matIdx
        +0x18 ptr->sdsc  +0x1c attribute->stream table (12 slots, -1 = absent)
        +0x4c nSubm  +0x50 ptr to the subm offset array.  See export_obj.py.
  node  skeleton BONE, and also the node that draws a mesh (NW4R; root is
        'nw4r_root'). +0x10 nameOff  +0x14 nameHash  +0x1c parentIdx(-1=root)
        +0x34 scale  +0x40 rotation  +0x4c translation   -> skeleton.py
        +0x58 per-part AABB  +0x70/+0x74 node->mesh table -> skinning.py
  mtrx  skinning matrix palette                          -> skinning.py
  sdsc  raw GX display-list container (opcode 0x98 strip, etc).

Global header (version 3):
  0x0c 'wii modl'  0x14 version  0x18 flags  0x1c dataSize
  0x20..0x38 AABB (min.xyz, max.xyz float)
  0x40 embedded material-name count; 0x60.. array of name pointers

Usage:
    python parse_model.py FILE.model             # tree summary
    python parse_model.py FILE.model --json
    python parse_model.py FILE.model --skeleton  # bone hierarchy only
"""
import sys, json, struct

KNOWN_MAGICS = (b"strm", b"mesh", b"node", b"mtrx", b"sdsc", b"mdlx", b"bbox")


def _u32(d, o): return struct.unpack_from(">I", d, o)[0]
def _s32(d, o): return struct.unpack_from(">i", d, o)[0]
def _f32(d, o): return struct.unpack_from(">f", d, o)[0]


def _cstr(d, o):
    if o == 0 or o >= len(d):
        return ""
    e = o
    while e < len(d) and d[e] != 0:
        e += 1
    return d[o:e].decode("latin1")


def classify_strm(bytes_per_elem):
    return {6: "POS(s16x3)", 3: "NRM(s8x3)", 4: "UV/CLR(4B)",
            8: "UV(f?)/2", 12: "POS(f32x3)"}.get(bytes_per_elem, f"?({bytes_per_elem}B)")


def parse(d):
    assert d[0:8] == b"chnkdata", "non e' un container chnkdata"
    subtag = d[0x0c:0x14].rstrip(b"\0").decode("latin1")
    model = {
        "subtag": subtag,
        "version": _u32(d, 0x14),
        "flags": _u32(d, 0x18),
        "dataSize": _u32(d, 0x1c),
        "aabb": {
            "min": [round(_f32(d, 0x20 + i * 4), 5) for i in range(3)],
            "max": [round(_f32(d, 0x2c + i * 4), 5) for i in range(3)],
        },
        "chunks": {"strm": [], "mesh": [], "node": [], "mtrx": [], "sdsc": [], "other": []},
    }

    # Robust scan: any 4-aligned offset whose bytes are a known magic AND whose
    # selfOffset field (+8) matches that offset is a valid chunk.
    o = 0x20
    n = len(d)
    while o + 16 <= n:
        magic = d[o:o + 4]
        if magic in KNOWN_MAGICS and _u32(d, o + 8) == o:
            size = _u32(d, o + 0x0c)
            tag = magic.decode("latin1")
            entry = {"offset": o, "size": size}
            if tag == "strm":
                cnt = _u32(d, o + 0x18)
                dataoff = _u32(d, o + 0x1c)
                nb = (o + size) - dataoff
                entry.update(name=_cstr(d, _u32(d, o + 0x10)), count=cnt,
                             dataOff=dataoff, bytes=nb,
                             perElem=(nb // cnt if cnt else 0))
                entry["attr"] = classify_strm(entry["perElem"])
                model["chunks"]["strm"].append(entry)
            elif tag == "mesh":
                mat = _u32(d, o + 0x14)
                entry.update(name=_cstr(d, _u32(d, o + 0x10)),
                             matIdx=(None if mat == 0xFFFFFFFF else mat),
                             dlPtr=_u32(d, o + 0x18))
                model["chunks"]["mesh"].append(entry)
            elif tag == "node":
                entry.update(name=_cstr(d, _u32(d, o + 0x10)),
                             nameHash=_u32(d, o + 0x14),
                             parent=_s32(d, o + 0x1c))
                model["chunks"]["node"].append(entry)
            elif tag in ("mtrx", "sdsc"):
                entry["name"] = _cstr(d, _u32(d, o + 0x10)) if tag == "sdsc" else ""
                model["chunks"][tag].append(entry)
            else:
                entry["magic"] = tag
                model["chunks"]["other"].append(entry)
            # skip to the next chunk (size includes the header, 16-aligned)
            step = max(16, (size + 15) & ~15)
            o += step
            continue
        o += 4

    return model


def parse_file(path):
    with open(path, "rb") as f:
        return parse(f.read())


def skeleton_tree(model):
    """Return text lines of the bone hierarchy, following parent indices."""
    nodes = model["chunks"]["node"]
    children = {}
    roots = []
    for i, nd in enumerate(nodes):
        p = nd["parent"]
        if p < 0 or p >= len(nodes):
            roots.append(i)
        else:
            children.setdefault(p, []).append(i)
    lines = []

    def walk(i, depth):
        lines.append("  " * depth + f"{nodes[i]['name']}")
        for c in children.get(i, []):
            walk(c, depth + 1)
    for r in roots:
        walk(r, 0)
    return lines


def _summary(model, path):
    c = model["chunks"]
    print(f"{path}")
    print(f"  {model['subtag']}  v{model['version']}  flags={model['flags']:#x}  "
          f"dataSize={model['dataSize']}")
    print(f"  AABB min={model['aabb']['min']}  max={model['aabb']['max']}")
    print(f"  chunks: {len(c['strm'])} strm, {len(c['mesh'])} mesh, "
          f"{len(c['node'])} node(bones), {len(c['mtrx'])} mtrx, {len(c['sdsc'])} sdsc"
          + (f", {len(c['other'])} other" if c["other"] else ""))
    print("  --- mesh (draw calls) ---")
    for m in c["mesh"]:
        print(f"    {m['name']:<12} mat={m['matIdx']}  dl->{m['dlPtr']:#x}")
    print("  --- strm (attributes) ---")
    for s in c["strm"]:
        print(f"    {s['name']:<28} {s['count']:>5} x{s['perElem']}B  {s['attr']}")
    if c["node"]:
        print(f"  --- skeleton ({len(c['node'])} bones) ---")
        for ln in skeleton_tree(model)[:40]:
            print("    " + ln)


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    flags = sys.argv[2:]
    model = parse_file(path)
    if "--json" in flags:
        print(json.dumps(model, indent=2, ensure_ascii=False))
    elif "--skeleton" in flags:
        print("\n".join(skeleton_tree(model)))
    else:
        _summary(model, path)


if __name__ == "__main__":
    _cli()
