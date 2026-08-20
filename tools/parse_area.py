"""The Last Story environment areas (.area) -- the zones of a level.

FORMAT: plain TSV, BLOCK-structured. 293 files in data/area/. A block starts at
an AREA row and runs to the next one; blank lines mean nothing.

    AREA <name> <minX> <minY> <minZ> <maxX> <maxY> <maxZ>
    AREA_BOX <6 floats>         EXTRA volumes belonging to the same block
    <environment overrides>     LIGHT, FOG, SHADOW, GODRAY, RAIN, ...
    SET_AREA <asset>            which assets belong to this zone

A .map names its area file with an AREAFILE row (see parse_map.py).
293 files, 448 zones, 89 AREA_BOX, 676 SET_AREA.

--- what it is for ---------------------------------------------------------
Two distinct things in the same block:

1. PER-VOLUME ENVIRONMENT OVERRIDES. Inside the AABB the zone's own lighting,
   fog, shadows, rain, godrays and colour matrix apply. This is why a room
   looks different from the courtyard next to it without changing map.

   That these really are OVERRIDES shows up when you compare the key sets with
   the .map's, and the split is clean in three groups:
     - in BOTH (the .map sets a scene default, the .area overrides it):
       LIGHT, LIGHTSURROUND, AMBIENT_COLOR, FOG, SHADOW, REFLECT, GODRAY,
       COLOR_MATRIX.
     - AREA ONLY: RAIN, RAINDROPS, HAZE, CLOUDMAP, COVERAGEMAP, EFF_CONFIG.
       Local phenomena -- weather has no scene-wide default.
     - MAP ONLY, never per-area: BLOOM, DOF, GAMMA, CLEAR_COLOR, CAMERA_CLIP.
       Post-processing and camera stay global to the frame: they cannot be made
       to vary per volume, and the engine offers no way to.

2. ASSET PARTITIONING (SET_AREA). Assigns assets to a zone. It is NOT chiefly
   an extra loader, which was the obvious guess: 626 of the 676 references are
   assets the .map that loaded the area already lists. So SET_AREA mostly
   PARTITIONS content that is already there -- a per-volume visibility /
   streaming set. See --check-setarea.
   Of the remaining 50: 18 belong to a DIFFERENT .map (some .area files are
   shared between maps -- title06_area names dg014 assets, dg054_01_area names
   dg048), 30 to no map at all (nearly all the camp menu UI: status_board,
   save_load_board, map_board...) and 2 do not exist on disc.

--- the AABB field order is PROVEN -----------------------------------------
Two independent checks, both in the tool (--check-box):

1. RAINDROPS ends with `BOX <6 floats>`. In 214 blocks it is IDENTICAL to the
   block's own AABB -- same six numbers, same order. That is as clean a test as
   there is. In 47 it is all zeros (unset) and in 68 it is a volume of its own:
   the rain box is an independent volume that merely defaults to the area's. It
   is NOT constrained to sit inside the AABB (30 inside, 38 not), so do not
   assume containment.
2. COVERAGEMAP carries `<minX> <minZ> <maxX> <maxZ>` plus a .texture, i.e. the
   XZ projection. In 325 of 433 blocks it is EXACTLY the XZ union of AREA and
   its AREA_BOXes -- which proves the field order AND that AREA_BOX rows belong
   to the block above them (33 of those 325 only match once the boxes are
   included).
   The other 108 do not match: the coverage map is hand-painted and there it
   covers more (63) or something else (45). A very strong correlation, not a
   law -- which is enough for the purpose.

Usage:
    python parse_area.py FILE.area       # structured dump
    python parse_area.py --census        # key census
    python parse_area.py --check-box     # validate the AABB field order
    python parse_area.py --check-setarea # SET_AREA: in the map? on disc?
"""
import sys, os, glob, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS = os.path.join(ROOT, "assets", "pack", "filesystem")
AREA_DIR = os.path.join(FS, "data", "area")
MAP_DIR = os.path.join(FS, "data", "map")


