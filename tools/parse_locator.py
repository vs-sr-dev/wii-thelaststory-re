r"""Parser for The Last Story `.locator` files -- THE PROP INSTANCES.

chnkdata container, subtag 'wii loct'. Reversed in the maps session; the layout
self-verifies by arithmetic (see below), so no field here is a guess.

--- header -----------------------------------------------------------------
    +0x00  'chnkdata'
    +0x0c  'wii loct'
    +0x14  u32  version (always 3)
    +0x18  u32  16
    +0x1c  u32  data size
    +0x20  ptr  -> name of the group's BAKE (lightmap) TEXTURE,
                  e.g. 'dg001_01_01_bake01.texture'
    +0x24  u32  nInstance
    +0x28  u32  0

--- instance array at +0x2c, 0x30 (48) byte records ------------------------
    +0x00  ptr      INSTANCE name, unique (e.g. 'dg001_arch10_0009')
    +0x04  f32[3]   position
    +0x10  f32[3]   rotation in DEGREES (not radians: the data holds exact 90.0
                    and 0.0 values; .motion uses radians instead)
    +0x1c  f32[3]   scale
    +0x28  u32      nParam (always 1 in the files seen)
    +0x2c  ptr      -> array of 16-byte params

--- param, 16 bytes --------------------------------------------------------
    +0x00  ptr      name of the ASSET to instantiate, WITHOUT extension
                    ('dg001_arch10' -> dg001_arch10.building / .model)
    +0x04  f32      u   \  this instance's tile within the
    +0x08  f32      v   /  lightmap atlas
    +0x0c  f32      tile side (0.11111 = 1/9 -> a 9x9 atlas)

ARITHMETIC CHECK (dg001_01_01.locator, n=53):
    end of instance array = 0x2c + 53*0x30            = 0xa1c
    first param pointer                                = 0xa1c   matches
    end of param array    = 0xa1c + 53*0x10           = 0xd6c
    header +0x20                                       = 0xd6c   matches
Strings start immediately after. The file is fully accounted for -- header,
instances, params, strings -- with no unexplained bytes left over.

The instance-to-asset ratio is what an instancing system should look like:
dg001_01_01 has 53 instances over 13 distinct assets, and every instance name
is different (asset + serial number).

See docs/11-maps-and-scenes.md.

Usage:
    python parse_locator.py FILE.locator          # summary
    python parse_locator.py FILE.locator --all    # every instance
"""
import math
import os
import struct
import sys

LOCDIR = os.path.join(os.path.dirname(__file__),
                      "..", "assets", "pack", "filesystem", "data", "locator")

INST_SIZE = 0x30
PARAM_SIZE = 0x10


def _u32(d, o): return struct.unpack_from(">I", d, o)[0]
def _f32(d, o): return struct.unpack_from(">f", d, o)[0]


def _cstr(d, o):
    if o <= 0 or o >= len(d):
        return ""
    e = d.index(b"\0", o)
    return d[o:e].decode("ascii", "replace")


def parse(d):
    assert d[0:8] == b"chnkdata", "not a chnkdata container"
    subtag = d[0x0c:0x14].rstrip(b"\0")
    assert subtag == b"wii loct", f"subtag {subtag!r}, expected 'wii loct'"

    n = _u32(d, 0x24)
    inst = []
    for i in range(n):
        o = 0x2c + i * INST_SIZE
        trs = [_f32(d, o + 4 + k * 4) for k in range(9)]
        np_ = _u32(d, o + 0x28)
        pp = _u32(d, o + 0x2c)
        params = []
        for j in range(np_):
            q = pp + j * PARAM_SIZE
            params.append({
                "asset": _cstr(d, _u32(d, q)),
                "uv": (_f32(d, q + 4), _f32(d, q + 8)),
                "tile": _f32(d, q + 12),
            })
        inst.append({
            "name": _cstr(d, _u32(d, o)),
            "pos": tuple(trs[0:3]),
            "rot": tuple(trs[3:6]),      # DEGREES
            "scale": tuple(trs[6:9]),
            "params": params,
            "asset": params[0]["asset"] if params else "",
        })
    return {"version": _u32(d, 0x14),
            "bake": _cstr(d, _u32(d, 0x20)),
            "instances": inst}


def parse_file(path):
    with open(path, "rb") as f:
        return parse(f.read())


def matrix(inst):
    """The instance's 4x4 matrix: T * Rz*Ry*Rx * S, as in skeleton.compose.

    Same composition convention as the rest of the engine; here, though, the
    rotation arrives in degrees and has to be converted.
    """
    tx, ty, tz = inst["pos"]
    rx, ry, rz = (math.radians(a) for a in inst["rot"])
    sx, sy, sz = inst["scale"]
    cx, sxr = math.cos(rx), math.sin(rx)
    cy, syr = math.cos(ry), math.sin(ry)
    cz, szr = math.cos(rz), math.sin(rz)
    r00 = cz * cy
    r01 = cz * syr * sxr - szr * cx
    r02 = cz * syr * cx + szr * sxr
    r10 = szr * cy
    r11 = szr * syr * sxr + cz * cx
    r12 = szr * syr * cx - cz * sxr
    r20 = -syr
    r21 = cy * sxr
    r22 = cy * cx
    return [[r00 * sx, r01 * sy, r02 * sz, tx],
            [r10 * sx, r11 * sy, r12 * sz, ty],
            [r20 * sx, r21 * sy, r22 * sz, tz],
            [0.0, 0.0, 0.0, 1.0]]


def apply(m, p):
    x, y, z = p
    return (m[0][0]*x + m[0][1]*y + m[0][2]*z + m[0][3],
            m[1][0]*x + m[1][1]*y + m[1][2]*z + m[1][3],
            m[2][0]*x + m[2][1]*y + m[2][2]*z + m[2][3])


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    if not os.path.exists(path):
        path = os.path.join(LOCDIR, path)
    L = parse_file(path)
    inst = L["instances"]
    print(f"{os.path.basename(path)}  version={L['version']}")
    print(f"  bake: {L['bake']}")
    print(f"  {len(inst)} instances")

    from collections import Counter
    assets = Counter(i["asset"] for i in inst)
    print(f"  {len(assets)} distinct assets:")
    for a, c in assets.most_common():
        print(f"    {a:<28} x{c}")

    show = inst if "--all" in sys.argv else inst[:8]
    print(f"\n  --- instances ({len(show)} di {len(inst)}) ---")
    for i in show:
        p, r, s = i["pos"], i["rot"], i["scale"]
        print(f"    {i['name']:<26} {i['asset']:<20} "
              f"pos=({p[0]:8.2f},{p[1]:7.2f},{p[2]:8.2f}) "
              f"rot=({r[0]:7.2f},{r[1]:7.2f},{r[2]:7.2f}) "
              f"scl=({s[0]:.3f},{s[1]:.3f},{s[2]:.3f})")


if __name__ == "__main__":
    _cli()
