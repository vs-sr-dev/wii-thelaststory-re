"""Parser for The Last Story `.map` files (LastWorld engine) -- THE SCENE.

Plain TSV, 
 line endings, '#' comments:
    # MAP dg001_01, ASSET 12047, 2009/12/10 19:26:03
    KEY 	 field 	 field ...

A .map holds no geometry: it is the scene's BILL OF MATERIALS. It lists the
pieces to load and the rendering parameters. Keys seen across all 468 files:

  MODEL        static model [+ flags]     the TERRAIN GEOMETRY lives here,
                                          in the file ending in _base.model
  LOCATORS     prop instance list         -> .locator (see parse_locator.py)
  GIMMICK_LOC  same, for interactive gimmicks
  COLLI_TREE   collision tree             -> .hocb
  AREAFILE     zones/triggers             -> .area
  EFP          effects                    -> .efp

  ...plus rendering keys, which carry no geometry but describe the lighting:
  AMBIENT_COLOR, LIGHT, LIGHTSURROUND, FOG, SHADOW, REFLECT, BLOOM, DOF,
  GODRAY, GAMMA, COLOR_MATRIX, CLEAR_COLOR, CAMERA_CLIP.

Flags seen on MODEL rows: HIDE_BIRDVIEW, REFRACT / FORCE_REFRACT,
REFLECT / FORCE_REFLECT, NO_SHADOW.

Note: 3 files write CREAR_COLOR instead of CLEAR_COLOR -- a typo present in the
shipped data, to be accepted as an alias.

See docs/11-maps-and-scenes.md.

Usage:
    python parse_map.py FILE.map            # summary
    python parse_map.py FILE.map --models   # models only, one per line
"""
import os
import sys

MAPDIR = os.path.join(os.path.dirname(__file__),
                      "..", "assets", "pack", "filesystem", "data", "map")

GEOMETRY_KEYS = ("MODEL", "LOCATORS", "GIMMICK_LOC")


def parse(text):
    """Returns {'comment':str, 'rows':[(key, [fields])], 'by_key':{...}}."""
    rows = []
    comment = ""
    for ln in text.splitlines():
        ln = ln.rstrip("\r")
        if not ln.strip():
            continue
        if ln.lstrip().startswith((";", "#")):
            if not comment:
                comment = ln.lstrip("#; ").strip()
            continue
        parts = ln.split("\t")
        key = parts[0].strip()
        if key == "CREAR_COLOR":          # typo in the shipped data
            key = "CLEAR_COLOR"
        rows.append((key, [p.strip() for p in parts[1:]]))

    by_key = {}
    for key, fields in rows:
        by_key.setdefault(key, []).append(fields)
    return {"comment": comment, "rows": rows, "by_key": by_key}


def parse_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


def models(m):
    """[(fileName, [flags])] of the MODEL rows, in file order."""
    return [(f[0], f[1:]) for f in m["by_key"].get("MODEL", []) if f]


def terrain(m):
    """The terrain model: the MODEL row ending in _base.model.

    If there is more than one (maps split into sectors) all are returned,
    skipping the _hide variants, which duplicate geometry for the overhead
    camera.
    """
    out = []
    for name, flags in models(m):
        if name.endswith("_base.model") and "HIDE_BIRDVIEW" not in flags:
            out.append(name)
    return out


def locators(m, gimmick=True):
    keys = ["LOCATORS"] + (["GIMMICK_LOC"] if gimmick else [])
    return [f[0] for k in keys for f in m["by_key"].get(k, []) if f]


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    if not os.path.exists(path):
        path = os.path.join(MAPDIR, path)
    m = parse_file(path)

    if "--models" in sys.argv:
        for name, flags in models(m):
            print(name + ("\t" + ",".join(flags) if flags else ""))
        return

    print(f"{os.path.basename(path)}   # {m['comment']}")
    print(f"  {len(m['rows'])} rows, {len(m['by_key'])} distinct keys\n")
    print("  --- geometry ---")
    for name in terrain(m):
        print(f"    TERRAIN   {name}")
    for name, flags in models(m):
        if name in terrain(m):
            continue
        print(f"    model     {name}" + (f"   [{','.join(flags)}]" if flags else ""))
    for name in m["by_key"].get("LOCATORS", []):
        print(f"    locator   {name[0]}" +
              (f"   [{','.join(name[1:])}]" if len(name) > 1 else ""))
    for name in m["by_key"].get("GIMMICK_LOC", []):
        print(f"    gimmick   {name[0]}")
    for k in ("COLLI_TREE", "AREAFILE", "EFP"):
        for f in m["by_key"].get(k, []):
            print(f"    {k.lower():<9} {f[0]}")

    print("\n  --- rendering ---")
    for k in ("CAMERA_CLIP", "AMBIENT_COLOR", "LIGHT", "FOG", "SHADOW", "DOF"):
        for f in m["by_key"].get(k, []):
            print(f"    {k:<14} {' '.join(f)}")


if __name__ == "__main__":
    _cli()
