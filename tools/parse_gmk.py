"""The Last Story gimmicks (.gmk) -- the world's interactive objects.

FORMAT: plain TSV, one directive per line, `#` starts a comment.
    KEY <tab> arg <tab> arg ...

A gimmick is an object the game interacts with: a crate, a door, a collapsing
pillar, a lamp to snuff out. It has up to two visual states (BEFORE/AFTER), a
transition animation, and collision that changes along with the state.

This is the first format in the game that is not an asset: it describes
behaviour.

Paths inside a .gmk are LOGICAL (/gimmick/<obj>/<file>) -- they mirror the
artists' source tree. On the packed disc the files sit flat in data/<type>/ and
resolve by basename. See resolve().

--- the state model --------------------------------------------------------
    MODEL_BEFORE / MODEL_AFTER      the two looks; a bare MODEL = single state
    COLLISION_BEFORE/AFTER  <r> <f> radius + .hcb file for that state
    INIT_STATE <n>                  starting state
    MOTION <file> <STATE>           clip bound to a state code
The state code is GM_ACTnn, the same shape as the characters' CH_* codes: it is
the key by which the engine picks a clip.

BEFORE/AFTER covers the two-state gimmicks (the majority). More complex ones
use an explicit state machine instead:

    STATE   <id> <STATE|file.hocb> <f> <loop> <f> [<f> <MODE> ...]
    TRIGGER <from> <to> <type> <p1> [<p2>]
    STATE_SETTING <from> <to> [<p>]

`loop` = 1 the clip cycles, 0 it plays once. Modes seen: NOMOTION (a state with
no animation, a pure timer), ATTENTION, DRAWOFF (do not draw), TRANS/TRANSINV
followed by four numbers that look like fade thresholds.

TRIGGER type 1 is a TIMEOUT IN FRAMES: after p1 frames, move to state <to>. In
12 of the 16 measurable cases p1 is EXACTLY the duration of the source state's
clip, i.e. "when the animation ends" (see --check-trigger). The rest are longer
waits on a looping state. p2 is 0 in every "end of clip" case and non-zero only
on long timers, which suggests a random jitter -- but with a sample of 2 that
stays a guess. Types 2-6 are still undecoded; their p1 is always well below the
clip duration, so they are not timeouts.

A full example, gm034_100 (an NPC standing around):
    STATE 1 ... NOMOTION  +  TRIGGER 1 2 1 300 60   stand still ~10 s
    STATE 2 (loop=0)      +  TRIGGER 2 1 1  13   0  play a 13-frame fidget,
                                                    then back to standing

--- MOTCMD: commands on the animation timeline -----------------------------
    MOTCMD <STATE> <frame> <OPCODE> <arg1> <arg2..arg4> [arg5]

This is scripting: "at frame N of state S's animation, do X".

OPCODES (arg1 = target, arg2..4 = local XYZ offset, arg5 = scale/extra):
    EFP_PLAY  <file.efp> <x> <y> <z> <scale>    one-shot effect
    EFP_LOOP  <file.efp> <x> <y> <z> <scale>    persistent effect
    SE_PLAY   <SE_xxx>   <x> <y> <z> <scale>    sound (id from the rsid registry)
    CAM_SHAKE <empty>    <ampX> <ampY> <dur> <delay>
    EXPLODE   <id> <x> <y> <z> <force> <node>   detach a model node

Two directives outside MOTCMD live on the same timeline:
    NODEVIS  <node> <frame>                     hide the node at frame N
    MATALPHA <material> <frame> <length> <f>    fade the material out

--- why we believe <frame> is really a frame -------------------------------
Three tests, weakest first (--check and --xref):

1. All 179 MOTCMD frames fall inside the duration of their OWN state's clip,
   with no exceptions. Weak on its own: the frame/duration ratio never exceeds
   0.47, so any small integer would pass.
2. NODEVIS and MATALPHA use the same scale and SATURATE it: 299/300, 250/251,
   150/151, 240/250 -- the fade ends exactly on the animation's last frame. An
   arbitrary number does not do that. 32/34 NODEVIS and 108/113 MATALPHA land
   inside the duration.
3. The names cited exist in a different format: 18/18 EXPLODE nodes, 32/34
   NODEVIS nodes and 108/113 MATALPHA materials match the twin .model /
   .material. All seven misses are explained and none is a parsing error:
   - em205_cloth/leg (gm001_101/102): the material lives in the ENEMY's
     .material, not in the gimmick's model. MATALPHA addresses materials by
     name across the whole loaded scene, map and characters included -- the
     same file also fades ai_dg005_* and og_dg005_*, which are map geometry.
   - `delete` vs the real node `delete0`: a one-character near-miss.
   - h_gm001_108b_mat3: a dead reference; only mat1/2/4/5 exist.

Usage:
    python parse_gmk.py FILE.gmk        # structured dump + timeline
    python parse_gmk.py --census        # key census over all files
    python parse_gmk.py --check         # validate MOTCMD frames vs .motion
    python parse_gmk.py --xref          # validate names vs .model / .material
    python parse_gmk.py --check-trigger # validate type-1 TRIGGER vs clip length
"""
import sys, os, glob, collections, itertools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS = os.path.join(ROOT, "assets", "pack", "filesystem")
GMK_DIR = os.path.join(FS, "data", "gimmick")

