r"""The Last Story effects, TEXT side: `.efp` (sequencer) and `.effconfig`.

The "effects" group is not one format but three, and two of them are plaintext:

    .efp        1,264 files   Shift-JIS XML     <- the sequencer, this tool
    .effconfig     34 files   one CSV line      <- area presets, this tool
    .eff        2,210 files   binary `@EFF$`    <- the real definition, NOT here

This tool covers the two text ones. A note for whoever opens the binary:
**`.eff` is LITTLE-ENDIAN**, the only format in the game that is not big-endian
(proof: the word at +0x08 read LE is the file size on 2210/2210), and its
offsets are ABSOLUTE, not self-relative like the collision formats.

--- `.efp`: the SEQUENCER ----------------------------------------------------
It contains no effect at all: it says WHEN to start a `.eff`, WHERE to put it
and WHAT to attach it to. This is the layer `.gmk` files reference with their
`EFP*` keys (341 resolved references, see parse_gmk.py).

    <EffectSequencer version="1|2|1.0.4">
      <EffectLine num="N"/>                    N = how many <Effect> follow
      <Effect file="X.eff" enable="0|1">
        <Frame start="" end=""/>
        <Pos x y z/> <Rot x y z/> <Scl val/> <Color a r g b/>
        <Parent type node obj flag release/>
        [<Throw flag speed><PointList num><Point x y z flag/>...</PointList></Throw>]
        [<Erase type frame/>]
      </Effect>
      [<Object path file><Pos/><Rot/><Motion file loop/></Object>]
    </EffectSequencer>

The grammar is COMPLETE: 15 tags, censused over every file (--check).
`Throw`/`Erase` appear in 13 files and `Object`/`Motion` in 6, all of them
version "1.0.4" - files left in the effect editor's own format, one of which
still carries the author's Windows path (`..\..\<mojibake>\`).

**`Parent` is the part that matters**: `type=4` (2487 of 2865 `<Effect>`) means
"attach this effect to a node", and `node` is then A BONE NAME - filled in 2485
of those 2487. With `type=0` (308) `node` is usually empty: world-space effect.
`obj` is filled only 7 times and names a `.hdb`, an extension with **not a
single file on the disc**: an editor reference left behind.

--- how we know `node` is a bone (--check-bones) -----------------------------
A cross-check between an XML file and an NW4R binary, two formats with nothing
in common. Two independent measurements:

1. **Narrow and honest**: for every gimmick declaring both `EFP` and `MODEL`,
   the `Parent node` names of that `.efp` must be bones of THAT model.
   288 files tested: **811/833 = 97.4%**.
2. **Global**: every name used must be a bone of SOME model. Across all 4,691
   `.model` files (13,202 distinct bone names):
   **2,582/2,653 references = 97.3%**, 566 distinct names out of 591.

The 71 remaining references are not misreads. They are names like
`eff_oar01..12`, `block_level01/02`, `polySurface505_DUP`, `up_model22` -
models that are not in `data/model/` (the recursive `levels`/`eventpacks` packs
are still unexploded). The misses in measurement 1 are even more telling:
`shard52`, `splinter80_1`, `hahen01_shard18` (hahen = 破片, fragment) - they
are debris, which lives in the model of the object's other state.

--- Frame: `end=0` means "no end" -------------------------------------------
303 `<Frame>` elements have `start > end`, which looks like corruption until
you look closer: **every one of them has `end=0`**. There is no `end<0` at all,
and no case of `start > end` with `end>0`. So:
    end > 0  -> a real interval, and then start <= end on **1509/1509 (100%)**
    end == 0 -> no declared end (1053 with start=0, 303 with start>0)
This is not an invariant that can hold by chance: if `end` were just another
frame number, `start > end` would also happen with `end` non-zero.

--- a trap when counting references from .gmk -------------------------------
The keys are not one but **11** (`EFP` 309, `EFP_BEFORE`, `EFP_WAIT`,
`EFP_ROLL`, `EFP_CRUSH`, `EFP_SHOOT`, `EFP_GET`, `EFP_ARROW`, `EFP_BURNOUT`,
`EFP_ITEM`, plus `EFPLIGHT` which names no file - it is four numbers). And one
row can carry more than one path, with empty trailing fields. Reading only
`EFP` and only the last argument counts 275 references instead of **341** -
a fifth of them lost. See gmk_efp_refs().

--- a real typo, shipped on the disc ----------------------------------------
`gm001_000b.efp` is NOT valid XML: it contains `<Pos x="0" y="0" y="0"/>`, with
`y` repeated in place of `z` (same on `<Rot>`). 1,263 of 1,264 files parse with
a strict XML parser; this one does not. parse() repairs it (the duplicate
attribute becomes `z`) and reports the repair in `["repaired"]`, because
dropping it silently would hide a real `.efp` with four effects.

There is a second, harmless authoring inconsistency: `ef_uc047.efp` declares
`<EffectLine num="6">` but carries 5 `<Effect>` elements. The two agree on all
the other 1,263 files, so `num` really is the count - but you cannot rely on it
to decide how many elements to read.

--- `.effconfig`: area presets ----------------------------------------------
34 files, one CSV line each (one has two). It is a zone's ambient-effect preset,
referenced by `.area` rows with the `EFF_CONFIG` key (16 references, 14
distinct, 0 missing):

    name , category , r , g , b , a , eff [, eff [, eff]]

    water,BE,0.75,0.75,0.75,1,be001_023,be001_024,be001_021
    yuge,BE,0.7,0.5,0.5,1,be003_013

The names follow the same romanised Japanese taxonomy as the rest of the disc:
`water`, `yuge` (湯気, steam), `yuge_big`, `blue_fire`, `hikari` (光, light).
The category is `BE` on 33 of 35 rows and `MAGIC_CIRCLE` on 2. The trailing
tokens are `.eff` names WITHOUT the extension and all of them exist, except the
special value `DEFAULT` (2 rows), which is a keyword and not a file.

Usage:
    python parse_efp.py FILE.efp          # summary of one sequencer
    python parse_efp.py --check           # grammar + invariants over every file
    python parse_efp.py --check-bones     # Parent node vs .model bone names
    python parse_efp.py --config          # the .effconfig files and their grammar
    python parse_efp.py --xref            # gmk -> efp -> eff, area -> effconfig
"""
import sys, os, glob, re, collections
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS = os.path.join(ROOT, "assets", "pack", "filesystem")
EFP_DIR = os.path.join(FS, "data", "efp")
EFF_DIR = os.path.join(FS, "data", "eff")
CFG_DIR = os.path.join(FS, "data", "effectconfig")
GMK_DIR = os.path.join(FS, "data", "gimmick")
AREA_DIR = os.path.join(FS, "data", "area")
MODEL_DIR = os.path.join(FS, "data", "model")

