"""The Last Story `.motion` animations (container 'wii anim' / NW4R).

Format reversed over 601 files and 32,237 `anmn` chunks sampled across the
whole disc, with zero structural errors. Full write-up, including the loop
conventions and the frame-rate measurement, in docs/10-animation.md.

--- header (chunk `anim` @0x10) --------------------------------------------
    +0x20  f32  frameCount     number of frames, indices 0..N-1
    +0x24  u32  nAnmn
    +0x28  u32  ptr -> array of `anmn` chunk offsets

--- chunk `anmn` = ONE BONE'S CURVES ---------------------------------------
    +0x04  u32  count      always 3 (the X/Y/Z of a TRS group)
    +0x10  ptr  bone name
    +0x14  u32  nameHash   matches node+0x14 in the .model
    +0x18  u32  mask       which TRS groups are animated (see below)
    +0x1c  u32  0xdeadbeef marker
    +0x20  ...  12-byte records, popcount(mask)*count of them:
                    +0x00 u16 channel   0-2 scale, 3-5 rotation, 6-8 position
                    +0x02 u16 fmt       0 = constant, 1 = keyframe, 4 = dense
                    +0x04 u16 nFrame    elements in the track
                    +0x06 u16 frac      fractional bits (value = s16 / 2^frac)
                    +0x08 u32 dataOff   absolute offset of the data

The bone is identified NOT by index but BY NAME (and hash): a .motion applies
to any skeleton carrying those names. On an008 all 96 names and all 96 hashes
match the twin .model's `node` chunks.

mask: bit0 = translation, bit1 = rotation, bit2 = scale. Confirmed by exact
count over the sample: masks containing bit1 (2,3,6,7) total 32,225 tracks,
exactly as many as there are tracks on channels 3/4/5; likewise for the other
two bits. A group absent from the mask means that bone keeps its .model bind
pose TRS.

--- the three track formats ------------------------------------------------
  fmt 0  CONSTANT   4 bytes: a single f32 (not quantised, frac = 0). The 64
                    constant-scale tracks all hold 0x3f800000, exactly 1.0,
                    which identifies the format unambiguously.
  fmt 1  KEYFRAME   nFrame x 6 bytes: (u16 frame, s16 value, s16 tangent),
                    padded to 4. HERMITE interpolation: the tangent is
                    d(value)/d(frame) in the same quantised units, positive
                    while the curve rises and negative while it falls.
  fmt 4  DENSE      nFrame x s16, one sample per frame, nothing to interpolate.
For fmt 1 and 4 the real value is s16 / 2^frac. Rotations in RADIANS,
translations in the same bone units as the .model (see skinning.py for how
they relate to the quantised POS). Note that .locator instance rotations are
in DEGREES instead -- do not feed both through one path.

Usage:
    python motion.py FILE.motion                 # summary
    python motion.py FILE.motion --bone hips     # dump one bone's curves
    python motion.py FILE.motion --pose 12       # every bone's TRS at frame 12
"""
import math
import struct
import sys

import parse_model as pm

CHANNELS = ("sclX", "sclY", "sclZ", "rotX", "rotY", "rotZ", "posX", "posY", "posZ")
FMT_CONST, FMT_KEY, FMT_DENSE = 0, 1, 4
BYTES_PER_ELEM = {FMT_CONST: 4, FMT_KEY: 6, FMT_DENSE: 2}
GROUPS = (("translation", 0x1), ("rotation", 0x2), ("scale", 0x4))


def _u16(d, o): return struct.unpack_from(">H", d, o)[0]
def _s16(d, o): return struct.unpack_from(">h", d, o)[0]


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def parse(d):
    """Returns {frameCount, bones: [{name, hash, mask, tracks:[...]}]}."""
    assert d[0:8] == b"chnkdata", "not a chnkdata container"
    subtag = d[0x0c:0x14].rstrip(b"\0")
    assert subtag == b"wii anim", f"subtag {subtag!r}, expected 'wii anim'"

    n = pm._s32(d, 0x24)
    ptr = pm._u32(d, 0x28)
    bones = []
    for i in range(n):
        o = pm._u32(d, ptr + i * 4)
        if o + 0x20 > len(d) or d[o:o + 4] != b"anmn":
            continue
        size = pm._u32(d, o + 0x0c)
        count = pm._u32(d, o + 0x04)
        mask = pm._u32(d, o + 0x18)
        tracks = []
        for j in range(bin(mask).count("1") * count):
            p = o + 0x20 + j * 12
            if p + 12 > o + size:
                break
            tracks.append({
                "channel": _u16(d, p),
                "fmt": _u16(d, p + 2),
                "nframe": _u16(d, p + 4),
                "frac": _u16(d, p + 6),
                "dataOff": pm._u32(d, p + 8),
            })
        bones.append({
            "name": pm._cstr(d, pm._u32(d, o + 0x10)),
            "hash": pm._u32(d, o + 0x14),
            "mask": mask,
            "offset": o,
            "tracks": tracks,
        })
    return {"frameCount": pm._f32(d, 0x20), "bones": bones}


