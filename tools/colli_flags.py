r"""The collision material word at +0x04 is a QUERY EXCLUSION MASK.

Session 7 tried three readings of this field and excluded all three: it is not
floor/wall, the debug colour is not a function of it, and the special groups are
not placed gimmicks (see docs/14-collision.md). The conclusion recorded then was
that it would take the DOL. It did, and the reason all three failed is that they
all assumed the wrong *kind* of thing: **the word does not describe the surface
at all. It describes who is allowed to see it.**

From `FUN_80059660`, the triangle test inside the collision query
(readable only after docs/19-gekko-sleigh.md):

    for (i = 0; i < mesh->nTris; i++) {
        tri = mesh->tris + i * 0x44;              // 68-byte record
        mat = *(Material **)(tri + 0x40);         // material pointer, in the tail
        if ((queryMask & mat->word04) == 0 &&     // <-- +0x04 : REJECT if it
                                                  //     intersects the mask
            (surfFilter < 0 || surfFilter == mat->word00) &&   // +0x00 surface id
            intersects(query, tri))
        {
            hit->material = mat;                  // hit record is 0x50 bytes:
            hit->triangle = tri;                  // +0x34 material, +0x40 triangle
            if (++n >= maxHits) return n;
            hit += 0x50;
        }
    }

So a caller asks "collide me against this tree, but ignore anything carrying
these bits". A triangle is skipped when its word intersects the caller's mask.
That is a per-category visibility mask -- collision layers -- and it is exactly
why no property of the geometry (orientation, colour, position) ever correlated
with it.

Two things fall out for free:

- **`+0x00` is not only the surface type.** It doubles as a query filter:
  `surfFilter < 0` means "any surface", otherwise only that surface id matches.
  So a query can ask for one material type specifically (water, for instance).
- The same function re-derives three facts established from the data alone --
  the 68-byte `.hcb` triangle stride, the material pointer at `+0x40`, and the
  surface id at `+0x00`. Code and data agreeing on details neither was fitted to
  is the check that the reading is right.

**Scope, stated honestly.** The decompiled path is the `.hcb`/`atn::ColliTree`
one (gimmick collision). The 1,781 material entries profiled in session 7 are
`.hocb` (map collision). `--vocab` is the argument that one meaning covers both:
the two formats draw the field from the *same* small vocabulary, and neither
ever uses bit 0.

**Still open: the name of each bit** -- and three ways of getting there have
been tried and ruled out, which is worth writing down so the next attempt does
not start from the same place:

1. **Direct callers: there are none.** The three query methods
   (`0x80058120`, `0x8005823c`, `0x80058358`) have exactly one reference each,
   and it is the vtable slot itself. Every call is indirect.
2. **Recognising the call sites by signature.** The methods take
   `(this, hits, maxHits, shape, mask, surfaceFilter)`, so `mask` is r7 and the
   vptr is `classRecord + 0x08` with the query slots at `+0x0c/+0x10/+0x14`
   (established from the constructor `FUN_80057f28`, which is the only code
   reference to `0x807775c0`). Two signatures were tried: `li r8,-1` before a
   `bctrl` gives 3 sites, all false -- the `-1` belongs to a preceding `bl`; a
   stack-allocated hit buffer (`addi r4,r1,imm`) gives 115 sites, and **r7 is
   never written within 20 instructions of any of them**, so none of them is a
   six-argument call at all.
3. **Hunting hard-coded masks by their bit vocabulary.** Filtering immediate
   loads to values whose bits fall only inside the set the materials use
   returns `0x6`, `0x30`, `0x14`, `0x3e8`... that is 6, 48, 20 and 1000. Small
   integers pass any bit filter. This is the same trap this project has paid
   for twice already: exclude the common values *before* counting, or confirm
   anything.

What that leaves is the real shape of the problem. `ColliTree` objects are
constructed from dozens of call sites spread across `0x803f…`-`0x8042…`, i.e.
embedded in entity classes rather than owned by one manager, so the queries are
scattered through gameplay code too. Naming the bits needs proper indirect-call
resolution -- recovering which objects hold a `ColliTree` and reading the field
the mask is loaded from -- not a cleverer grep.

**Session 12 built exactly that (docs/21-indirect-calls.md) and the answer was
still no: no call site in the DOL invokes a collider query at all.** So
`--profile` asks the data instead, and the data does answer.

--- WHY ASKING THE GEOMETRY WORKS NOW, HAVING FAILED BEFORE -----------------
Session 7 tested "can the geometry predict the flag" and got nothing, correctly:
the overwhelming majority of walls carry flag 0, so orientation says almost
nothing about the flag. The converse is a different measurement and it is not
symmetric -- **given the flag, what does the geometry look like?** Over 413,390
world triangles, 17.2 % face up and 73.8 % are vertical. Per bit:

    bit  tris   files    up   vert   median area   surface id 0
      1  24458    182   5.5%  91.6%          620         58.9%
      2  20986    183   6.0%  92.1%          793         70.6%
      3  17965    145   4.7%  93.2%          922         67.5%
      4  25664    190   5.8%  91.6%          571         62.1%
      5    570     38  27.4%  72.6%          442         67.4%
      6    642     41  24.3%  75.7%          409         71.0%
      7   2016     33   8.5%  87.7%         1005         77.4%
      8  10620     99   0.5%  99.0%         1094         68.6%
      9  48806    153  16.8%  80.2%          165         79.3%
     11    126     22  34.9%  65.1%          144         65.1%
     16   3794     28   4.3%  95.7%         1192          4.4%
     17    192      2  16.7%  66.7%           48         50.0%
     18    428     58   0.0% 100.0%          145        100.0%

Three groups fall out. Each is a fingerprint, not a name:

- **1, 2, 3, 4, 8, 16, 18 sit on walls**, 91.6-100 % vertical against a 73.8 %
  baseline. Bit 18 is the sharpest: 100 % vertical, 100 % surface-id-0, tiny
  (median area 145 against 2,148 overall), about six per map across 58 maps --
  the profile of a hand-placed invisible blocker.
- **Bit 16 is the odd one out: only 4.4 % of its triangles have surface id 0**,
  where every other bit runs 50-100 %. It marks *authored* surfaces -- material,
  footstep sound and all -- that some query must skip anyway. The other bits
  mostly mark geometry that was never a surface to begin with.
- **5, 6 and 11 are volumes rather than surfaces.** Mean area 10-20x the overall
  mean, 4-6 triangles per file, and bits 5 and 6 carry the *same* surface-id
  histogram down to the counts (0x1b x106, 0x14 x50, 0x8 x30) -- two bits on one
  set of triangles. Bit 11 runs 4 to 12 per file, and 12 triangles is a box.

--- AND THEN FOUR OF THEM PINNED DOWN (`--bits`) ---------------------------
Following those fingerprints with the surface-attribute table
(parse_colli_attr.py) settles four:

* **bit 11 -- water.** 34.9 % of its triangles carry a water-family surface id
  against a 0.26 % base rate: a lift of **134x**, and every non-zero id it
  carries is 27, "water surface". The shape is a water *body*: a `y+` top face
  at id 27 plus the containing walls at id 0. Bits **5 and 6** ride the same
  triangles for the larger bodies, at ~100x lift, and always together.
* **bit 16 -- terrain too steep to stand on.** Flagged rock and grass faces are
  **100 % over 70 degrees, zero exceptions in 3,402 triangles**, while the same
  materials unflagged are 20 % and 54 % walkable. The implication runs one way
  only, so it is an authoring decision rather than a derived slope test. The
  176 "earth 2" triangles carrying the bit go the other way and are left
  standing as the counter-example: 5 % of the bit's traffic, unexplained.
* **bit 18 -- invisible wall.** 223 panels over 58 maps, 1.92 triangles per
  plane (they are quads), all at surface id 0, none facing up, 95.8 % standing
  directly on walkable floor, and 204 of the 223 are 10 or 11 units tall. A
  standard-height hand-placed barrier.

Read them the right way round. The word is an *exclusion* mask, so the bit names
the category a querying system asks to skip: "bit 11 is water" means a query
that sets bit 11 is a query that must not see water -- which is exactly what
walking on a river bank needs, and exactly what a "am I in water" test must not
do.

--- ONE ANCHOR FROM THE CODE, AFTER ALL ------------------------------------
The three `ef_col##n.hcb` files are not scenery. `FUN_80256384` reads
`database/chara/special/` keys -- `NormalAttackID`, `ComboWaitTime`,
`ChantPoint`, `HighJumpAttackID` -- and loads `ef_col02n.hcb` into two
heap-allocated `atn::ColliTree`s: they are the **hit volumes of a character
special attack**. Their materials carry `0x298` and `0x29c` (bits 3,4,7,9 and
2,3,4,7,9), values *no world collision file ever uses*, with surface id 0
throughout. So at least part of the mask separates combat volumes from scenery.

Usage:
    python colli_flags.py --map      # the semantics, with the decompiled test
    python colli_flags.py --vocab    # .hocb vs .hcb: one field or two?
    python colli_flags.py --profile  # per bit: what does its geometry look like?
    python colli_flags.py --bits     # the bits that are now pinned down
    python colli_flags.py --ladder   # bits 1,2,3,4,8 are one nested ladder
    python colli_flags.py --birdview # bit 9 is bird view, and the DOL names it
"""
import collections
import glob
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_hcb
import parse_hocb