# <Pos x=".." y=".." y=".."/> - the second y is a typo for z (1 file)
_DUP = re.compile(r'(<(?:Pos|Rot)\b[^>]*?\sy="[^"]*")\s+y=(")', re.I)


def _xml(path):
    """-> (Element, repaired?). See the gm001_000b.efp typo."""
    raw = open(path, "rb").read().decode("shift-jis", "replace")
    try:
        return ET.fromstring(raw), False
    except ET.ParseError:
        fixed = _DUP.sub(r"\1 z=\2", raw)
        return ET.fromstring(fixed), True


def _xyz(el, keys=("x", "y", "z")):
    if el is None:
        return None
    return tuple(float(el.get(k, 0) or 0) for k in keys)


def parse(path):
    """-> the sequencer as a dict. <Effect> entries keep file order."""
    root, repaired = _xml(path)
    line = root.find("EffectLine")
    out = {"file": os.path.basename(path), "version": root.get("version"),
           "line_num": int(line.get("num")) if line is not None else None,
           "repaired": repaired, "effects": [], "objects": []}
    for e in root.findall("Effect"):
        fr = e.find("Frame")
        pa = e.find("Parent")
        th = e.find("Throw")
        er = e.find("Erase")
        eff = {
            "file": e.get("file"), "enable": int(e.get("enable", 1)),
            "start": int(fr.get("start")), "end": int(fr.get("end")),
            "pos": _xyz(e.find("Pos")), "rot": _xyz(e.find("Rot")),
            "scale": float(e.find("Scl").get("val")),
            "color": _xyz(e.find("Color"), ("r", "g", "b", "a")),
            "parent": {"type": int(pa.get("type")), "node": pa.get("node"),
                       "obj": pa.get("obj"), "flag": int(pa.get("flag")),
                       "release": int(pa.get("release"))} if pa is not None else None,
        }
        if th is not None:
            eff["throw"] = {"flag": int(th.get("flag")),
                            "speed": float(th.get("speed")),
                            "points": [(_xyz(pt), int(pt.get("flag")))
                                       for pt in th.iter("Point")]}
        if er is not None:
            eff["erase"] = {"type": int(er.get("type")),
                            "frame": int(er.get("frame"))}
        out["effects"].append(eff)
    for ob in root.findall("Object"):
        mo = ob.find("Motion")
        out["objects"].append({
            "path": ob.get("path"), "file": ob.get("file"),
            "pos": _xyz(ob.find("Pos")), "rot": _xyz(ob.find("Rot")),
            "motion": mo.get("file") if mo is not None else None,
            "loop": int(mo.get("loop")) if mo is not None else None})
    return out


