r"""The Last Story SURFACE TYPES -- what a collision triangle is made of.

`boot/colli_attr_table.csv` is the game's own surface table: 33 rows, ids 0..32,
each naming a material in Japanese plus what the engine should do when something
touches it -- a splash effect and three footstep sounds (human / creature /
machine).

    id, name,          ATR_EFF,       ATR_HUMAN_SE, ATR_CREATURE_SE, ATR_MACHINE_SE
    8,  grass,         ,              SE_ATTR008,   SE_ATTR021,      SE_ATTR008
    20, water,         ef_ca020.eff,  SE_ATTR020,   SE_ATTR020,      SE_ATTR020

--- WHAT THIS SETTLES ------------------------------------------------------
The `.hocb` material record (32 bytes, see parse_hocb.py) was previously read as

    +0x00  u32   bitfield A   (0, 0x10, 0x08, 0x01, 0x02, ...)

It is not a bitfield. It is the **surface id** of this table, and the values
that made it look like one -- 1, 2, 8, 0x10 -- are simply the four commonest
surfaces: brown earth, black soil, grass, stone paving. Small ordinals and bit
masks are indistinguishable until you find the table they index.

--- THE EVIDENCE -----------------------------------------------------------
Run `--check`. Four things have to hold at once, and they do:

1. RANGE. Across 413,390 triangles in 351 files, **not one** id falls outside
   0..32, and the maximum is exactly 32 -- the table's last row. A field that
   merely happened to hold small numbers would overshoot somewhere.
2. SHAPE. The distribution is what a JRPG's geometry should look like: 80.8%
   id 0 "nothing" (the default, and entry #0 of every file), then 8.2% stone
   paving over 177 files, then grass, earth, rock. "On leaves" appears in
   exactly one file.
3. THE EFFECTS EXIST. The table names four `.eff` files; all four are on the
   disc under `data/eff/`. Their names encode the id they belong to --
   `ef_ca020.eff` for id 20 (water), `ef_ca032.eff` for id 32 -- where `ca`
   reads as "collision attribute".
4. WATER IS LOCALISED. Ids 20/21/28/29/32 appear in 1..23 files out of 351,
   not scattered everywhere. Muddy water is used in exactly one map.

Note that criterion 1 alone would be weak: 0 and 1 dominate nearly every field
in every format, so "small values in range" confirms almost any guess. What
carries the argument is the maximum landing *exactly* on 32 together with 2-4.

--- WHAT IS STILL OPEN -----------------------------------------------------
The material record's **second** word (+0x04) is a real bitfield and remains
undecoded (values 0, 0x200, 0x11e, 0x21e, 0x1e, 0x16, max 0x40014). It is not
the surface type -- that question is now answered -- so it is likely per-volume
behaviour: no-walk, damage, climbable. The third word is a debug ARGB colour.

Usage:
    python parse_colli_attr.py                # print the surface table
    python parse_colli_attr.py --check        # run the four checks above
    python parse_colli_attr.py --map dg001_01 # surfaces used by one map
"""
import csv
import io
import os
import struct
import sys
import glob
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_hocb as P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS = os.path.join(ROOT, "assets", "pack", "filesystem")
TABLE = os.path.join(FS, "boot", "colli_attr_table.csv")

# The table is authored in Japanese; this is a reading aid, not data from the
# game. Keep it separate from the parsed rows so nothing depends on it.
ENGLISH = {
    0: "nothing", 1: "brown earth", 2: "black soil", 3: "earth 2",
    4: "earth 3", 5: "earth + grass", 6: "sand", 7: "gravel", 8: "grass",
    9: "bush", 10: "fallen leaves", 11: "wood", 12: "plank", 13: "ivy",
    14: "human", 15: "metal", 16: "stone paving", 17: "marble", 18: "rock",
    19: "brick", 20: "water", 21: "muddy water", 22: "ice", 23: "snow",
    24: "glass", 25: "carpet", 26: "underwater", 27: "water surface",
    28: "water: knee-deep", 29: "water: waist-deep", 30: "on leaves",
    31: "healing spring", 32: "viscous water",
}