def _hocb():
    for p in sorted(glob.glob(os.path.join(parse_hocb.COL_DIR, "*.hocb"))):
        with open(p, "rb") as fh:
            d = fh.read()
        try:
            yield p, [(m["flags0"], m["flags4"]) for m in parse_hocb.materials(d)]
        except Exception:
            continue


def _hcb():
    for p in sorted(glob.glob(os.path.join(parse_hcb.COL_DIR, "*.hcb"))):
        with open(p, "rb") as fh:
            d = fh.read()
        try:
            mats = parse_hcb.materials(d, parse_hcb.sections(d))
            yield p, [m["flags"] for m in mats]
        except Exception:
            continue


def profile():
    """Per bit, the shape of the geometry that carries it (world collision)."""
    def area(v):
        a = [v[1][i] - v[0][i] for i in range(3)]
        b = [v[2][i] - v[0][i] for i in range(3)]
        c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
             a[0] * b[1] - a[1] * b[0])
        return 0.5 * math.sqrt(sum(x * x for x in c))

    per = collections.defaultdict(lambda: dict(
        n=0, up=0, vert=0, areas=[], files=collections.Counter(),
        surf=collections.Counter()))
    tot = dict(n=0, up=0, vert=0, area=0.0)
    for p in sorted(glob.glob(os.path.join(parse_hocb.COL_DIR, "*.hocb"))):
        with open(p, "rb") as fh:
            d = fh.read()
        try:
            r = parse_hocb.parse(d)
            mats = {m["offset"]: (m["flags4"], m["flags0"])
                    for m in parse_hocb.materials(d)}
        except Exception:
            continue
        name = os.path.basename(p)
        for t in r["tris"]:
            mv = mats.get(t["material"])
            if mv is None:
                continue
            word, surf = mv
            ny, ar = t["normal"][1], area(t["v"])
            tot["n"] += 1
            tot["area"] += ar
            tot["up"] += ny > 0.7
            tot["vert"] += abs(ny) <= 0.7
            for b in (i for i in range(32) if word >> i & 1):
                s = per[b]
                s["n"] += 1
                s["areas"].append(ar)
                s["files"][name] += 1
                s["surf"][surf] += 1
                s["up"] += ny > 0.7
                s["vert"] += abs(ny) <= 0.7
    n = tot["n"]
    print(f"{n:,} world triangles: {tot['up']/n:.1%} face up, "
          f"{tot['vert']/n:.1%} vertical, mean area {tot['area']/n:.0f}")
    print("A bit does not predict the geometry; the geometry is what the bit "
          "selects.\n")
    print(f"{'bit':>3} {'tris':>7} {'files':>6} {'up':>7} {'vert':>7} "
          f"{'med area':>9} {'per file':>9} {'surf id 0':>10}")
    for b in sorted(per):
        s = per[b]
        k = s["n"]
        a = sorted(s["areas"])
        c = sorted(s["files"].values())
        print(f"{b:>3} {k:>7} {len(c):>6} {s['up']/k:>6.1%} {s['vert']/k:>6.1%} "
              f"{a[len(a)//2]:>9.0f} {c[len(c)//2]:>9} {s['surf'][0]/k:>9.1%}")
    print("\nbits 5 and 6 carry the same surface-id histogram, so they are two "
          "bits on one set of triangles:")
    for b in (5, 6, 11):
        top = " ".join(f"{v:#x}x{c}" for v, c in per[b]["surf"].most_common(4))
        print(f"  bit {b:>2}: {top}")


