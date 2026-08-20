"""Parser for The Last Story `.building` files -- THE PROP AND ITS LODs.

Plain TSV, 
 line endings. A .building holds no geometry: it is the recipe
for a single prop, i.e. the model+material pair plus its levels of detail. It
is the link between the .locator (which says WHERE and HOW MANY instances) and
the .model (which has the triangles).

Keys, censused over all 1753 files:
    MODEL       <file.model> <file.material>              1749 rows
    MODEL_LOD   <file.model> <file.material> <distance>    201 rows
    OCCLUSION   <file.model>                                52 rows
    FOLDER      <name>                                      47 rows

MODEL_LOD distances are in world units (300 and 600 = 30 m and 60 m at
1 unit ~ 10 cm): past that threshold the cheaper model takes over. OCCLUSION is
the mesh used for occlusion culling and must not be drawn.

See docs/11-maps-and-scenes.md.

Usage:
    python parse_building.py FILE.building
"""
import os
import sys

BLDDIR = os.path.join(os.path.dirname(__file__),
                      "..", "assets", "pack", "filesystem", "data", "building")


def parse(text):
    """{'model':(mdl,mat)|None, 'lods':[(mdl,mat,dist)], 'occlusion':str|None}"""
    out = {"model": None, "lods": [], "occlusion": None, "folder": None}
    for ln in text.splitlines():
        ln = ln.rstrip("\r")
        if not ln.strip():
            continue
        p = [x.strip() for x in ln.split("\t")]
        key = p[0]
        if key == "MODEL" and len(p) >= 3 and out["model"] is None:
            out["model"] = (p[1], p[2])
        elif key == "MODEL_LOD" and len(p) >= 4:
            try:
                dist = float(p[3])
            except ValueError:
                dist = 0.0
            out["lods"].append((p[1], p[2], dist))
        elif key == "OCCLUSION" and len(p) >= 2:
            out["occlusion"] = p[1]
        elif key == "FOLDER" and len(p) >= 2:
            out["folder"] = p[1]
    return out


def parse_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


def resolve(asset, bld_dir=BLDDIR):
    """A .locator asset name ('dg001_arch10') -> recipe, or None."""
    p = os.path.join(bld_dir, asset + ".building")
    return parse_file(p) if os.path.exists(p) else None


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    if not os.path.exists(path):
        path = os.path.join(BLDDIR, path)
        if not os.path.exists(path):
            path += ".building"
    b = parse_file(path)
    print(os.path.basename(path))
    if b["model"]:
        print(f"  model      {b['model'][0]}   material {b['model'][1]}")
    for mdl, mat, dist in b["lods"]:
        print(f"  LOD >{dist:g}u  {mdl}   material {mat}")
    if b["occlusion"]:
        print(f"  occlusion  {b['occlusion']}  (do not draw)")
    if b["folder"]:
        print(f"  folder     {b['folder']}")


if __name__ == "__main__":
    _cli()