def parse(path):
    """-> list of blocks {name, aabb, boxes, rows, setarea}.

    Rows before the first AREA (comments, in practice) are dropped.
    """
    blocks, cur = [], None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            key, args = parts[0], parts[1:]
            if key == "AREA":
                cur = {"name": args[0] if args else "",
                       "aabb": [float(x) for x in args[1:7]],
                       "boxes": [], "rows": [], "setarea": []}
                blocks.append(cur)
            elif cur is None:
                continue
            elif key == "AREA_BOX":
                cur["boxes"].append([float(x) for x in args[:6]])
            elif key == "SET_AREA":
                cur["setarea"].append(args[0] if args else "")
            else:
                cur["rows"].append((key, args))
    return blocks


def union_xz(block):
    """XZ rectangle (minX, minZ, maxX, maxZ) of AREA plus all its AREA_BOXes."""
    a = block["aabb"]
    xs, zs = [a[0], a[3]], [a[2], a[5]]
    for b in block["boxes"]:
        xs += [b[0], b[3]]
        zs += [b[2], b[5]]
    return min(xs), min(zs), max(xs), max(zs)


def dump(path):
    blocks = parse(path)
    print(f"=== {os.path.basename(path)} - {len(blocks)} zones ===")
    for b in blocks:
        a = b["aabb"]
        print(f"\n  AREA {b['name']}")
        print(f"    volume  min({a[0]:.1f}, {a[1]:.1f}, {a[2]:.1f})"
              f"  max({a[3]:.1f}, {a[4]:.1f}, {a[5]:.1f})")
        for bx in b["boxes"]:
            print(f"    + box   min({bx[0]:.1f}, {bx[1]:.1f}, {bx[2]:.1f})"
                  f"  max({bx[3]:.1f}, {bx[4]:.1f}, {bx[5]:.1f})")
        for k, args in b["rows"]:
            print(f"    {k:<15} {' '.join(args)[:100]}")
        for s in b["setarea"]:
            print(f"    SET_AREA        {s}")


def census():
    files = sorted(glob.glob(os.path.join(AREA_DIR, "*.area")))
    keys = collections.Counter()
    nblocks = nboxes = nset = 0
    for p in files:
        for b in parse(p):
            nblocks += 1
            nboxes += len(b["boxes"])
            nset += len(b["setarea"])
            keys.update(k for k, _ in b["rows"])
    print(f"{len(files)} .area files, {nblocks} zones, {nboxes} AREA_BOX, "
          f"{nset} SET_AREA\n")
    for k, n in keys.most_common():
        print(f"  {n:>5}  {k}")


def check_box():
    """Is the AABB field order minXYZ then maxXYZ?

    Test 1 (decisive): RAINDROPS repeats the same AABB after its BOX keyword.
    Test 2 (strong): COVERAGEMAP is the XZ projection of AREA + AREA_BOX.
    """
    rain_cls = collections.Counter()
    cov_cls = collections.Counter()
    examples = []
    for p in sorted(glob.glob(os.path.join(AREA_DIR, "*.area"))):
        for b in parse(p):
            for k, args in b["rows"]:
                if k != "RAINDROPS" or "BOX" not in args:
                    continue
                i = args.index("BOX")
                try:
                    box = [float(x) for x in args[i + 1:i + 7]]
                except ValueError:
                    continue
                if len(box) < 6 or len(b["aabb"]) < 6:
                    continue
                onoff = args[0] if args else "?"
                d = max(abs(box[j] - b["aabb"][j]) for j in range(6))
                if not any(box):
                    tag = "all zeros (unset)"
                elif d < 0.01:
                    tag = "== the block's AABB"
                else:
                    a = b["aabb"]
                    inside = all(box[j] >= a[j] - 0.01 for j in range(3)) and \
                             all(box[j] <= a[j] + 0.01 for j in range(3, 6))
                    tag = ("own volume, inside the AABB" if inside
                           else "own volume, NOT inside")
                    if len(examples) < 4:
                        examples.append((os.path.basename(p), b["name"],
                                         b["aabb"], box))
                rain_cls[(tag, onoff)] += 1

            cov = [r for r in b["rows"] if r[0] == "COVERAGEMAP"]
            if not cov or len(b["aabb"]) < 6:
                continue
            pred = union_xz(b)
            try:
                got = tuple(float(x) for x in cov[0][1][:4])
            except (ValueError, IndexError):
                continue
            if len(got) < 4:
                continue
            d = max(abs(pred[i] - got[i]) for i in range(4))
            contains = (got[0] <= pred[0] + .01 and got[1] <= pred[1] + .01 and
                        got[2] >= pred[2] - .01 and got[3] >= pred[3] - .01)
            tag = "exact" if d < 0.01 else ("larger" if contains else "other")
            cov_cls[(tag, "with AREA_BOX" if b["boxes"] else "no AREA_BOX")] += 1

    print("test 1 - RAINDROPS ... BOX <6f> vs the block's AABB:")
    for k in sorted(rain_cls):
        print(f"  {k[0]:<30} RAINDROPS={k[1]:<4} {rain_cls[k]}")
    print("  (examples of an own volume:)")
    for f, n, a, bx in examples:
        print(f"   {f}/{n}\n     AREA {[round(x, 1) for x in a]}"
              f"\n     BOX  {[round(x, 1) for x in bx]}")
    print("\ntest 2 - COVERAGEMAP vs the XZ union of AREA + AREA_BOX:")
    for k in sorted(cov_cls):
        print(f"  {k[0]:<8} {k[1]:<16} {cov_cls[k]}")