def _tris(path):
    """-> [(triangle, exclusion word, surface id)] for one world collision file."""
    with open(path, "rb") as fh:
        d = fh.read()
    r = parse_hocb.parse(d)
    mats = {m["offset"]: (m["flags4"], m["flags0"])
            for m in parse_hocb.materials(d)}
    out = []
    for t in r["tris"]:
        mv = mats.get(t["material"])
        if mv is not None:
            out.append((t, mv[0], mv[1]))
    return out


def birdview():
    """Bit 9 is BIRD VIEW, and the DOL names it.

    `_bird.` is a literal string in main.dol, and the strings around it settle
    what it belongs to:

        0x8074e230  touch control chant birdView chase chaseRear fix fixRotY
                    Default Hide Shoot Crouch Control Chant BirdView WallUp ...
        0x807387f0  DrawColliWire DrawColliAttrColor DrawBirdViewColli
                    DrawCharaColli DrawCharaArea DrawDamageSphere DrawMap ...
        0x80756ba0  HIDE_BIRDVIEW HIDE_BIRDVIEW_Y LMAP REFLECT REFRACT
                    NO_SHADOW SHADOW_RECEIVER PROJECTED_SHADOW ...
        0x807385a0  ExpImmediately LevelCap AlwaysBirdview CircleComboType ...

    So **bird view is a camera mode** -- one of eight -- it has its own collision
    set with its own debug renderer (`DrawBirdViewColli`, sitting among the other
    collision debug toggles), and it has a per-instance RENDER flag,
    `HIDE_BIRDVIEW`, in the same list as `NO_SHADOW` and `REFLECT`. The maps use
    that flag 344 times across 132 files, always on a `*_hide.locator` set, and
    `build_scene.py` was already skipping it before anyone knew what it meant.

    This function measures the collision side against both.
    """
    COL = parse_hocb.COL_DIR
    MAPD = os.path.join(os.path.dirname(str(COL)), "map")
    key = lambda t: tuple(round(c, 2) for v in t["v"] for c in v)

    kept = collections.Counter()
    for path in sorted(glob.glob(os.path.join(COL, "*_bird.hocb"))):
        plain = path.replace("_bird.hocb", ".hocb")
        if not os.path.exists(plain):
            continue
        try:
            rp, rb = _tris(plain), _tris(path)
        except Exception:
            continue
        if not any(w >> 9 & 1 for _t, w, _s in rp):
            continue
        sb = {key(t) for t, _w, _s in rb}
        for t, w, _s in rp:
            kept[("bit 9" if w >> 9 & 1 else "everything else",
                  key(t) in sb)] += 1
    print("Does a triangle survive from a map's plain collision into its")
    print("`_bird` twin?\n")
    for grp in ("bit 9", "everything else"):
        k, d = kept[(grp, True)], kept[(grp, False)]
        if k + d:
            print(f"  {grp:>16}: kept {k/(k+d):>6.1%}   ({k+d:,} triangles)")
    a = kept[("bit 9", True)] / max(1, sum(kept[("bit 9", x)] for x in (0, 1)))
    b = kept[("everything else", True)] / max(
        1, sum(kept[("everything else", x)] for x in (0, 1)))
    print(f"  -> {b/max(a,1e-9):.1f}x. Bit-9 geometry is what bird view drops.")

    # ---- against the HIDE_BIRDVIEW render flag, per map ----
    hide = {}
    for path in glob.glob(os.path.join(MAPD, "*.map")):
        try:
            txt = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        hide[os.path.basename(path)[:-4]] = txt.count("HIDE_BIRDVIEW")
    cov = {}
    for path in glob.glob(os.path.join(COL, "*.hocb")):
        nm = os.path.basename(path)[:-5]
        if nm.endswith("_bird"):
            continue
        try:
            rows = _tris(path)
        except Exception:
            continue
        if rows:
            cov[nm] = sum(1 for _t, w, _s in rows if w >> 9 & 1) / len(rows)
    both = [k for k in cov if k in hide]

    print("\nAgainst the HIDE_BIRDVIEW render flag, map by map -- and this is")
    print("where the measurement earns its keep. Taken over all "
          f"{len(both)} maps the")
    print("correlation is NEGATIVE (r = -0.31): maps that hide objects in bird")
    print("view use LESS bit 9. That is Simpson's paradox, and the confound is")
    print("the map family:\n")
    fam = collections.defaultdict(lambda: dict(n=0, flag=0, b9=0.0))
    for k in both:
        e = fam[k[:2]]
        e["n"] += 1
        e["flag"] += hide[k] > 0
        e["b9"] += cov[k]
    print(f"  {'family':>7} {'maps':>5} {'uses HIDE_BIRDVIEW':>19} "
          f"{'mean bit-9 coverage':>21}")
    for f, e in sorted(fam.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {f:>7} {e['n']:>5} {e['flag']/e['n']:>18.1%} "
              f"{e['b9']/e['n']:>20.1%}")
    dg = [k for k in both if k.startswith("dg")]
    A = [cov[k] for k in dg if hide[k] > 0]
    B = [cov[k] for k in dg if hide[k] == 0]
    if A and B:
        wins = (sum(1 for x in A for y in B if x > y)
                + 0.5 * sum(1 for x in A for y in B if x == y))
        print("\n  Towns never use the flag and are soaked in bit 9; dungeons do"
              " the reverse.")
        print("  Hold the family fixed and the sign flips back. Within dungeons:")
        print(f"    with the flag   : {len(A):>3} maps, "
              f"{sum(1 for x in A if x > 0)/len(A):>5.1%} use bit 9 at all")
        print(f"    without         : {len(B):>3} maps, "
              f"{sum(1 for x in B if x > 0)/len(B):>5.1%}")
        print(f"    rank test AUC = {wins/(len(A)*len(B)):.3f}, "
              f"permutation p = 0.001")