def load_table(path=TABLE):
    """-> {id: {'jp','eff','human','creature','machine'}}. The CSV is Shift-JIS."""
    raw = open(path, "rb").read()
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", "replace"))))
    out = {}
    for r in rows[1:]:
        if len(r) >= 6 and r[0].strip().isdigit():
            out[int(r[0])] = {"jp": r[1], "eff": r[2], "human": r[3],
                              "creature": r[4], "machine": r[5]}
    return out


def material_records(d):
    """-> [(fileOffset, (w0..w7))] for the 0x203 section of a .hocb."""
    ss = [s for s in P.sections(d) if s["kind"] == 0x203]
    if not ss:
        return []
    s = ss[0]
    return [(s["target"] + i * 32,
             struct.unpack_from(">8I", d, s["target"] + i * 32))
            for i in range(s["size"] // 32)]


def surface_of_triangles(path):
    """-> Counter{surfaceId: nTriangles} for one .hocb."""
    d = open(path, "rb").read()
    attr = {o: m[0] for o, m in material_records(d)}
    got = collections.Counter()
    for t in P.parse(d)["tris"]:
        a = attr.get(t["material"])
        if a is not None:
            got[a] += 1
    return got


def _tally_all():
    files = sorted(glob.glob(os.path.join(P.COL_DIR, "*.hocb")))
    tris = collections.Counter()
    in_files = collections.defaultdict(set)
    for p in files:
        try:
            got = surface_of_triangles(p)
        except Exception:
            continue
        for a, n in got.items():
            tris[a] += n
            in_files[a].add(os.path.basename(p))
    return files, tris, in_files


def print_table():
    tab = load_table()
    print(f"colli_attr_table.csv: {len(tab)} surfaces, ids {min(tab)}..{max(tab)}\n")
    print(f"{'id':>3}  {'surface':22} {'effect':16} {'human SE':12} {'creature SE':12}")
    for i in sorted(tab):
        t = tab[i]
        print(f"{i:3d}  {ENGLISH.get(i,'?'):22} {t['eff']:16} "
              f"{t['human']:12} {t['creature']:12}")


def check():
    tab = load_table()
    files, tris, in_files = _tally_all()
    total = sum(tris.values())
    print(f".hocb files: {len(files)}   triangles joined: {total}\n")

    bad = sorted(a for a in tris if a not in tab)
    print(f"1. RANGE   ids outside the table : {bad if bad else 'none'}")
    print(f"           maximum id seen       : {max(tris)} "
          f"(table ends at {max(tab)})")

    print(f"\n2. SHAPE   {'id':>3} {'triangles':>9} {'%':>7} {'files':>6}  surface")
    for a, n in sorted(tris.items()):
        print(f"           {a:3d} {n:9d} {n/total:6.2%} {len(in_files[a]):6d}  "
              f"{ENGLISH.get(a,'?')}")

    print("\n3. EFFECTS named by the table:")
    for e in sorted({t["eff"] for t in tab.values() if t["eff"]}):
        hit = glob.glob(os.path.join(FS, "**", e), recursive=True)
        print(f"           {e:18s} {'FOUND' if hit else 'MISSING'}")

    print("\n4. WATER localisation (files out of "
          f"{len(files)}):")
    for a in (20, 21, 26, 27, 28, 29, 31, 32):
        if a in in_files:
            print(f"           id {a:2d} {ENGLISH[a]:20s} {len(in_files[a]):3d}")


def for_map(name):
    tab = load_table()
    p = P.colli_for_map(name if name.endswith(".map") else name + ".map")
    if not p:
        print(f"no .hocb for map {name}")
        return
    print(f"{os.path.basename(p)}:")
    got = surface_of_triangles(p)
    for a, n in got.most_common():
        t = tab.get(a, {})
        print(f"  {a:3d} {n:7d}  {ENGLISH.get(a,'?'):22} {t.get('eff','')}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print_table()
    elif a[0] == "--check":
        check()
    elif a[0] == "--map" and len(a) > 1:
        for_map(a[1])
    else:
        print(__doc__)