def parse_file(path):
    with open(path, "rb") as f:
        return parse(f.read())


# --------------------------------------------------------------------------
# valutazione delle curve
# --------------------------------------------------------------------------
def _hermite(v0, m0, v1, m1, dt, u):
    """Cubic Hermite; m0/m1 are d(value)/d(frame), dt = frames between keys."""
    u2 = u * u
    u3 = u2 * u
    return ((2*u3 - 3*u2 + 1) * v0 + (u3 - 2*u2 + u) * dt * m0 +
            (-2*u3 + 3*u2) * v1 + (u3 - u2) * dt * m1)


def eval_track(d, track, t):
    """The track's value at frame t (float, interpolated)."""
    fmt, n, frac, off = track["fmt"], track["nframe"], track["frac"], track["dataOff"]
    if fmt == FMT_CONST:
        return pm._f32(d, off)

    scale = float(1 << frac)
    if fmt == FMT_DENSE:
        if n <= 0:
            return 0.0
        i = int(math.floor(t))
        if i < 0:
            return _s16(d, off) / scale
        if i >= n - 1:
            return _s16(d, off + (n - 1) * 2) / scale
        a = _s16(d, off + i * 2) / scale
        b = _s16(d, off + (i + 1) * 2) / scale
        return a + (b - a) * (t - i)          # linear between two samples

    if fmt == FMT_KEY:
        if n <= 0:
            return 0.0

        def key(k):
            p = off + k * 6
            return _u16(d, p), _s16(d, p + 2) / scale, _s16(d, p + 4) / scale

        f0, v0, _ = key(0)
        if t <= f0:
            return v0
        fl, vl, _ = key(n - 1)
        if t >= fl:
            return vl
        lo, hi = 0, n - 1                      # binary search for the bracketing pair
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if key(mid)[0] <= t:
                lo = mid
            else:
                hi = mid
        fa, va, ma = key(lo)
        fb, vb, mb = key(hi)
        dt = fb - fa
        if dt <= 0:
            return va
        return _hermite(va, ma, vb, mb, dt, (t - fa) / dt)

    raise ValueError(f"unknown fmt: {fmt}")


def pose(d, motion, t):
    """{boneName: {channelIdx: value}} at frame t. Animated channels only."""
    out = {}
    for b in motion["bones"]:
        vals = {}
        for tr in b["tracks"]:
            vals[tr["channel"]] = eval_track(d, tr, t)
        out[b["name"]] = vals
    return out


# --------------------------------------------------------------------------
# posa -> matrici world
# --------------------------------------------------------------------------
def world_matrices_at(md, model, ad, motion, t):
    """The skeleton's world matrices at frame t.

    Animated channels REPLACE the bind TRS, they do not add to it: verified on
    an008, where hips.posY is 3.0810 at bind and 3.0103 animated -- the pelvis
    dropping as the character walks -- while hips.rotY stays -1.5708 against
    -1.5711. Groups absent from the bone's mask stay at bind.
    """
    import skeleton as sk
    nodes = model["chunks"]["node"]
    vals = pose(ad, motion, t)
    world = [None] * len(nodes)

    def local(i):
        o = nodes[i]["offset"]
        trs = [pm._f32(md, o + 0x34 + k*4) for k in range(3)] + \
              [pm._f32(md, o + 0x40 + k*4) for k in range(3)] + \
              [pm._f32(md, o + 0x4c + k*4) for k in range(3)]
        for ch, v in vals.get(nodes[i]["name"], {}).items():
            if 0 <= ch < 9:
                trs[ch] = v
        return sk.compose(trs[0:3], trs[3:6], trs[6:9])

    def get(i):
        if world[i] is None:
            p = nodes[i]["parent"]
            L = local(i)
            world[i] = L if (p < 0 or p >= len(nodes)) else sk._matmul(get(p), L)
        return world[i]

    for i in range(len(nodes)):
        get(i)
    return nodes, world