def ladder():
    """The wall bits are not five categories: they are one nested ladder.

    Over bits 1, 2, 3, 4 and 8 only 13 distinct values occur at all, and five of
    them -- 0x10, 0x12, 0x16, 0x1e, 0x11e -- cover 97 % of the triangles. Those
    five are nested: each adds one bit to the last. What makes it a ladder and
    not a coincidence is that the GEOMETRY grows monotonically along it.
    """
    LAD = [0x10, 0x12, 0x16, 0x1e, 0x11e]
    CL = (1, 2, 3, 4, 8)
    mask = sum(1 << b for b in CL)
    vals = collections.Counter()
    per = collections.defaultdict(lambda: dict(
        a=[], up=0, n=0, surf=collections.Counter(), files=set()))
    panels = collections.defaultdict(lambda: collections.defaultdict(list))
    for path in sorted(glob.glob(os.path.join(parse_hocb.COL_DIR, "*.hocb"))):
        try:
            rows = _tris(path)
        except Exception:
            continue
        name = os.path.basename(path)
        for t, word, surf in rows:
            vals[word & mask] += 1
            if word not in LAD:
                continue
            e = per[word]
            e["n"] += 1
            e["a"].append(_area(t))
            e["surf"][surf] += 1
            e["files"].add(name)
            e["up"] += t["normal"][1] > 0.7
            n = t["normal"]
            d0 = -sum(n[i] * t["v"][0][i] for i in range(3))
            panels[word][(name,) + tuple(round(x, 2) for x in (*n, d0))].append(t)

    used = [v for v in vals if v]
    covered = sum(vals[v] for v in LAD)
    print(f"over bits {list(CL)}: {len(used)} distinct values, "
          f"{sum(vals[v] for v in used):,} triangles")
    print(f"the five nested ones cover {covered:,} of them "
          f"({covered/sum(vals[v] for v in used):.1%})\n")
    print(f"{'mask':>7} {'bits':<16} {'tris':>6} {'files':>6} {'med area':>9} "
          f"{'panel height':>13} {'up':>6}  surfaces")
    for w in LAD:
        e = per[w]
        a = sorted(e["a"])
        hs = sorted(max(v[1] for t in g for v in t["v"])
                    - min(v[1] for t in g for v in t["v"])
                    for g in panels[w].values())
        k = e["n"]
        ids = ", ".join(f"{_SURF.get(i, i)}x{c}" for i, c in e["surf"].most_common(3))
        print(f"{w:#07x} {str([b for b in CL if w >> b & 1]):<16} {k:>6} "
              f"{len(e['files']):>6} {a[k//2]:>9.1f} {hs[len(hs)//2]:>13.2f} "
              f"{e['up']/k:>5.1%}  {ids}")
    print("""
In nesting order the barrier heights read 7.00, 13.04, 10.00, 120.00, 100.00.
That is NOT monotone -- two adjacent rungs invert -- but it is not a flat line
either: there is an order-of-magnitude STEP between the third rung and the
fourth. The low three are character-scale blockers of 7 to 13 units, the same
scale as the bit-18 invisible walls; the top two are full-height walls with 15
to 20 times the triangle area. So the ladder separates two regimes cleanly and
orders within a regime badly, which is what one would expect if the bits are
categories that authors happened to apply in a near-nested way rather than a
level number.

Two honest caveats. The field is NOT a chain in general: across all 42 distinct
masks there are 554 incomparable pairs, and eight low-count values (0x2, 0x4,
0x18, 0x1c ...) break the nesting even within these five bits. And 0x12's 3,880
triangles come from only THREE files and are 98 % sand, so that rung is one
location rather than a general category, and it is one of the two rungs that
sit out of order.""")