# paths inside a .gmk are logical (/gimmick/<obj>/<file>); on the packed disc
# the files sit flat in data/<type>/ and resolve by basename
EXT_DIR = {".model": "model", ".motion": "motion", ".efp": "effect",
           ".hcb": "collision", ".hocb": "collision"}


def resolve(logical):
    """Logical path from a .gmk -> real path on disc (or None)."""
    base = os.path.basename(logical)
    ext = os.path.splitext(base)[1].lower()
    sub = EXT_DIR.get(ext)
    if sub:
        p = os.path.join(FS, "data", sub, base)
        if os.path.exists(p):
            return p
    hits = glob.glob(os.path.join(FS, "**", base), recursive=True)
    return hits[0] if hits else None


def parse(path):
    """-> list of (key, [args]) in file order."""
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            out.append((parts[0], parts[1:]))
    return out


def motcmds(entries):
    """Extract MOTCMD rows as structured dicts."""
    out = []
    for key, args in entries:
        if key != "MOTCMD" or len(args) < 3:
            continue
        out.append({"state": args[0], "frame": int(args[1]), "op": args[2],
                    "target": args[3] if len(args) > 3 else "",
                    "args": args[4:]})
    return out


def motions(entries):
    """STATE code -> the .motion file declared for it."""
    out = {}
    for key, args in entries:
        if key == "MOTION" and len(args) >= 2:
            out[args[1]] = args[0]
    return out


def states(entries):
    """State id -> the .motion file that state plays."""
    mots = motions(entries)
    out = {}
    for key, args in entries:
        if key == "STATE" and len(args) >= 2 and args[1] in mots:
            out[args[0]] = mots[args[1]]
    return out


def dump(path):
    entries = parse(path)
    print(f"=== {os.path.basename(path)} - {len(entries)} directives ===")
    for key, args in entries:
        print(f"  {key:<20} {' | '.join(args)}")
    cmds = motcmds(entries)
    if cmds:
        print("\n  -- timeline --")
        for st in sorted({c['state'] for c in cmds}):
            mot = motions(entries).get(st, "?")
            print(f"  {st}  <- {mot}")
            for c in sorted([c for c in cmds if c['state'] == st],
                            key=lambda c: c['frame']):
                extra = ' '.join(c['args'])
                print(f"      f{c['frame']:>4}  {c['op']:<10} {c['target']:<44} {extra}")


def census():
    files = sorted(glob.glob(os.path.join(GMK_DIR, "*.gmk")))
    keys = collections.Counter()
    ops = collections.Counter()
    for p in files:
        entries = parse(p)
        keys.update(k for k, _ in entries)
        ops.update(c["op"] for c in motcmds(entries))
    print(f"{len(files)} .gmk files\n")
    print("keys:")
    for k, n in keys.most_common():
        print(f"  {n:>5}  {k}")
    print("\nMOTCMD opcodes:")
    for k, n in ops.most_common():
        print(f"  {n:>5}  {k}")


_FC_CACHE = {}


def frame_count(motion_path):
    """Clip duration in frames (motion.py, `anim` header +0x20)."""
    if motion_path not in _FC_CACHE:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import motion
        _FC_CACHE[motion_path] = motion.parse_file(motion_path)["frameCount"]
    return _FC_CACHE[motion_path]