def parse_config(path):
    """-> list of presets. One row per preset (one file has two)."""
    txt = open(path, "rb").read().decode("shift-jis", "replace")
    out = []
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        f = line.split(",")
        out.append({"name": f[0], "category": f[1],
                    "color": tuple(float(x) for x in f[2:6]),
                    "effects": [x for x in f[6:] if x]})
    return out


def _files(d, ext):
    return sorted(glob.glob(os.path.join(d, "*" + ext)))


def gmk_efp_refs(entries):
    """Every .efp path a .gmk references.

    There are 11 keys (`EFP`, `EFP_BEFORE`, `EFP_CRUSH`, `EFP_SHOOT`, ...) and
    a row can carry several paths plus empty fields; `EFPLIGHT` names no file
    at all, it is four numbers. Taking only `k == "EFP"` and only the last
    argument loses a fifth of the references.
    """
    out = []
    for k, args in entries:
        if not k.startswith("EFP"):
            continue
        out += [a for a in args if a.endswith(".efp")]
    return out


# --------------------------------------------------------------------------
def check():
    """The full grammar and the invariants, over every .efp."""
    files = _files(EFP_DIR, ".efp")
    tags = collections.Counter()
    attrs = collections.defaultdict(collections.Counter)
    st = collections.defaultdict(collections.Counter)
    repaired = []
    frame = collections.Counter()
    ptype = collections.Counter()
    missing_eff = []
    for p in files:
        try:
            root, rep = _xml(p)
        except ET.ParseError as e:
            st["valid XML"][False] += 1
            print(f"  UNPARSEABLE: {os.path.basename(p)} - {e}")
            continue
        st["valid XML"][True] += 1
        if rep:
            repaired.append(os.path.basename(p))
        for el in root.iter():
            tags[el.tag] += 1
            for k in el.attrib:
                attrs[el.tag][k] += 1
        m = parse(p)
        st["EffectLine num == n. of <Effect>"][
            m["line_num"] == len(m["effects"])] += 1
        if m["line_num"] != len(m["effects"]):
            print(f"    {m['file']}: num={m['line_num']} but {len(m['effects'])} <Effect>")
        for e in m["effects"]:
            frame["end<0"] += e["end"] < 0
            if e["end"] > 0:
                frame["end>0, start<=end"] += e["start"] <= e["end"]
                frame["end>0, start>end"] += e["start"] > e["end"]
            else:
                frame["end==0, start==0"] += e["start"] == 0
                frame["end==0, start>0"] += e["start"] > 0
            ptype[e["parent"]["type"]] += 1
            st["<Effect file> exists on disc"][
                os.path.exists(os.path.join(EFF_DIR, e["file"]))] += 1
            if not os.path.exists(os.path.join(EFF_DIR, e["file"])):
                missing_eff.append(e["file"])
            t, nd = e["parent"]["type"], e["parent"]["node"]
            st[f"parent type={t}: node filled in"][bool(nd)] += 1
    print(f"=== .efp: {len(files)} files ===")
    print("  version:", dict(collections.Counter(
        parse(p)["version"] for p in files)))
    print("  tags and attributes (the complete grammar):")
    for t in sorted(tags):
        print(f"    <{t:16s}> x{tags[t]:5d}  attributes: {sorted(attrs[t])}")
    print()
    for k, v in st.items():
        tot = sum(v.values())
        print(f"  {k:36s} {v.get(True,0)}/{tot}")
    print(f"\n  repaired (duplicate attribute): {repaired}")
    print(f"  Frame: {dict(frame)}")
    print("    -> end==0 means 'no end': every start>end case has end==0,"
          " and with end>0, start<=end holds 100%.")
    print(f"  Parent type: {dict(ptype.most_common())}")
    if missing_eff:
        print(f"  .eff referenced but missing: {len(missing_eff)} {missing_eff[:5]}")