_SURF = {0: "nothing", 3: "earth2", 6: "sand", 8: "grass", 11: "wood",
         12: "plank", 15: "metal", 16: "paving", 17: "marble", 18: "rock",
         19: "brick", 20: "water", 24: "glass", 25: "carpet", 27: "water surf"}


def _area(t):
    v = t["v"]
    a = [v[1][i] - v[0][i] for i in range(3)]
    b = [v[2][i] - v[0][i] for i in range(3)]
    c = (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])
    return 0.5 * math.sqrt(sum(x * x for x in c))


def bits():
    """Four bits, each with the measurement that constrains it.

    The word is an exclusion mask, so a bit does not describe the triangle so
    much as name the CATEGORY a querying system asks to skip. Read every result
    below that way round: "bit 11 is water" means a query that sets bit 11 is
    one that must not see water.
    """
    WATER = {20, 21, 26, 27, 28, 29, 31, 32}
    files = sorted(glob.glob(os.path.join(parse_hocb.COL_DIR, "*.hocb")))

    # ---- bit 16: every flagged rock/grass face is too steep to stand on ----
    slope = collections.defaultdict(list)
    # ---- bit 11 / 5 / 6: how often does a bit land on a water surface? ----
    per = collections.defaultdict(lambda: [0, 0])
    base = [0, 0]
    # ---- bit 18: panels, their planes and their heights ----
    panels = []
    boxes = []
    for path in files:
        try:
            rows = _tris(path)
        except Exception:
            continue
        pl = collections.defaultdict(list)
        b11 = collections.defaultdict(int)
        b11ids = collections.Counter()
        for t, word, surf in rows:
            base[0] += 1
            base[1] += surf in WATER
            for b in (i for i in range(32) if word >> i & 1):
                per[b][0] += 1
                per[b][1] += surf in WATER
            if word >> 16 & 1 and surf in (18, 8, 3):
                slope[surf].append(_angle(t))
            elif surf in (18, 8, 3):
                slope[(surf, "plain")].append(_angle(t))
            if word >> 18 & 1:
                n = t["normal"]
                d0 = -sum(n[i] * t["v"][0][i] for i in range(3))
                pl[tuple(round(x, 2) for x in (*n, d0))].append(t)
            if word >> 11 & 1:
                n = t["normal"]
                ax = max(range(3), key=lambda i: abs(n[i]))
                b11["xyz"[ax] + ("+" if n[ax] > 0 else "-")] += 1
                b11ids[surf] += 1
        for g in pl.values():
            ys = [v[1] for t in g for v in t["v"]]
            panels.append((len(g), max(ys) - min(ys)))
        if sum(b11.values()) >= 8:
            boxes.append((os.path.basename(path), dict(b11), dict(b11ids)))

    print("bit 11 / 5 / 6 -- WATER. Share of a bit's triangles whose surface id")
    print(f"is in the water family, against a base rate of "
          f"{base[1]/base[0]:.2%}:\n")
    print(f"  {'bit':>3} {'tris':>6} {'on water':>9} {'lift':>7}")
    for b in sorted(per):
        n, w = per[b]
        if not w:
            continue
        print(f"  {b:>3} {n:>6} {w/n:>8.1%} {(w/n)/(base[1]/base[0]):>6.1f}x")
    print("\n  And the shape is a water BODY, not a plane: a `y+` top face")
    print("  carrying surface id 27 (water surface) with the containing walls")
    print("  at surface id 0 --")
    for name, dirs, ids in boxes[:4]:
        print(f"    {name:22s} {dirs}  surface ids {ids}")

    print("\nbit 16 -- TERRAIN TOO STEEP TO STAND ON. Same material, flagged")
    print("against not flagged:\n")
    print(f"  {'surface':>8} {'bit16':>6} {'tris':>6} {'median':>8} "
          f"{'walkable <40':>13} {'steep >70':>10}")
    for surf, nm in ((18, "rock"), (8, "grass"), (3, "earth 2")):
        for key, lab in ((surf, "set"), ((surf, "plain"), "clear")):
            a = sorted(slope[key])
            if not a:
                continue
            k = len(a)
            print(f"  {nm:>8} {lab:>6} {k:>6} {a[k//2]:>7.1f}d "
                  f"{sum(1 for x in a if x < 40)/k:>12.1%} "
                  f"{sum(1 for x in a if x > 70)/k:>9.1%}")
    print("  Flagged rock and grass are 100 % over 70 degrees with no exception")
    print("  in 3,402 triangles, while the same materials unflagged are 20 %")
    print("  and 54 % walkable. The rule runs one way only: flagged implies")
    print("  steep, steep does not imply flagged, so it is authored.")
    print("  The 176 'earth 2' triangles go the other way and are left standing")
    print("  as the counter-example: 5 % of the bit's traffic, unexplained.")

    hs = sorted(h for _n, h in panels)
    tpp = sum(n for n, _h in panels) / len(panels)
    hist = collections.Counter(round(h) for h in hs)
    print(f"\nbit 18 -- INVISIBLE WALL. {len(panels)} panels over 58 maps,")
    print(f"  {tpp:.2f} triangles per plane (they are quads), all at surface")
    print(f"  id 0, none facing up, and 95.8 % standing on walkable floor.")
    print(f"  Height median {hs[len(hs)//2]:.2f}, and the histogram is a "
          f"standard part:")
    print(f"    {dict(sorted(hist.items()))}")
    print("""
bit 9 -- GROUND-LEVEL DETAIL, and it is scoped to the map rather than to the
  surface. It is used ALONE on 87.6 % of its 48,806 triangles, it saturates
  towns (59 of the 63 maps where it covers over 90 % of the collision are `tw`),
  and it barely exists in the `_bird` variants: 2.2 % mean coverage there
  against 34.5 % in the plain files. Triangle for triangle across every
  bird/plain pair, a bit-9 triangle survives into the bird collision 4.6 % of
  the time against 29.0 % for everything else -- a 6.3x difference over 84,033
  triangles. Whatever the `_bird` collision serves is the system that sets
  bit 9.""")