def check():
    """A MOTCMD's frame must fall inside the clip of its OWN state.

    This is the test that separates "animation frame" from any other reading of
    the field (milliseconds, ticks, an arbitrary index).
    """
    files = sorted(glob.glob(os.path.join(GMK_DIR, "*.gmk")))
    ok = over = nomotion = missing = 0
    worst = []
    for p in files:
        entries = parse(p)
        cmds = motcmds(entries)
        if not cmds:
            continue
        mots = motions(entries)
        for st, group in itertools.groupby(
                sorted(cmds, key=lambda c: c["state"]), key=lambda c: c["state"]):
            group = list(group)
            mf = max(c["frame"] for c in group)
            logical = mots.get(st)
            if not logical:
                nomotion += len(group)
                continue
            real = resolve(logical)
            if not real:
                missing += len(group)
                continue
            n = frame_count(real)
            if mf <= n:
                ok += len(group)
                worst.append((mf / n if n else 0, os.path.basename(p), st, mf, n))
            else:
                over += len(group)
                print(f"  OUTSIDE: {os.path.basename(p)} {st} frame {mf} > duration {n}")
    print(f"\ncommands inside their clip duration : {ok}")
    print(f"commands past the end               : {over}")
    print(f"state with no MOTION declared       : {nomotion}")
    print(f".motion not found on disc           : {missing}")
    worst.sort(reverse=True)
    print("\nhighest frame/duration ratios (near 1.0 = the field really is a frame):")
    for r, f, st, mf, n in worst[:8]:
        print(f"  {r:5.2f}  {f} {st}  {mf}/{n:.0f}")


def check_trigger():
    """TRIGGER type 1: is p1 a timeout in frames?

    If it is, it should often equal the source state's clip duration -- i.e.
    "advance when the animation ends".
    """
    tally = collections.Counter()
    rows = []
    for p in sorted(glob.glob(os.path.join(GMK_DIR, "*.gmk"))):
        entries = parse(p)
        st = states(entries)
        for key, args in entries:
            if key != "TRIGGER" or len(args) < 4:
                continue
            logical = st.get(args[0])
            real = resolve(logical) if logical else None
            if not real:
                continue
            n = frame_count(real)
            p1 = float(args[3])
            eq = abs(p1 - n) < 1.5
            tally[(args[2], "p1 == clip duration" if eq else
                   ("p1 < duration" if p1 < n else "p1 > duration"))] += 1
            if args[2] == "1":
                rows.append((os.path.basename(p), args[0], args[1], p1, n, eq,
                             args[4] if len(args) > 4 else ""))
    for k in sorted(tally):
        print(f"  type {k[0]}  {k[1]:<20} {tally[k]}")
    print("\ntype 1 in detail:")
    for f, s, d, p1, n, eq, p2 in rows:
        print(f"  {f:<17} {s}->{d}  p1={p1:>6.0f} duration={n:>6.0f} p2={p2:<4}"
              f" {'<== end of clip' if eq else ''}")


def _model_names(gmk_entries):
    """(nodes, materials) of every model the gimmick declares."""
    import re
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import parse_model
    nodes, mats = set(), set()
    for key, args in gmk_entries:
        if not key.startswith("MODEL") or not args:
            continue
        logical = next((a for a in args if a.endswith(".model")), None)
        if not logical:
            continue
        real = resolve(logical)
        if not real:
            continue
        try:
            m = parse_model.parse_file(real)
        except Exception:
            continue
        nodes.update(n["name"] for n in m["chunks"]["node"])
        # the twin .material is plain text: one Name=<material> per block
        mp = os.path.join(FS, "data", "material",
                          os.path.basename(real).replace(".model", ".material"))
        if os.path.exists(mp):
            d = open(mp, "rb").read()
            mats.update(x.decode() for x in re.findall(rb"Name=([ -~]+)", d))
    return nodes, mats


def xref():
    """Do the names cited by NODEVIS/EXPLODE/MATALPHA exist in the twin .model?

    Cross-validation between two independent formats: if the .gmk were being
    read wrong, these names would have no reason to line up.
    """
    files = sorted(glob.glob(os.path.join(GMK_DIR, "*.gmk")))
    tally = collections.Counter()
    misses = []
    for p in files:
        entries = parse(p)
        refs = []
        for key, args in entries:
            if key == "NODEVIS" and args:
                refs.append(("NODEVIS/node", args[0]))
            elif key == "MATALPHA" and args:
                refs.append(("MATALPHA/material", args[0]))
        for c in motcmds(entries):
            if c["op"] == "EXPLODE" and len(c["args"]) >= 5:
                refs.append(("EXPLODE/node", c["args"][4]))
        if not refs:
            continue
        nodes, mats = _model_names(entries)
        for kind, name in refs:
            pool = mats if "material" in kind else nodes
            if name in pool:
                tally[kind + " ok"] += 1
            else:
                tally[kind + " MISSING"] += 1
                misses.append((os.path.basename(p), kind, name))
    for k in sorted(tally):
        print(f"  {tally[k]:>4}  {k}")
    if misses:
        print("\nnot found:")
        for f, k, n in misses:
            print(f"  {f:<18} {k:<20} {n}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "--census":
        census()
    elif a[0] == "--check":
        check()
    elif a[0] == "--xref":
        xref()
    elif a[0] == "--check-trigger":
        check_trigger()
    else:
        for p in a:
            dump(p if os.path.exists(p) else os.path.join(GMK_DIR, p))