def _area_to_maps():
    """basename of a .area -> the .map files declaring it with AREAFILE."""
    out = collections.defaultdict(list)
    for mp in glob.glob(os.path.join(MAP_DIR, "*.map")):
        with open(mp, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\r\n").split("\t")
                if parts[0] == "AREAFILE" and len(parts) > 1:
                    out[os.path.basename(parts[1])].append(mp)
    return out


def _map_assets(mp):
    out = set()
    with open(mp, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\r\n").split("\t")
            if parts[0] in ("LOCATORS", "MODEL", "GIMMICK_LOC") and len(parts) > 1:
                out.add(os.path.basename(parts[1]))
    return out


def check_setarea():
    """Does SET_AREA add assets, or partition the ones the .map already loads?"""
    a2m = _area_to_maps()
    # every asset named by ANY .map: separates "no map loads this" from
    # "another map loads this"
    anywhere = set()
    for mp in glob.glob(os.path.join(MAP_DIR, "*.map")):
        anywhere |= _map_assets(mp)
    tally = collections.Counter()
    only_area, missing = [], []
    for p in sorted(glob.glob(os.path.join(AREA_DIR, "*.area"))):
        maps = a2m.get(os.path.basename(p), [])
        in_map = set()
        for mp in maps:
            in_map |= _map_assets(mp)
        for b in parse(p):
            for s in b["setarea"]:
                base = os.path.basename(s)
                ext = base.rsplit(".", 1)[-1].lower()
                sub = {"locator": "locator", "model": "model"}.get(ext)
                exists = bool(sub) and os.path.exists(
                    os.path.join(FS, "data", sub, base))
                if base in in_map:
                    where = "in the loading .map"
                elif base in anywhere:
                    where = "in ANOTHER .map"
                else:
                    where = "in no .map"
                tally[(where, "exists" if exists else "MISSING")] += 1
                if base not in in_map:
                    (only_area if exists else missing).append(
                        (os.path.basename(p), b["name"], base, where))
    total = sum(tally.values())
    print(f"{total} SET_AREA references; {len(a2m)} .area reached by a .map\n")
    for k in sorted(tally):
        print(f"  {k[0]:<24} {k[1]:<10} {tally[k]}")
    print(f"\n{len(only_area)} references outside the .map that loaded the area:")
    for f, n, b, w in only_area:
        print(f"   {f:<24} {n:<22} {b:<34} [{w}]")
    if missing:
        print(f"\n{len(missing)} references to files that do not exist:")
        for f, n, b, w in missing:
            print(f"   {f:<24} {n:<22} {b}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "--census":
        census()
    elif a[0] == "--check-box":
        check_box()
    elif a[0] == "--check-setarea":
        check_setarea()
    else:
        for p in a:
            dump(p if os.path.exists(p) else os.path.join(AREA_DIR, p))