def check_bones():
    """`Parent node` is a bone name: checked against the .model files."""
    import parse_model as M
    import parse_gmk as G

    cache = {}

    def bones(path):
        if path not in cache:
            try:
                cache[path] = {n["name"] for n in M.parse_file(path)["chunks"]["node"]}
            except Exception:
                cache[path] = set()
        return cache[path]

    # --- 1) narrow: against the model of the SAME gimmick
    hit = miss = tested = 0
    lost = collections.Counter()
    for gp in _files(GMK_DIR, ".gmk"):
        ent = G.parse(gp)
        efps = gmk_efp_refs(ent)
        models = [a[-1] for k, a in ent if k.startswith("MODEL") and a
                  and a[-1].endswith(".model")]
        if not efps or not models:
            continue
        bs = set()
        for m in models:
            mp = G.resolve(m)
            if mp:
                bs |= bones(mp)
        if not bs:
            continue
        for ep in efps:
            rp = G.resolve(ep) or os.path.join(EFP_DIR, os.path.basename(ep))
            if not os.path.exists(rp):
                continue
            tested += 1
            for e in parse(rp)["effects"]:
                nd = e["parent"]["node"]
                if not nd:
                    continue
                if nd in bs:
                    hit += 1
                else:
                    miss += 1
                    lost[nd] += 1
    print("=== Parent node vs .model bone names ===")
    print(f"  1) against the same gimmick's model ({tested} .efp files):")
    print(f"     {hit}/{hit+miss} = {100*hit/max(hit+miss,1):.1f}%")
    print(f"     not found: {lost.most_common(8)}")

    # --- 2) global: against EVERY model
    names = collections.Counter()
    for p in _files(EFP_DIR, ".efp"):
        for e in parse(p)["effects"]:
            if e["parent"]["node"]:
                names[e["parent"]["node"]] += 1
    universe = set()
    models = _files(MODEL_DIR, ".model")
    for p in models:
        universe |= bones(p)
    ok = sum(v for k, v in names.items() if k in universe)
    tot = sum(names.values())
    absent = [k for k in names if k not in universe]
    print(f"  2) against all {len(models)} .model files"
          f" ({len(universe)} distinct bone names):")
    print(f"     {ok}/{tot} references = {100*ok/tot:.1f}%,"
          f" {len(names)-len(absent)}/{len(names)} distinct names")
    print(f"     never seen as a bone ({len(absent)}):",
          [k for k in sorted(absent, key=lambda x: -names[x])][:12])


def config():
    """The .effconfig files: grammar and references."""
    files = _files(CFG_DIR, ".effconfig")
    rows = [(os.path.basename(p), parse_config(p)) for p in files]
    nlines = collections.Counter(len(r) for _, r in rows)
    cat = collections.Counter()
    nam = collections.Counter()
    neff = collections.Counter()
    missing = []
    for _, rs in rows:
        for r in rs:
            cat[r["category"]] += 1
            nam[r["name"]] += 1
            neff[len(r["effects"])] += 1
            for e in r["effects"]:
                if not os.path.exists(os.path.join(EFF_DIR, e + ".eff")):
                    missing.append(e)
    print(f"=== .effconfig: {len(files)} files ===")
    print(f"  rows per file: {dict(nlines)}")
    print(f"  names:      {dict(nam.most_common())}")
    print(f"  categories: {dict(cat)}")
    print(f"  .eff per row: {dict(sorted(neff.items()))}")
    print(f"  referenced .eff that do not exist: {collections.Counter(missing)}"
          f"   <- 'DEFAULT' is a keyword, not a file")
    print("\n  contents:")
    for n, rs in rows:
        for r in rs:
            print(f"    {n:38s} {r['name']:10s} {r['category']:12s}"
                  f" rgba={r['color']}  {r['effects']}")