def invert_affine(m):
    """Inverse of a 4x4 affine matrix (rotation + scale + translation)."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0]*(a[1][1]*a[2][2] - a[1][2]*a[2][1])
           - a[0][1]*(a[1][0]*a[2][2] - a[1][2]*a[2][0])
           + a[0][2]*(a[1][0]*a[2][1] - a[1][1]*a[2][0]))
    if abs(det) < 1e-12:
        return [[1 if i == j else 0 for j in range(4)] for i in range(4)]
    inv = [[0.0]*3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            r1, r2 = [k for k in range(3) if k != j]
            c1, c2 = [k for k in range(3) if k != i]
            cof = a[r1][c1]*a[r2][c2] - a[r1][c2]*a[r2][c1]
            inv[i][j] = ((-1) ** (i + j)) * cof / det
    tx, ty, tz = m[0][3], m[1][3], m[2][3]
    out = []
    for i in range(3):
        t = -(inv[i][0]*tx + inv[i][1]*ty + inv[i][2]*tz)
        out.append([inv[i][0], inv[i][1], inv[i][2], t])
    out.append([0.0, 0.0, 0.0, 1.0])
    return out


def skin_matrices(bind_world, anim_world):
    """Per bone, the matrix to use on BLEND vertices (model-space bind):
    W_anim @ W_bind^-1, which is the identity at bind pose. RIGID vertices use
    anim_world directly (they are in bone space). See skinning.py."""
    out = []
    for b in range(len(bind_world)):
        import skeleton as sk
        out.append(sk._matmul(anim_world[b], invert_affine(bind_world[b])))
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    argv = sys.argv[2:]
    d = open(path, "rb").read()
    m = parse(d)

    if "--pose" in argv:
        t = float(argv[argv.index("--pose") + 1])
        for name, vals in pose(d, m, t).items():
            s = "  ".join(f"{CHANNELS[c]}={v:+.4f}" for c, v in sorted(vals.items()))
            print(f"  {name:<20} {s}")
        return

    if "--bone" in argv:
        want = argv[argv.index("--bone") + 1]
        for b in m["bones"]:
            if b["name"] != want:
                continue
            print(f"{b['name']}  mask={b['mask']:#x} "
                  f"({', '.join(g for g, bit in GROUPS if b['mask'] & bit)})")
            for tr in b["tracks"]:
                print(f"  {CHANNELS[tr['channel']]}  fmt={tr['fmt']} "
                      f"n={tr['nframe']} frac={tr['frac']}")
                if tr["fmt"] == FMT_CONST:
                    print(f"    constant {pm._f32(d, tr['dataOff']):+.5f}")
                elif tr["fmt"] == FMT_KEY:
                    for k in range(tr["nframe"]):
                        p = tr["dataOff"] + k * 6
                        print(f"    frame {_u16(d, p):>4}  v={_s16(d, p+2)/(1<<tr['frac']):+.5f}"
                              f"  tan={_s16(d, p+4)/(1<<tr['frac']):+.5f}")
                else:
                    vs = [_s16(d, tr["dataOff"] + k*2) / (1 << tr["frac"])
                          for k in range(tr["nframe"])]
                    print("    " + " ".join(f"{v:+.4f}" for v in vs))
        return

    print(f"{path}")
    print(f"  frameCount={m['frameCount']:g}  {len(m['bones'])} animated bones")
    nt = sum(len(b["tracks"]) for b in m["bones"])
    from collections import Counter
    fc = Counter(tr["fmt"] for b in m["bones"] for tr in b["tracks"])
    print(f"  {nt} tracks  (constant={fc[0]}, keyframe={fc[1]}, dense={fc[4]})")
    for b in m["bones"]:
        groups = ",".join(g for g, bit in GROUPS if b["mask"] & bit)
        kinds = " ".join(f"{CHANNELS[tr['channel']]}:{tr['fmt']}" for tr in b["tracks"])
        print(f"    {b['name']:<20} [{groups}]  {kinds}")


if __name__ == "__main__":
    _cli()
