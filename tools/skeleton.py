"""Skeleton of The Last Story `.model` files: rebuilds the world bind matrices.

Every `node` chunk carries a LOCAL TRS:
    scale        +0x34 (3 floats)
    rotation     +0x40 (3 floats, Euler radians, ZYX order)
    translation  +0x4c (3 floats)
    parent       +0x1c (index, -1 = root)
Local matrix L = T * Rz*Ry*Rx * S; world = world[parent] * L.

Validated on an008: hips/spine/neck/head with increasing Y, and a tail that
extends along -Z (that model is a cat). These are the matrices `.motion`
(`wii anim`) animates, and the ones skinning.py applies to bone-local vertices.

Usage:
    python skeleton.py FILE.model               # bones + world positions
    python skeleton.py FILE.model --obj OUT.obj # skeleton as OBJ line segments
"""
import sys, math, struct
import parse_model as pm


def _f(d, o): return struct.unpack_from(">f", d, o)[0]


def _matmul(A, B):
    return [[sum(A[i][k]*B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def local_matrix(d, node):
    o = node["offset"]
    return compose((_f(d, o+0x34), _f(d, o+0x38), _f(d, o+0x3c)),
                   (_f(d, o+0x40), _f(d, o+0x44), _f(d, o+0x48)),
                   (_f(d, o+0x4c), _f(d, o+0x50), _f(d, o+0x54)))


def compose(scale, rot, trans):
    """L = T * Rz*Ry*Rx * S. Split out of local_matrix because `.motion`
    replaces individual TRS channels before composing (see motion.py)."""
    sx, sy, sz = scale
    rx, ry, rz = rot
    tx, ty, tz = trans
    cx, sxr = math.cos(rx), math.sin(rx)
    cy, syr = math.cos(ry), math.sin(ry)
    cz, szr = math.cos(rz), math.sin(rz)
    # R = Rz * Ry * Rx
    r00 = cz*cy
    r01 = cz*syr*sxr - szr*cx
    r02 = cz*syr*cx + szr*sxr
    r10 = szr*cy
    r11 = szr*syr*sxr + cz*cx
    r12 = szr*syr*cx - cz*sxr
    r20 = -syr
    r21 = cy*sxr
    r22 = cy*cx
    return [
        [r00*sx, r01*sy, r02*sz, tx],
        [r10*sx, r11*sy, r12*sz, ty],
        [r20*sx, r21*sy, r22*sz, tz],
        [0, 0, 0, 1],
    ]


def world_matrices(d, model=None):
    if model is None:
        model = pm.parse(d)
    nodes = model["chunks"]["node"]
    world = [None]*len(nodes)

    def get(i):
        if world[i] is not None:
            return world[i]
        p = nodes[i]["parent"]
        L = local_matrix(d, nodes[i])
        world[i] = L if (p < 0 or p >= len(nodes)) else _matmul(get(p), L)
        return world[i]
    for i in range(len(nodes)):
        get(i)
    return nodes, world


def _cli():
    if len(sys.argv) < 2:
        print(__doc__); return
    path = sys.argv[1]
    d = open(path, "rb").read()
    nodes, world = world_matrices(d)

    if "--obj" in sys.argv:
        out = sys.argv[sys.argv.index("--obj")+1]
        with open(out, "w") as f:
            for w in world:
                f.write(f"v {w[0][3]:.5f} {w[1][3]:.5f} {w[2][3]:.5f}\n")
            for i, nd in enumerate(nodes):
                p = nd["parent"]
                if 0 <= p < len(nodes):
                    f.write(f"l {p+1} {i+1}\n")
        print(f"{out}: {len(nodes)} bones (skeleton segments)")
        return

    for i, nd in enumerate(nodes):
        w = world[i]
        pn = nodes[nd["parent"]]["name"] if 0 <= nd["parent"] < len(nodes) else "-"
        print(f"  [{i:3}] {nd['name']:20} parent={pn:16} "
              f"world=({w[0][3]:8.3f},{w[1][3]:8.3f},{w[2][3]:8.3f})")


if __name__ == "__main__":
    _cli()
