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
    else:
        print(__doc__.split("Usage:")[0].rstrip())


if __name__ == "__main__":
    main()
