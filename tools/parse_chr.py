"""Parser for The Last Story `.chr` / `.mchr` -- THE CHARACTER STATE MACHINE.

Plain TSV, 
 line endings. A .chr defines a character; a .mchr is a SHARED
ANIMATION SET, pulled in via MOTION_SET.

The key that matters for movement:
    MOTION   <file.motion>   <STATE>

States are 8-character codes, CH_ + 3 letters + 2 digits. The three that drive
locomotion, verified on na000_00.mchr:
    CH_WTN00   na000_wtn00_00.motion    idle (wait)
    CH_WKN00   na000_wkn00_00.motion    walk
    CH_RNN00   na000_rnn00_00.motion    run

The delegation works like this: pc001_bs00_00.chr lists no MOTION of its own,
only

    MOTION_SET   /database/chara/motion/na000_00.chr

and the real file is na000_00.MCHR in that same directory (the engine resolves
the extension; the na000_00.chr under data/character is a 0-byte file). That is
why every human shares na000_*: it is one library, as already seen from the
.motion side, where curves bind to bones BY NAME.

Other keys present (censused over 1597 files): MODEL, MODEL_LOD, OPTION_PARTS,
NODE_EDIT, BOUND_CENTER_NODE, EDIT_DATABASE, SCALE, PBONE, PROTECTOR, EFP,
COLLISION, EQUIP, COLLI_RADIUS (collision radius, 3 = 30 cm).

See docs/11-maps-and-scenes.md.

Usage:
    python parse_chr.py FILE.chr              # summary
    python parse_chr.py FILE.chr --states     # every state
"""
import os
import sys

CHARDIR = os.path.join(os.path.dirname(__file__), "..", "assets", "pack",
                       "filesystem", "data", "character")
DBDIR = os.path.join(os.path.dirname(__file__), "..", "assets", "pack",
                     "filesystem", "database", "chara", "motion")

LOCOMOTION = {"idle": "CH_WTN00", "walk": "CH_WKN00", "run": "CH_RNN00"}


def parse(text):
    out = {"model": None, "lods": [], "motions": {}, "motion_set": [],
           "rows": [], "colli_radius": None}
    for ln in text.splitlines():
        ln = ln.rstrip("\r")
        if not ln.strip():
            continue
        p = [x.strip() for x in ln.split("\t")]
        out["rows"].append(p)
        key = p[0]
        if key == "MODEL" and len(p) >= 3 and out["model"] is None:
            out["model"] = (p[1], p[2])
        elif key == "MODEL_LOD" and len(p) >= 3:
            out["lods"].append(tuple(p[1:]))
        elif key == "MOTION" and len(p) >= 3:
            out["motions"].setdefault(p[2], p[1])
        elif key in ("MOTION_SET", "MOTION_SET_EX") and len(p) >= 2:
            out["motion_set"].append(p[1])
        elif key == "COLLI_RADIUS" and len(p) >= 2:
            try:
                out["colli_radius"] = float(p[1])
            except ValueError:
                pass
    return out


def parse_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


def _resolve_set(ref):
    """'/database/chara/motion/na000_00.chr' -> the real .mchr path."""
    base = os.path.basename(ref)
    stem = os.path.splitext(base)[0]
    for cand in (os.path.join(DBDIR, stem + ".mchr"),
                 os.path.join(DBDIR, base),
                 os.path.join(CHARDIR, base)):
        if os.path.exists(cand) and os.path.getsize(cand) > 0:
            return cand
    return None


def load(path, follow=True):
    """The .chr with its MOTION_SET states already resolved and merged.

    States defined in the file itself take precedence over inherited ones.
    """
    c = parse_file(path)
    if not follow:
        return c
    for ref in c["motion_set"]:
        p = _resolve_set(ref)
        if not p:
            continue
        sub = parse_file(p)
        for state, mot in sub["motions"].items():
            c["motions"].setdefault(state, mot)
    return c


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    if not os.path.exists(path):
        for d in (CHARDIR, DBDIR):
            if os.path.exists(os.path.join(d, path)):
                path = os.path.join(d, path)
                break
    c = load(path)
    print(os.path.basename(path))
    if c["model"]:
        print(f"  model     {c['model'][0]}   material {c["model"][1]}")
    if c["colli_radius"] is not None:
        print(f"  collision radius {c['colli_radius']:g} u "
              f"({c['colli_radius']*10:g} cm)")
    for ref in c["motion_set"]:
        p = _resolve_set(ref)
        print(f"  motion_set {ref}  ->  "
              f"{os.path.basename(p) if p else 'UNRESOLVED'}")
    print(f"  {len(c['motions'])} animation states")
    print("\n  --- locomotion ---")
    for label, state in LOCOMOTION.items():
        print(f"    {label:<6} {state:<10} {c['motions'].get(state, '(absent)')}")
    if "--states" in sys.argv:
        print("\n  --- all states ---")
        for state in sorted(c["motions"]):
            print(f"    {state:<12} {c['motions'][state]}")


if __name__ == "__main__":
    _cli()