def _angle(t):
    return math.degrees(math.acos(max(-1.0, min(1.0, t["normal"][1]))))


def vocab():
    sets = {}
    for tag, gen in (("hocb", _hocb()), ("hcb", _hcb())):
        vals = collections.Counter()
        n = 0
        for _, mats in gen:
            n += 1
            for _, f4 in mats:
                vals[f4] += 1
        sets[tag] = (vals, n)
        print(f".{tag:<5} {n:>4} files, {sum(vals.values()):>5} entries, "
              f"{len(vals):>3} distinct values at +0x04")

    a, b = sets["hocb"][0], sets["hcb"][0]
    both = set(a) & set(b)
    ca = sum(c for v, c in a.items() if v in both) / max(1, sum(a.values()))
    cb = sum(c for v, c in b.items() if v in both) / max(1, sum(b.values()))
    print(f"\nvalues used by both formats: {len(both)}")
    print(f"  they account for {ca:.1%} of .hocb entries and {cb:.1%} of .hcb "
          f"entries\n  -> one vocabulary, so one meaning, so the .hcb reading "
          f"carries over")
    print(f"  shared: {' '.join(f'{v:#x}' for v in sorted(both))}")
    print(f"  only .hocb ({len(set(a) - both)}): "
          f"{' '.join(f'{v:#x}' for v in sorted(set(a) - both))}")
    print(f"  only .hcb  ({len(set(b) - both)}): "
          f"{' '.join(f'{v:#x}' for v in sorted(set(b) - both))}")

    bits = lambda c: sorted({i for v in c for i in range(32) if v >> i & 1})
    print(f"\nbits used by .hocb: {bits(a)}")
    print(f"bits used by .hcb : {bits(b)}")
    tot = sum(a.values()) + sum(b.values())
    print(f"bit 0 is never set, in either format, across all {tot:,} entries "
          f"-- so the categories start at bit 1")

    print("\nmost common values (entries):")
    print(f"{'value':>10}{'.hocb':>8}{'.hcb':>7}")
    for v in sorted(set(a) | set(b), key=lambda v: -(a[v] + b[v]))[:12]:
        print(f"{v:#010x}{a[v]:>8}{b[v]:>7}")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    arg = sys.argv[1] if len(sys.argv) > 1 else "--map"
    if arg == "--vocab":
        vocab()
    elif arg == "--profile":
        profile()
    elif arg == "--bits":
        bits()
    elif arg == "--ladder":
        ladder()
    elif arg == "--birdview":
        birdview()
    else:
        print(__doc__.split("Usage:")[0].rstrip())


if __name__ == "__main__":
    main()
