"""Parser for The Last Story `.material` files -- LastWorld engine.

Format: PLAINTEXT, INI-like, TAB-indented, CRLF line endings.
This is the mesh<->texture BRIDGE: every `Material` block maps its shading
channels (TexColor/TexEmboss/TexSpec/TexLightSurround...) to a texture file by
name (e.g. pc001_04.tga -> asset pc001_04.texture -> textures_png/...png).

Structure (nesting level = number of leading TABs):
    Material                      # 0 tabs: start of a material block
        Name=pc001_armor          # 1 tab:  scalar material property
        Shader=emboss
        TexColor1                 # 1 tab:  start of a texture channel
            name=pc001_04.tga     # 2 tabs: channel property
            wrapU=1
            indScale=0.7,0.7
        MatSrc=VtxColor
        AmbColor=0.5 0.5 0.5
        ...

CLI:
    python parse_material.py FILE.material             # readable dump
    python parse_material.py FILE.material --json      # JSON dump
    python parse_material.py FILE.material --textures  # referenced texture names
"""
import sys, json, os

# Key names that open a "texture channel" sub-block (they carry a `name=...`
# child). Everything else at 1 tab is a scalar property.
TEX_CHANNEL_PREFIXES = ("TexColor", "TexEmboss", "TexSpec", "TexLight",
                        "TexBump", "TexNormal", "TexAlpha", "TexRefl",
                        "TexEnv", "TexMask", "Tex")


def _indent(line):
    """Number of leading TABs."""
    n = 0
    while n < len(line) and line[n] == "\t":
        n += 1
    return n


def parse(text):
    """Return a list of materials. Each material is a dict:
        {name, shader, params:{k:v}, textures:{Channel:{name, wrapU, ...}}}
    """
    materials = []
    cur = None          # current material
    cur_chan = None     # name of the current texture channel, inside a material

    for raw in text.splitlines():
        if not raw.strip():
            continue
        ind = _indent(raw)
        line = raw.strip()

        if ind == 0:
            # new top-level block: in practice always "Material"
            if line == "Material":
                cur = {"name": None, "shader": None, "params": {}, "textures": {}}
                materials.append(cur)
                cur_chan = None
            continue

        if cur is None:
            continue

        if ind == 1:
            cur_chan = None
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "Name":
                    cur["name"] = v
                elif k == "Shader":
                    cur["shader"] = v
                else:
                    cur["params"][k] = v
            else:
                # a 1-tab line with no '=' is a texture channel header
                cur_chan = line
                cur["textures"][cur_chan] = {}
        elif ind >= 2 and cur_chan is not None:
            if "=" in line:
                k, v = line.split("=", 1)
                cur["textures"][cur_chan][k.strip()] = v.strip()

    return materials


def parse_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


def texture_names(materials):
    """Ordered set of every referenced .tga (channels with a non-empty name)."""
    names = []
    seen = set()
    for m in materials:
        for chan, props in m["textures"].items():
            nm = props.get("name", "").strip()
            if nm and nm not in seen:
                seen.add(nm)
                names.append(nm)
    return names


def tga_to_asset(tga_name):
    """pc001_04.tga -> pc001_04  (stem, used to resolve .texture / .png)."""
    return os.path.splitext(os.path.basename(tga_name))[0]


def resolve_png(tga_name, png_root="textures_png"):
    """Resolve a material's .tga name to the extracted PNG.
    Real assets are <stem>.texture; the PNGs are <stem>.texture.png under a
    pack/filesystem/data/texture/ hierarchy. Returns the path or None."""
    stem = tga_to_asset(tga_name)
    for dirpath, _dirs, files in os.walk(png_root):
        target = stem + ".texture.png"
        if target in files:
            return os.path.join(dirpath, target)
    return None


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    flags = sys.argv[2:]
    mats = parse_file(path)

    if "--json" in flags:
        print(json.dumps(mats, indent=2, ensure_ascii=False))
        return
    if "--textures" in flags:
        for nm in texture_names(mats):
            print(f"{nm}\t-> {tga_to_asset(nm)}")
        return

    # readable dump
    print(f"{path}: {len(mats)} materials")
    for m in mats:
        print(f"\n[{m['name']}]  shader={m['shader']}")
        for k, v in m["params"].items():
            print(f"    {k} = {v}")
        for chan, props in m["textures"].items():
            nm = props.get("name", "")
            extra = " ".join(f"{k}={v}" for k, v in props.items() if k != "name")
            arrow = f"  -> {tga_to_asset(nm)}" if nm else ""
            print(f"    {chan}: {nm}{arrow}   {extra}".rstrip())


if __name__ == "__main__":
    _cli()