def xref():
    """Who references what: gmk -> efp -> eff, area -> effconfig -> eff."""
    import parse_gmk as G
    gmk = collections.Counter()
    gmk_missing = []
    for gp in _files(GMK_DIR, ".gmk"):
        for ref in gmk_efp_refs(G.parse(gp)):
            b = os.path.basename(ref)
            gmk[b] += 1
            if not os.path.exists(os.path.join(EFP_DIR, b)):
                gmk_missing.append(b)
    efp_files = {os.path.basename(p) for p in _files(EFP_DIR, ".efp")}
    eff_ref = collections.Counter()
    for p in _files(EFP_DIR, ".efp"):
        for e in parse(p)["effects"]:
            eff_ref[e["file"]] += 1
    eff_files = {os.path.basename(p) for p in _files(EFF_DIR, ".eff")}
    area = collections.Counter()
    area_missing = []
    for p in _files(AREA_DIR, ".area"):
        for line in open(p, encoding="utf-8", errors="replace"):
            for tok in line.rstrip().split("\t"):
                if tok.endswith(".effconfig"):
                    b = os.path.basename(tok)
                    area[b] += 1
                    if not os.path.exists(os.path.join(CFG_DIR, b)):
                        area_missing.append(b)
    print("=== cross-format references ===")
    print(f"  .gmk -> .efp        {sum(gmk.values()):5d} refs,"
          f" {len(gmk)} distinct, missing {len(gmk_missing)}")
    print(f"  .efp -> .eff        {sum(eff_ref.values()):5d} refs,"
          f" {len(eff_ref)} distinct, missing"
          f" {len([x for x in eff_ref if x not in eff_files])}")
    print(f"  .area -> .effconfig {sum(area.values()):5d} refs,"
          f" {len(area)} distinct, missing {len(area_missing)}")
    print(f"\n  .efp never referenced by a .gmk: {len(efp_files - set(gmk))}"
          f" of {len(efp_files)}  (be*/ef_* = battle and ambient effects)")
    print(f"  .eff never referenced by a .efp: {len(eff_files - set(eff_ref))}"
          f" of {len(eff_files)}")


def summary(path):
    m = parse(path)
    print(f"=== {m['file']}  version {m['version']}"
          + ("  [REPAIRED: duplicate attribute]" if m["repaired"] else ""))
    print(f"  EffectLine num={m['line_num']}, {len(m['effects'])} effects")
    for e in m["effects"]:
        pa = e["parent"]
        tgt = (f"node {pa['node']!r}" if pa["type"] == 4 and pa["node"]
               else "world" if pa["type"] == 0 else f"type={pa['type']}")
        end = "no end" if e["end"] == 0 else str(e["end"])
        print(f"    {e['file']:24s} frame {e['start']}->{end:11s}"
              f" {tgt:26s} flag={pa['flag']} release={pa['release']}"
              + ("" if e["enable"] else "  [DISABLED]"))
        if e["pos"] != (0.0, 0.0, 0.0) or e["rot"] != (0.0, 0.0, 0.0) or e["scale"] != 1.0:
            print(f"      pos={e['pos']} rot={e['rot']} scale={e['scale']}")
        if e["color"] != (1.0, 1.0, 1.0, 1.0):
            print(f"      colour rgba={e['color']}")
        if "throw" in e:
            print(f"      throw flag={e['throw']['flag']}"
                  f" speed={e['throw']['speed']} points={len(e['throw']['points'])}")
        if "erase" in e:
            print(f"      erase type={e['erase']['type']} frame={e['erase']['frame']}")
    for o in m["objects"]:
        print(f"    <Object> {o['file']!r} pos={o['pos']} motion={o['motion']!r}"
              f"  (author path: {o['path']!r})")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "--check":
        check()
    elif a[0] == "--check-bones":
        check_bones()
    elif a[0] == "--config":
        config()
    elif a[0] == "--xref":
        xref()
    else:
        p = a[0] if os.path.exists(a[0]) else os.path.join(EFP_DIR, a[0])
        if not os.path.exists(p):
            sys.exit(f"{a[0]}: not found (neither as a path nor in {EFP_DIR})")
        summary(p)
