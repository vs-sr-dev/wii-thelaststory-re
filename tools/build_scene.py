"""Compose a whole The Last Story MAP into a single OBJ.

Joins up the full chain reversed so far:

    .map ------> the scene's bill of materials         (parse_map)
      |- MODEL         -> .model directly (terrain is the *_base.model)
      |- LOCATORS      -> .locator = instances with TRS  (parse_locator)
                            |- asset -> .building        (parse_building)
                                          |- .model      (export_obj/parse_model)

Each prop's vertices come out of model_geometry() in model space and are then
transformed by the instance matrix. Instanced geometry is decoded ONCE per
asset and reused for all of its instances -- on a map with hundreds of
instances the cost would otherwise explode.

See docs/11-maps-and-scenes.md.

Usage:
    python build_scene.py dg001_01.map out.obj
    python build_scene.py dg001_01.map out.obj --terrain-only
    python build_scene.py dg001_01.map out.obj --no-gimmick --limit 200
    python build_scene.py dg001_01.map out.obj --backdrop     # keep sky/far
"""
import os
import sys

import export_obj as eo
import parse_building as pb
import parse_locator as pl
import parse_map as pm_

DATA = os.path.join(os.path.dirname(__file__), "..", "assets", "pack",
                    "filesystem", "data")
MODELDIR = os.path.join(DATA, "model")
LOCDIR = os.path.join(DATA, "locator")

# .map MODEL rows that are not part of the solid scene.
SKIP_SUFFIX = ("_occ.model",)                    # occlusion-culling mesh
SKIP_FLAGS = ("HIDE_BIRDVIEW",)                  # duplicates for the overhead view

# Backdrop: skydome, distant silhouettes, volumetric light shafts. They are
# enormous next to the walkable area and are excluded by default, or the real
# map becomes a speck inside the skydome.
BACKDROP = ("_sky", "_far", "_lightshaft")


def is_backdrop(name):
    stem = name[:-len(".model")] if name.endswith(".model") else name
    return any(k in stem for k in BACKDROP)


class Scene:
    def __init__(self):
        self.verts, self.uvs, self.faces, self.mat_png = [], [], [], {}
        self.cache = {}
        self.stats = {"model": 0, "inst": 0, "missing": []}

    def geometry(self, model_file):
        """A .model's geometry, decoded only once."""
        if model_file in self.cache:
            return self.cache[model_file]
        path = os.path.join(MODELDIR, model_file)
        if not os.path.exists(path):
            self.cache[model_file] = None
            self.stats["missing"].append(model_file)
            return None
        try:
            g = eo.model_geometry(path)
        except Exception as e:                     # one broken asset must not
            print(f"    ! {model_file}: {e}")      # bring down the whole map
            g = None
        self.cache[model_file] = g
        return g

    def add(self, model_file, mat=None, group=""):
        """Add a .model with the identity matrix (already in world space)."""
        return self._merge(self.geometry(model_file), None, group or model_file)

    def add_instance(self, model_file, inst, group=""):
        return self._merge(self.geometry(model_file), pl.matrix(inst),
                           group or inst["name"])

    def _merge(self, g, mtx, group):
        if not g:
            return False
        verts, uvs, faces, mat_png, _, _ = g
        base = len(self.verts)
        if mtx is None:
            self.verts.extend(verts)
        else:
            self.verts.extend(pl.apply(mtx, v) for v in verts)
        self.uvs.extend(uvs)
        for (a, b, c, mat) in faces:
            self.faces.append((base + a, base + b, base + c, mat))
        for k, v in mat_png.items():
            self.mat_png.setdefault(k, v)
        return True

    def write(self, out, scale=1.0):
        if not self.verts:
            print("no vertices: empty scene")
            return
        mtl_path = os.path.splitext(out)[0] + ".mtl"
        with open(out, "w") as f:
            f.write(f"# TLS scene  {len(self.verts)} verts {len(self.faces)} tris\n")
            f.write(f"mtllib {os.path.basename(mtl_path)}\n")
            for (x, y, z) in self.verts:
                f.write(f"v {x*scale:.4f} {y*scale:.4f} {z*scale:.4f}\n")
            for (u, v) in self.uvs:
                f.write(f"vt {u:.5f} {1.0-v:.5f}\n")
            last = None
            for (a, b, c, mat) in self.faces:
                if mat != last:
                    f.write(f"usemtl {mat}\n")
                    last = mat
                f.write(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")
        used = sorted({fc[3] for fc in self.faces})
        ntex = 0
        with open(mtl_path, "w") as f:
            for mat in used:
                f.write(f"newmtl {mat}\nKd 0.8 0.8 0.8\n")
                png = self.mat_png.get(mat)
                if png:
                    f.write(f"map_Kd {os.path.abspath(png)}\n")
                    ntex += 1
                f.write("\n")
        print(f"\n{out}: {len(self.verts)} vertices, {len(self.faces)} triangles, "
              f"{ntex}/{len(used)} textured materials")


def build(map_file, out, terrain_only=False, gimmick=True, limit=None,
          scale=1.0, backdrop=False):
    path = map_file if os.path.exists(map_file) else \
        os.path.join(pm_.MAPDIR, map_file)
    m = pm_.parse_file(path)
    sc = Scene()
    terr = set(pm_.terrain(m))

    print(f"{os.path.basename(path)}  # {m['comment']}")
    print("\n--- direct MODEL rows ---")
    for name, flags in pm_.models(m):
        if any(name.endswith(s) for s in SKIP_SUFFIX):
            continue
        if any(fl in SKIP_FLAGS for fl in flags):
            continue
        if backdrop is False and is_backdrop(name):
            continue
        if terrain_only and name not in terr:
            continue
        ok = sc.add(name)
        tag = "TERRAIN" if name in terr else "       "
        print(f"  {tag} {name:<40} {'ok' if ok else 'MISSING'}")
        if ok:
            sc.stats["model"] += 1

    if terrain_only:
        sc.write(out, scale)
        return sc

    print("\n--- LOCATOR ---")
    ninst = 0
    for locname in pm_.locators(m, gimmick=gimmick):
        lp = os.path.join(LOCDIR, locname)
        if not os.path.exists(lp):
            print(f"  {locname:<40} MISSING")
            continue
        L = pl.parse_file(lp)
        placed = 0
        for inst in L["instances"]:
            if limit is not None and ninst >= limit:
                break
            recipe = pb.resolve(inst["asset"])
            mdl = recipe["model"][0] if recipe and recipe["model"] else \
                inst["asset"] + ".model"
            if sc.add_instance(mdl, inst):
                placed += 1
                ninst += 1
        print(f"  {locname:<40} {placed}/{len(L['instances'])} instances"
              f"   (bake {L['bake']})")
    sc.stats["inst"] = ninst

    if sc.stats["missing"]:
        miss = sorted(set(sc.stats["missing"]))
        print(f"\n  {len(miss)} models not found: {', '.join(miss[:6])}"
              + (" ..." if len(miss) > 6 else ""))
    print(f"\n  {sc.stats['model']} direct models + {ninst} instances")
    sc.write(out, scale)
    return sc


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit()
    a = sys.argv
    build(a[1], a[2],
          terrain_only="--terrain-only" in a,
          gimmick="--no-gimmick" not in a,
          limit=int(a[a.index("--limit") + 1]) if "--limit" in a else None,
          scale=float(a[a.index("--scale") + 1]) if "--scale" in a else 1.0,
          backdrop="--backdrop" in a)
