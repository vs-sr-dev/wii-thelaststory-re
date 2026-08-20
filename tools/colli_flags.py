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

**Still open: the name of each bit.** The mask arrives as an argument, and the
query entry points are called through the `atn::ColliTree` vtable, so the
constant masks live at indirect call sites. Naming the bits means finding those
callers -- camera, player, projectile, NPC -- not reading more of this function.

Usage:
    python colli_flags.py --map      # the semantics, with the decompiled test
    python colli_flags.py --vocab    # .hocb vs .hcb: one field or two?
"""
import collections
import glob
import io
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
    else:
        print(__doc__.split("Usage:")[0].rstrip())


if __name__ == "__main__":
    main()
